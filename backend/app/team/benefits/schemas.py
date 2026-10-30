"""Data model for travel benefit programs and the check API.

Null convention (applies to every field below):
- A rule object or value that is ``None`` means "not confirmed from any source".
  It never means "no restriction" or "0 won".
- A confirmed "no restriction" is written explicitly: an empty list (``[]``),
  ``0`` for a minimum amount, ``required=False``, ``repeat_allowed=True``, etc.
- Inside a confirmed range rule (AgeRule, PartyRule, YouthRule) a ``None`` bound
  means the source states no bound in that direction.
"""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

SourceType = Literal["gov24_api", "official_webpage", "official_notice", "news_report", "project_doc"]
VerificationStatus = Literal["verified", "unverified"]
# closed = 게시 상태 "마감" (현재 접수 불가. 사업 종료·예산 소진 여부는 구분되지 않음)
PostedStatus = Literal["upcoming", "open", "closing_soon", "closed", "closed_early", "budget_exhausted", "ended"]
ReviewStatus = Literal["auto_extracted", "needs_review", "conflict", "admin_reviewed"]
DataOrigin = Literal["gov24_api", "kto_tour50", "manual_registry", "merged"]
BenefitType = Literal["cash_refund", "local_voucher", "onsite_discount"]
SpendCategory = Literal[
    "lodging", "food", "cafe", "experience", "admission",
    "local_product", "shopping", "transport", "other",
]
AgeBasis = Literal[
    "full_age_on_trip_start",        # 만 나이, 여행 시작일 기준
    "full_age_on_application_date",  # 만 나이, 신청일 기준
    "full_age_on_fixed_date",        # 만 나이, 공고에 정한 날짜 기준
    "birth_year",                    # 연 나이 (기준 연도 - 출생 연도)
]
Verdict = Literal["potentially_eligible", "ineligible", "needs_verification"]
CheckStatus = Literal[
    "met", "unmet", "missing_user_info", "unconfirmed_program_rule", "conflict", "not_applicable",
]


class Region(BaseModel):
    sido: str | None = Field(default=None, max_length=30, description="시·도, 예: 전라남도")
    sigungu: str | None = Field(default=None, max_length=30, description="시·군·구, 예: 무안군")

    @model_validator(mode="after")
    def _not_empty(self):
        if not (self.sido or self.sigungu):
            raise ValueError("region needs sido or sigungu")
        return self


class DateRange(BaseModel):
    """``start``/``end`` of None means that side is not confirmed (not open-ended)."""
    start: date | None = None
    end: date | None = None


# ---------------------------------------------------------------- program rules
class SourceRef(BaseModel):
    source_type: SourceType
    title: str | None = None
    url: str | None = None
    retrieved_at: datetime | None = None
    note: str | None = None


class FieldConflict(BaseModel):
    field: str
    values: list[dict] = Field(description="[{source, value}] — every conflicting value is kept")
    note: str | None = None


class ResidenceRule(BaseModel):
    excluded_regions: list[Region] = Field(
        default_factory=list, description="[] with scope=listed = confirmed no residence exclusion")
    exclude_scope: Literal["listed", "visited_target_regions"] = Field(
        default="listed",
        description="visited_target_regions: residents of the target region being visited are excluded")


class AgeRule(BaseModel):
    min_age: int | None = None
    max_age: int | None = None
    basis: AgeBasis | None = Field(default=None, description="None = 판정 기준일 미확인")
    fixed_reference_date: date | None = None


class YouthRule(BaseModel):
    min_age: int | None = None
    max_age: int | None = None
    basis: AgeBasis | None = None
    fixed_reference_date: date | None = None


class PartyRule(BaseModel):
    min_size: int | None = None
    max_size: int | None = None


class FamilyRule(BaseModel):
    requires_family: bool
    requires_same_address: bool


class ParticipationRule(BaseModel):
    repeat_allowed: bool
    same_program_ids: list[str] = Field(default_factory=list,
                                        description="Program IDs that count as the same 사업")


class VisitRule(BaseModel):
    must_include: list[str] = Field(default_factory=list)
    any_of: list[str] = Field(default_factory=list)
    min_any_of: int = 0
    min_total_places: int | None = None


