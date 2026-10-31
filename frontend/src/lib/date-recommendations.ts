// Client for POST /api/team/date-recommendations (backend/app/team/date_recommend.py).
import type { Festival } from './festivals.ts'
import type { Benefit } from './benefits.ts'

export type Judgment = 'potentially_eligible' | 'needs_verification' | 'ineligible'
export type Period = { start: string | null; end: string | null } | null
export type FestivalItem = {
  content_id: string; title: string; start_date: string | null; end_date: string | null;
  place: string | null; overview: string | null; source: string; source_url: string | null; fetched_at: string | null;
}
export type ProgramItem = {
  program_id: string; round_id: string | null; name: string; judgment: Judgment;
  posted_status: string | null; application_open: boolean | null;
  trip_period: Period; application_period: Period;
  application_start_at: string | null; application_end_at: string | null;
  support: string | null; payout_method: string | null; conditions_text: string | null;
  match_basis?: 'target_region' | 'text_hint' | null;
  audience?: 'general' | 'targeted';
  estimated_amount: number | null; budget_remaining: number | null;
  apply_url: string | null; official_url: string | null;
  missing_user_fields: string[]; needs_official_check: string[]; reasons: string[];
  data_origin: string | null; source_type: string | null; verification_status: string | null;
  review_status: string | null; last_success_at: string | null; last_verified_at: string | null;
  stale: boolean | null; sources: { type: string; title: string | null; url: string | null }[];
  excluded_reason?: string;
}
export type RegionItem = {
  sigungu_code: string; name: string; sido: string; group: 1 | 2 | 3; category: string; reason: string;
  festivals: FestivalItem[];
  benefits: { applicable: ProgramItem[]; needs_verification: ProgramItem[]; excluded: ProgramItem[] };
  missing_user_fields: string[]; data_warnings: string[];
}
export type FestivalSource = {
  status: string; records: number; key_configured: boolean; last_attempt_at: string | null;
  last_success_at: string | null; stale: boolean; message: string | null;
}
export type BenefitSource = {
  source: string; collection_method: string | null; status: string; records: number;
  last_attempt_at: string | null; last_success_at: string | null; stale: boolean | null;
  error_code: string | null; message: string | null;
}
export type DateRecommendResponse = {
  query: { start_date: string; end_date: string; days: number; provided: string[] };
  today: string; outcome: 'matches_found' | 'no_match_in_scope' | 'source_unavailable';
  message: string; complete: boolean; regions: RegionItem[]; selected_region: SelectedRegion | null;
  regions_not_matched: { names: string[]; meaning: string };
  missing_user_fields: string[];
  data_status: {
    festivals: FestivalSource;
    benefits: { lookup_status: string; failed_sources: string[]; message: string | null;
                scope_note: string | null; sources: BenefitSource[] };
    prepare_commands: Record<string, string> | null;
  };
  disclaimer: string;
}
export type SelectedRegion = Omit<RegionItem, 'group'> & {
  group: 1 | 2 | 3 | null; festivals_undated: FestivalItem[];
  states: { festivals: 'found' | 'none_in_period' | 'unavailable'; festivals_stale: boolean;
            benefits: 'found' | 'excluded_only' | 'none_in_scope' | 'unavailable'; benefits_partial: boolean;
            needs_user_info: boolean };
}
export type SearchInput = {
  start_date: string; end_date: string; sigungu_code?: string;
  residence?: string; party_size?: number; birth_date?: string;
}

export function requestBody(input: SearchInput) {
  const body: Record<string, string | number> = { start_date: input.start_date, end_date: input.end_date }
  if (input.sigungu_code) body.sigungu_code = input.sigungu_code
  if (input.residence) body.residence = input.residence
  if (input.party_size) body.party_size = input.party_size
  if (input.birth_date) body.birth_date = input.birth_date
  return body
}

/**
 * Build the request for the selected slingshot region. Only fields that exist in the
 * settings dialog (거주 시군구, 여행 인원) are sent; anything missing is omitted, never guessed.
 * Birth date is never sent because the UI has no such field.
 */
export function regionRequest(code: string, start: string, end: string,
  user: { residence?: string | null; party_size?: number | null } = {}): SearchInput {
  const party = user.party_size
  return { start_date: start, end_date: end, sigungu_code: code,
    residence: user.residence && /^\d{5}$/.test(user.residence) ? user.residence : undefined,
    party_size: typeof party === 'number' && Number.isInteger(party) && party >= 1 ? party : undefined }
}

export type FestivalOutcome = {
  rows: Festival[];
  /** found / none_in_period / unavailable (collection failed or never collected: not "no festivals"). */
  state: 'found' | 'none_in_period' | 'unavailable';
  /** Last collection attempt failed; rows come from the previous successful collection. */
  usingPrevious: boolean;
  lastSuccessAt: string | null;
}

