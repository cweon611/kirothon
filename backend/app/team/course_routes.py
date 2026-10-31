"""F1/F2 endpoints under /api/team (design 9). Benefit judgment lives in /api/benefits/*.

Residence and other user conditions arrive only in POST bodies, are passed to
the benefit port, and are never stored, logged or echoed back.
"""
from datetime import date, timedelta, timezone
import json
import secrets
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlmodel import Session, delete, select

from ..database import get_session
from . import benefit_port
from .benefit_port import ProgramSummary, RegionBenefitQuery
from .course_refund import check_course
from .geo import move_minutes
from .program_list import list_programs
from .planner import build_course, closed_on, fee_krw, opening_window, rest_text
from .reasons import MAX_CALLS_PER_COURSE, apply_state, generate_for_day
from .recommend import DISPLAYABLE_PHOTO, TRAVEL_CAP_MIN, TripQuery, recommend
from .regions import CONTENT_TYPES, SPOT_TYPES, interests, load_codes, origins, sigungu_map, today_kst
from .tourapi import TourApiClient, TourApiError, has_service_key
from .tourism_data import PlaceLite, cache_stats, load_snapshot
from .tourism_models import Course, HubRank, Place, RelatedPlace, utc_now
from .sync_tourism import fetch_detail

router = APIRouter(tags=["course"])
SessionDep = Annotated[Session, Depends(get_session)]
COURSE_ID_CHARS = "abcdefghijkmnpqrstuvwxyz23456789"
COURSE_TTL = timedelta(days=30)


def error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": message, "code": code})


class TripQueryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trip_type: Literal["day", "1N2D"]
    start_date: date
    origin: str
    interests: list[str] = Field(min_length=1, max_length=3)
    party_size: int = Field(ge=1, le=20)
    transport: Literal["car", "transit"] = "car"

    @field_validator("origin")
    @classmethod
    def known_origin(cls, value: str) -> str:
        if value not in origins():
            raise ValueError("출발지는 meta의 origins 중 하나여야 해요")
        return value

    @field_validator("interests")
    @classmethod
    def known_interests(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value) or any(v not in interests() for v in value):
            raise ValueError("관심 분야는 meta의 interests 중 서로 다른 1~3개여야 해요")
        return value

    @field_validator("start_date")
    @classmethod
    def not_past(cls, value: date) -> date:
        if value < today_kst()[0]:
            raise ValueError("여행 시작일은 오늘 이후여야 해요")
        return value

    def to_query(self, meal_cost: int | None = None, room_price: int | None = None) -> TripQuery:
        return TripQuery(self.trip_type, self.start_date, self.origin, self.interests, self.party_size,
                         self.transport, meal_cost, room_price)


class BenefitContextIn(TripQueryIn):
    residence_code: str | None = Field(default=None, pattern=r"^\d{5}$")
    benefit_conditions: dict | None = None


class RecommendIn(BenefitContextIn):
    pass


class CourseIn(BenefitContextIn):
    sigungu_code: str
    program_id: str | None = Field(default=None, max_length=100)
    meal_cost_krw: int | None = Field(default=None, ge=0, le=200_000)
    room_price_krw: int | None = Field(default=None, ge=0, le=2_000_000)

    @field_validator("sigungu_code")
    @classmethod
    def known_region(cls, value: str) -> str:
        if value not in sigungu_map():
            raise ValueError("sigungu_code는 meta의 광주·전남 시군구 코드여야 해요")
        return value


class RefundIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    residence_code: str | None = Field(default=None, pattern=r"^\d{5}$")
    benefit_conditions: dict | None = None


class ReasonsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    day: int = Field(ge=1, le=2)


class SwapIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    day: int = Field(ge=1, le=2)
    order: int = Field(ge=1, le=30)
    content_id: str = Field(min_length=1, max_length=64)


def benefit_query(body: BenefitContextIn, codes: tuple[str, ...]) -> RegionBenefitQuery:
    query = body.to_query()
    return RegionBenefitQuery(query.trip_type, query.start_date, query.end_date, codes, query.party_size,
                              today_kst()[0], body.residence_code, dict(body.benefit_conditions or {}))


