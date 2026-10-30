"""한국관광공사 '대한민국 반값여행' 현황 페이지 수집 (official_webpage).

URL: https://korean.visitkorea.or.kr/dgtourcard/tour50.do
- 공개 API가 아닌 공식 웹페이지다. robots.txt(User-agent: *)는 Allow: / (2026-10-30 확인).
- 페이지는 서버에서 렌더링되며 지역별 <aside class="cl-posi-detail" data-…> 블록과
  '지역별 신청 일정' 목록을 담는다. 이 두 구조에서 명시된 값만 뽑는다.
- 공통 안내(환급률·한도)는 "지자체마다 상이할 수 있음"이라는 단서가 있어 지역별 확정값으로 쓰지 않는다.
- 거주지 인접 제한 지역 목록, 인정 업종, 정산 기한, 예산 잔액은 페이지에 없다 → null.
- 구조가 바뀌어 블록을 찾지 못하면 Tour50StructureError를 던지고 기존 데이터를 그대로 둔다.
"""
from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import httpx

from .schemas import (
    BenefitProgram, BenefitRule, CapRule, DateRange, FieldConflict, PaymentRule, PayoutRule,
    PreApplyRule, Region, SourceRef, YouthRule,
)

URL = "https://korean.visitkorea.or.kr/dgtourcard/tour50.do"
PROGRAM_NAME = "지역사랑 휴가지원 사업(대한민국 반값여행)"
USER_AGENT = "kirothon-benefit-sync/1.0 (+periodic status check; 1 request per run)"
TIMEOUT = httpx.Timeout(15.0, connect=5.0)
KST = timezone(timedelta(hours=9))
STATUS_MAP = {"ONGOING": "open", "READY": "upcoming", "END": "closed"}

# Fields that come straight from the page's structured attributes/schedule list.
STRUCTURED_FIELDS = ["target_regions", "posted_status", "application_period", "trip_period",
                     "business_period"]
ALWAYS_MISSING = [
    "residence_rule(인접 지역 목록 미제공)", "age_rule", "party_rule", "family_rule",
    "participation_rule", "benefit.eligible_spend", "benefit.rounding_unit", "benefit.lodging_cap",
    "visit_rule(특이사항 원문만 제공)", "stay_rule", "proof_items", "pre_apply.days_before_trip",
    "settlement_days_after_trip", "budget_remaining", "stackable_with",
]


