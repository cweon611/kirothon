"""Deterministic eligibility and estimate logic. No AI, no network.

Every check returns one of: met, unmet, missing_user_info,
unconfirmed_program_rule, conflict, not_applicable.

Verdict
- ineligible:            an unmet check whose rule comes from a verified source
- needs_verification:    anything unresolved, or an unmet check based on unverified data
- potentially_eligible:  every check met (approval still not guaranteed)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from .regions import region_label, region_matches
from .schemas import (
    BenefitCheckRequest, BenefitProgram, CapRule, ConditionResult, Estimate, HowToApply,
    MatchedVisit, ProgramEvaluation, Region, Timeline, VisitInput,
)

KST = timezone(timedelta(hours=9))
STALE_DAYS = 7
CLOSED = {"closed", "closed_early", "budget_exhausted", "ended"}


def today_kst() -> date:
    return datetime.now(KST).date()


def visit_dates(v: VisitInput) -> list[date]:
    return [v.start_date + timedelta(days=i) for i in range((v.end_date - v.start_date).days + 1)]


# ------------------------------------------------------------------ age helpers
def _full_age(birth: date, on: date) -> int:
    return on.year - birth.year - ((on.month, on.day) < (birth.month, birth.day))


def possible_ages(req: BenefitCheckRequest, basis: str, on: date, ref: date) -> set[int] | None:
    """Ages the user can have under ``basis`` on date ``on``. None if no age info."""
    if req.birth_date:
        if basis == "birth_year":
            return {on.year - req.birth_date.year}
        return {_full_age(req.birth_date, on)}
    if req.age is None:
        return None
    # Only "full age on ref" is known, so the birth date lies in (ref - (A+1)y, ref - A y].
    youngest = _years_before(ref, req.age)
    oldest = _years_before(ref, req.age + 1) + timedelta(days=1)
    if basis == "birth_year":
        return {on.year - youngest.year, on.year - oldest.year}
    return set(range(_full_age(youngest, on), _full_age(oldest, on) + 1))


def _years_before(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year - years)
    except ValueError:  # Feb 29
        return d.replace(year=d.year - years, day=28)


def _basis_dates(basis: str | None, fixed: date | None, trip_start: date, ref: date):
    table = {
        "full_age_on_trip_start": [("full_age_on_trip_start", trip_start)],
        "full_age_on_application_date": [("full_age_on_application_date", ref)],
        "birth_year": [("birth_year", trip_start)],
    }
    if basis == "full_age_on_fixed_date" and fixed:
        return [("full_age_on_fixed_date", fixed)], True
    if basis in table:
        return table[basis], True
    # basis unknown -> evaluate every plausible basis and see if the answer changes
    return [("full_age_on_trip_start", trip_start), ("full_age_on_application_date", ref),
            ("birth_year", trip_start)], False


def age_in_range(req, lo, hi, basis, fixed, trip_start, ref):
    """Return (status, detail). status in met/unmet/missing_user_info/unconfirmed_program_rule."""
    options, basis_known = _basis_dates(basis, fixed, trip_start, ref)
    outcomes = []
    for name, on in options:
        ages = possible_ages(req, name, on, ref)
        if ages is None:
            return "missing_user_info", "생년월일 또는 나이 미입력"
        ok = {(lo is None or a >= lo) and (hi is None or a <= hi) for a in ages}
        outcomes.append((name, on, ages, ok))
    flat = set().union(*(o[3] for o in outcomes))
    rng = f"{lo if lo is not None else ''}~{hi if hi is not None else ''}세"
    desc = ", ".join(f"{n}({d}): {sorted(a)}세" for n, d, a, _ in outcomes)
    if flat == {True}:
        return "met", f"기준 {rng} 충족 [{desc}]"
    if flat == {False}:
        return "unmet", f"기준 {rng} 불충족 [{desc}]"
    # Mixed result. With a known basis only the unknown birthday can cause it.
    if basis_known:
        return "missing_user_info", f"생일에 따라 결과가 달라짐(기준 {rng}) — 생년월일 필요 [{desc}]"
    return "unconfirmed_program_rule", f"연령 판정 기준일에 따라 결과가 달라짐(기준 {rng}) [{desc}]"


# ------------------------------------------------------------------ evaluation
@dataclass
class _Ctx:
    req: BenefitCheckRequest
    program: BenefitProgram
    visits: list[tuple[int, VisitInput, str]]
    ref: date
    verified: bool
    results: list[ConditionResult] = field(default_factory=list)
    official: list[str] = field(default_factory=list)

    @property
    def data_trusted(self) -> bool:
        """Collected data counts only while fresh, present in the source, and conflict-free."""
        s = self.program.sync
        return s is None or not (s.stale or s.missing_from_source_since or s.review_status == "conflict")

    def add(self, code, label, status, detail, user_fields=(), program_fields=()):
        roots = {f.split(".")[0] for f in program_fields}
        confirmed = self.data_trusted and (
            self.verified or (bool(roots) and roots <= set(self.program.verified_fields)))
        self.results.append(ConditionResult(code=code, label=label, status=status, detail=detail,
                                            rule_confirmed=confirmed,
                                            user_fields=list(user_fields),
                                            program_fields=list(program_fields)))

    @property
    def first_day(self) -> date:
        return min(v.start_date for _, v, _ in self.visits)

    @property
    def last_day(self) -> date:
        return max(v.end_date for _, v, _ in self.visits)


def match_visits(program: BenefitProgram, req: BenefitCheckRequest):
    matched = []
    for i, v in enumerate(req.visits):
        if program.target_regions:
            if any(region_matches(t, v.region) for t in program.target_regions):
                matched.append((i, v, "target_region"))
        elif program.region_hints:
            if any(region_matches(h, v.region) for h in program.region_hints):
                matched.append((i, v, "text_hint"))
    return matched


def _check_status(c: _Ctx):
    p = c.program
    if p.posted_status is None:
        c.add("posted_status", "게시된 접수 상태", "unconfirmed_program_rule", "접수 상태 미확인",
              program_fields=["posted_status"])
    elif p.posted_status in CLOSED:
        c.add("posted_status", "게시된 접수 상태", "unmet", f"게시 상태: {p.posted_status}",
              program_fields=["posted_status"])
    elif p.posted_status == "upcoming":
        c.add("posted_status", "게시된 접수 상태", "unconfirmed_program_rule", "접수 시작 전",
              program_fields=["posted_status"])
    else:
        c.add("posted_status", "게시된 접수 상태", "met", f"게시 상태: {p.posted_status}",
              program_fields=["posted_status"])
    if p.posted_status and (p.status_checked_at is None or
                            (c.ref - p.status_checked_at.astimezone(KST).date()).days > STALE_DAYS):
        c.official.append(f"접수 상태 확인 시각이 {STALE_DAYS}일보다 오래됨 — 공고 재확인 필요")


def _check_application_period(c: _Ctx):
    ap = c.program.application_period
    label = "신청(접수) 기간"
    if ap is None:
        c.add("application_period", label, "unconfirmed_program_rule", "접수 기간 미확인",
              program_fields=["application_period"])
        return
    p = c.program
    start_txt = p.application_start_at.astimezone(KST).strftime("%Y-%m-%d %H:%M") if p.application_start_at else ap.start
    end_txt = p.application_end_at.astimezone(KST).strftime("%Y-%m-%d %H:%M") if p.application_end_at else ap.end
    if ap.end is not None and c.ref > ap.end:
        c.add("application_period", label, "unmet", f"접수 마감 {end_txt} (기준일 {c.ref})",
              program_fields=["application_period.end"])
    elif ap.start is not None and c.ref < ap.start:
        c.add("application_period", label, "unconfirmed_program_rule", f"접수 시작 전 (시작 {start_txt})",
              program_fields=["application_period.start"])
    elif ap.end is None:
        c.add("application_period", label, "unconfirmed_program_rule",
              f"접수 시작 {start_txt or '미확인'}, 마감일 미확인(예산 소진 시 마감 가능)",
              program_fields=["application_period.end"])
    elif ap.start is None:
        c.add("application_period", label, "unconfirmed_program_rule",
              f"접수 마감 {end_txt}, 시작일 미확인", program_fields=["application_period.start"])
    else:
        c.add("application_period", label, "met", f"접수 기간 {start_txt}~{end_txt} 내 (기준일 {c.ref})",
              program_fields=["application_period"])


def pre_apply_deadlines(c: _Ctx) -> dict[str, date] | None:
    pa = c.program.pre_apply
    if pa is None or not pa.required or pa.days_before_trip is None:
        return None
    n = pa.days_before_trip
    return {"trip_start": c.req.trip_start - timedelta(days=n),
            "region_visit_start": c.first_day - timedelta(days=n)}


def _check_pre_apply(c: _Ctx):
    pa = c.program.pre_apply
    label = "사전 신청 기한"
    if pa is None:
        c.add("pre_apply", label, "unconfirmed_program_rule", "사전 신청 필요 여부 미확인",
              program_fields=["pre_apply"])
        return
    if not pa.required:
        c.add("pre_apply", label, "not_applicable", "사전 신청 불필요(확인됨)")
        return
    if pa.days_before_trip is None:
        c.add("pre_apply", label, "unconfirmed_program_rule", "사전 신청 필요, 기한(여행 N일 전) 미확인",
              program_fields=["pre_apply.days_before_trip"])
        return
    d = pre_apply_deadlines(c)
    passed = {k: c.ref > v for k, v in d.items()}
    if all(passed.values()):
        c.add("pre_apply", label, "unmet",
              f"사전 신청 기한 {d['region_visit_start']} 경과 (기준일 {c.ref})",
              program_fields=["pre_apply.days_before_trip"])
    elif not any(passed.values()):
        c.add("pre_apply", label, "met", f"사전 신청 기한 {min(d.values())}까지 가능",
              program_fields=["pre_apply.days_before_trip"])
    else:
        c.add("pre_apply", label, "unconfirmed_program_rule",
              f"기한 기준(전체 여행 시작 {d['trip_start']} / 해당 지역 방문 시작 {d['region_visit_start']})에 따라 결과가 달라짐",
              program_fields=["pre_apply.basis"])
    if pa.channel:
        c.official.append(f"사전 신청 채널: {pa.channel}")


def _check_trip_period(c: _Ctx):
    tp = c.program.trip_period
    label = "여행 인정 기간"
    if tp is None:
        c.add("trip_period", label, "unconfirmed_program_rule", "여행 인정 기간 미확인",
              program_fields=["trip_period"])
        return
    days = sorted({d for _, v, _ in c.visits for d in visit_dates(v)})
    inside, outside, unknown = [], [], []
    for d in days:
        if (tp.start and d < tp.start) or (tp.end and d > tp.end):
            outside.append(d)
        elif tp.start is None or tp.end is None:
            unknown.append(d)
        else:
            inside.append(d)
    rng = f"{tp.start or '?'}~{tp.end or '?'}"
    if outside and not inside and not unknown:
        c.add("trip_period", label, "unmet", f"방문일 {days[0]}~{days[-1]}이 인정 기간 {rng} 밖",
              program_fields=["trip_period"])
    elif outside:
        c.add("trip_period", label, "unconfirmed_program_rule",
              f"일부 방문일({', '.join(map(str, outside))})이 인정 기간 {rng} 밖 — 부분 인정 여부 공고 확인",
              program_fields=["trip_period"])
    elif unknown:
        c.add("trip_period", label, "unconfirmed_program_rule", f"인정 기간 {rng} 중 한쪽 끝 미확인",
              program_fields=["trip_period"])
    else:
        c.add("trip_period", label, "met", f"방문일 {days[0]}~{days[-1]} 모두 인정 기간 {rng} 안",
              program_fields=["trip_period"])


def _check_residence(c: _Ctx):
    rule = c.program.residence_rule
    label = "거주지 조건"
    if rule is None:
        c.add("residence", label, "unconfirmed_program_rule", "거주지 제한 미확인",
              program_fields=["residence_rule"])
        return
    res = c.req.residence
    excluded = (rule.excluded_regions if rule.exclude_scope == "listed"
                else [v.region for _, v, _ in c.visits])
    if not excluded:
        c.add("residence", label, "met", "거주지 제외 조건 없음(확인됨)", program_fields=["residence_rule"])
        return
    if res is None:
        c.add("residence", label, "missing_user_info", "주민등록상 거주지 미입력", user_fields=["residence"])
        return
    needs_sigungu = any(e.sigungu for e in excluded) and not res.sigungu
    if needs_sigungu:
        c.add("residence", label, "missing_user_info", "시군구 단위 제외 조건 — 거주 시군구 필요",
              user_fields=["residence.sigungu"])
        return
    hit = [e for e in excluded if region_matches(e, res)]
    names = ", ".join(region_label(e) for e in excluded)
    if hit:
        c.add("residence", label, "unmet", f"거주지 {region_label(res)}는 제외 지역({names})",
              program_fields=["residence_rule"])
    else:
        c.add("residence", label, "met", f"거주지 {region_label(res)}는 제외 지역({names}) 아님",
              program_fields=["residence_rule"])


def _check_age(c: _Ctx):
    rule = c.program.age_rule
    label = "연령 조건"
    if rule is None:
        c.add("age", label, "unconfirmed_program_rule", "연령 조건 미확인", program_fields=["age_rule"])
        return
    if rule.min_age is None and rule.max_age is None:
        c.add("age", label, "met", "연령 제한 없음(확인됨)", program_fields=["age_rule"])
        return
    status, detail = age_in_range(c.req, rule.min_age, rule.max_age, rule.basis,
                                  rule.fixed_reference_date, c.first_day, c.ref)
    needs_birth = status == "missing_user_info" or (status == "unconfirmed_program_rule"
                                                    and c.req.birth_date is None)
    c.add("age", label, status, detail,
          user_fields=["birth_date"] if needs_birth else [],
          program_fields=["age_rule.basis"] if status == "unconfirmed_program_rule" else ["age_rule"])


def youth_status(c: _Ctx) -> tuple[bool | None, str]:
    rule = c.program.youth_rule
    if rule is None:
        return None, "청년 기준 미확인"
    status, detail = age_in_range(c.req, rule.min_age, rule.max_age, rule.basis,
                                  rule.fixed_reference_date, c.first_day, c.ref)
    return {"met": True, "unmet": False}.get(status), detail


def _check_party(c: _Ctx):
    rule = c.program.party_rule
    label = "인원 조건"
    if rule is None:
        c.add("party_size", label, "unconfirmed_program_rule", "인원 조건 미확인", program_fields=["party_rule"])
        return
    n = c.req.party_size
    if n is None:
        c.add("party_size", label, "missing_user_info", "여행 인원 미입력", user_fields=["party_size"])
        return
    ok = (rule.min_size is None or n >= rule.min_size) and (rule.max_size is None or n <= rule.max_size)
    c.add("party_size", label, "met" if ok else "unmet",
          f"{n}명 (기준 {rule.min_size or ''}~{rule.max_size or ''}명)", program_fields=["party_rule"])


def _check_family(c: _Ctx):
    rule = c.program.family_rule
    label = "가족·동일 주소 조건"
    if rule is None:
        c.add("family", label, "unconfirmed_program_rule", "가족 조건 미확인", program_fields=["family_rule"])
        return
    if not rule.requires_family and not rule.requires_same_address:
        c.add("family", label, "not_applicable", "가족·동일 주소 조건 없음(확인됨)")
        return
    for need, value, uf, text in ((rule.requires_family, c.req.is_family, "is_family", "가족 여부"),
                                  (rule.requires_same_address, c.req.same_address, "same_address", "동일 주소 여부")):
        if not need:
            continue
        if value is None:
            c.add(uf, label, "missing_user_info", f"{text} 미입력", user_fields=[uf])
        else:
            c.add(uf, label, "met" if value else "unmet", f"{text}: {'예' if value else '아니오'}",
                  program_fields=["family_rule"])


def _check_participation(c: _Ctx):
    rule = c.program.participation_rule
    label = "과거 참여 이력"
    if rule is None:
        c.add("participation", label, "unconfirmed_program_rule", "재참여 제한 미확인",
              program_fields=["participation_rule"])
        return
    if rule.repeat_allowed:
        c.add("participation", label, "met", "재참여 허용(확인됨)", program_fields=["participation_rule"])
        return
    history = c.req.prior_participated_program_ids
    if history is None:
        c.add("participation", label, "missing_user_info", "동일 사업 참여 이력 미입력",
              user_fields=["prior_participated_program_ids"])
        return
    same = {c.program.program_id, c.program.id, *rule.same_program_ids}
    hit = same & set(history)
    c.add("participation", label, "unmet" if hit else "met",
          "동일 사업 참여 이력 있음" if hit else "동일 사업 참여 이력 없음", program_fields=["participation_rule"])


def _norm(s: str) -> str:
    return s.replace(" ", "")


def _check_visits(c: _Ctx):
    rule = c.program.visit_rule
    label = "필수 방문 조건"
    if rule is None:
        c.add("visit_places", label, "unconfirmed_program_rule", "필수 방문 조건 미확인",
              program_fields=["visit_rule"])
        return
    if not (rule.must_include or rule.any_of or rule.min_total_places):
        c.add("visit_places", label, "not_applicable", "필수 방문 조건 없음(확인됨)")
        return
    unknown = [f"visits[{i}].places" for i, v, _ in c.visits if v.places is None]
    places = [_norm(p) for _, v, _ in c.visits for p in (v.places or [])]
    has = lambda name: any(_norm(name) in p for p in places)  # noqa: E731
    problems = [f"'{n}' 미포함" for n in rule.must_include if not has(n)]
    hits = [n for n in rule.any_of if has(n)]
    if rule.any_of and len(hits) < rule.min_any_of:
        problems.append(f"대상 장소 {rule.min_any_of}곳 이상 필요(일치 {len(hits)}곳)")
    if rule.min_total_places and len(set(places)) < rule.min_total_places:
        problems.append(f"방문지 {rule.min_total_places}곳 이상 필요(입력 {len(set(places))}곳)")
    if problems and unknown:
        c.add("visit_places", label, "missing_user_info",
              "방문 장소 미입력 지역이 있어 판단 불가: " + "; ".join(problems), user_fields=unknown)
        return
    c.add("visit_places", label, "unmet" if problems else "met",
          "; ".join(problems) if problems else "필수 방문 조건 충족", program_fields=["visit_rule"])


def _checkins(v: VisitInput) -> list[date] | None:
    if v.nights == 0:
        return []
    if v.checkin_dates:
        return sorted(v.checkin_dates)
    if v.nights is not None and v.nights == (v.end_date - v.start_date).days:
        return [v.start_date + timedelta(days=i) for i in range(v.nights)]  # consecutive nights
    return None


def _check_stay(c: _Ctx):
    rule = c.program.stay_rule
    label = "숙박 조건"
    if rule is None:
        c.add("stay", label, "unconfirmed_program_rule", "숙박 조건 미확인", program_fields=["stay_rule"])
        return
    if rule.min_nights == 0 and rule.checkin_weekdays is None:
        c.add("stay", label, "not_applicable", "숙박 조건 없음(확인됨)")
        return
    missing = [f"visits[{i}].nights" for i, v, _ in c.visits if v.nights is None]
    if missing:
        c.add("stay", label, "missing_user_info", "지역 숙박 수 미입력", user_fields=missing)
        return
    nights = sum(v.nights for _, v, _ in c.visits)
    if nights < rule.min_nights:
        c.add("stay", label, "unmet", f"숙박 {nights}박 < 최소 {rule.min_nights}박", program_fields=["stay_rule"])
        return
    if rule.checkin_weekdays is None:
        c.add("stay", label, "met", f"숙박 {nights}박 (요일 제한 없음)", program_fields=["stay_rule"])
        return
    checkins = []
    for i, v, _ in c.visits:
        ci = _checkins(v)
        if ci is None:
            c.add("stay", label, "missing_user_info", "체크인 날짜 필요(연속 숙박이 아님)",
                  user_fields=[f"visits[{i}].checkin_dates"])
            return
        checkins.extend(ci)
    checkins.sort()
    ok_day = lambda d: d.weekday() in rule.checkin_weekdays  # noqa: E731
    first_ok = ok_day(checkins[0])
    all_ok = all(ok_day(d) for d in checkins)
    names = "월화수목금토일"
    allowed = "".join(names[d] for d in rule.checkin_weekdays)
    detail = f"체크인 {', '.join(f'{d}({names[d.weekday()]})' for d in checkins)}, 허용 요일 {allowed}"
    scope = rule.checkin_scope
    result = (first_ok if scope == "first" else all_ok if scope == "all" else
              (True if all_ok else False if not first_ok else None))
    if result is None:
        c.add("stay", label, "unconfirmed_program_rule", detail + " — 요일 조건 적용 범위 미확인",
              program_fields=["stay_rule.checkin_scope"])
    else:
        c.add("stay", label, "met" if result else "unmet", detail, program_fields=["stay_rule"])


def _check_freshness(c: _Ctx):
    s = c.program.sync
    if s is None:
        return
    last = s.last_success_at.astimezone(KST).strftime("%Y-%m-%d %H:%M") if s.last_success_at else "없음"
    if s.stale:
        c.add("data_freshness", "정보 최신성", "unconfirmed_program_rule",
              f"마지막 정상 수집 {last} — 갱신 주기를 넘겨 오래된 정보", program_fields=["sync"])
    if s.missing_from_source_since:
        c.add("source_presence", "원본 게시 여부", "unconfirmed_program_rule",
              "최근 정상 수집에서 이 항목이 보이지 않음 — 종료·마감으로 단정하지 않고 공식 확인 필요",
              program_fields=["sync"])
    if s.review_status == "conflict":
        c.add("review_status", "수집 자료 검토 상태", "conflict",
              "같은 공식 출처 안에서 값이 맞지 않음 — 판정·금액 확정에 쓰지 않음", program_fields=["sync"])


# gov24 lists every public service whose name contains "여행/관광/휴가" (school trips,
# welfare outings ...). Only services whose official text names visitors as the target
# are treated as travel support for a general tourist.
VISITOR_WORDS = ("관광객", "여행객", "방문객", "외지인", "관외 거주", "타 지역 거주", "타지역 거주",
                 "반값여행", "휴가지원", "휴가 지원")
RESTRICTED_WORDS = ("수급자", "차상위", "저소득", "학생", "아동", "청소년", "영유아", "장애인", "노인", "어르신",
                    "한부모", "다문화", "임산부", "보훈", "농업인", "어업인", "근로자", "소상공인", "재학",
                    "주민", "군민", "시민", "도민", "구민", "거주자", "기업")


def audience_check(p: BenefitProgram) -> tuple[str, str] | None:
    """gov24 only: ("met" | "unmet", detail) from the official text; None for other sources."""
    if p.source_type != "gov24_api":
        return None
    texts = [p.name] + [p.raw_text.get(k, "") for k in ("지원대상", "선정기준", "서비스목적요약", "서비스목적")]
    blob = " ".join(texts)
    target = (p.raw_text.get("지원대상") or "").strip()
    quote = f"원문 지원대상: {target[:80]}" if target else "원문 지원대상 없음"
    if any(w in blob for w in VISITOR_WORDS):
        return "met", f"원문에 방문객 대상 표현이 있음 — {quote}"
    restricted = [w for w in RESTRICTED_WORDS if w in blob]
    return "unmet", (f"특정 대상({', '.join(restricted[:4])}) 전용으로 보임 — {quote}" if restricted
                     else f"방문객 대상이라는 근거가 원문에 없음 — {quote}")


def _check_audience(c: _Ctx):
    result = audience_check(c.program)
    if result:
        c.add("audience", "지원 대상(일반 관광객 여부)", result[0], result[1], program_fields=["raw_text"])


def _check_source(c: _Ctx):
    p = c.program
    if p.verification_status != "verified":
        c.add("source_verification", "출처 검증", "unconfirmed_program_rule",
              f"공식 공고로 검토되지 않은 자료({p.source_type}) — 공식 공고 확인 필요",
              program_fields=["verification_status"])
    for conflict in p.conflicts:
        c.add(f"conflict:{conflict.field}", "출처 충돌", "conflict",
              f"{conflict.field}: " + " / ".join(f"{v.get('source')}={v.get('value')}" for v in conflict.values),
              program_fields=[conflict.field])


# ------------------------------------------------------------------ estimate
def _recognized_spend(c: _Ctx, est: Estimate, reasons: list[str], missing: set[str]):
    b = c.program.benefit
    if b.eligible_spend is None:
        reasons.append("인정 지출 항목 미확인")
        return None, False
    total, lodging_counted = 0, False
    single = len(c.req.visits) == 1
    for i, v, _ in c.visits:
        spend = v.expected_spend
        if spend is None and single and c.req.expected_spend_total is not None:
            reasons.append("항목별 예상 지출이 없어 인정 지출을 구분할 수 없음")
            missing.add(f"visits[{i}].expected_spend.by_category")
            return None, False
        if spend is None:
            reasons.append(f"{region_label(v.region)} 예상 지출 미입력")
            missing.add(f"visits[{i}].expected_spend")
            return None, False
        if not spend.by_category:
            reasons.append(f"{region_label(v.region)} 항목별 지출 필요(인정 항목만 합산)")
            missing.add(f"visits[{i}].expected_spend.by_category")
            return None, False
        excluded = set(b.excluded_spend or [])
        for cat, amount in spend.by_category.items():
            if cat not in b.eligible_spend or cat in excluded:
                if amount:
                    est.notes.append(f"{cat} {amount:,}원은 인정 항목이 아니어서 제외")
                continue
            if cat == "lodging" and amount:
                lodging_counted = True
                cap = b.lodging_cap
                if cap and cap.applies:
                    if cap.amount_per_night is None or v.nights is None:
                        reasons.append("숙박 1박 한도 금액 또는 숙박 수 미확인")
                        return None, False
                    limit = cap.amount_per_night * v.nights
                    if amount > limit:
                        est.notes.append(f"숙박비 {amount:,}원 → 1박 한도 적용 {limit:,}원")
                        amount = limit
            total += amount
    return total, lodging_counted


def _select_cap(c: _Ctx, caps: list[CapRule], youth: bool | None, reasons, missing) -> CapRule | None:
    req = c.req
    nights = None
    if all(v.nights is not None for _, v, _ in c.visits):
        nights = sum(v.nights for _, v, _ in c.visits)
    needs = {
        "party_size": any(x.min_party_size or x.max_party_size or x.per == "person" for x in caps),
        "nights": any(x.min_nights is not None or x.max_nights is not None for x in caps),
        "youth": any(x.youth is not None for x in caps),
        "family": any(x.family is not None for x in caps),
    }
    if needs["party_size"] and req.party_size is None:
        reasons.append("여행 인원 미입력"); missing.add("party_size")
    if needs["nights"] and nights is None:
        reasons.append("숙박 수 미입력"); missing.update(f"visits[{i}].nights" for i, v, _ in c.visits if v.nights is None)
    if needs["youth"] and youth is None:
        reasons.append("청년 여부 판단 불가"); missing.add("birth_date")
    if needs["family"] and req.is_family is None:
        reasons.append("가족 여부 미입력"); missing.add("is_family")
    if reasons:
        return None

    def fits(x: CapRule) -> bool:
        n = req.party_size
        return ((x.min_party_size is None or n >= x.min_party_size)
                and (x.max_party_size is None or n <= x.max_party_size)
                and (x.min_nights is None or nights >= x.min_nights)
                and (x.max_nights is None or nights <= x.max_nights)
                and (x.youth is None or x.youth == youth)
                and (x.family is None or x.family == req.is_family))
    matched = [x for x in caps if fits(x)]
    if not matched:
        reasons.append("해당하는 지원 상한 구간 없음")
        return None
    if len(matched) > 1:
        reasons.append("적용 가능한 상한 구간이 여러 개(" + ", ".join(x.label for x in matched) + ") — 공고 확인 필요")
        return None
    return matched[0]


def estimate(c: _Ctx, verdict: str) -> tuple[Estimate, set[str]]:
    b = c.program.benefit
    missing: set[str] = set()
    if b is None:
        return Estimate(unavailable_reasons=["혜택(환급률·상한) 규칙 미확인"]), missing
    est = Estimate(benefit_type=b.benefit_type)
    if verdict == "ineligible":
        est.unavailable_reasons.append("확인된 필수 조건 불충족으로 계산하지 않음")
        return est, missing
    if c.program.sync and c.program.sync.review_status == "conflict":
        est.unavailable_reasons.append("수집 자료에 출처 충돌이 있어 금액을 계산하지 않음")
        return est, missing
    reasons: list[str] = []
    youth, _ = youth_status(c)
    rate = b.refund_rate
    if b.youth_refund_rate is not None:
        if youth is None:
            reasons.append("청년 환급률 적용 여부 판단 불가")
            missing.add("birth_date")
        elif youth:
            rate = b.youth_refund_rate
    if rate is None:
        reasons.append("환급률 미확인")
    spend, lodging_counted = _recognized_spend(c, est, reasons, missing)
    tier = None
    if b.caps is None:
        reasons.append("지원 상한 미확인")
    else:
        tier = _select_cap(c, b.caps, youth, reasons, missing)
    min_spend = tier.min_spend if tier and tier.min_spend is not None else b.min_spend
    if tier is not None and min_spend is None:
        reasons.append("최소 인정 소비액 미확인")
    if reasons:
        est.unavailable_reasons = list(dict.fromkeys(reasons))
        est.recognized_spend = spend
        return est, missing

    cap = tier.amount
    if tier.per == "person":
        persons = c.req.party_size if tier.max_persons is None else min(c.req.party_size, tier.max_persons)
        cap = tier.amount * persons
    est.recognized_spend, est.refund_rate = spend, rate
    est.cap_label, est.cap_amount, est.min_spend = tier.label, cap, min_spend
    if spend < min_spend:
        est.amount, est.amount_kind = 0, "calculated"
        est.shortfall_to_min_spend = min_spend - spend
        est.notes.append(f"인정 지출이 최소 {min_spend:,}원보다 {min_spend - spend:,}원 적음")
        return est, missing
    raw = int(spend * rate)
    amount = min(raw, cap)
    kind = "calculated"
    if b.rounding_unit is None:
        kind = "upper_bound"
        est.notes.append("절사 규칙 미확인 — 실제 지급액은 이보다 적을 수 있음")
    else:
        amount = amount // b.rounding_unit * b.rounding_unit
    if lodging_counted and b.lodging_cap is None:
        kind = "upper_bound"
        est.notes.append("숙박 1박 한도 여부 미확인 — 실제 지급액은 이보다 적을 수 있음")
    if c.program.verification_status != "verified":
        est.notes.append("공식 공고로 검토되지 않은 자료 기준 계산(참고용, 확정 금액 아님)")
    est.amount, est.amount_kind = amount, kind
    return est, missing


# ------------------------------------------------------------------ public
def evaluate(program: BenefitProgram, origin: str, req: BenefitCheckRequest, ref: date) -> ProgramEvaluation | None:  # noqa: C901
    visits = match_visits(program, req)
    if not visits:
        return None
    c = _Ctx(req=req, program=program, visits=visits, ref=ref,
             verified=program.verification_status == "verified")
    for check in (_check_status, _check_application_period, _check_pre_apply, _check_trip_period,
                  _check_residence, _check_age, _check_party, _check_family, _check_participation,
                  _check_visits, _check_stay, _check_freshness, _check_audience, _check_source):
        check(c)

    unmet = [r for r in c.results if r.status == "unmet"]
    unresolved = [r for r in c.results if r.status in
                  {"missing_user_info", "unconfirmed_program_rule", "conflict"}]
    met = [r for r in c.results if r.status in {"met", "not_applicable"}]
    if any(r.rule_confirmed for r in unmet):
        verdict = "ineligible"
    elif unmet or unresolved:
        verdict = "needs_verification"
    else:
        verdict = "potentially_eligible"

    est, est_missing = estimate(c, verdict)
    missing = sorted({f for r in unresolved for f in r.user_fields} | est_missing)
    official = list(dict.fromkeys(
        [f"{r.label}: {r.detail}" for r in unresolved if r.status != "missing_user_info"]
        + [f"미검증 자료 기준 불충족: {r.label}" for r in unmet if not r.rule_confirmed]
        + c.official
        + [f"미확인 항목: {', '.join(program.unverified_fields)}"] * bool(program.unverified_fields)))
    if any(m == "text_hint" for _, _, m in visits):
        official.insert(0, "대상 지역이 구조화되어 있지 않아 기관명·본문 텍스트로만 연결됨 — 대상 지역 확인 필요")

    closed_codes = {"posted_status", "application_period", "pre_apply"}
    blocking = [r for r in unmet if r.code in closed_codes]
    open_ok = all(any(r.code == code and r.status in {"met", "not_applicable"} and r.rule_confirmed
                      for r in c.results) for code in closed_codes)
    can_apply = False if blocking else (True if open_ok else None)

    p = program
    deadlines = pre_apply_deadlines(c)
    settle = (c.last_day + timedelta(days=p.settlement_days_after_trip)
              if p.settlement_days_after_trip is not None else None)
    timeline = Timeline(
        application_period=p.application_period,
        application_start_at=p.application_start_at, application_end_at=p.application_end_at,
        budget_remaining=p.budget_remaining,
        application_closed=(c.ref > p.application_period.end
                            if p.application_period and p.application_period.end else None),
        pre_apply_deadline=min(deadlines.values()) if deadlines else None,
        pre_apply_deadline_passed=(c.ref > min(deadlines.values())) if deadlines else None,
        trip_period=p.trip_period,
        settlement_deadline=settle,
        posted_status=p.posted_status,
        status_checked_at=p.status_checked_at,
    )
    how = HowToApply(
        application_url=p.application_url, official_info_url=p.official_info_url, contacts=p.contacts,
        pre_apply_channel=p.pre_apply.channel if p.pre_apply else None,
        payment_methods=p.payment_rule.methods if p.payment_rule else None,
        proof_items=p.proof_items, payout=p.payout,
    )
    return ProgramEvaluation(
        benefit_id=p.id, program_id=p.program_id, round_id=p.round_id, name=p.name, provider=p.provider,
        data_origin=origin, source_type=p.source_type, verification_status=p.verification_status,
        review_status=p.sync.review_status if p.sync else None, data_freshness=p.sync,
        verdict=verdict, can_apply_now=can_apply,
        matched_visits=[MatchedVisit(region=v.region, start_date=v.start_date, end_date=v.end_date,
                                     match_basis=m) for _, v, m in visits],
        met_conditions=met, unmet_conditions=unmet, unresolved_conditions=unresolved,
        missing_user_fields=missing, official_checks_needed=official,
        timeline=timeline, estimate=est, how_to_apply=how,
        sources=p.sources, last_verified_at=p.last_verified_at, conflicts=p.conflicts,
        related_program_ids=p.related_program_ids,
    )


def visit_regions(req: BenefitCheckRequest) -> list[Region]:
    seen = {}
    for v in req.visits:
        seen.setdefault(region_label(v.region), v.region)
    return list(seen.values())