def lookup_view(lookup) -> dict:
    return {"status": lookup.status, "checked_at": lookup.checked_at, "scope_note": lookup.scope_note,
            "message": lookup.message, "failed_sources": list(lookup.failed_sources),
            "connected": benefit_port.is_connected()}


def program_brief(program: ProgramSummary | None) -> dict | None:
    """Public program facts for a stored/shared course: no user-specific judgment."""
    if program is None:
        return None
    return {"program_id": program.program_id, "round_id": program.round_id, "name": program.name,
            "posted_status": program.posted_status, "application_open": program.application_open,
            "rate": program.rate, "cap_krw": program.cap_krw, "stale": program.stale,
            "last_verified_at": program.last_verified_at, "source_url": program.source_url}


def residence_options(codes: dict) -> dict:
    rows = codes.get("ldong_all") or []
    if not rows:
        groups: dict[str, list] = {}
        for region in sigungu_map().values():
            groups.setdefault(region.sido, []).append({"code": region.code, "name": region.name})
        return {"basis": "seed_gwangju_jeonnam_only", "sido": [{"name": k, "sigungu": v} for k, v in groups.items()]}
    groups = {}
    for row in rows:
        groups.setdefault(row["sido"], []).append({"code": row["code"], "name": row["name"]})
    return {"basis": "ldongCode2", "resolved_at": codes.get("resolved_at"),
            "sido": [{"name": k, "sigungu": v} for k, v in groups.items()]}


@router.get("/meta")
def meta(session: SessionDep):
    today, fixed = today_kst()
    codes = load_codes()
    groups: dict[str, list] = {}
    for region in sigungu_map().values():
        groups.setdefault(region.sido, []).append({"code": region.code, "name": region.name})
    return {
        "today": today.isoformat(), "today_fixed": fixed, "timezone": "Asia/Seoul",
        "trip_types": [{"key": "day", "label": "당일"}, {"key": "1N2D", "label": "1박2일"}],
        "transports": [{"key": "car", "label": "자차"}, {"key": "transit", "label": "대중교통"}],
        "origins": [{"key": o.key, "name": o.name} for o in origins().values()],
        "interests": [{"key": i.key, "label": i.label} for i in interests().values()],
        "trip_regions": [{"sido": k, "sigungu": v} for k, v in groups.items()],
        "residence_options": residence_options(codes),
        "travel_cap_min": TRAVEL_CAP_MIN,
        "ai_calls_per_course": MAX_CALLS_PER_COURSE,
        "tourism_data": cache_stats(session),
        "benefit_port": {"connected": benefit_port.is_connected(), "check_api": "/api/benefits/check"},
        "programs_open": list_programs(session, today)["counts"]["open_now"],
    }


@router.get("/programs")
def programs(session: SessionDep):
    return list_programs(session, today_kst()[0])


@router.post("/recommend")
def recommend_regions(body: RecommendIn, session: SessionDep):
    query = body.to_query()
    stats = cache_stats(session)
    snapshot = load_snapshot(session)
    base = {"query": query.public(), "today": today_kst()[0].isoformat(), "today_fixed": today_kst()[1],
            "tourism_data": stats}
    if snapshot.is_empty:
        return {**base, "regions": [], "no_refund_notice": None, "benefit_lookup": None,
                "notice": {"code": "tourism_cache_empty",
                           "message": "관광 데이터 캐시가 비어 있어요. 운영자가 수집 스크립트를 먼저 실행해야 해요."}}
    lookup = benefit_port.safe_lookup(benefit_query(body, tuple(sigungu_map())))
    result = recommend(snapshot, query, origins()[body.origin], lookup)
    return {**base, **result, "benefit_lookup": lookup_view(lookup), "notice": None}


def new_course_id(session: Session) -> str:
    while True:
        candidate = "".join(secrets.choice(COURSE_ID_CHARS) for _ in range(8))
        if session.get(Course, candidate) is None:
            return candidate


def course_response(course: Course) -> dict:
    body = apply_state(json.loads(course.body_json), json.loads(course.reasons_json or "{}"))
    state = json.loads(course.reasons_json or "{}")
    return {"id": course.id, **body, "ai_calls": course.ai_calls,
            "ai_calls_left": max(0, MAX_CALLS_PER_COURSE - course.ai_calls),
            "reasons_done": state.get("days", {})}


