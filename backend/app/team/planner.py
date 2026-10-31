"""F2 itinerary builder (requirements 2, design 9-4).

Deterministic rules only; AI wording is added later by reasons.py. Program
constraints come from benefit_port and are applied as course constraints, not
as an eligibility decision.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
import re

from .benefit_port import CourseConstraints, ProgramSummary
from .geo import haversine_km, move_minutes
from .reasons import rule_sentence
from .recommend import TripQuery, program_view
from .regions import KST, SPOT_TYPES, Origin, name_key, name_variants, sigungu_map
from .tourism_data import Candidate, PlaceLite, Snapshot

DWELL_MIN = {"12": 90, "14": 60, "28": 120}
MEAL_MIN = 60
DEFAULT_MEAL_COST = 12_000
DEFAULT_ROOM_PRICE = 100_000
MOVE_WARN_MIN = 40
MEAL_RADIUS_KM = 5.0
DEPART = {1: 9 * 60, 2: 9 * 60 + 30}
END_LIMIT = {"day": 19 * 60, "1N2D": 17 * 60}  # day trip: last item end, 1N2D day 2: return departure
MEALS = {
    ("day", 1): [(12 * 60, "lunch", False), (17 * 60 + 30, "dinner", True)],
    ("1N2D", 1): [(12 * 60 + 30, "lunch", False), (18 * 60 + 30, "dinner", False)],
    ("1N2D", 2): [(12 * 60, "lunch", False)],
}
WEEKDAY_CHARS = "월화수목금토일"
QUALIFIERS = ("첫째", "둘째", "셋째", "넷째", "다섯째", "격주", "공휴일", "명절", "설날", "추석", "다음날", "임시", "변동")


# ---------- place facts read from detailIntro2 text ----------

def parse_minutes(text: str | None) -> int | None:
    if not text:
        return None
    hours = re.search(r"(\d+)\s*시간", text)
    minutes = re.search(r"(\d+)\s*분", text)
    total = (int(hours.group(1)) * 60 if hours else 0) + (int(minutes.group(1)) if minutes else 0)
    return total if 10 <= total <= 480 else None


def dwell_minutes(place: PlaceLite) -> int:
    if place.content_type_id == "14":
        parsed = parse_minutes(place.intro.get("spendtime"))
        if parsed:
            return parsed
    return DWELL_MIN.get(place.content_type_id, 90)


def rest_text(place: PlaceLite) -> str | None:
    for key in ("restdate", "restdateculture", "restdateleports", "restdatefood"):
        if place.intro.get(key):
            return place.intro[key]
    return None


def closed_on(place: PlaceLite, day: date) -> bool | None:
    """True = closed that weekday, False = open, None = could not read (show '방문 전 확인')."""
    text = rest_text(place)
    if not text:
        return None
    compact = text.replace(" ", "")
    if "연중무휴" in compact or compact in ("없음", "무휴", "휴무없음"):
        return False
    days: set[int] = set()
    for group in re.findall(r"((?:[월화수목금토일]\s*[,·/및]?\s*)+)요일", text):
        days |= {WEEKDAY_CHARS.index(ch) for ch in group if ch in WEEKDAY_CHARS}
    if day.weekday() in days:
        return True
    if not days or any(q in text for q in QUALIFIERS):
        return None
    return False


def opening_window(place: PlaceLite) -> tuple[int, int] | None:
    text = place.intro.get("usetime") or place.intro.get("usetimeculture") or place.intro.get("usetimeleports") \
        or place.intro.get("opentimefood")
    if not text:
        return None
    ranges = re.findall(r"(\d{1,2}):(\d{2})\s*[~∼～\-]\s*(\d{1,2}):(\d{2})", text)
    if len(ranges) != 1:
        return None  # seasonal or multiple ranges: do not guess
    h1, m1, h2, m2 = map(int, ranges[0])
    start, end = h1 * 60 + m1, h2 * 60 + m2
    return (start, end) if 0 <= start < end <= 24 * 60 else None


def fee_krw(place: PlaceLite) -> int | None:
    text = place.intro.get("usefee") or place.intro.get("usefeeleports")
    if not text:
        return None
    amounts = re.findall(r"(\d{1,3}(?:,\d{3})+|\d+)\s*원", text)
    if not amounts and "무료" in text:
        return 0
    return int(amounts[0].replace(",", "")) if len(amounts) == 1 else None


# ---------- ordering ----------

def path_cost(start: tuple[float, float], places: list[PlaceLite]) -> float:
    total, cur = 0.0, start
    for place in places:
        total += haversine_km(cur, place.coord)
        cur = place.coord
    return total


def order_places(start: tuple[float, float], places: list[PlaceLite]) -> list[PlaceLite]:
    """Nearest neighbour from the start, then 2-opt on the open path."""
    rest, route, cur = list(places), [], start
    while rest:
        nxt = min(rest, key=lambda p: (haversine_km(cur, p.coord), p.content_id))
        route.append(nxt)
        rest.remove(nxt)
        cur = nxt.coord
    improved = True
    while improved and len(route) > 2:
        improved = False
        for i in range(len(route) - 1):
            for k in range(i + 1, len(route)):
                trial = route[:i] + route[i:k + 1][::-1] + route[k + 1:]
                if path_cost(start, trial) < path_cost(start, route) - 1e-9:
                    route, improved = trial, True
    return route


def hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


# ---------- course building ----------

@dataclass
class Ctx:
    snapshot: Snapshot
    query: TripQuery
    origin: Origin
    region: str
    program: ProgramSummary | None
    today: date
    constraints: CourseConstraints = field(default_factory=CourseConstraints)
    warnings: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    used_food: set[str] = field(default_factory=set)
    related_ids: set[str] = field(default_factory=set)
    candidates: dict[str, Candidate] = field(default_factory=dict)
    extras: list[PlaceLite] = field(default_factory=list)

    def warn(self, code: str, message: str, **extra) -> None:
        if not any(w["code"] == code and w["message"] == message for w in self.warnings):
            self.warnings.append({"code": code, "message": message, **extra})

    @property
    def dates(self) -> list[date]:
        return [self.query.start_date + timedelta(days=i) for i in range(2 if self.query.trip_type == "1N2D" else 1)]


def resolve_required(ctx: Ctx) -> list[PlaceLite]:
    c = ctx.constraints
    region_places = ctx.snapshot.by_sigungu.get(ctx.region, [])
    found: list[PlaceLite] = []
    for content_id in c.required_content_ids or ():
        place = ctx.snapshot.places.get(content_id)
        if place and place.coord:
            found.append(place)
    def find(name: str) -> PlaceLite | None:
        spots = [p for p in region_places if p.coord and p.content_type_id in SPOT_TYPES]
        exact = [p for p in spots if name_key(p.title) == name_key(name)]
        if len(exact) == 1:
            return exact[0]
        loose = [p for p in spots if name_variants(name, ctx.region) & name_variants(p.title, ctx.region)]
        return loose[0] if not exact and len(loose) == 1 else None

    missing = []
    for name in c.required_place_names or ():
        hit = find(name)
        if hit is None:
            missing.append(name)
        elif hit not in found:
            found.append(hit)
    if missing:
        ctx.warn("required_place_unmatched", "환급 조건의 필수 방문지를 관광 데이터에서 찾지 못해 일정에 넣지 못했어요: "
                 + ", ".join(missing), places=missing)
    if c.any_of_place_names and c.min_any_of:
        options = [hit for name in c.any_of_place_names if (hit := find(name)) and hit not in found]
        found.extend(options[:c.min_any_of])
        if len(options) < c.min_any_of:
            ctx.warn("required_any_unmatched",
                     f"환급 조건의 대상 장소({', '.join(c.any_of_place_names)}) 중 {c.min_any_of}곳 이상을 넣어야 하는데 "
                     f"이 지역 관광 데이터에서 {len(options)}곳만 찾았어요.",
                     places=list(c.any_of_place_names))
    return found


def pick_spots(ctx: Ctx, count: int, required: list[PlaceLite], excluded: set[str]) -> list[PlaceLite]:
    strict = ctx.snapshot.candidates(ctx.region, ctx.query.interests, strict=True)
    loose = ctx.snapshot.candidates(ctx.region, ctx.query.interests, strict=False)
    for cand in strict + loose:
        ctx.candidates.setdefault(cand.place.content_id, cand)
    strict_ids = {c.place.content_id for c in strict}
    chosen = list(required)
    for cand in strict + loose:
        if len(chosen) >= count:
            break
        place = cand.place
        if place in chosen or place.content_id in excluded or not place.coord:
            continue
        if any(closed_on(place, d) is True for d in ctx.dates):
            continue
        if place.content_id not in strict_ids and "interest_widened" not in ctx.notes:
            ctx.notes.append("interest_widened")
        chosen.append(place)
    ctx.extras = [c.place for c in strict + loose
                  if c.place not in chosen and c.place.content_id not in excluded and c.place.coord
                  and not any(closed_on(c.place, d) is True for d in ctx.dates)]
    if len(chosen) < count:
        ctx.warn("not_enough_spots", f"이 지역 관광 데이터가 부족해 관광지를 {len(chosen)}곳만 넣었어요.")
    return chosen


def pick_meal(ctx: Ctx, near: tuple[float, float], day: date) -> PlaceLite | None:
    pool = [p for p in ctx.snapshot.of_type(ctx.region, "39")
            if p.coord and p.content_id not in ctx.used_food and closed_on(p, day) is not True]
    if not pool:
        return None
    rank = lambda p: (p.content_id not in ctx.related_ids, haversine_km(near, p.coord), p.content_id)  # noqa: E731
    close = [p for p in pool if haversine_km(near, p.coord) <= MEAL_RADIUS_KM]
    choice = min(close or pool, key=rank)
    ctx.used_food.add(choice.content_id)
    return choice


def pick_stay(ctx: Ctx, near: tuple[float, float]) -> PlaceLite | None:
    pool = [p for p in ctx.snapshot.of_type(ctx.region, "32") if p.coord]
    return min(pool, key=lambda p: (haversine_km(near, p.coord), p.content_id)) if pool else None


def place_view(place: PlaceLite) -> dict:
    return {"content_id": place.content_id, "title": place.title, "lat": place.lat, "lng": place.lng,
            "category": place.category, "sigungu_code": place.sigungu_code, "source": place.source,
            "image_url": place.image_url if place.cpyright_type in ("Type1", "Type3") else None}


def schedule_day(ctx: Ctx, day_no: int, day: date, start_name: str, start: tuple[float, float],
                 spots: list[PlaceLite], required_ids: set[str], *, with_stay: bool,
                 last_day: bool) -> dict:
    t = DEPART[day_no]
    cur = start
    items: list[dict] = []
    meals = list(MEALS[(ctx.query.trip_type, day_no)])
    queue = list(spots)
    transport = ctx.query.transport
    limit = END_LIMIT[ctx.query.trip_type] if last_day else 24 * 60

    def add(kind: str, place: PlaceLite | None, start_min: int, dwell: int, move: int, **extra) -> None:
        items.append({"order": len(items) + 1, "start": hhmm(start_min),
                      "end": hhmm(start_min + dwell) if dwell else None, "kind": kind,
                      "place": place_view(place) if place else None, "move_min_from_prev": move,
                      "move_warning": move > MOVE_WARN_MIN,
                      "transit_note": "실제 배차 확인" if transport == "transit" else None, **extra})

    while queue or meals:
        meal = meals[0] if meals else None
        nxt = queue[0] if queue else None
        if meal and nxt:
            arrive = t + move_minutes(cur, nxt.coord, transport)
            take_meal = t >= meal[0] - 45 or arrive + dwell_minutes(nxt) > meal[0] + 60
        else:
            take_meal = meal is not None
        if take_meal and not queue and with_stay and ctx.extras:
            # Overnight day: fill a 2h+ idle gap before a meal with one more nearby spot.
            gap = meal[0] - 30 - t
            fits = [p for p in ctx.extras
                    if move_minutes(cur, p.coord, transport) + dwell_minutes(p) <= gap - 30]
            if gap >= 120 and fits:
                extra = min(fits, key=lambda p: (move_minutes(cur, p.coord, transport), p.content_id))
                ctx.extras.remove(extra)
                queue.append(extra)
                continue
        if take_meal:
            meals.pop(0)
            ref, kind, optional = meal
            food = pick_meal(ctx, cur, day)
            move = move_minutes(cur, food.coord, transport) if food else 0
            begin = max(t + move, ref - 30)
            if optional and begin + MEAL_MIN > limit:
                if food:
                    ctx.used_food.discard(food.content_id)
                continue
            if not food:
                ctx.warn("meal_not_found", "이 지역 음식점 정보가 없어 식사 장소를 비워 두었어요.")
            add("meal", food, begin, MEAL_MIN, move, meal=kind, label=None if food else "식사 장소 직접 선택",
                required=False, swappable=False)
            t, cur = begin + MEAL_MIN, food.coord if food else cur
            continue
        queue.pop(0)
        move = move_minutes(cur, nxt.coord, transport)
        dwell = dwell_minutes(nxt)
        window = opening_window(nxt)
        begin = max(t + move, window[0]) if window else t + move  # arrived early: wait for opening
        add("spot", nxt, begin, dwell, move, meal=None, label=None,
            required=nxt.content_id in required_ids, swappable=nxt.content_id not in required_ids)
        t, cur = begin + dwell, nxt.coord
    day_view = {"day": day_no, "date": day.isoformat(), "start_point": start_name, "depart": hhmm(DEPART[day_no]),
                "items": items}
    if with_stay:
        stay = pick_stay(ctx, cur)
        move = move_minutes(cur, stay.coord, transport) if stay else 0
        if not stay:
            ctx.warn("stay_not_found", "이 지역 숙박 정보가 없어 숙소를 비워 두었어요.")
        add("stay", stay, t + move, 0, move, meal=None, label=None if stay else "숙소 직접 선택",
            required=False, swappable=False)
        day_view["stay_coord"] = stay.coord if stay else cur
    else:
        back = move_minutes(cur, (ctx.origin.lat, ctx.origin.lng), transport)
        day_view["return_move_min"] = back
        day_view["return_depart"] = hhmm(t)
        day_view["home_arrival"] = hhmm(t + back)
    day_view["end_min"] = t
    return day_view


def outside_hours(place: PlaceLite, item: dict) -> bool:
    window = opening_window(place)
    if not window or not item.get("end"):
        return False
    start, end = (int(x[:2]) * 60 + int(x[3:]) for x in (item["start"], item["end"]))
    return start < window[0] or end > window[1]


def hours_conflicts(ctx: Ctx, days: list[dict], required_ids: set[str]) -> set[str]:
    """Region spots visited outside a readable opening window; they get replaced by the next candidate."""
    bad = set()
    for day in days:
        for item in day["items"]:
            if item["kind"] != "spot" or item["place"]["content_id"] in required_ids:
                continue
            place = ctx.snapshot.places[item["place"]["content_id"]]
            if place.sigungu_code == ctx.region and outside_hours(place, item):
                bad.add(place.content_id)
    return bad


def build_days(ctx: Ctx, plan: dict, required_ids: set[str]) -> list[dict]:
    origin_point = (ctx.origin.lat, ctx.origin.lng)
    days = []
    if ctx.query.trip_type == "day":
        days.append(schedule_day(ctx, 1, ctx.dates[0], ctx.origin.name, origin_point, plan[1], required_ids,
                                 with_stay=False, last_day=True))
        return days
    day1 = schedule_day(ctx, 1, ctx.dates[0], ctx.origin.name, origin_point, plan[1], required_ids,
                        with_stay=True, last_day=False)
    stay_coord = day1.pop("stay_coord")
    stay_item = day1["items"][-1]
    stay_name = stay_item["place"]["title"] if stay_item["place"] else "숙소"
    day2_spots = plan[2] if plan.get("fixed") else order_places(stay_coord, plan[2])
    day2 = schedule_day(ctx, 2, ctx.dates[1], stay_name, stay_coord, day2_spots, required_ids,
                        with_stay=False, last_day=True)
    return [day1, day2]


def trim_to_limits(ctx: Ctx, plan: dict, required_ids: set[str], link: PlaceLite | None) -> list[dict]:
    """Drop the last swappable spot of the last day until it ends by the limit (19:00 / 17:00)."""
    for _ in range(6):
        days = build_days(ctx, plan, required_ids)
        last = days[-1]
        if last["end_min"] <= END_LIMIT[ctx.query.trip_type]:
            return days
        key = 2 if ctx.query.trip_type == "1N2D" else 1
        removable = [p for p in plan[key] if p.content_id not in required_ids and p is not link]
        if not removable:
            ctx.warn("time_limit", "필수 방문지 때문에 권장 종료 시각을 넘겨요. 일정을 확인해 주세요.")
            return days
        plan[key] = [p for p in plan[key] if p is not removable[-1]]
        ctx.warn("time_trimmed", "권장 종료 시각(당일 19:00, 1박2일 둘째 날 17:00)에 맞추려고 관광지를 줄였어요.")
    return build_days(ctx, plan, required_ids)


def make_plan(ctx: Ctx, required: list[PlaceLite], link: PlaceLite | None, excluded: set[str]) -> dict:
    per_day = {"day": [3], "1N2D": [3, 3]}[ctx.query.trip_type][:]
    if link:
        per_day[0] -= 1
    total = max(sum(per_day), ctx.constraints.min_spots or 0, len(required))
    if total > sum(per_day):
        per_day[-1] += total - sum(per_day)
    spots = pick_spots(ctx, total, required, excluded | ({link.content_id} if link else set()))
    entry = link.coord if link else (ctx.origin.lat, ctx.origin.lng)
    ordered = order_places(entry, spots)
    if ctx.query.trip_type == "day":
        return {1: ([link] if link else []) + ordered}
    first = ordered[:per_day[0]]
    return {1: ([link] if link else []) + first, 2: ordered[per_day[0]:]}


def fixed_plan(ctx: Ctx, fixed: dict[int, list[str]]) -> dict:
    plan: dict = {"fixed": True}
    for day, ids in fixed.items():
        plan[int(day)] = [ctx.snapshot.places[i] for i in ids if i in ctx.snapshot.places
                          and ctx.snapshot.places[i].coord]
    return plan


def stay_checks(ctx: Ctx) -> None:
    c = ctx.constraints
    name = ctx.program.name if ctx.program else "환급제"
    if ctx.query.trip_type == "day" and (c.min_nights or 0) >= 1:
        ctx.warn("needs_stay", f"{name}은(는) {c.min_nights}박 이상 여행이 조건이라 당일 일정에는 적용되지 않을 수 있어요.")
    if ctx.query.trip_type == "1N2D" and c.stay_checkin_weekdays:
        allowed = set(c.stay_checkin_weekdays)
        if ctx.query.start_date.weekday() not in allowed:
            options = [ctx.query.start_date + timedelta(days=sign * k) for k in range(1, 8) for sign in (1, -1)]
            options = [d for d in options if d >= ctx.today and d.weekday() in allowed]
            suggested = min(options, key=lambda d: (abs((d - ctx.query.start_date).days), -d.toordinal()),
                            default=None)
            days = "·".join(WEEKDAY_CHARS[i] for i in sorted(allowed))
            ctx.warn("stay_weekday", f"{name}은(는) {days}요일 체크인 숙박만 인정돼요.",
                     suggested_date=suggested.isoformat() if suggested else None)


def spend(ctx: Ctx, days: list[dict]) -> dict:
    party = ctx.query.party_size
    meal_cost = ctx.query.meal_cost_krw or DEFAULT_MEAL_COST
    items, unknown = [], []
    for day in days:
        for item in day["items"]:
            place = ctx.snapshot.places.get(item["place"]["content_id"]) if item["place"] else None
            code = place.sigungu_code if place else ctx.region
            if item["kind"] == "meal":
                items.append({"label": f"{day['day']}일차 {'점심' if item['meal'] == 'lunch' else '저녁'} "
                                       f"{party}명 × {meal_cost:,}원", "krw": party * meal_cost,
                              "sigungu_code": code, "category": "food",
                              "basis": "user" if ctx.query.meal_cost_krw else "default"})
            elif item["kind"] == "stay":
                if ctx.query.room_price_krw:
                    price, basis = ctx.query.room_price_krw, "user"
                elif place and place.room_price_krw:
                    price, basis = place.room_price_krw, "tourapi_room_fee"
                else:
                    price, basis = DEFAULT_ROOM_PRICE, "default"
                items.append({"label": "숙박 1박(객실 1개 기준)", "krw": price, "sigungu_code": code,
                              "category": "lodging", "basis": basis})
            elif item["kind"] == "spot" and place:
                fee = fee_krw(place)
                if fee:
                    items.append({"label": f"{place.title} 이용요금 {party}명", "krw": fee * party,
                                  "sigungu_code": code, "category": "admission", "basis": "tourapi_usefee"})
                elif fee is None and (place.intro.get("usefee") or place.intro.get("usefeeleports")):
                    unknown.append(place.title)
    by_code: dict[str, int] = {}
    for item in items:
        by_code[item["sigungu_code"]] = by_code.get(item["sigungu_code"], 0) + item["krw"]
    return {"total_krw": sum(i["krw"] for i in items), "items": items, "by_sigungu": by_code,
            "fees_not_parsed": unknown}


def decorate(ctx: Ctx, days: list[dict]) -> None:
    """Rule-based reason tags and refund notes (AI wording comes later)."""
    region_name = sigungu_map()[ctx.region].label
    refund_region = ctx.program is not None and ctx.program.judgment != "ineligible"
    for day in days:
        for item in day["items"]:
            place = ctx.snapshot.places.get(item["place"]["content_id"]) if item["place"] else None
            in_region = bool(place and place.sigungu_code == ctx.region)
            tags = []
            if item.get("required"):
                tags.append("환급 조건 필수 방문지")
            if item["kind"] == "spot" and place:
                cand = ctx.candidates.get(place.content_id)
                if not in_region and place.sigungu_code and place.sigungu_code.startswith("29"):
                    tags.append("광주 문화관광")
                if in_region and refund_region:
                    tags.append("환급 지역")
                tags += [f"관심 분야: {label}" for label in ctx.snapshot.interest_labels(place, ctx.query.interests)[:1]]
                tags += [e for e in (cand.evidence if cand else []) if not e.startswith("관심 분야")][:2]
            elif item["kind"] == "meal":
                tags.append(f"{region_name} 음식점" if place else "식사")
                if place and place.content_id in ctx.related_ids:
                    tags.append("방문객이 함께 찾는 곳")
            elif item["kind"] == "stay":
                tags.append("환급 지역 안 숙소" if refund_region and in_region else f"{region_name} 숙소")
            if item["move_min_from_prev"] and item["move_min_from_prev"] <= 20:
                tags.append(f"이전 장소에서 {item['move_min_from_prev']}분")
            if not tags:
                tags.append(f"{region_name} 관광지")
            item["reason_tags"] = tags
            item["reason_text"] = rule_sentence(tags)
            item["reason_by"] = "rule"
            item["in_refund_region"] = in_region and refund_region
            item["refund_note"] = "영수증 보관" if item["in_refund_region"] and item["kind"] in ("meal", "stay") else None
            checks = []
            if place and item["kind"] in ("spot", "meal"):
                state = closed_on(place, date.fromisoformat(day["date"]))
                if state is None:
                    checks.append("쉬는 날 정보 없음" if not rest_text(place) else "쉬는 날 표기 확인 필요")
                if item["kind"] == "spot" and not opening_window(place):
                    checks.append("이용시간 확인 필요")
                elif item["kind"] == "spot" and outside_hours(place, item):
                    checks.append("이용시간 밖 일정")
            if place and place.source == "demo":
                checks.append("시연 데이터")
            item["check_before_visit"] = bool(checks)
            item["check_reasons"] = checks


def build_course(snapshot: Snapshot, query: TripQuery, origin: Origin, region: str,
                 program: ProgramSummary | None, program_status: str, today: date,
                 fixed: dict[int, list[str]] | None = None) -> dict:
    ctx = Ctx(snapshot, query, origin, region, program, today,
              program.constraints if program else CourseConstraints())
    ctx.related_ids = {r.rel_content_id for r in snapshot.related.get(region, []) if r.rel_content_id}
    stay_checks(ctx)
    required = resolve_required(ctx)
    required_ids = {p.content_id for p in required}
    # No automatic stop outside the chosen destination: the former "Gwangju culture spot first" rule put the
    # same Gwangju place into every course just because the origin was in Gwangju. Spots now come only from
    # the destination's candidates; `link` stays None (kept for the existing plan/trim plumbing).
    link: PlaceLite | None = None
    excluded: set[str] = set()
    base_warnings, base_notes = list(ctx.warnings), list(ctx.notes)
    for _ in range(10):
        ctx.used_food.clear()
        ctx.extras = []
        ctx.warnings, ctx.notes = list(base_warnings), list(base_notes)
        plan = fixed_plan(ctx, fixed) if fixed else make_plan(ctx, required, link, excluded)
        days = trim_to_limits(ctx, plan, required_ids, link)
        conflicts = hours_conflicts(ctx, days, required_ids)
        if fixed or not conflicts:
            break
        excluded |= conflicts
    for day in days:
        day.pop("end_min", None)
    decorate(ctx, days)
    cost = spend(ctx, days)
    if "interest_widened" in ctx.notes:
        ctx.notes = [n for n in ctx.notes if n != "interest_widened"]
        ctx.notes.append("관심 분야에 맞는 장소가 부족해 다른 관광지도 함께 넣었어요.")
    if program_status in ("not_connected", "error"):
        ctx.warn("benefit_unchecked", "지원제도 조건을 확인하지 못해 필수 방문지·숙박 요일 조건을 반영하지 않았어요.")
    if query.transport == "transit":
        ctx.notes.append("대중교통 이동시간은 자차 추정치 × 1.5예요. 실제 배차를 확인하세요.")
    return {
        "trip_type": query.trip_type, **query.public(),
        "region": {"sigungu_code": region, "name": sigungu_map()[region].label,
                   "refund_program_id": program.program_id if program else None,
                   "refund_program": program_view(program, "selected") if program else None,
                   "benefit_status": program_status},
        "days": days,
        "estimated_spend_krw": cost["total_krw"],
        "spend_breakdown": cost,
        "spend_inputs": {"meal_cost_krw": query.meal_cost_krw, "room_price_krw": query.room_price_krw},
        "estimated_refund_krw": None,
        "refund_estimate_note": "예상 지원액은 지원제도 확인 API(POST /api/benefits/check)에 spend_breakdown.by_sigungu를 "
                                "넘겨 계산해요. 이 응답은 금액을 계산하지 않아요.",
        "warnings": ctx.warnings,
        "notes": ctx.notes,
        "generated_at": datetime.now(timezone.utc).astimezone(KST).isoformat(timespec="seconds"),
    }
