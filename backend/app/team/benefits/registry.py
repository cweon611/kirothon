"""Manually registered travel benefit programs (secondary data).

Why this exists
    The gov24 공공서비스(혜택) API returns free-text fields (지원대상, 지원내용,
    신청기한 …) and only a few structured conditions (age range, income, etc.).
    It has no structured travel period, refund rate, cap, minimum spend,
    eligible spend categories, required places, stay rule, pre-apply deadline,
    budget balance or application status. Regional half-price travel programs
    may also be missing from it entirely. Those fields are kept here.

Review workflow
    1. Read the official notice (지자체 공고문 / 공식 신청 페이지).
    2. Fill only what the notice states. Leave everything else ``None`` and list
       the field name in ``unverified_fields``.
    3. Add the notice as a ``SourceRef(source_type="official_notice", url=…)``,
       set ``verification_status="verified"`` and ``last_verified_at``.
    4. If the notice disagrees with gov24 or a news report, keep both values in
       ``conflicts`` instead of picking one.
    5. Set ``external_service_id`` when the same program exists in gov24 so the
       two records are merged and compared.

Current entries
    Every entry below was transcribed from docs/feature-definition.md, which
    cites news reports (not official notices). They are therefore
    ``verification_status="unverified"`` and can never yield
    ``potentially_eligible`` until an official notice is reviewed.
"""
from datetime import date, datetime, timedelta, timezone

from .schemas import (
    AgeRule, BenefitProgram, BenefitRule, CapRule, DateRange, FieldConflict, PartyRule,
    PayoutRule, PaymentRule, PreApplyRule, Region, ResidenceRule, SourceRef, StayRule,
    VisitRule, YouthRule,
)

KST = timezone(timedelta(hours=9))
_DOC = "docs/feature-definition.md (2026-10-30 기준 정리)"


def _jn(*names: str) -> list[Region]:
    return [Region(sido="전라남도", sigungu=n) for n in names]


_COMMON_UNVERIFIED_NOTE = "공식 공고문 미검토(보도·프로젝트 문서 기준)"

