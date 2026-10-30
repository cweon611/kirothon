"""Synthetic tourism cache and fake benefit port for F1/F2 tests.

Every place name starts with '테스트' and every coordinate is made up near the
region; none of this is real tourism or benefit data.
"""
from datetime import datetime, timezone
import json

from app.team.benefit_port import BenefitLookup, CourseConstraints, ProgramSummary
from app.team.tourism_data import PlaceLite, Snapshot
from app.team.tourism_models import HubRank, Place, RelatedPlace

MUAN, HAMPYEONG, DONGGU, SINAN = "46840", "46860", "29110", "46910"


def lite(cid, title, code, lat, lng, ctype="12", **intro) -> PlaceLite:
    return PlaceLite(cid, ctype, title, code, lat, lng, intro=dict(intro), has_detail=bool(intro),
                     cpyright_type="Type1", image_url=f"https://example.invalid/{cid}.jpg")


def places() -> list[PlaceLite]:
    return [
        lite("m1", "테스트갯벌랜드", MUAN, 34.990, 126.470, restdate="매주 월요일", usetime="09:00~18:00"),
        lite("m2", "테스트연꽃방죽", MUAN, 34.960, 126.500, restdate="연중무휴", usetime="09:00~18:00"),
        lite("m3", "테스트박물관", MUAN, 35.000, 126.480, "14", restdateculture="연중무휴",
             usetimeculture="09:00~18:00", spendtime="1시간", usefee="성인 2,000원"),
        lite("m4", "테스트승달산", MUAN, 34.950, 126.450),
        lite("m5", "테스트생태공원", MUAN, 35.010, 126.520, restdate="연중무휴", usetime="06:00~22:00"),
        lite("m6", "테스트문화관", MUAN, 34.980, 126.510, "14", restdateculture="매월 첫째 월요일"),
        lite("m7", "테스트레저파크", MUAN, 34.970, 126.490, "28", restdateleports="연중무휴",
             usetimeleports="09:00~18:00"),
        lite("f1", "테스트식당가", MUAN, 34.985, 126.475, "39", restdatefood="연중무휴"),
        lite("f2", "테스트낙지집", MUAN, 34.965, 126.505, "39"),
        lite("f3", "테스트한정식", MUAN, 35.005, 126.515, "39"),
        lite("s1", "테스트펜션", MUAN, 34.995, 126.485, "32"),
        lite("s2", "테스트호텔", MUAN, 34.955, 126.455, "32"),
        *[lite(f"h{i}", f"테스트함평숲{i}", HAMPYEONG, 35.06 + i * 0.004, 126.51 + i * 0.003, restdate="연중무휴",
               usetime="09:00~18:00") for i in range(1, 7)],
        lite("g1", "테스트문화전당", DONGGU, 35.147, 126.920, "14", restdateculture="연중무휴",
             usetimeculture="10:00~18:00", spendtime="1시간"),
        lite("g2", "테스트미술관", DONGGU, 35.150, 126.925, "14"),
        lite("x1", "테스트먼섬", SINAN, 34.680, 125.430),
    ]


def hub_rows() -> list[HubRank]:
    rows = [(MUAN, 1, "m1"), (MUAN, 2, "m3"), (MUAN, 3, "m2"), (HAMPYEONG, 1, "h1"), (DONGGU, 1, "g1")]
    by_id = {p.content_id: p for p in places()}
    return [HubRank(base_ym="202410", sigungu_code=code, rank=rank, hub_code=f"T{cid}", name=by_id[cid].title,
                    lat=by_id[cid].lat, lng=by_id[cid].lng, content_id=cid, match_method="name+coord")
            for code, rank, cid in rows]


def related_rows() -> list[RelatedPlace]:
    return [RelatedPlace(base_ym="202410", sigungu_code=MUAN, src_code="Tm1", src_name="테스트갯벌랜드",
                         rel_code="Tm5", rel_name="테스트생태공원", rel_sigungu_code=MUAN, rank=1,
                         src_content_id="m1", rel_content_id="m5"),
            RelatedPlace(base_ym="202410", sigungu_code=MUAN, src_code="Tm1", src_name="테스트갯벌랜드",
                         rel_code="Tf2", rel_name="테스트낙지집", rel_sigungu_code=MUAN, rank=2,
                         src_content_id="m1", rel_content_id="f2")]


def snapshot(extra: list[PlaceLite] | None = None) -> Snapshot:
    data = {p.content_id: p for p in places() + (extra or [])}
    hubs, related = {}, {}
    for row in hub_rows():
        hubs.setdefault(row.sigungu_code, []).append(row)
    for row in related_rows():
        related.setdefault(row.sigungu_code, []).append(row)
    return Snapshot(data, hubs, related, {})


def program(pid="muan_test", judgment="potentially_eligible", application_open=True, cap=200_000,
            codes=(MUAN,), **constraints) -> ProgramSummary:
    return ProgramSummary(program_id=pid, name=f"{pid} 반값여행", judgment=judgment, round_id=f"{pid}-r1",
                          sigungu_codes=tuple(codes), posted_status="접수중" if application_open else "마감",
                          application_open=application_open, rate=0.5, cap_krw=cap, stale=False,
                          last_verified_at="2026-10-30T09:00:00+09:00", source_url="https://example.invalid/notice",
                          reasons=("테스트 판정",), constraints=CourseConstraints(**constraints))


class FakePort:
    connected = True

    def __init__(self, by_region: dict | None = None, status: str = "ok", alternatives=(), fail: bool = False):
        self.by_region = by_region or {}
        self.status = status
        self.alternatives = tuple(alternatives)
        self.fail = fail
        self.queries = []

    def lookup(self, query):
        self.queries.append(query)
        if self.fail:
            raise RuntimeError("benefit module down")
        return BenefitLookup(self.status, "2026-10-30T09:00:00+09:00",
                             {k: tuple(v) for k, v in self.by_region.items()}, scope_note="테스트 수록 범위",
                             alternatives=self.alternatives)

    def program(self, program_id, query):
        self.queries.append(query)
        for programs in self.by_region.values():
            for item in programs:
                if item.program_id == program_id:
                    return item
        return None


def place_rows() -> list[Place]:
    now = datetime.now(timezone.utc)
    rows = []
    for p in places():
        rows.append(Place(content_id=p.content_id, content_type_id=p.content_type_id, title=p.title,
                          sigungu_code=p.sigungu_code, lat=p.lat, lng=p.lng, image_url=p.image_url,
                          cpyright_type=p.cpyright_type, intro_json=json.dumps(p.intro, ensure_ascii=False)
                          if p.intro else None, overview=f"{p.title} 소개 문장", source="kor", fetched_at=now,
                          detail_fetched_at=now if p.intro else None))
    return rows