class StayRule(BaseModel):
    min_nights: int
    checkin_weekdays: list[int] | None = Field(
        default=None, description="0=월 … 6=일. None = 요일 제한 없음(규칙 자체는 확인됨)")
    checkin_scope: Literal["first", "all"] | None = Field(
        default=None, description="요일 조건을 첫 체크인에만/모든 체크인에 적용. None = 미확인")


class PaymentRule(BaseModel):
    methods: list[str]
    note: str | None = None


class PreApplyRule(BaseModel):
    required: bool
    days_before_trip: int | None = Field(
        default=None, description="deadline = trip start - N days (inclusive). None = 기한 미확인")
    channel: str | None = None


class CapRule(BaseModel):
    """One cap tier. A None condition means the tier applies regardless of that attribute."""
    label: str
    amount: int = Field(ge=0)
    per: Literal["person", "group"]
    min_party_size: int | None = None
    max_party_size: int | None = None
    min_nights: int | None = None
    max_nights: int | None = None
    youth: bool | None = None
    family: bool | None = None
    max_persons: int | None = Field(default=None, description="per=person 일 때 인원 상한")
    min_spend: int | None = Field(default=None, description="이 구간의 최소 인정 소비액")


class LodgingCap(BaseModel):
    applies: bool
    amount_per_night: int | None = None


class BenefitRule(BaseModel):
    benefit_type: BenefitType | None = None
    refund_rate: float | None = Field(default=None, ge=0, le=1)
    youth_refund_rate: float | None = Field(default=None, ge=0, le=1)
    min_spend: int | None = Field(default=None, ge=0, description="0 = confirmed no minimum")
    caps: list[CapRule] | None = None
    rounding_unit: int | None = Field(default=None, ge=1, description="1 = no rounding")
    lodging_cap: LodgingCap | None = None
    eligible_spend: list[SpendCategory] | None = None
    excluded_spend: list[SpendCategory] | None = None
    spend_rule_note: str | None = None


class PayoutRule(BaseModel):
    method: str | None = None
    voucher_valid_until: date | None = None
    voucher_validity_note: str | None = None


class SyncMeta(BaseModel):
    """Collection timestamps of a stored external record (None for manual entries)."""
    source: str
    source_key: str
    record_version: int
    review_status: ReviewStatus
    review_notes: list[str] = Field(default_factory=list)
    source_updated_at: datetime | None = Field(default=None, description="원본이 제공한 수정 시각, 없으면 null")
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    content_changed_at: datetime | None = None
    missing_from_source_since: datetime | None = None
    stale: bool = False


class BenefitProgram(BaseModel):
    id: str
    program_id: str = Field(description="사업 ID (차수와 무관)")
    round_id: str | None = Field(default=None, description="모집 차수 ID")
    provider: str | None = None
    external_service_id: str | None = Field(default=None, description="gov24 서비스ID")
    name: str
    target_regions: list[Region] | None = None
    region_hints: list[Region] = Field(
        default_factory=list, description="target_regions 미확인 시 텍스트 일치로 찾은 지역(근거 아님)")
    application_period: DateRange | None = None
    application_start_at: datetime | None = Field(default=None, description="원문에 시각이 있을 때만")
    application_end_at: datetime | None = Field(default=None, description="원문에 시각이 있을 때만")
    business_period: DateRange | None = Field(default=None, description="사업기간(접수·여행 기간과 별개)")
    trip_period: DateRange | None = Field(default=None, description="여행 인정 기간")
    posted_status: PostedStatus | None = None
    status_checked_at: datetime | None = None
    budget_remaining: int | None = Field(default=None, description="잔액을 제공하는 출처가 없으면 null")
    contacts: list[str] | None = None
    residence_rule: ResidenceRule | None = None
    age_rule: AgeRule | None = None
    youth_rule: YouthRule | None = None
    party_rule: PartyRule | None = None
    family_rule: FamilyRule | None = None
    participation_rule: ParticipationRule | None = None
    benefit: BenefitRule | None = None
    visit_rule: VisitRule | None = None
    stay_rule: StayRule | None = None
    payment_rule: PaymentRule | None = None
    proof_items: list[str] | None = None
    pre_apply: PreApplyRule | None = None
    settlement_days_after_trip: int | None = None
    payout: PayoutRule | None = None
    stackable_with: list[str] | None = Field(default=None, description="중복 적용이 확인된 benefit id")
    official_info_url: str | None = None
    application_url: str | None = None
    source_type: SourceType
    sources: list[SourceRef]
    verification_status: VerificationStatus
    last_verified_at: datetime | None = None
    external_updated_at: str | None = Field(default=None, description="gov24 수정일시 원문")
    unverified_fields: list[str] = Field(default_factory=list)
    verified_fields: list[str] = Field(
        default_factory=list,
        description="verification_status가 unverified여도 공식 출처(API 구조화 필드)로 확인된 필드")
    conflicts: list[FieldConflict] = Field(default_factory=list)
    raw_text: dict[str, str] = Field(default_factory=dict, description="외부 API 원문 텍스트(해석하지 않음)")
    sync: SyncMeta | None = None
    related_program_ids: list[str] = Field(
        default_factory=list, description="관련 가능성만 표시(자동 병합하지 않음)")