/** Map the selected destination's festivals onto the existing festival card shape. Nothing is invented. */
export function festivalsFromSelected(data: DateRecommendResponse, region: string): FestivalOutcome {
  const sel = data.selected_region
  const src = data.data_status.festivals
  const toRow = (f: FestivalItem): Festival => ({
    id: f.content_id, region_name: region, title: f.title, start_date: f.start_date, end_date: f.end_date,
    // Empty strings mean "not in the data": the card leaves that row out instead of printing a placeholder.
    period_note: f.start_date || f.end_date ? `${f.start_date || '미확인'} ~ ${f.end_date || '미확인'}` : '',
    location: f.place?.trim() || '', source_url: f.source_url?.trim() || '', source_status: '',
    collected_at: f.fetched_at || '', source: f.source?.trim() || undefined,
  })
  const rows = sel ? [...sel.festivals, ...sel.festivals_undated].map(toRow) : []
  const state = sel?.states.festivals ?? 'unavailable'
  return { rows, state, usingPrevious: state !== 'unavailable' && src.status !== 'ok',
           lastSuccessAt: src.last_success_at }
}

const OFFICIAL_SOURCE_TYPES = ['official_webpage', 'official_notice', 'gov24_api']
const POSTED_TEXT: Record<string, string> = { open: '신청접수중', closing_soon: '마감 임박', upcoming: '준비중', closed: '마감',
  closed_early: '조기 마감', budget_exhausted: '예산 소진', ended: '종료' }
const trimmed = (value: string | null | undefined) => (typeof value === 'string' ? value.trim() : '')

/**
 * One period-judged program (selected_region.benefits) in the existing benefit card shape.
 * `extra` is the same program's /api/team/programs row (collected 지역화폐·특이사항·문의처), used only to fill
 * empty text. The judgment always comes from the date lookup and is never upgraded.
 */
export function benefitFromItem(p: ProgramItem, region: string, extra?: Benefit): Benefit {
  const trip = p.trip_period
  const app = p.application_period
  return {
    id: `${p.program_id}@${region}`, name: p.name, region_name: region,
    source_status: p.posted_status ? POSTED_TEXT[p.posted_status] || p.posted_status : '확인 필요',
    status: p.posted_status || 'unknown',
    source_url: trimmed(p.official_url), apply_url: trimmed(p.apply_url) || null,
    trip_start: trip?.start || '', trip_end: trip?.end || '',
    period_note: trip && (trip.start || trip.end) ? `여행 인정 기간 ${trip.start || '미확인'} ~ ${trip.end || '미확인'}` : '여행 인정 기간 미확인',
    payment_rule: extra?.payment_rule || trimmed(p.payout_method),
    conditions: extra?.conditions || trimmed(p.conditions_text),
    contact: extra?.contact || '',
    collected_at: p.last_success_at || extra?.collected_at || '', verified_at: p.last_verified_at,
    needs_review: p.verification_status !== 'verified', present_in_source: true, refund_rate: extra?.refund_rate ?? null,
    data_origin: p.data_origin ?? extra?.data_origin, source_type: p.source_type ?? extra?.source_type ?? null,
    application_start: app?.start || '', application_end: app?.end || '',
    source_pages: (p.sources || []).filter(s => OFFICIAL_SOURCE_TYPES.includes(s.type)).map(s => ({ title: s.title, url: s.url })),
    judgment: p.judgment, excluded_reason: p.excluded_reason, audience: p.audience ?? 'general',
  }
}

export type RegionBenefits = { shown: Benefit[]; excluded: Benefit[]; state: SelectedRegion['states']['benefits']; partial: boolean }
/** applicable first, then needs_verification (both shown), excluded kept separately. Nothing is dropped. */
export function benefitsFromSelected(data: DateRecommendResponse, region: string, rows: Benefit[] = []): RegionBenefits {
  const sel = data.selected_region
  const extra = (p: ProgramItem) => rows.find(r => r.id === `${p.program_id}@${region}`)
  const map = (list: ProgramItem[]) => list.map(p => benefitFromItem(p, region, extra(p)))
  if (!sel) return { shown: [], excluded: [], state: 'unavailable', partial: false }
  // General tourist support leads; group-limited travel support follows (it is never 'applicable' anyway).
  const shown = map([...sel.benefits.applicable, ...sel.benefits.needs_verification])
  return { shown: [...shown.filter(b => b.audience !== 'targeted'), ...shown.filter(b => b.audience === 'targeted')],
           excluded: map(sel.benefits.excluded),
           state: sel.states.benefits, partial: sel.states.benefits_partial }
}