@router.post("/courses")
def create_course(body: CourseIn, session: SessionDep):
    snapshot = load_snapshot(session)
    if snapshot.is_empty:
        return error(503, "tourism_cache_empty", "관광 데이터 캐시가 비어 있어 코스를 만들 수 없어요.")
    if not snapshot.spots(body.sigungu_code):
        # A course without a single collected spot would be an empty template, not a recommendation.
        return error(503, "tourism_cache_empty", "이 지역의 관광 데이터가 아직 수집되지 않아 일정을 만들 수 없어요.")
    query = body.to_query(body.meal_cost_krw, body.room_price_krw)
    program, status = None, "none"
    if body.program_id:
        program, status = benefit_port.safe_program(body.program_id, benefit_query(body, (body.sigungu_code,)))
        if program and program.sigungu_codes and body.sigungu_code not in program.sigungu_codes:
            return error(422, "program_region_mismatch", "선택한 지원제도의 대상 지역이 아니에요.")
    today = today_kst()[0]
    course_body = build_course(snapshot, query, origins()[body.origin], body.sigungu_code, program, status, today)
    if body.program_id and status == "not_found":
        course_body["warnings"].append({"code": "program_not_found",
                                        "message": "지원제도 정보를 찾지 못해 환급 조건을 반영하지 않았어요."})
    course_body["region"]["refund_program"] = program_brief(program)
    session.exec(delete(Course).where(Course.created_at < utc_now() - COURSE_TTL))
    course = Course(id=new_course_id(session), trip_type=query.trip_type, start_date=query.start_date.isoformat(),
                    origin=query.origin, interests=",".join(query.interests), party_size=query.party_size,
                    transport=query.transport, sigungu_code=body.sigungu_code, program_id=body.program_id,
                    body_json=json.dumps(course_body, ensure_ascii=False))
    session.add(course)
    session.commit()
    session.refresh(course)
    return course_response(course)


@router.get("/courses/{course_id}")
def get_course(course_id: str, session: SessionDep):
    course = session.get(Course, course_id)
    if course is None:
        return error(404, "course_not_found", "코스를 찾을 수 없어요. 30일이 지나 정리됐을 수 있어요.")
    return course_response(course)


@router.post("/courses/{course_id}/reasons")
def course_reasons(course_id: str, body: ReasonsIn, session: SessionDep):
    course = session.get(Course, course_id)
    if course is None:
        return error(404, "course_not_found", "코스를 찾을 수 없어요.")
    course_body = json.loads(course.body_json)
    if body.day > len(course_body["days"]):
        return error(422, "day_out_of_range", "코스에 없는 일차예요.")
    ids = [i["place"]["content_id"] for d in course_body["days"] for i in d["items"]
           if i["kind"] == "spot" and i.get("place")]
    overviews = {p.content_id: p.overview for p in session.exec(select(Place).where(Place.content_id.in_(ids)))}
    state, calls, status = generate_for_day(course_body, json.loads(course.reasons_json or "{}"), body.day,
                                            course.ai_calls, overviews)
    course.reasons_json = json.dumps(state, ensure_ascii=False)
    course.ai_calls = calls
    session.add(course)
    session.commit()
    merged = apply_state(course_body, state)
    day = next(d for d in merged["days"] if d["day"] == body.day)
    return {"day": body.day, "status": status, "ai_calls": calls,
            "items": [{"order": i["order"], "content_id": i["place"]["content_id"], "reason_text": i["reason_text"],
                       "reason_by": i["reason_by"]} for i in day["items"] if i["kind"] == "spot" and i.get("place")]}


@router.post("/courses/{course_id}/refund")
def course_refund(course_id: str, body: RefundIn, session: SessionDep):
    """F3: verdict, estimate and dated steps for this course. Conditions are used once, never stored."""
    course = session.get(Course, course_id)
    if course is None:
        return error(404, "course_not_found", "코스를 찾을 수 없어요.")
    course_body = json.loads(course.body_json)
    try:
        result = check_course(session, course_body, course.program_id, body.residence_code,
                              body.benefit_conditions, today_kst()[0])
    except ValidationError as exc:
        fields = sorted({".".join(str(p) for p in e["loc"]) for e in exc.errors()})
        return error(422, "invalid_benefit_conditions",
                     "benefit_conditions가 지원제도 API 입력 형식과 맞지 않아요: " + ", ".join(fields))
    return {"course_id": course.id, "today": today_kst()[0].isoformat(), **result}


