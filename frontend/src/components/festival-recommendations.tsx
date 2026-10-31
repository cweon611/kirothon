import { useEffect, useState } from 'react'
import { CalendarDays, ExternalLink, MapPin, Sparkles, RefreshCw } from 'lucide-react'
import { type Festival, festivalState, festivalStale, rankFestivals } from '@/lib/festivals'
import { type Trip, today, addDays } from '@/lib/benefits'
import { cleanUrl } from '@/lib/links'
import { festivalsFromSelected, kstTime } from '@/lib/date-recommendations'
import { type DateRec } from '@/lib/use-date-recommendation'
import './festival-recommendations.css'

const PREVIEW=import.meta.env.VITE_REVIEW_PREVIEW==='true'

/**
 * Festivals for the slingshot destination during the trip dates. The request is made once in App
 * (`rec`, shared with the support-program area) and only after the dates were confirmed.
 */
export function FestivalRecommendations({region,trip,confirmed,rec}:{region:string;trip:Trip;confirmed:boolean;rec:DateRec}) {
  const [preview,setPreview]=useState<{rows:Festival[];error:boolean}|null>(null)
  const [showAll,setShowAll]=useState(false)
  const end=addDays(trip.date,trip.type==='당일'?0:1)
  useEffect(()=>{
    if(!PREVIEW||!confirmed)return
    const controller=new AbortController()
    fetch('/review-data/festivals.json',{signal:controller.signal})
      .then(async response=>{if(!response.ok)throw new Error();const body=await response.json();if(!Array.isArray(body.items))throw new Error();setPreview({rows:body.items,error:false})})
      .catch(()=>setPreview({rows:[],error:true}))
    return ()=>controller.abort()
  },[confirmed])
  const outcome=!PREVIEW&&rec.status==='done'&&rec.data?festivalsFromSelected(rec.data,region):null
  const data=PREVIEW?preview?.rows??[]:outcome?.rows??[]
  const loading=confirmed&&(PREVIEW?!preview:rec.status==='loading'||rec.status==='idle')
  const error=PREVIEW?(preview?.error?'축제 정보를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.':''):rec.status==='error'?rec.error:''
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
    :error?<div className="festival-empty" role="alert"><p>{error}</p><button className="text-button" onClick={rec.retry}>다시 불러오기</button></div>
    :outcome?.state==='unavailable'?<div className="festival-empty" role="alert"><p>이 지역의 축제 자료를 아직 수집하지 못했어요. ‘축제 없음’이라는 뜻은 아니에요.</p><button className="text-button" onClick={rec.retry}>다시 불러오기</button></div>:<>
      {outcome?.usingPrevious&&<p className="festival-hint" role="status">최근 수집이 실패해 {kstTime(outcome.lastSuccessAt)}에 수집한 자료를 보여드려요. 최신 일정은 방문 전에 다시 확인해 주세요.</p>}
      {!matching.length&&<p className="festival-hint">{ranked.length?'여행일과 겹치는 것으로 확인된 축제는 없어요. 아래 행사는 일정이 확인되지 않았어요.':'이 기간에 진행이 확인된 축제가 없어요.'}</p>}
      <div className="festival-list">{shown.map(row=>{
        const state=festivalState(row,trip.date,end,current),stale=festivalStale(row)
        const href=cleanUrl(row.source_url)
        const collected=Number.isFinite(Date.parse(row.collected_at))?`${kstTime(row.collected_at)} 수집`:''
        const source=[row.source,collected].filter(Boolean).join(' · ')
        return <article className={`festival-card festival-${state}`} key={row.id}>
          <div className="festival-calendar" aria-hidden="true"><span>{row.start_date?`${Number(row.start_date.slice(5,7))}월`:'일정'}</span><strong>{row.start_date?row.start_date.slice(8):'?'}</strong><span>FESTIVAL</span></div>
          <div className="festival-content"><span className="festival-state">{stateLabels[state]}{stale?' · 정보 재확인 필요':''}</span><h3>{row.title}</h3>{row.period_note&&<p><CalendarDays size={14}/>{row.period_note}</p>}{row.location&&<p><MapPin size={14}/>{row.location}</p>}{(source||href)&&<div className="festival-source">{source&&<small>{source}</small>}{href&&<a href={href} target="_blank" rel="noopener noreferrer" aria-label={`${row.title} 공식 안내 (새 탭)`}>공식 안내 <ExternalLink size={13}/></a>}</div>}</div>
        </article>
      })}</div>
      {ranked.length>live.slice(0,3).length&&<button className="festival-more" aria-expanded={showAll} onClick={()=>setShowAll(value=>!value)}>{showAll?'예정 축제만 보기':`일정 미확인 행사 포함 ${ranked.length}개 모두 보기`}</button>}
    </>}
    <div className="festival-footnote"><span>운영시간·취소 여부는 방문 전 공식 안내를 확인해 주세요.</span><a href="https://www.mcst.go.kr/site/s_culture/festival/festivalList.jsp?pSido=15" target="_blank" rel="noopener noreferrer">문화체육관광부 지역축제 목록 <ExternalLink size={12}/><span className="sr-only"> (새 탭)</span></a></div>
  </section>
}