export function validateDates(start: string, end: string, today: string): string | null {
  const iso = /^\d{4}-\d{2}-\d{2}$/
  if (!iso.test(start) || !iso.test(end)) return '여행 시작일과 종료일을 모두 선택해 주세요.'
  if (start < today) return '여행 시작일은 오늘 이후여야 해요.'
  if (end < start) return '종료일은 시작일과 같거나 이후여야 해요.'
  const days = (Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) / 86400000
  if (days >= 60) return '여행 기간은 60일 미만으로 선택해 주세요.'
  return null
}

/** FastAPI 422 bodies carry {detail: [{msg}]} or {detail: "text"}. */
export function errorMessage(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail.length) {
    const msg = String((detail[0] as { msg?: string }).msg || '')
    return msg.replace(/^Value error, /, '') || '입력값을 확인해 주세요.'
  }
  if (status >= 500) return '서버에서 오류가 났어요. 잠시 후 다시 시도해 주세요.'
  return `요청을 처리하지 못했어요 (HTTP ${status}).`
}

export async function fetchRecommendations(input: SearchInput, signal?: AbortSignal): Promise<DateRecommendResponse> {
  let response: Response
  try {
    response = await fetch('/api/team/date-recommendations', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(requestBody(input)), signal,
    })
  } catch (error) {
    if ((error as Error).name === 'AbortError') throw error
    throw new Error('서버에 연결하지 못했어요. 인터넷 연결을 확인하고 다시 시도해 주세요.')
  }
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(errorMessage(response.status, body))
  if (!body || !Array.isArray(body.regions) || !body.data_status) throw new Error('서버 응답을 읽지 못했어요. 잠시 후 다시 시도해 주세요.')
  if (input.sigungu_code && body.selected_region?.sigungu_code !== input.sigungu_code)
    throw new Error('선택한 여행지의 결과를 받지 못했어요. 다시 시도해 주세요.')
  return body as DateRecommendResponse
}

const FIELD_LABELS: Record<string, string> = {
  residence: '주민등록상 거주지', 'residence.sigungu': '거주 시군구', party_size: '여행 인원',
  birth_date: '생년월일', is_family: '가족 여부', same_address: '동일 주소 여부',
  prior_participated_program_ids: '과거 참여 이력',
}
const VISIT_LABELS: Record<string, string> = {
  nights: '숙박 수', checkin_dates: '체크인 날짜', places: '방문 장소', expected_spend: '예상 지출',
  'expected_spend.by_category': '항목별 예상 지출',
}
export function fieldLabel(field: string): string {
  if (FIELD_LABELS[field]) return FIELD_LABELS[field]
  const visit = field.match(/^visits\[\d+\]\.(.+)$/)
  if (visit) return VISIT_LABELS[visit[1]] || visit[1]
  return field
}
export function fieldLabels(fields: string[]): string[] {
  return [...new Set(fields.map(fieldLabel))]
}

export const JUDGMENT_LABEL: Record<Judgment, string> = {
  potentially_eligible: '신청 가능 예상', needs_verification: '추가 확인 필요', ineligible: '대상 아님',
}
export const CATEGORY_LABEL: Record<string, string> = {
  festival_and_benefit: '축제 + 신청 가능 예상 혜택', festival_only: '축제', benefit_only: '신청 가능 예상 혜택',
  benefit_needs_verification: '확인 필요 지역',
  festival_and_benefit_needs_verification: '축제 + 확인 필요 혜택',
}
export const POSTED_LABEL: Record<string, string> = {
  open: '신청접수중', closing_soon: '마감 임박', upcoming: '준비중', closed: '마감',
  closed_early: '조기 마감', budget_exhausted: '예산 소진', ended: '종료',
}
export function originLabel(p: Pick<ProgramItem, 'data_origin' | 'source_type' | 'verification_status'>): string {
  if (p.data_origin === 'kto_tour50') return '한국관광공사 반값여행 현황(공식 페이지 수집)'
  if (p.data_origin === 'gov24_api') return '행정안전부 공공서비스 API 수집'
  if (p.data_origin === 'merged') return '공공 API + 수동 등록'
  if (p.data_origin === 'manual_registry')
    return p.verification_status === 'verified' ? '수동 등록(공고 검토 완료)' : '수동 등록 자료(보도 기반·공식 공고 미검토)'
  return p.data_origin || '출처 미상'
}
export function periodText(p: Period): string {
  if (!p || (!p.start && !p.end)) return '미확인'
  return `${p.start || '미확인'} ~ ${p.end || '미확인'}`
}
export function kstTime(value: string | null): string {
  if (!value) return '확인 기록 없음'
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return value
  return new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit',
    day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(date)
}
export function emptyStateKind(data: DateRecommendResponse): 'none' | 'no_match' | 'unavailable' {
  if (data.regions.length) return 'none'
  return data.outcome === 'no_match_in_scope' ? 'no_match' : 'unavailable'
}
