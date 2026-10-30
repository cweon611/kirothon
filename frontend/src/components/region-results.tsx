import { useEffect, useRef, useState } from 'react'
import { CalendarDays, ExternalLink, MapPin, RefreshCw, Sparkles, Ticket, TriangleAlert } from 'lucide-react'
import { safeUrl, today } from '@/lib/benefits'
import {
  type DateRecommendResponse, type FestivalItem, type ProgramItem, JUDGMENT_LABEL, POSTED_LABEL,
  fetchRecommendations, fieldLabels, kstTime, originLabel, periodText, regionRequest, validateDates,
} from '@/lib/date-recommendations'
import './region-results.css'

function Link({ url, children }: { url: string | null; children: string }) {
  const href = safeUrl(url)
  return href ? <a className="rr-link" href={href} target="_blank" rel="noopener noreferrer">{children} <ExternalLink size={13}/><span className="sr-only"> (새 탭)</span></a> : null
}

function Festival({ f }: { f: FestivalItem }) {
  return <li className="rr-festival">
    <strong>{f.title}</strong>
    <span><CalendarDays size={13}/> {f.start_date || '날짜 미확인'} ~ {f.end_date || '날짜 미확인'}</span>
    <span><MapPin size={13}/> {f.place || '장소 미확인'}</span>
    {f.overview && <p className="rr-overview">{f.overview.slice(0, 220)}{f.overview.length > 220 ? '…' : ''}</p>}
    <small>출처: {f.source} · 마지막 수집 {kstTime(f.fetched_at)}{f.source_url ? '' : ' · 공식 링크 미수집'}</small>
    <Link url={f.source_url}>공식 안내</Link>
  </li>
}

function Program({ p }: { p: ProgramItem }) {
  const missing = fieldLabels(p.missing_user_fields)
  const appPeriod = p.application_start_at || p.application_end_at
    ? `${p.application_start_at ? kstTime(p.application_start_at) : '미확인'} ~ ${p.application_end_at ? kstTime(p.application_end_at) : '미확인'}`
    : periodText(p.application_period)
  return <li className={`rr-program rr-${p.judgment}`}>
    <div className="rr-program-head">
      <span className={`rr-judgment rr-j-${p.excluded_reason ? 'ineligible' : p.judgment}`}>{p.excluded_reason ? '대상 아님·접수 마감' : JUDGMENT_LABEL[p.judgment]}</span>
      <span className="rr-chip">게시 상태: {p.posted_status ? POSTED_LABEL[p.posted_status] || p.posted_status : '미확인'}</span>
      {p.stale && <span className="rr-chip rr-warn">정보 오래됨</span>}
    </div>
    <h4>{p.name}{p.round_id ? <small> · 차수 {p.round_id}</small> : null}</h4>
    <dl className="rr-facts">
      <dt>여행 인정 기간</dt><dd>{periodText(p.trip_period)}</dd>
      <dt>신청 기간</dt><dd>{appPeriod}</dd>
      <dt>지원 내용</dt><dd>{p.support || '공식 공고 확인 필요'}</dd>
      <dt>지급 방식</dt><dd>{p.payout_method || '미확인'}</dd>
      <dt>주요 조건</dt><dd>{p.conditions_text || '원문 조건 미수집 · 공식 공고 확인 필요'}</dd>
      <dt>예상 지원액</dt><dd>{p.estimated_amount != null ? `${p.estimated_amount.toLocaleString()}원` : '확인 불가(지출·조건 미확인)'}</dd>
    </dl>
    {p.match_basis === 'text_hint' && <p className="rr-check">지역 연결: 기관명·본문 글자 일치로만 찾은 공공서비스예요. 여행지원 제도인지와 대상 지역을 공식 안내에서 확인해 주세요.</p>}
    {p.excluded_reason && <p className="rr-excluded-reason">제외 사유: {p.excluded_reason}</p>}
    {missing.length > 0 && <p className="rr-missing">추가로 필요한 정보: {missing.join(', ')}</p>}
    {p.needs_official_check.length > 0 && <p className="rr-check">공식 확인 필요: {p.needs_official_check.slice(0, 6).join(', ')}</p>}
    <div className="rr-source">
      <span>출처: {originLabel(p)}</span>
      <span>마지막 확인: {kstTime(p.last_success_at || p.last_verified_at)}</span>
      <span className="rr-links"><Link url={p.apply_url}>신청 페이지</Link><Link url={p.official_url}>공식 안내</Link></span>
    </div>
  </li>
}