def find_item(course_body: dict, day_no: int, order: int) -> tuple[dict | None, dict | None]:
    day = next((d for d in course_body["days"] if d["day"] == day_no), None)
    item = next((i for i in day["items"] if i["order"] == order), None) if day else None
    return day, item


def previous_point(course_body: dict, day: dict, item: dict, origin) -> tuple[float, float]:
    prior = [i for i in day["items"] if i["order"] < item["order"] and i.get("place") and i["place"].get("lat")]
    if prior:
        return prior[-1]["place"]["lat"], prior[-1]["place"]["lng"]
    if day["day"] == 2:
        stay = next((i for i in course_body["days"][0]["items"] if i["kind"] == "stay" and i.get("place")), None)
        if stay:
            return stay["place"]["lat"], stay["place"]["lng"]
    return origin.lat, origin.lng


@router.get("/courses/{course_id}/candidates")
def swap_candidates(course_id: str, session: SessionDep, day: Annotated[int, Query(ge=1, le=2)],
                    order: Annotated[int, Query(ge=1, le=30)]):
    course = session.get(Course, course_id)
    if course is None:
        return error(404, "course_not_found", "코스를 찾을 수 없어요.")
    course_body = json.loads(course.body_json)
    day_view, item = find_item(course_body, day, order)
    if not item or item["kind"] != "spot" or not item.get("swappable"):
        return error(422, "not_swappable", "바꿀 수 없는 일정이에요(필수 방문지·식사·숙소).")
    snapshot = load_snapshot(session)
    used = {i["place"]["content_id"] for d in course_body["days"] for i in d["items"] if i.get("place")}
    point = previous_point(course_body, day_view, item, origins()[course.origin])
    trip_day = date.fromisoformat(day_view["date"])
    selected = course.interests.split(",")
    options = []
    for cand in snapshot.candidates(course.sigungu_code, selected, strict=False):
        place = cand.place
        if place.content_id in used or not place.coord or closed_on(place, trip_day) is True:
            continue
        options.append((not cand.interest_labels, move_minutes(point, place.coord, course.transport), cand))
    options.sort(key=lambda o: (o[0], o[1], o[2].place.content_id))
    return {"day": day, "order": order, "candidates": [
        {"content_id": c.place.content_id, "title": c.place.title, "category": c.place.category,
         "move_min_from_prev": minutes, "evidence": c.evidence[0], "interest_labels": c.interest_labels,
         "image_url": c.place.image_url if c.place.cpyright_type in DISPLAYABLE_PHOTO else None,
         "source": c.place.source} for _, minutes, c in options[:3]]}


@router.post("/courses/{course_id}/swap")
def swap_place(course_id: str, body: SwapIn, session: SessionDep):
    course = session.get(Course, course_id)
    if course is None:
        return error(404, "course_not_found", "코스를 찾을 수 없어요.")
    course_body = json.loads(course.body_json)
    _, item = find_item(course_body, body.day, body.order)
    if not item or item["kind"] != "spot" or not item.get("swappable"):
        return error(422, "not_swappable", "바꿀 수 없는 일정이에요(필수 방문지·식사·숙소).")
    snapshot = load_snapshot(session)
    place = snapshot.places.get(body.content_id)
    used = {i["place"]["content_id"] for d in course_body["days"] for i in d["items"] if i.get("place")}
    if (not place or place.sigungu_code != course.sigungu_code or place.content_type_id not in SPOT_TYPES
            or not place.coord or body.content_id in used):
        return error(422, "invalid_replacement", "이 코스 지역의 다른 관광지만 고를 수 있어요.")
    fixed = {}
    for day in course_body["days"]:
        fixed[day["day"]] = [body.content_id if (day["day"] == body.day and i["order"] == body.order)
                             else i["place"]["content_id"] for i in day["items"] if i["kind"] == "spot" and i.get("place")]
    inputs = course_body.get("spend_inputs") or {}
    query = TripQuery(course.trip_type, date.fromisoformat(course.start_date), course.origin,
                      course.interests.split(","), course.party_size, course.transport,
                      inputs.get("meal_cost_krw"), inputs.get("room_price_krw"))
    program, status = None, "none"
    if course.program_id:
        bq = RegionBenefitQuery(query.trip_type, query.start_date, query.end_date, (course.sigungu_code,),
                                query.party_size, today_kst()[0])
        program, status = benefit_port.safe_program(course.program_id, bq)
    rebuilt = build_course(snapshot, query, origins()[course.origin], course.sigungu_code, program, status,
                           today_kst()[0], fixed=fixed)
    rebuilt["region"]["refund_program"] = program_brief(program) or course_body["region"].get("refund_program")
    course.body_json = json.dumps(rebuilt, ensure_ascii=False)
    session.add(course)
    session.commit()
    session.refresh(course)
    return course_response(course)


