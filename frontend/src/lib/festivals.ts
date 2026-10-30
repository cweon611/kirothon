export type Festival = {
  id:string; region_name:string; title:string; start_date:string|null; end_date:string|null;
  period_note:string; location:string; source_url:string; source_status:string; collected_at:string;
}
export function festivalState(row:Festival, start:string, end:string, today:string) {
  if (/취소|연기|미정/.test(row.source_status)) return 'unconfirmed'
  if (!row.start_date || !row.end_date) return 'unknown'
  if (row.end_date < today) return 'ended'
  if (row.start_date <= end && row.end_date >= start) return 'match'
  return 'other'
}
export function festivalStale(row:Festival, now=Date.now()) {
  const collected=Date.parse(row.collected_at)
  return !Number.isFinite(collected)||now-collected>7*86400000
}
export function rankFestivals(rows:Festival[], region:string, start:string, end:string, today:string) {
  const order={match:0,other:1,unknown:2,unconfirmed:3,ended:4}
  return rows.filter(row=>row.region_name===region).slice().sort((a,b)=>{
    const stateA=festivalState(a,start,end,today),stateB=festivalState(b,start,end,today)
    return order[stateA]-order[stateB] || (stateA==='ended'?(b.end_date||'').localeCompare(a.end_date||''):(a.start_date||'9999').localeCompare(b.start_date||'9999')) || a.title.localeCompare(b.title,'ko')
  })
}
