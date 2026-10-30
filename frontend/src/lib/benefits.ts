export type Benefit = {
  id: string; name: string; region_name: string; source_status: string;
  status: string; source_url: string; apply_url: string | null;
  trip_start: string; trip_end: string; period_note: string;
  payment_rule: string; conditions: string; contact: string;
  collected_at: string; verified_at: string | null; needs_review: boolean;
  present_in_source: boolean; refund_rate: number | null;
}
export type Trip = {
  type: '당일' | '1박 2일'; date: string; origin: string; residence: string;
  people: number; transport: '자차' | '대중교통';
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
  return new Intl.DateTimeFormat('ko-KR',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',timeZone:'Asia/Seoul'}).format(new Date(row.collected_at))
}
export function isStale(row: Benefit) {
  return !Number.isFinite(Date.parse(row.collected_at)) || Date.now()-Date.parse(row.collected_at)>7*86400000
}
export function inPeriod(row: Benefit, trip: Trip) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(trip.date) || !Number.isFinite(Date.parse(trip.date))) return false
  return trip.date >= row.trip_start && addDays(trip.date,trip.type==='당일'?0:1)<=row.trip_end
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