function SourceStatus({ data }: { data: DateRecommendResponse }) {
  const f = data.data_status.festivals
  const label: Record<string, string> = { gov24_api: '공공서비스(혜택) API', kto_tour50: '반값여행 현황 페이지' }
  return <details className={`rr-status ${data.complete ? '' : 'rr-status-incomplete'}`} open={!data.complete}>
    <summary>데이터 확인 상태 {data.complete ? '· 정상' : '· 일부 확인 실패/오래됨'}</summary>
    <ul>
      <li><strong>축제(관광공사 KorService2)</strong>: {f.status === 'ok' ? '정상' : f.message || f.status} · 저장 {f.records}건 · 마지막 정상 수집 {kstTime(f.last_success_at)}</li>
      {data.data_status.benefits.sources.map(s => <li key={s.source}><strong>{label[s.source] || s.source}</strong>: {s.status === 'ok' && !s.stale ? '정상' : (s.message || s.status)}{s.stale ? ' (오래됨)' : ''} · 저장 {s.records}건 · 마지막 정상 수집 {kstTime(s.last_success_at)}</li>)}
      {data.data_status.benefits.lookup_status === 'error' && <li><strong>지원제도 판정</strong>: {data.data_status.benefits.message || '판정 모듈 오류'}</li>}
      <li><strong>수동 등록 자료</strong>: 보도·프로젝트 문서 기반, 공식 공고 미검토(실제 수집 데이터 아님)</li>
    </ul>
    {!data.complete && <p className="rr-hint">데이터 준비: <code>.\scripts\prepare-date-data.ps1</code> · 키는 서버의 <code>backend\.env</code>(<code>TOURAPI_SERVICE_KEY</code>, <code>KIROTHON_DATA_GO_KR_SERVICE_KEY</code>)</p>}
  </details>
}

/**
 * Step 3 result area. Dates, residence and party size come only from the existing
 * 여행 정보 수정 dialog; nothing is queried until that dialog has been submitted.
 */
