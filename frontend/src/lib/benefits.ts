export type Benefit = {
  id: string; name: string; region_name: string; source_status: string;
  status: string; source_url: string; apply_url: string | null;
  trip_start: string; trip_end: string; period_note: string;
  payment_rule: string; conditions: string; contact: string;
  collected_at: string; verified_at: string | null; needs_review: boolean;
  present_in_source: boolean; refund_rate: number | null;
  /** Where the row came from (kto_tour50 / gov24_api / manual_registry); absent in preview data. */
  data_origin?: string; source_type?: string | null;
  application_start?: string; application_end?: string;
  source_pages?: { title: string | null; url: string | null }[];
  /** Set only for rows from the date lookup: its judgment for the selected period. */
  judgment?: string; excluded_reason?: string;
  /** general = 일반 관광객 대상, targeted = 특정 대상 전용 관광지원 (from the server's classification). */
  audience?: 'general' | 'targeted';
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
  program_id: string; name: string; sigungu_names: string[]; posted_status: string | null;
  open_now: boolean | null; trip_period: { start: string | null; end: string | null } | null;
  application_period: { start: string | null; end: string | null } | null;
  refund_rate: number | null; data_origin: string; verification_status: string;
  status_checked_at: string | null; superseded_by: string[];
  official_info_url: string | null; application_url: string | null;
  source_type?: string | null;
  /** Collected text shown as-is (null when the source has none). */
  payment_methods?: string[] | null; contacts?: string[] | null; notes?: string | null;
  source_pages?: { title: string | null; url: string | null }[];
  audience?: 'general' | 'targeted';
}
const clean = (value: string | null | undefined) => (typeof value === 'string' ? value.trim() : '')
const joined = (values: string[] | null | undefined, sep: string) => (values ?? []).map(clean).filter(Boolean).join(sep)
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
    payment_rule: joined(row.payment_methods, ', '), conditions: clean(row.notes), contact: joined(row.contacts, ' · '),
    collected_at: row.status_checked_at || '', verified_at: null,
    needs_review: row.verification_status !== 'verified',
    present_in_source: row.superseded_by.length === 0, refund_rate: row.refund_rate,
    data_origin: row.data_origin, source_type: row.source_type ?? null,
    application_start: row.application_period?.start || '', application_end: row.application_period?.end || '',
    source_pages: row.source_pages ?? [], audience: row.audience ?? 'general',
  })))
}

const ORIGIN_RANK: Record<string, number> = { kto_tour50: 0, manual_registry: 1, merged: 1, gov24_api: 2 }
/** The program featured for a destination: 반값여행 rounds first, public services last.
 *  Order within a source is the API's (open first). Display choice only; no eligibility judgment. */
export function pickRegionBenefit(rows: Benefit[], region: string | undefined): Benefit | undefined {
  if (!region) return undefined
  return rows.map((row, i) => ({ row, i }))
    .filter(({ row }) => row.region_name === region && row.present_in_source)
    .sort((a, b) => (ORIGIN_RANK[a.row.data_origin ?? ''] ?? 1) - (ORIGIN_RANK[b.row.data_origin ?? ''] ?? 1) || a.i - b.i)[0]?.row
}
/** Card label that matches what the program actually is. */
export function programKind(row: Pick<Benefit, 'data_origin' | 'audience'>): string {
  if (row.audience === 'targeted') return '특정 대상 전용 관광지원'
  if (row.data_origin === 'gov24_api') return '공공서비스'
  if (row.data_origin === 'manual_registry') return '여행 지원제도 · 보도 기준'
  return '지역사랑 휴가지원'
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
