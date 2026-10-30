export type Benefit = {
  id: string; name: string; region_name: string; source_status: string;
  status: string; source_url: string; apply_url: string | null;
  trip_start: string; trip_end: string; period_note: string;
  payment_rule: string; conditions: string; contact: string;
  collected_at: string; verified_at: string | null; needs_review: boolean;
  present_in_source: boolean; refund_rate: number | null;
  /** From GET /api/team/programs only (absent in preview snapshots). null = the source did not state it. */
  family_id?: string; application_note?: string; application_end?: string | null;
  pre_apply_days?: number | null; settle_days?: number | null;
}
export type Trip = {
  type: '당일' | '1박 2일'; date: string; origin: string; residence: string;
  people: number; transport: '자차' | '대중교통';
}
/** Trip end date derived from the existing settings dialog (여행 시작일 + 여행 유형). */
export function tripEnd(trip: Pick<Trip, 'date' | 'type'>) {
  return addDays(trip.date, trip.type === '당일' ? 0 : 1)
}

/** One row of GET /api/team/programs (backend/app/team/program_list.py). */
export type ProgramRow = {
  program_id: string; family_id?: string; name: string; sigungu_names: string[]; posted_status: string | null;
  open_now: boolean | null; trip_period: { start: string | null; end: string | null } | null;
  application_period: { start: string | null; end: string | null } | null;
  refund_rate: number | null; data_origin: string; verification_status: string;
  status_checked_at: string | null; superseded_by: string[];
  official_info_url: string | null; application_url: string | null;
  // null = the source did not state it (shown as "공식 공고 확인 필요"), never "no requirement".
  payment_methods?: string[] | null; proof_items?: string[] | null; contacts?: string[] | null;
  visit_rule?: { must_include: string[]; any_of: string[]; min_any_of: number; min_total_places: number | null } | null;
  conditions_text?: string | null;
  pre_apply_days_before_trip?: number | null; settlement_days_after_trip?: number | null;
}
/** 방문·증빙 조건 text: structured rules first, then the source's own wording. Unverified data says so. */
export function conditionsText(row: ProgramRow): string {
  const v = row.visit_rule
  const parts = [
    v?.must_include.length ? `${v.must_include.join('·')} 포함 방문` : '',
    v?.any_of.length ? `${v.any_of.join('·')} 중 ${v.min_any_of || 1}곳 이상 방문` : '',
    v?.min_total_places ? `관광지 ${v.min_total_places}곳 이상 방문` : '',
    row.proof_items?.length ? `증빙: ${row.proof_items.join(', ')}` : '',
    row.conditions_text?.trim() ? `원문: ${row.conditions_text.trim()}` : '',
  ].filter(Boolean)
  if (parts.length && row.verification_status !== 'verified') parts.push('※ 공식 공고로 최종 확인이 필요해요.')
  return parts.join('\n')
}
const POSTED: Record<string, string> = { open: '신청접수중', closing_soon: '마감 임박', upcoming: '준비중', closed: '마감' }
/** Expand programs into one row per region for the existing list/compare screens. Nothing is invented:
 * unknown periods stay empty strings (never "in period"), unknown check times make rows stale. */