@router.get("/places/{content_id}")
def place_detail(content_id: str, session: SessionDep,
                 visit_date: Annotated[date | None, Query(alias="date")] = None):
    row = session.get(Place, content_id)
    if row is None:
        snapshot = load_snapshot(session)
        demo = snapshot.places.get(content_id)
        if demo is None or demo.source != "demo":
            return error(404, "place_not_found", "장소를 찾을 수 없어요.")
        return {"content_id": demo.content_id, "title": demo.title, "category": demo.category,
                "sigungu_code": demo.sigungu_code, "addr": demo.addr, "lat": demo.lat, "lng": demo.lng,
                "overview": demo.overview, "source": "demo", "detail_status": "demo_data", "evidence": []}
    detail_status = "cached" if row.detail_fetched_at else ("standard_data" if row.source == "std" else "not_fetched")
    if not row.detail_fetched_at and row.source == "kor" and has_service_key():
        try:
            with TourApiClient(timeout=5.0, retries=0, min_interval=0) as client:
                fetch_detail(client, row)
            session.add(row)
            session.commit()
            session.refresh(row)
            detail_status = "fetched"
        except TourApiError:
            detail_status = "unavailable"
    lite = PlaceLite.from_row(row)
    evidence = [f"{sigungu_map()[h.sigungu_code].label if h.sigungu_code in sigungu_map() else h.sigungu_code} "
                f"중심 관광지 {h.rank}위"
                for h in session.exec(select(HubRank).where(HubRank.content_id == content_id)
                                      .order_by(HubRank.rank).limit(2))]
    evidence += [f"{r.src_name} 방문객이 함께 찾는 곳 {r.rank}위"
                 for r in session.exec(select(RelatedPlace).where(RelatedPlace.rel_content_id == content_id)
                                       .order_by(RelatedPlace.rank).limit(3))]
    window = opening_window(lite)
    closed = closed_on(lite, visit_date) if visit_date else None
    return {
        "content_id": row.content_id, "title": row.title, "category": CONTENT_TYPES.get(row.content_type_id, "기타"),
        "content_type_id": row.content_type_id, "sigungu_code": row.sigungu_code, "addr": row.addr,
        "lat": row.lat, "lng": row.lng, "tel": row.tel, "overview": (row.overview or "")[:300] or None,
        "intro": lite.intro, "rest_text": rest_text(lite),
        "opening_window": {"open": f"{window[0] // 60:02d}:{window[0] % 60:02d}",
                           "close": f"{window[1] // 60:02d}:{window[1] % 60:02d}"} if window else None,
        "fee_krw": fee_krw(lite), "room_price_krw": row.room_price_krw,
        "visit_date": visit_date.isoformat() if visit_date else None,
        "closed_on_visit_date": closed, "check_before_visit": visit_date is not None and closed is None,
        "image_url": row.image_url if row.cpyright_type in DISPLAYABLE_PHOTO else None,
        "image_credit": "한국관광공사" if row.image_url else None, "cpyright_type": row.cpyright_type,
        "evidence": evidence, "source": row.source, "source_modified": row.source_modified,
        "fetched_at": row.fetched_at.replace(tzinfo=timezone.utc).isoformat() if row.fetched_at else None,
        "detail_fetched_at": (row.detail_fetched_at.replace(tzinfo=timezone.utc).isoformat()
                              if row.detail_fetched_at else None),
        "detail_status": detail_status,
    }