_ENTRIES: list[BenefitProgram] = [
    BenefitProgram(
        id="manual:muan-halfprice-2026",
        program_id="muan-halfprice",
        round_id="2026",
        provider="전라남도 무안군",
        name="2026 갯벌愛 무안 반값여행",
        target_regions=_jn("무안군"),
        application_period=DateRange(start=date(2026, 9, 14), end=None),
        trip_period=None,
        residence_rule=ResidenceRule(excluded_regions=_jn("무안군")),
        benefit=BenefitRule(
            benefit_type="local_voucher",
            refund_rate=0.5,
            caps=[
                CapRule(label="1박형 개인", amount=100_000, per="group", max_party_size=1,
                        min_nights=1, max_nights=1, min_spend=100_000),
                CapRule(label="1박형 팀", amount=200_000, per="group", min_party_size=2,
                        min_nights=1, max_nights=1, min_spend=100_000),
                CapRule(label="2박 이상 개인", amount=200_000, per="group", max_party_size=1,
                        min_nights=2, min_spend=200_000),
                CapRule(label="2박 이상 팀", amount=400_000, per="group", min_party_size=2,
                        min_nights=2, min_spend=200_000),
            ],
            eligible_spend=["lodging", "food", "cafe", "local_product", "experience", "admission"],
        ),
        visit_rule=VisitRule(must_include=["무안황토갯벌랜드"], min_total_places=2),
        stay_rule=StayRule(min_nights=1, checkin_weekdays=[0, 1, 2, 3, 4]),
        pre_apply=PreApplyRule(required=True, days_before_trip=None, channel=None),
        settlement_days_after_trip=7,
        proof_items=["숙박 자료", "방문 사진", "영수증"],
        payout=PayoutRule(method="모바일 무안사랑상품권"),
        source_type="project_doc",
        sources=[
            SourceRef(source_type="news_report", title="MTN 보도",
                      url="https://news.mtn.co.kr/news-detail/2026091118124235889"),
            SourceRef(source_type="project_doc", title=_DOC),
        ],
        verification_status="unverified",
        unverified_fields=[
            "trip_period", "application_period.end", "posted_status", "age_rule", "party_rule",
            "caps.team_definition(2인 이상으로 해석)", "benefit.rounding_unit",
            "benefit.lodging_cap", "benefit.excluded_spend", "stay_rule.checkin_scope",
            "pre_apply.days_before_trip", "application_url", "official_info_url",
            "participation_rule", "family_rule", "stackable_with",
        ],
    ),
    BenefitProgram(
        id="manual:jangheung-vacation-2026h2",
        program_id="local-love-vacation",
        round_id="2026-h2-jangheung",
        provider="전라남도 장흥군",
        name="지역사랑 휴가지원 하반기 (장흥군)",
        target_regions=_jn("장흥군"),
        # 같은 사업으로 보이는 공식 페이지 수집 레코드. 자동 병합하지 않고 관련 표시만 한다.
        related_program_ids=["kto50:12770:2026"],
        application_period=None,
        trip_period=None,
        residence_rule=None,
        age_rule=AgeRule(min_age=18, basis=None),
        youth_rule=YouthRule(min_age=19, max_age=34, basis=None),
        benefit=BenefitRule(
            benefit_type="local_voucher",
            refund_rate=0.5,
            youth_refund_rate=0.7,
            caps=[
                CapRule(label="개인", amount=100_000, per="group", max_party_size=1, youth=False),
                CapRule(label="청년 개인", amount=140_000, per="group", max_party_size=1, youth=True),
                CapRule(label="2인 이상", amount=200_000, per="group", min_party_size=2),
                CapRule(label="가족(최대 5명)", amount=500_000, per="group", min_party_size=2,
                        max_party_size=5, family=True),
            ],
        ),
        pre_apply=PreApplyRule(required=True, days_before_trip=None, channel="대한민국 구석구석"),
        proof_items=["영수증", "방문 인증"],
        payout=PayoutRule(method="모바일 지역사랑상품권"),
        source_type="project_doc",
        sources=[
            SourceRef(source_type="news_report", title="아시아경제 보도",
                      url="https://view.asiae.co.kr/article/2026090416020175550"),
            SourceRef(source_type="project_doc", title=_DOC),
        ],
        verification_status="unverified",
        unverified_fields=[
            "application_period", "trip_period", "posted_status", "residence_rule",
            "age_rule.basis", "youth_rule.basis", "party_rule", "family_rule",
            "benefit.min_spend", "benefit.eligible_spend", "benefit.rounding_unit",
            "caps.family_vs_group_precedence", "pre_apply.days_before_trip",
            "settlement_days_after_trip", "participation_rule", "application_url",
            "official_info_url", "stackable_with",
        ],
    ),
    BenefitProgram(
        id="manual:jn-island-halfprice-2026",
        program_id="jn-island-halfprice",
        round_id="2026",
        provider=None,
        name="전남광주 섬 반값여행",
        target_regions=_jn("목포시", "여수시", "고흥군", "보성군", "강진군", "영광군", "진도군", "신안군"),
        application_period=None,
        trip_period=DateRange(start=date(2026, 8, 29), end=date(2026, 11, 4)),
        posted_status="closing_soon",
        status_checked_at=datetime(2026, 10, 30, tzinfo=KST),
        residence_rule=ResidenceRule(exclude_scope="visited_target_regions"),
        benefit=BenefitRule(
            benefit_type="local_voucher",
            refund_rate=0.5,
            caps=[CapRule(label="1인", amount=100_000, per="person")],
            eligible_spend=["lodging", "food", "cafe", "experience"],
            spend_rule_note="섬에서 일정 금액 이상 사용 시 해당 시군 가맹점 사용분도 인정(금액은 충돌 항목 참고)",
        ),
        visit_rule=VisitRule(any_of=[
            "달리도", "외달도", "하화도", "사도", "거문도", "개도", "금오도", "쑥섬", "연홍도",
            "장도", "가우도", "송이도", "관매도", "흑산도", "반월박지도", "증도",
        ], min_any_of=1),
        payment_rule=PaymentRule(methods=["시군 지역화폐 앱(Chak·그리고) 가맹점 결제"]),
        pre_apply=PreApplyRule(required=True, days_before_trip=5, channel="JG TOUR 앱·누리집"),
        settlement_days_after_trip=10,
        payout=PayoutRule(method="모바일 지역화폐", voucher_validity_note="해당 지역 재방문·지역 온라인몰 사용(보도 기준)"),
        source_type="project_doc",
        sources=[
            SourceRef(source_type="news_report", title="서울신문 보도(2026-08-06)",
                      url="https://m.go.seoul.co.kr/news/2026/08/06/20260806500202"),
            SourceRef(source_type="news_report", title="MTN 보도(섬 목록)",
                      url="https://news.mtn.co.kr/news-detail/2026083016565081727"),
            SourceRef(source_type="project_doc", title=_DOC),
        ],
        verification_status="unverified",
        unverified_fields=[
            "provider", "application_period", "age_rule", "party_rule", "family_rule",
            "benefit.min_spend", "benefit.rounding_unit", "benefit.lodging_cap",
            "benefit.excluded_spend", "participation_rule", "application_url",
            "official_info_url", "proof_items", "stackable_with",
        ],
        conflicts=[FieldConflict(
            field="benefit.spend_rule_note",
            values=[
                {"source": _DOC, "value": "섬에서 3만 원 이상 사용 시 시군 가맹점 사용분 인정"},
                {"source": "서울신문 보도(2026-08-06)", "value": "섬에서 5만 원 이상 사용 시 시군 가맹점 사용분 인정"},
            ],
            note="공식 공고로 기준 금액 확인 필요",
        )],
    ),
    BenefitProgram(
        id="manual:jn-vacation-2026h1",
        program_id="local-love-vacation",
        round_id="2026-h1-jeonnam",
        provider=None,
        name="지역사랑 휴가지원 상반기 (전남 6개 군)",
        target_regions=_jn("강진군", "해남군", "고흥군", "완도군", "영암군", "영광군"),
        related_program_ids=["kto50:12780:2026", "kto50:12790:2026", "kto50:12740:2026",
                             "kto50:12850:2026", "kto50:12800:2026", "kto50:12830:2026"],
        application_period=None,
        trip_period=None,
        age_rule=AgeRule(min_age=18, basis=None),
        benefit=BenefitRule(
            benefit_type="local_voucher",
            refund_rate=0.5,
            caps=[
                CapRule(label="개인", amount=100_000, per="group", max_party_size=1),
                CapRule(label="2인 이상", amount=200_000, per="group", min_party_size=2),
            ],
        ),
        pre_apply=PreApplyRule(required=True, days_before_trip=None, channel=None),
        proof_items=["지출 증빙"],
        payout=PayoutRule(method="모바일 지역사랑상품권", voucher_validity_note="해당 연도 안 사용(보도 기준)"),
        source_type="project_doc",
        sources=[
            SourceRef(source_type="news_report", title="뉴시스 보도",
                      url="https://www.newsis.com/view/NISX20260227_0003528809"),
            SourceRef(source_type="news_report", title="세계일보 보도(6개 군)",
                      url="https://www.segye.com/newsView/20260727518262"),
            SourceRef(source_type="project_doc", title=_DOC),
        ],
        verification_status="unverified",
        unverified_fields=[
            "application_period", "trip_period", "posted_status", "residence_rule",
            "age_rule.basis", "party_rule", "family_rule", "benefit.min_spend",
            "benefit.eligible_spend", "benefit.rounding_unit", "pre_apply.days_before_trip",
            "settlement_days_after_trip", "participation_rule", "application_url",
            "official_info_url", "stackable_with",
        ],
    ),
]


def manual_programs() -> list[BenefitProgram]:
    """Return copies so callers cannot mutate the registry."""
    return [p.model_copy(deep=True) for p in _ENTRIES]


def find_manual(benefit_id: str) -> BenefitProgram | None:
    for p in _ENTRIES:
        if p.id == benefit_id:
            return p.model_copy(deep=True)
    return None


def manual_by_external_id() -> dict[str, BenefitProgram]:
    return {p.external_service_id: p.model_copy(deep=True) for p in _ENTRIES if p.external_service_id}