export function RegionResults({ regionName, code, start, end, confirmed, residence, residenceName, people }: {
  regionName: string; code: string | null; start: string; end: string; confirmed: boolean;
  residence: string | null; residenceName: string; people: number | null;
}) {
  const [data, setData] = useState<DateRecommendResponse | null>(null)
  const [state, setState] = useState<'idle' | 'loading' | 'done' | 'error'>(confirmed ? 'loading' : 'idle')
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const latest = useRef(0)
  useEffect(() => {
    const id = ++latest.current
    const ac = new AbortController()
    const finish = (fn: () => void) => { if (id === latest.current) fn() }
    if (!confirmed) { finish(() => { setState('idle'); setError(''); setData(null) }); return () => ac.abort() }
    const invalid = !code ? '선택한 지역의 코드를 찾지 못했어요.' : validateDates(start, end, today())
    if (invalid) { finish(() => { setError(invalid); setState('error'); setData(null) }); return () => ac.abort() }
    finish(() => { setState('loading'); setError('') })
    const timer = window.setTimeout(() => ac.abort(), 20000)
    fetchRecommendations(regionRequest(code!, start, end, { residence, party_size: people }), ac.signal)
      .then(body => finish(() => { setData(body); setState('done') }))
      .catch(e => finish(() => {
        setData(null); setState('error')
        setError((e as Error).name === 'AbortError' ? '응답이 늦어 요청을 중단했어요. 다시 시도해 주세요.' : (e as Error).message)
      }))
      .finally(() => clearTimeout(timer))
    return () => { clearTimeout(timer); ac.abort() }
  }, [code, start, end, confirmed, residence, people, retry])

  const sel = data?.selected_region
  const b = sel?.benefits
  const shownPrograms = b ? [...b.applicable, ...b.needs_verification] : []
  return <section className="rr-panel" aria-labelledby="rr-title" aria-busy={state === 'loading'}>
    <header className="rr-head">
      <div><span className="rr-eyebrow">선택한 여행지</span><h2 id="rr-title"><MapPin size={20}/> {regionName}</h2>
        {confirmed && <p className="rr-period"><CalendarDays size={15}/> {start} ~ {end}</p>}</div>
    </header>
    <div aria-live="polite">
      {state === 'idle' && <div className="rr-idle" role="status">
        <p>여행 날짜를 아직 정하지 않았어요. 위의 <strong>여행 정보 수정</strong>에서 여행 시작일과 유형을 정하면 그 기간의 축제와 여행지원 제도를 보여드려요.</p>
      </div>}
      {confirmed && !residence && <p className="rr-note">거주 시군구 ‘{residenceName}’는 지역 코드로 확인할 수 없어 거주지 조건은 판정하지 않았어요(‘추가 확인 필요’).</p>}
      {state === 'loading' && <div role="status" className="rr-loading"><RefreshCw size={17} className="loading-spin"/> 저장된 공식 출처 데이터를 확인하고 있어요…</div>}
      {state === 'error' && <div role="alert" className="rr-error"><TriangleAlert size={18}/> <span>{error}</span> <button type="button" className="rr-textbtn" onClick={() => setRetry(v => v + 1)}>다시 시도</button></div>}
      {state === 'done' && data && sel && <>
        <SourceStatus data={data}/>
        {sel.reason && <p className="rr-reason">{sel.reason}</p>}
        <section className="rr-section"><h3><Sparkles size={17}/> 기간 내 축제·행사</h3>
          {sel.states.festivals !== 'unavailable' && data.data_status.festivals.status !== 'ok' &&
            <p className="rr-warning-line"><TriangleAlert size={14}/> 마지막 축제 수집 시도가 실패했어요. {kstTime(data.data_status.festivals.last_success_at)}에 정상 수집한 자료를 보여드려요.</p>}
          {sel.states.festivals === 'found' && <ul className="rr-list">{sel.festivals.map(f => <Festival key={f.content_id} f={f}/>)}</ul>}
          {sel.states.festivals === 'none_in_period' && <p className="rr-empty">이 기간에 진행이 확인된 축제가 없어요{sel.states.festivals_stale ? ' (축제 데이터가 오래됐어요. 최신 일정은 공식 안내를 확인해 주세요)' : ''}.</p>}
          {sel.states.festivals === 'unavailable' && <p className="rr-empty rr-empty-warn"><TriangleAlert size={15}/> 축제 데이터를 확인하지 못했어요(수집 실패 또는 미수집). ‘축제 없음’이 아니에요.</p>}
          {sel.festivals_undated.length > 0 && <details className="rr-undated"><summary>일정 미확인 행사 {sel.festivals_undated.length}건 (기간 내 개최 확인 안 됨)</summary>
            <ul className="rr-list">{sel.festivals_undated.map(f => <Festival key={f.content_id} f={f}/>)}</ul></details>}
        </section>
        <section className="rr-section"><h3><Ticket size={17}/> 여행지원 제도</h3>
          {sel.states.benefits === 'unavailable' && <p className="rr-empty rr-empty-warn"><TriangleAlert size={15}/> 지원제도 판정을 하지 못했어요(연결 오류). ‘지원제도 없음’이 아니에요.</p>}
          {sel.states.benefits_partial && <p className="rr-warning-line"><TriangleAlert size={14}/> 일부 지원제도 출처를 확인하지 못했거나 오래돼 저장된 자료로 판정했어요.</p>}
          {sel.states.needs_user_info && <p className="rr-missing">입력받지 않은 정보는 추측하지 않고 ‘추가 확인 필요’로 표시해요: {fieldLabels(sel.missing_user_fields).join(', ')}</p>}
          {shownPrograms.length > 0 && <ul className="rr-list">{shownPrograms.map(p => <Program key={p.program_id} p={p}/>)}</ul>}
          {(sel.states.benefits === 'none_in_scope' || sel.states.benefits === 'excluded_only') &&
            <p className="rr-empty">조회 범위에서 이 기간에 신청 가능하거나 확인이 필요한 지원제도를 찾지 못했어요. 그 지역에 지원제도가 없다는 뜻은 아니에요.</p>}
          {b && b.excluded.length > 0 && <details className="rr-undated"><summary>대상 아님·접수 마감 {b.excluded.length}건</summary>
            <ul className="rr-list">{b.excluded.map(p => <Program key={p.program_id} p={p}/>)}</ul></details>}
        </section>
        <p className="rr-note">{data.disclaimer}</p>
      </>}
    </div>
  </section>
}
