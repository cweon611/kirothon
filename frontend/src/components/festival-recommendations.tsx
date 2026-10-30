import { useEffect, useRef, useState } from 'react'
import { CalendarDays, ExternalLink, MapPin, Sparkles, RefreshCw } from 'lucide-react'
import { type Festival, festivalState, festivalStale, rankFestivals } from '@/lib/festivals'
import { type Trip, today, addDays, safeUrl } from '@/lib/benefits'
import { type FestivalOutcome, fetchRecommendations, festivalsFromSelected, kstTime, regionRequest, validateDates } from '@/lib/date-recommendations'
import './festival-recommendations.css'

/**
 * Festivals for the slingshot destination (`code`) during the trip dates.
 * Dates come only from the existing trip inputs; nothing is requested until the user has
 * confirmed them (`confirmed`). Only the destination code and dates are sent.
 */
export function FestivalRecommendations({region,code,trip,confirmed}:{region:string;code:string|null;trip:Trip;confirmed:boolean}) {
  const [data,setData]=useState<Festival[]>([])
  const [outcome,setOutcome]=useState<Omit<FestivalOutcome,'rows'>|null>(null)
  const [loading,setLoading]=useState(confirmed)
  const [error,setError]=useState('')
  const [retry,setRetry]=useState(0)
  const [showAll,setShowAll]=useState(false)
  const latest=useRef(0)
  const end=addDays(trip.date,trip.type==='당일'?0:1)
  useEffect(()=>{
    const id=++latest.current
    const mine=(fn:()=>void)=>{if(id===latest.current)fn()}
    const controller=new AbortController()
    if(!confirmed){mine(()=>{setLoading(false);setError('');setData([]);setOutcome(null)});return ()=>controller.abort()}
    if(import.meta.env.VITE_REVIEW_PREVIEW==='true'){
      fetch('/review-data/festivals.json',{signal:controller.signal})
        .then(async response=>{if(!response.ok)throw new Error();const body=await response.json();if(!Array.isArray(body.items))throw new Error();mine(()=>{setData(body.items);setOutcome(null)})})
        .catch(()=>mine(()=>setError('축제 정보를 불러오지 못했어요.'))).finally(()=>mine(()=>setLoading(false)))
      return ()=>controller.abort()
    }
    const invalid=!code?'선택한 여행지의 지역 코드를 찾지 못했어요.':validateDates(trip.date,end,today())
    if(invalid){mine(()=>{setLoading(false);setError(invalid);setData([]);setOutcome(null)});return ()=>controller.abort()}
    mine(()=>{setLoading(true);setError('')})
    const timeout=window.setTimeout(()=>controller.abort(),20000)
    fetchRecommendations(regionRequest(code!,trip.date,end),controller.signal)
      .then(body=>{const {rows,...rest}=festivalsFromSelected(body,region);mine(()=>{setData(rows);setOutcome(rest)})})
      .catch(e=>mine(()=>{setData([]);setOutcome(null);setError((e as Error).name==='AbortError'?'응답이 늦어 요청을 중단했어요.':(e as Error).message)}))
      .finally(()=>{clearTimeout(timeout);mine(()=>setLoading(false))})
    return ()=>{clearTimeout(timeout);controller.abort()}
  },[region,code,trip.date,end,confirmed,retry])
  const current=today()
  const ranked=rankFestivals(data,region,trip.date,end,current)
  const matching=ranked.filter(row=>festivalState(row,trip.date,end,current)==='match')
  const live=ranked.filter(row=>['match','other'].includes(festivalState(row,trip.date,end,current)))
  const shown=showAll?ranked:live.slice(0,3)
  const stateLabels={match:'여행일과 겹쳐요',other:'다른 일정',unknown:'일정 확인 필요',ended:'종료된 행사',unconfirmed:'개최 여부 확인 필요'}
  return <section className="festival-section" aria-labelledby="festival-title">
    <div className="festival-intro"><span className="festival-eyebrow"><Sparkles size={15}/> 여행의 이유가 되는 순간</span><h2 id="festival-title">{region}에서 만나는 축제</h2><p>가고 싶은 축제 하나, 이번 여행에 더해보세요.</p></div>
    <div className="festival-trip"><CalendarDays size={17}/><span>{trip.date} ~ {end}</span><strong>{!confirmed?'날짜 확인 전':loading?'확인 중':`여행일에 맞는 축제 ${matching.length}개`}</strong></div>
    {!confirmed?<div className="festival-empty" role="status"><p>여행 날짜를 아직 확인하지 않았어요. 위의 <strong>여행 정보 수정</strong>에서 여행 시작일과 유형을 정하면 그 기간의 축제를 보여드려요.</p></div>
    :loading?<div className="festival-empty" role="status"><RefreshCw className="loading-spin" size={22}/><p>지역 축제를 찾고 있어요.</p></div>
    :error||outcome?.state==='unavailable'?<div className="festival-empty" role="alert"><p>{error||'축제 데이터를 확인하지 못했어요(수집 실패 또는 미수집). ‘축제 없음’이 아니에요.'}</p><button className="text-button" onClick={()=>setRetry(value=>value+1)}>다시 불러오기</button></div>:<>
      {outcome?.usingPrevious&&<p className="festival-hint">마지막 축제 수집이 실패해 {kstTime(outcome.lastSuccessAt)}에 정상 수집한 자료를 보여드려요. 최신 일정은 공식 안내를 확인해 주세요.</p>}
      {!matching.length&&<p className="festival-hint">{ranked.length?'여행일과 겹치는 것으로 확인된 축제는 없어요. 일정이 확인되지 않은 행사는 공식 안내를 확인해 주세요.':'이 기간에 진행이 확인된 축제가 없어요. 새 일정은 공식 목록에서 확인해 주세요.'}</p>}
      <div className="festival-list">{shown.map(row=>{
        const state=festivalState(row,trip.date,end,current),stale=festivalStale(row)
        const href=safeUrl(row.source_url)
        return <article className={`festival-card festival-${state}`} key={row.id}>
          <div className="festival-calendar" aria-hidden="true"><span>{row.start_date?`${Number(row.start_date.slice(5,7))}월`:'일정'}</span><strong>{row.start_date?row.start_date.slice(8):'?'}</strong><span>FESTIVAL</span></div>
          <div className="festival-content"><span className="festival-state">{stateLabels[state]}{stale?' · 정보 재확인 필요':''}</span><h3>{row.title}</h3><p><CalendarDays size={14}/>{row.period_note}</p><p><MapPin size={14}/>{row.location}</p><div className="festival-source"><small>{row.source||'문체부'} · {row.collected_at?`${row.collected_at.slice(0,10)} 수집`:'수집일 미확인'}</small>{href&&<a href={href} target="_blank" rel="noopener noreferrer" aria-label={`${row.title} 공식 안내 (새 탭)`}>공식 안내 <ExternalLink size={13}/></a>}</div></div>
        </article>
      })}</div>
      {ranked.length>live.slice(0,3).length&&<button className="festival-more" aria-expanded={showAll} onClick={()=>setShowAll(value=>!value)}>{showAll?'예정 축제만 보기':`일정 미확인 행사 포함 ${ranked.length}개 모두 보기`}</button>}
    </>}
    <div className="festival-footnote"><span>운영시간·취소 여부는 방문 전 공식 안내를 확인해 주세요.</span><a href="https://www.mcst.go.kr/site/s_culture/festival/festivalList.jsp?pSido=15" target="_blank" rel="noopener noreferrer">공식 축제 목록 <ExternalLink size={12}/></a></div>
  </section>
}