# ---------------------------------------------------------------- request
class ExpectedSpend(BaseModel):
    by_category: dict[SpendCategory, int] | None = None
    total: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _non_negative(self):
        if self.by_category and any(v < 0 for v in self.by_category.values()):
            raise ValueError("spend amounts must be >= 0")
        return self


class VisitInput(BaseModel):
    region: Region
    start_date: date
    end_date: date
    nights: int | None = Field(default=None, ge=0, le=60, description="이 지역 숙박 수")
    checkin_dates: list[date] | None = None
    places: list[str] | None = Field(default=None, max_length=50)
    expected_spend: ExpectedSpend | None = None

    @model_validator(mode="after")
    def _dates(self):
        if self.end_date < self.start_date:
            raise ValueError("visit end_date is before start_date")
        if self.nights is not None and self.nights > (self.end_date - self.start_date).days:
            raise ValueError("visit nights exceed the visit date span")
        for d in self.checkin_dates or []:
            if not (self.start_date <= d < self.end_date):
                raise ValueError("checkin_dates must fall within the visit (before end_date)")
        return self


class BenefitCheckRequest(BaseModel):
    departure: Region | None = Field(default=None, description="출발지 (거주지와 별개)")
    residence: Region | None = Field(default=None, description="주민등록상 거주지")
    trip_start: date
    trip_end: date
    visits: list[VisitInput] = Field(min_length=1, max_length=20)
    party_size: int | None = Field(default=None, ge=1, le=50)
    expected_spend_total: int | None = Field(default=None, ge=0)
    birth_date: date | None = None
    age: int | None = Field(default=None, ge=0, le=120, description="birth_date가 없을 때, 기준일 현재 만 나이")
    is_family: bool | None = None
    same_address: bool | None = None
    prior_participated_program_ids: list[str] | None = Field(
        default=None, description="참여한 사업 ID 목록. [] = 참여 이력 없음, null = 미입력")
    reference_date: date | None = Field(default=None, description="판정 기준일(신청일로 간주). 기본: 오늘(KST)")
    include_external: bool = True

    @model_validator(mode="after")
    def _trip(self):
        if self.trip_end < self.trip_start:
            raise ValueError("trip_end is before trip_start")
        if (self.trip_end - self.trip_start).days > 60:
            raise ValueError("trip longer than 60 days is not supported")
        for v in self.visits:
            if v.start_date < self.trip_start or v.end_date > self.trip_end:
                raise ValueError("every visit must fall within trip_start..trip_end")
        return self


# ---------------------------------------------------------------- response
class ConditionResult(BaseModel):
    code: str
    label: str
    status: CheckStatus
    detail: str
    rule_confirmed: bool = Field(description="판정에 쓴 제도 조건이 검증된 출처에서 왔는지")
    user_fields: list[str] = Field(default_factory=list)
    program_fields: list[str] = Field(default_factory=list)


