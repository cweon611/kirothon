import { useEffect, useState } from 'react'
import { CalendarDays, ExternalLink, MapPin, Sparkles, RefreshCw } from 'lucide-react'
import { type Festival, festivalState, festivalStale, rankFestivals } from '@/lib/festivals'
import { type Trip, today, addDays, safeUrl } from '@/lib/benefits'
import './festival-recommendations.css'

export function FestivalRecommendations({region,trip}:{region:string;trip:Trip}) {
  const [data,setData]=useState<Festival[]>([])
  const [loading,setLoading]=useState(true)
  const [error,setError]=useState(false)
  const [retry,setRetry]=useState(0)
  const [showAll,setShowAll]=useState(false)
  useEffect(()=>{
    let active=true
    const controller=new AbortController()
    const timeout=window.setTimeout(()=>controller.abort(),12000)
    fetch(import.meta.env.VITE_REVIEW_PREVIEW==='true'?'/review-data/festivals.json':`/api/team/festivals?region=${encodeURIComponent(region)}`,{signal:controller.signal})
      .then(async response=>{if(!response.ok)throw new Error();const body=await response.json();if(!Array.isArray(body.items))throw new Error();if(active)setData(body.items)})
      .catch(()=>{if(active)setError(true)})
      .finally(()=>{clearTimeout(timeout);if(active)setLoading(false)})
    return ()=>{active=false;clearTimeout(timeout);controller.abort()}
  },[region,retry])
  const end=addDays(trip.date,trip.type==='당일'?0:1)
  const current=today()
  const ranked=rankFestivals(data,region,trip.date,end,current)
  const matching=ranked.filter(row=>festivalState(row,trip.date,end,current)==='match')
  const live=ranked.filter(row=>['match','other'].includes(festivalState(row,trip.date,end,current)))
  const shown=showAll?ranked:live.slice(0,3)
  const stateLabels={match:'여행일과 겹쳐요',other:'다른 일정',unknown:'일정 확인 필요',ended:'종료된 행사',unconfirmed:'개최 여부 확인 필요'}
  return <section className="festival-section" aria-labelledby="festival-title">
    <div className="festival-intro"><span className="festival-eyebrow"><Sparkles size={15}/> 여행의 이유가 되는 순간</span><h2 id="festival-title">{region}에서 만나는 축제</h2><p>가고 싶은 축제 하나, 이번 여행에 더해보세요.</p></div>
    <div className="festival-trip"><CalendarDays size={17}/><span>{trip.date} ~ {end}</span><strong>{loading?'확인 중':`여행일에 맞는 축제 ${matching.length}개`}</strong></div>
    {loading?<div className="festival-empty" role="status"><RefreshCw className="loading-spin" size={22}/><p>지역 축제를 찾고 있어요.</p></div>:error?<div className="festival-empty" role="alert"><p>축제 정보를 불러오지 못했어요.</p><button className="text-button" onClick={()=>{setLoading(true);setError(false);setRetry(value=>value+1)}}>다시 불러오기</button></div>:<>
      {!matching.length&&<p className="festival-hint">{live.length?'여행일과 겹치는 축제는 아직 없어요. 다른 일정의 축제를 둘러보세요.':ranked.length?'현재 확인된 예정 축제가 없어요. 지난 축제를 참고하거나 공식 목록을 확인해 주세요.':'이 지역에서 확인된 축제 정보가 아직 없어요. 새 일정은 공식 목록에서 확인해 주세요.'}</p>}
      <div className="festival-list">{shown.map(row=>{
        const state=festivalState(row,trip.date,end,current),stale=festivalStale(row)
        const href=safeUrl(row.source_url)
        return <article className={`festival-card festival-${state}`} key={row.id}>
          <div className="festival-calendar" aria-hidden="true"><span>{row.start_date?`${Number(row.start_date.slice(5,7))}월`:'일정'}</span><strong>{row.start_date?row.start_date.slice(8):'?'}</strong><span>FESTIVAL</span></div>
          <div className="festival-content"><span className="festival-state">{stateLabels[state]}{stale?' · 정보 재확인 필요':''}</span><h3>{row.title}</h3><p><CalendarDays size={14}/>{row.period_note}</p><p><MapPin size={14}/>{row.location}</p><div className="festival-source"><small>문체부 · {row.collected_at.slice(0,10)} 수집</small>{href&&<a href={href} target="_blank" rel="noopener noreferrer" aria-label={`${row.title} 공식 안내 (새 탭)`}>공식 안내 <ExternalLink size={13}/></a>}</div></div>
        </article>
      })}</div>
      {ranked.length>0&&<button className="festival-more" aria-expanded={showAll} onClick={()=>setShowAll(value=>!value)}>{showAll?'예정 축제만 보기':`지난 행사·다른 일정 포함 ${ranked.length}개 모두 보기`}</button>}
    </>}
    <div className="festival-footnote"><span>운영시간·취소 여부는 방문 전 공식 안내를 확인해 주세요.</span><a href="https://www.mcst.go.kr/site/s_culture/festival/festivalList.jsp?pSido=15" target="_blank" rel="noopener noreferrer">공식 축제 목록 <ExternalLink size={12}/></a></div>
  </section>
}