class Tour50Error(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


class Tour50StructureError(Tour50Error):
    pass


@dataclass
class Extracted:
    source_key: str
    program_key: str
    round_key: str | None
    title: str
    sigungu_code: str | None
    program: BenefitProgram
    raw: dict
    review_status: str
    review_notes: list[str] = field(default_factory=list)
    source_updated_at: datetime | None = None


# ------------------------------------------------------------------ fetch
def fetch_html(transport: httpx.BaseTransport | None = None, retries: int = 2) -> str:
    delay = 2.0
    last: Tour50Error | None = None
    for attempt in range(retries + 1):
        try:
            with httpx.Client(timeout=TIMEOUT, transport=transport, follow_redirects=False,
                              headers={"User-Agent": USER_AGENT}) as client:
                r = client.get(URL)
        except httpx.TimeoutException:
            last = Tour50Error("timeout", "반값여행 현황 페이지 응답 시간 초과")
        except httpx.HTTPError:
            last = Tour50Error("network_error", "반값여행 현황 페이지 연결 실패")
        else:
            if r.status_code == 200:
                return r.text
            code = "rate_limited" if r.status_code == 429 else (
                "upstream_error" if r.status_code >= 500 else "http_error")
            last = Tour50Error(code, f"반값여행 현황 페이지 HTTP {r.status_code}")
            if code == "http_error":
                break
        if attempt < retries:
            time.sleep(delay)
            delay *= 2.5
    raise last  # type: ignore[misc]


# ------------------------------------------------------------------ parse helpers
_ASIDE = re.compile(
    r'<aside class="cl-posi-detail[^"]*"\s+data-trvid="(?P<trvid>\d+)"\s+data-mtpcdocd="(?P<sidocd>\d*)"'
    r'\s+data-mtpcdocdnm="(?P<sido>[^"]*)"\s+data-signgucd="(?P<sggcd>\d*)"\s+data-signgucdnm="(?P<sgg>[^"]*)"'
    r'\s+data-govnm="[^"]*"\s+data-trvnm="(?P<trvnm>[^"]*)"\s+data-link="(?P<link>[^"]*)"'
    r'\s+data-evtbgndt="(?P<bgn>[^"]*)"\s+data-evtenddt="(?P<end>[^"]*)"\s+data-sttscd="(?P<stts>[^"]*)"'
    r'\s+data-sttsnm="(?P<sttsnm>[^"]*)"\s*>(?P<body>.*?)</aside>', re.S)
_SCHEDULE = re.compile(
    r"<a href=\"javascript:func_go_detail\('[^']*','(?P<trvid>\d+)'\)\"\s*data-trvid=\"\d+\"\s*"
    r'data-signgucd="(?P<sggcd>\d+)"\s*data-town="[^"]*">\s*<dl>\s*<dt>[^<]*</dt>\s*<dd>\s*<ol>(?P<ol>.*?)</ol>',
    re.S)
_SCHED_ITEM = re.compile(r'<li class="(?P<cls>[^"]*)">\s*<span>(?P<round>[^<]*)</span>\s*<p>(?P<p>.*?)</p>', re.S)
_DL = re.compile(r"<dt>\s*(?P<k>[^<:]+?)\s*:\s*</dt>\s*<dd>(?P<v>.*?)</dd>", re.S)
_TEL = re.compile(r'href="tel:([^"]+)"')
_BTN = re.compile(r'<button data-href="(?P<href>[^"]*)"\s+class="cl-request"[^>]*>(?P<label>[^<]+)</button>')
_MD_RANGE = re.compile(r"(\d{1,2})\.(\d{1,2})\s*~\s*(\d{1,2})\.(\d{1,2})")
_MD_TIME = re.compile(r"(\d{1,2})\.(\d{1,2})\s+(\d{1,2})(?::(\d{2})|시)")
_MD_PAREN_TIME = re.compile(r"(\d{1,2})\.(\d{1,2})\([^)]*\)\s*(\d{1,2})시(?:\s*(\d{1,2})분)?")
_YMD_RANGE = re.compile(r"(\d{4})\.(\d{2})\.(\d{2})\s*-\s*(\d{4})\.(\d{2})\.(\d{2})")


def _text(fragment: str) -> str:
    t = re.sub(r"<br\s*/?>", "\n", fragment)
    t = re.sub(r"<!--.*?-->", "", t, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t).replace("\xa0", " ")
    return "\n".join(" ".join(line.split()) for line in t.splitlines() if line.strip())


def _iso(value: str) -> date | None:
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


class _Years:
    """Resolve month.day into a date inside the business period."""

    def __init__(self, start: date | None, end: date | None):
        self.start, self.end = start, end

    def md(self, month: int, day: int) -> date | None:
        years = sorted({d.year for d in (self.start, self.end) if d}) or [datetime.now(KST).year]
        candidates = []
        for y in years:
            try:
                candidates.append(date(y, month, day))
            except ValueError:
                return None
        if len(candidates) == 1 or not (self.start and self.end):
            return candidates[0]
        inside = [d for d in candidates if self.start - timedelta(days=60) <= d <= self.end]
        return inside[0] if len(inside) == 1 else None

    def at(self, month, day, hour, minute) -> datetime | None:
        d = self.md(int(month), int(day))
        if d is None or not (0 <= int(hour) <= 23):
            return None
        return datetime(d.year, d.month, d.day, int(hour), int(minute or 0), tzinfo=KST)

    def range(self, m1, d1, m2, d2) -> DateRange | None:
        a, b = self.md(int(m1), int(d1)), self.md(int(m2), int(d2))
        if a and b and b < a and self.end and b.replace(year=b.year + 1) <= self.end:
            b = b.replace(year=b.year + 1)
        return DateRange(start=a, end=b) if a and b and a <= b else None


@dataclass
class _Round:
    number: int | None
    trip: DateRange | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    active: bool = False
    raw: list[str] = field(default_factory=list)
    conflicts: list[FieldConflict] = field(default_factory=list)


def _round_no(label: str) -> int | None:
    m = re.search(r"(\d+)\s*차", label)
    return int(m.group(1)) if m else None


def _parse_schedule_p(text: str, years: _Years) -> tuple[DateRange | None, datetime | None, datetime | None]:
    trip = start = end = None
    for line in text.splitlines():
        label, _, value = line.partition(":")
        label, value = label.strip(), value.strip()
        if label in {"여행기간", "여행일정"}:
            m = _MD_RANGE.search(value)
            trip = years.range(*m.groups()) if m else None
        elif label in {"신청마감", "신청접수", "추가접수"}:
            m = _MD_TIME.search(value)
            at = years.at(*m.groups()) if m else None
            if label == "신청마감":
                end = at
            else:
                start = at
    return trip, start, end


def _parse_detail_period(text: str, years: _Years) -> list[_Round]:
    rounds = []
    for seg in text.split("●")[1:]:
        m = re.search(r"(?:(\d+)\s*차\s*)?여행기간\s*:\s*(\d{1,2})\.(\d{1,2})\s*~\s*(\d{1,2})\.(\d{1,2})", seg)
        if not m:
            continue
        r = _Round(number=int(m.group(1)) if m.group(1) else None, trip=years.range(*m.groups()[1:]),
                   raw=[seg.strip()])
        rest = seg[m.end():]
        line = next((ln for ln in rest.splitlines() if ln.strip().startswith("-")), "")
        times = [years.at(*t.groups()) for t in _MD_PAREN_TIME.finditer(line)]
        if len(times) >= 2 and "~" in line:
            r.start_at, r.end_at = times[0], times[1]
        elif len(times) == 1:
            if "마감" in line:
                r.end_at = times[0]
            elif any(k in line for k in ("부터", "~", "예정", "접수")):
                r.start_at = times[0]
        rounds.append(r)
    return rounds


def _general_terms(page_text: str) -> tuple[BenefitRule | None, YouthRule | None, list[str]]:
    """Parse the page-wide guidance. Returns None when the expected sentences are absent."""
    notes = []
    rate = re.search(r"사용한 금액의\s*(\d{1,2})%를 환급", page_text)
    single = re.search(r"1인 최대\s*(\d+)만원", page_text)
    group = re.search(r"2인 이상은 최대\s*(\d+)만원", page_text)
    if not (rate and single and group):
        return None, None, ["공통 환급 안내 문구를 찾지 못함"]
    caps = [CapRule(label="개인(공통 안내)", amount=int(single.group(1)) * 10_000, per="group", max_party_size=1),
            CapRule(label="2인 이상(공통 안내)", amount=int(group.group(1)) * 10_000, per="group", min_party_size=2)]
    youth_rule = None
    youth_rate = None
    y = re.search(r"청년\(([^)]*?)(\d{2})~(\d{2})세[^)]*\)[^\n]*?(\d{2})%인 최대\s*(\d+)만원", page_text)
    if y:
        youth_rule = YouthRule(min_age=int(y.group(2)), max_age=int(y.group(3)), basis=None)
        youth_rate = int(y.group(4)) / 100
        caps.append(CapRule(label="청년(공통 안내)", amount=int(y.group(5)) * 10_000, per="person", youth=True))
        notes.append("청년 기준일: 원문 '" + y.group(1).strip() + "' — 공고일/개시일 중 어느 쪽인지 지역별 확인 필요")
    fam = re.search(r"가족 단체로 신청시\s*(\d+)인까지는 최대\s*(\d+)만원", page_text)
    if fam:
        caps.append(CapRule(label="가족(공통 안내)", amount=int(fam.group(2)) * 10_000, per="group",
                            min_party_size=2, max_party_size=int(fam.group(1)), family=True))
    if "지자체마다 상이할 수 있" in page_text:
        notes.append("공통 안내는 '지자체마다 상이할 수 있음' 단서가 있어 지역별 확정값이 아님")
    rule = BenefitRule(benefit_type="local_voucher" if "지역화폐로 환급" in page_text else None,
                       refund_rate=int(rate.group(1)) / 100, youth_refund_rate=youth_rate, caps=caps,
                       spend_rule_note="숙박·식사·체험 '등'으로 안내(인정 업종 전체 목록 아님)")
    return rule, youth_rule, notes


# ------------------------------------------------------------------ main parser
def parse(page: str, fetched_at: datetime) -> list[Extracted]:
    asides = list(_ASIDE.finditer(page))
    if not asides:
        raise Tour50StructureError("structure_changed", "지역별 상세 블록을 찾지 못함(페이지 구조 변경 가능)")
    page_text = _text(page)
    general, youth_rule, general_notes = _general_terms(page_text)
    pre_apply_required = "사전에 신청하지 않을 경우 지원 불가" in page_text

    schedules: dict[str, list[tuple[str, str, str]]] = {}
    for m in _SCHEDULE.finditer(page):
        schedules.setdefault(m.group("sggcd"), [
            (i.group("cls"), _text(i.group("round")), _text(i.group("p"))) for i in _SCHED_ITEM.finditer(m.group("ol"))])

    out: list[Extracted] = []
    for a in asides:
        g = a.groupdict()
        body = g["body"]
        biz_start, biz_end = _iso(g["bgn"]), _iso(g["end"])
        years = _Years(biz_start, biz_end)
        year = biz_start.year if biz_start else None
        notes = list(general_notes)
        conflicts: list[FieldConflict] = []
        name_year = re.match(r"(\d{4})-", g["trvnm"])
        if name_year and year and int(name_year.group(1)) != year:
            conflicts.append(FieldConflict(field="program_year", values=[
                {"source": "tour50 data-trvnm", "value": g["trvnm"]},
                {"source": "tour50 data-evtbgndt", "value": g["bgn"]}], note="사업 연도 표기 불일치"))
        dl = {k.strip(): v for k, v in ((m.group("k"), m.group("v")) for m in _DL.finditer(body))}
        period_text = _text(dl.get("사업기간", ""))
        currency = _text(dl.get("지역화폐", "")) or None
        special = _text(dl.get("특이사항", "")) or None
        contacts = [t.strip() for t in _TEL.findall(body)] or None
        buttons = {html.unescape(b.group("label")).strip(): b.group("href").strip() for b in _BTN.finditer(body)}
        apply_url = buttons.get("신청하러 가기")
        home_url = buttons.get("홈페이지 바로가기") or g["link"].strip() or None
        biz_text = _YMD_RANGE.search(period_text)
        if biz_text:
            t_start = date(*map(int, biz_text.groups()[:3]))
            t_end = date(*map(int, biz_text.groups()[3:]))
            if (t_start, t_end) != (biz_start, biz_end):
                conflicts.append(FieldConflict(field="business_period", values=[
                    {"source": "tour50 data-evtbgndt/evtenddt", "value": f"{g['bgn']}~{g['end']}"},
                    {"source": "tour50 사업기간 본문", "value": f"{t_start}~{t_end}"}]))

        # rounds: schedule list first, then detail text
        rounds: dict[int | None, _Round] = {}
        for cls, label, ptext in schedules.get(g["sggcd"], []):
            trip, start, end = _parse_schedule_p(ptext, years)
            r = _Round(number=_round_no(label), trip=trip, start_at=start, end_at=end,
                       active="on" in cls.split(), raw=[f"{label} {ptext}"])
            rounds[r.number] = r
        for d in _parse_detail_period(period_text, years):
            key = d.number
            if key is None:
                key = next((n for n, r in rounds.items() if r.trip and d.trip and
                            (r.trip.start, r.trip.end) == (d.trip.start, d.trip.end)), None)
            target = rounds.get(key)
            if target is None:
                d.number = key
                rounds[key] = d
                continue
            target.raw += d.raw
            for fname in ("trip", "start_at", "end_at"):
                mine, theirs = getattr(target, fname), getattr(d, fname)
                if mine is None:
                    setattr(target, fname, theirs)
                elif theirs is not None and mine != theirs:
                    target.conflicts.append(FieldConflict(field=fname, values=[
                        {"source": "tour50 지역별 신청 일정", "value": str(mine)},
                        {"source": "tour50 지역 상세", "value": str(theirs)}]))
        if not rounds:
            rounds[None] = _Round(number=None)
            notes.append("모집 차수 정보를 찾지 못함")
        for r in rounds.values():
            if r.start_at and r.end_at and r.start_at >= r.end_at:
                r.conflicts.append(FieldConflict(field="start_at", values=[
                    {"source": "tour50", "value": f"접수 시작 {r.start_at.isoformat()}"},
                    {"source": "tour50", "value": f"접수 마감 {r.end_at.isoformat()}"}],
                    note="같은 페이지 안에서 접수 시작·마감 표기가 맞지 않음"))
        numbered = [n for n in rounds if n is not None]
        current = next((n for n, r in rounds.items() if r.active), max(numbered) if numbered else None)

        min_spend = None
        if special:
            ms = re.search(r"최소\s*(\d+)\s*만\s*원\s*이상", special)
            min_spend = int(ms.group(1)) * 10_000 if ms else None
        valid_until = None
        vu = re.search(r"소비기한\s*:\s*(\d{4})\.(\d{1,2})\.(\d{1,2})", period_text)
        if vu:
            valid_until = date(*map(int, vu.groups()))

        sido, sgg = g["sido"].strip() or None, g["sgg"].strip() or None
        program_key = f"kto50:{g['sggcd']}:{year}" if year else f"kto50:{g['sggcd']}"
        for number, r in rounds.items():
            round_tag = str(number) if number is not None else "x"
            rid = f"kto50:{g['sggcd']}-{year}-{round_tag}"
            is_current = number == current
            rconf = conflicts + r.conflicts
            verified = [f for f in STRUCTURED_FIELDS]
            for c in rconf:
                mapped = {"trip": "trip_period", "start_at": "application_period", "end_at": "application_period",
                          "business_period": "business_period", "program_year": "business_period"}.get(c.field)
                if mapped in verified:
                    verified.remove(mapped)
            if not is_current:
                verified.remove("posted_status")
            ap = None
            if r.start_at or r.end_at:
                ap = DateRange(start=r.start_at.date() if r.start_at else None,
                               end=r.end_at.date() if r.end_at else None)
            benefit = None
            if general:
                benefit = general.model_copy(deep=True)
                if min_spend is not None:
                    benefit.min_spend = min_spend
            program = BenefitProgram(
                id=rid, program_id=program_key, round_id=f"{year}-{round_tag}",
                provider=f"{sido or ''} {sgg or ''}".strip() or None,
                name=f"{PROGRAM_NAME} {sgg or g['trvnm']}" + (f" {number}차" if number else ""),
                target_regions=[Region(sido=sido, sigungu=sgg)] if sgg else None,
                application_period=ap, application_start_at=r.start_at, application_end_at=r.end_at,
                business_period=DateRange(start=biz_start, end=biz_end) if (biz_start or biz_end) else None,
                trip_period=r.trip,
                posted_status=STATUS_MAP.get(g["stts"]) if is_current else None,
                status_checked_at=fetched_at if is_current else None,
                youth_rule=youth_rule, benefit=benefit,
                payment_rule=PaymentRule(methods=[currency], note="특이사항 원문 확인") if currency else None,
                pre_apply=PreApplyRule(required=True, days_before_trip=None, channel="지역 신청 페이지")
                if pre_apply_required else None,
                payout=PayoutRule(method=currency, voucher_valid_until=valid_until) if (currency or valid_until) else None,
                official_info_url=home_url, application_url=apply_url, contacts=contacts,
                source_type="official_webpage",
                sources=[SourceRef(source_type="official_webpage", title="한국관광공사 대한민국 반값여행 현황",
                                   url=URL, retrieved_at=fetched_at,
                                   note="출처: 한국관광공사 대한민국 구석구석")],
                verification_status="unverified",
                unverified_fields=list(ALWAYS_MISSING) + ([] if is_current else ["posted_status(현재 차수만 게시)"]),
                verified_fields=verified,
                conflicts=rconf,
                raw_text={k: v for k, v in {
                    "사업기간": period_text, "지역화폐": currency or "", "특이사항": special or "",
                    "차수원문": " / ".join(r.raw), "게시상태": g["sttsnm"], "사업명": g["trvnm"],
                }.items() if v},
            )
            out.append(Extracted(
                source_key=f"tour50:{g['sggcd']}:{year}:{round_tag}", program_key=program_key,
                round_key=program.round_id, title=program.name, sigungu_code=g["sggcd"], program=program,
                raw={"aside_attrs": {k: v for k, v in g.items() if k != "body"}, "round": r.raw},
                review_status="conflict" if rconf else "needs_review",
                review_notes=notes + ["필수 조건 일부 미제공: " + ", ".join(ALWAYS_MISSING[:5]) + " 등"],
            ))
    return out


def collect(transport: httpx.BaseTransport | None = None, retries: int = 2) -> tuple[list[Extracted], int]:
    page = fetch_html(transport, retries)
    return parse(page, datetime.now(timezone.utc)), 1