class Estimate(BaseModel):
    benefit_type: BenefitType | None = None
    amount: int | None = None
    amount_kind: Literal["calculated", "upper_bound"] | None = None
    recognized_spend: int | None = None
    refund_rate: float | None = None
    cap_label: str | None = None
    cap_amount: int | None = None
    min_spend: int | None = None
    shortfall_to_min_spend: int | None = None
    unavailable_reasons: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class Timeline(BaseModel):
    application_period: DateRange | None = None
    application_start_at: datetime | None = None
    application_end_at: datetime | None = None
    application_closed: bool | None = None
    pre_apply_deadline: date | None = None
    pre_apply_deadline_passed: bool | None = None
    trip_period: DateRange | None = None
    settlement_deadline: date | None = None
    posted_status: PostedStatus | None = None
    status_checked_at: datetime | None = None
    budget_remaining: int | None = Field(default=None, description="제공 출처 없음 → null. 접수중 문구로 추정하지 않음")


class HowToApply(BaseModel):
    application_url: str | None = None
    official_info_url: str | None = None
    contacts: list[str] | None = None
    pre_apply_channel: str | None = None
    payment_methods: list[str] | None = None
    proof_items: list[str] | None = None
    payout: PayoutRule | None = None


class MatchedVisit(BaseModel):
    region: Region
    start_date: date
    end_date: date
    match_basis: Literal["target_region", "text_hint"]


class ProgramEvaluation(BaseModel):
    benefit_id: str
    program_id: str
    round_id: str | None
    name: str
    provider: str | None
    data_origin: DataOrigin
    source_type: SourceType
    verification_status: VerificationStatus
    review_status: ReviewStatus | None
    data_freshness: SyncMeta | None
    verdict: Verdict
    can_apply_now: bool | None
    matched_visits: list[MatchedVisit]
    met_conditions: list[ConditionResult]
    unmet_conditions: list[ConditionResult]
    unresolved_conditions: list[ConditionResult]
    missing_user_fields: list[str]
    official_checks_needed: list[str]
    timeline: Timeline
    estimate: Estimate
    how_to_apply: HowToApply
    sources: list[SourceRef]
    last_verified_at: datetime | None
    conflicts: list[FieldConflict]
    related_program_ids: list[str] = Field(default_factory=list)


class SourceStatus(BaseModel):
    source: Literal["gov24_api", "kto_tour50", "manual_registry"]
    status: Literal["ok", "partial", "error", "not_configured", "skipped", "never_synced"]
    data_origin: Literal["live_api", "cache", "mixed", "local_registry", "stored_sync"] | None = None
    collection_method: Literal["public_api", "official_webpage", "admin_registry"] | None = None
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    stale: bool | None = None
    refresh_interval_seconds: int | None = None
    queries: list[str] = Field(default_factory=list)
    pages_fetched: int = 0
    records_seen: int = 0
    candidates: int = 0
    truncated: bool = False
    fetched_at: datetime | None = None
    error_code: str | None = None
    message: str | None = None


class VisitScope(BaseModel):
    region: Region
    dates: list[date]


class SearchScope(BaseModel):
    trip_start: date
    trip_end: date
    reference_date: date
    visits: list[VisitScope]
    gov24_keywords: list[str]


class CombinedEstimate(BaseModel):
    amount: int | None = None
    benefit_ids: list[str] = Field(default_factory=list)
    note: str


class BenefitCheckResponse(BaseModel):
    success: bool = Field(description="모든 자동 수집 출처가 최근에 정상 수집됨")
    partial_failure: bool = Field(description="일부 출처가 미설정·오류·오래됨·미수집")
    outcome: Literal["candidates_found", "no_match_in_scope", "source_unavailable", "insufficient_information"]
    message: str
    checked_at: datetime
    scope: SearchScope
    sources: list[SourceStatus]
    coverage_note: str
    missing_fields: list[str]
    results: list[ProgramEvaluation]
    combined_estimate: CombinedEstimate
    disclaimer: str


class BenefitDetailResponse(BaseModel):
    benefit: BenefitProgram
    data_origin: DataOrigin
    source_status: SourceStatus
    stale_status: bool | None = Field(description="status_checked_at older than 7 days, None if unknown")
    disclaimer: str


class SourcesResponse(BaseModel):
    checked_at: datetime
    update_method: str
    sources: list[SourceStatus]
