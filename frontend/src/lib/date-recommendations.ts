// Client for POST /api/team/date-recommendations (backend/app/team/date_recommend.py).
import type { Festival } from './festivals.ts'

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
    period_note: `${f.start_date || '날짜 미확인'} ~ ${f.end_date || '날짜 미확인'}`,
    location: f.place || '장소 미확인', source_url: f.source_url || '', source_status: '',
    collected_at: f.fetched_at || '', source: f.source,
  })
  const rows = sel ? [...sel.festivals, ...sel.festivals_undated].map(toRow) : []
  const state = sel?.states.festivals ?? 'unavailable'
  return { rows, state, usingPrevious: state !== 'unavailable' && src.status !== 'ok',
           lastSuccessAt: src.last_success_at }
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
  if (status >= 500) return '서버에서 오류가 났어요. 백엔드 실행 상태를 확인해 주세요.'
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
    throw new Error('백엔드 서버에 연결하지 못했어요. 백엔드(127.0.0.1:8000)가 켜져 있는지 확인해 주세요.')
  }
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(errorMessage(response.status, body))
  if (!body || !Array.isArray(body.regions) || !body.data_status) throw new Error('추천 결과 형식을 확인할 수 없어요.')
  if (input.sigungu_code && body.selected_region?.sigungu_code !== input.sigungu_code)
    throw new Error('선택한 지역의 결과가 응답에 없어요. 백엔드 버전을 확인해 주세요.')
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