export function benefitsFromPrograms(rows: ProgramRow[]): Benefit[] {
  return rows.flatMap(row => row.sigungu_names.map(region => ({
    id: `${row.program_id}@${region}`, name: row.name, region_name: region,
    source_status: row.posted_status ? POSTED[row.posted_status] || row.posted_status : '확인 필요',
    status: row.posted_status || 'unknown',
    source_url: row.official_info_url || '', apply_url: row.application_url,
    trip_start: row.trip_period?.start || '', trip_end: row.trip_period?.end || '',
    period_note: row.trip_period ? `여행 인정 기간 ${row.trip_period.start || '미확인'} ~ ${row.trip_period.end || '미확인'}` : '여행 인정 기간 미확인',
    payment_rule: (row.payment_methods ?? []).join(', '), conditions: conditionsText(row),
    contact: (row.contacts ?? []).join('\n'),
    collected_at: row.status_checked_at || '', verified_at: null,
    needs_review: row.verification_status !== 'verified',
    present_in_source: row.superseded_by.length === 0, refund_rate: row.refund_rate,
    family_id: row.family_id ?? row.program_id, application_end: row.application_period?.end ?? null,
    application_note: row.application_period ? `신청 기간 ${row.application_period.start || '미확인'} ~ ${row.application_period.end || '미확인'}` : '신청 기간 미확인',
    pre_apply_days: row.pre_apply_days_before_trip ?? null, settle_days: row.settlement_days_after_trip ?? null,
  })))
}
export const rateText = (rate: number | null | undefined) => typeof rate === 'number' ? `${Math.round(rate * 100)}%` : null
/** Dated reminders from the program's stated rules; null when the source did not state that rule. */
export function deadlineNotes(row: Benefit, trip: Pick<Trip, 'date' | 'type'>) {
  const check = row.needs_review ? ' (공식 공고로 확인 필요)' : ''
  return {
    apply: row.application_end ? `신청 마감 ${row.application_end}${check}` : null,
    preApply: typeof row.pre_apply_days === 'number'
      ? `여행 시작 ${row.pre_apply_days}일 전인 ${addDays(trip.date, -row.pre_apply_days)}까지 사전 신청${check}` : null,
    settle: typeof row.settle_days === 'number'
      ? `여행 종료 후 ${row.settle_days}일 이내, ${addDays(tripEnd(trip), row.settle_days)}까지 증빙 제출${check}` : null,
  }
}
export function today() {
  return new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date())
}
export function addDays(day: string, days: number) {
  const value = new Date(`${day}T12:00:00Z`)
  value.setUTCDate(value.getUTCDate()+days)
  return value.toISOString().slice(0,10)
}
export function shortDate(day: string) {
  return new Intl.DateTimeFormat('ko-KR',{month:'long',day:'numeric',timeZone:'Asia/Seoul'}).format(new Date(`${day}T12:00:00+09:00`))
}
export function observation(row: Benefit) {
  if (!Number.isFinite(Date.parse(row.collected_at))) return '확인 시각 미상'
  return new Intl.DateTimeFormat('ko-KR',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',timeZone:'Asia/Seoul'}).format(new Date(row.collected_at))
}
export function isStale(row: Benefit) {
  return !Number.isFinite(Date.parse(row.collected_at)) || Date.now()-Date.parse(row.collected_at)>7*86400000
}
export function inPeriod(row: Benefit, trip: Pick<Trip, 'date' | 'type'>) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(trip.date) || !Number.isFinite(Date.parse(trip.date))) return false
  if (!row.trip_start || !row.trip_end) return false
  return trip.date >= row.trip_start && tripEnd(trip)<=row.trip_end
}
export function isOpen(row: Benefit) {
  return row.present_in_source && !isStale(row) && row.source_status==='신청접수중'
}
/** Every listed program of a region, in API order. A region can have several (e.g. 휴가지원 차수 + 섬 반값여행). */
export function regionPrograms(rows: Benefit[], region: string | undefined) {
  return region ? rows.filter(row => row.region_name === region && row.present_in_source) : []
}
/** The program the user picked, else the first open one, else the first listed. */
export function pickProgram(rows: Benefit[], id: string | null): Benefit | undefined {
  return rows.find(row => row.id === id) ?? rows.find(isOpen) ?? rows[0]
}
export function safeUrl(value: string | null) {
  if (!value) return undefined
  try { const url=new URL(value); return ['http:','https:'].includes(url.protocol) && !url.username && !url.password ? url.href : undefined } catch { return undefined }
}
export function readStored<T>(key: string, fallback: T): T {
  try { return JSON.parse(sessionStorage.getItem(key) || 'null') ?? fallback } catch { return fallback }
}
export function writeStored(key: string, value: unknown) {
  try { sessionStorage.setItem(key,JSON.stringify(value)) } catch { /* Storage can be disabled. */ }
}
