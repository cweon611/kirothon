import { useEffect, useRef, useState, lazy, Suspense, type ReactNode } from 'react'
import { ArrowLeft, ArrowRight, CalendarDays, MapPin, Check, ChevronRight, ExternalLink, Info, Ticket, Wallet, Receipt, Camera, SlidersHorizontal, RefreshCw, Waves, Compass, ShieldCheck, CircleHelp, CheckCircle2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogClose } from '@/components/ui/dialog'
import { type Benefit, type Trip, today, addDays, shortDate, observation, isStale, inPeriod, isOpen, safeUrl, readStored, writeStored, benefitsFromPrograms, regionPrograms, pickProgram, rateText, deadlineNotes } from '@/lib/benefits'
import { EvidenceWorkspace } from '@/components/evidence-workspace'
import { type Evidence } from '@/lib/evidence'
import destinations from '@/datasets/destinations.json'
import { FestivalRecommendations } from '@/components/festival-recommendations'
import { CoursePlanner } from '@/components/course-planner'
import { ORIGINS, applyMeta, cleanInterests, sigunguCode } from '@/lib/course'
import { regionDirectionsUrl } from '@/lib/directions'
import { DirectionsLink } from '@/components/directions-link'
import { EligibilityPanel } from '@/components/eligibility-panel'
const DestinationDart = lazy(() => import('@/components/destination-dart').then(module => ({ default: module.DestinationDart })))
import './App.css'

const steps = ['여행지 뽑기', '지역 비교', '일정 추천', '축제·여행 혜택', '준비 체크리스트']
const regions = [...destinations.map(row=>row.region_name),'그 외 지역']
const photo = 'https://images.unsplash.com/photo-1697983586877-1ae4e3656f6b?auto=format&fit=crop&w=1000&q=85'
const initialTrip: Trip = {type:'1박 2일',date:addDays(today(),7),origin:'광주 북구',residence:'광주 북구',people:2,transport:'자차'}
function loadTrip(): Trip {
  const saved = readStored<Trip>('halfroute-trip',initialTrip)
  if (!saved || !/^\d{4}-\d{2}-\d{2}$/.test(saved.date) || saved.date<today() || !['당일','1박 2일'].includes(saved.type) || !(saved.people>=1 && saved.people<=10)) return initialTrip
  return {type:saved.type,date:saved.date,origin:ORIGINS.some(row=>row.name===saved.origin)?saved.origin:initialTrip.origin,residence:saved.residence||initialTrip.residence,people:saved.people,transport:saved.transport==='대중교통'?'대중교통':'자차'}
}
/** True only after the user submitted the existing 여행 정보 수정 dialog in this tab. Defaults are not user input. */
const CONFIRMED_KEY='halfroute-trip-confirmed'
function loadConfirmed() { try { return sessionStorage.getItem(CONFIRMED_KEY)==='1' } catch { return false } }
function Tag({children,tone='teal'}:{children:ReactNode;tone?:string}) { return <span className={`badge badge-${tone}`}>{children}</span> }
function Note({children,warning=false}:{children:ReactNode;warning?:boolean}) { return <div className={warning?'warning-note':'info-note'}><Info size={19}/><div>{children}</div></div> }
function OfficialLink({url,children,primary=false}:{url:string|null;children:ReactNode;primary?:boolean}) {
  const href=safeUrl(url)
  return href ? <a className={primary?'button full-button official-cta':'official-link'} href={href} target="_blank" rel="noopener noreferrer">{children}<ExternalLink size={16}/><span className="sr-only"> (새 탭)</span></a> : <p className="muted-copy">공식 링크를 확인 중이에요.</p>
}
function Brand({onClick}:{onClick:()=>void}) {return <button className="brand" onClick={onClick} aria-label="갈랑가? 홈"><span className="brand-mark"><MapPin size={20}/></span><span className="brand-name">갈랑가?</span></button>}

export default function App() {
  const [trip,setTrip]=useState<Trip>(loadTrip)
  const [step,setStep]=useState(0)
  const [settingsOpen,setSettingsOpen]=useState(false)
  const [tripDraft,setTripDraft]=useState<Trip>(trip)
  const openSettings=()=>{setTripDraft({...trip});setSettingsOpen(true)}
  const [confirmed,setConfirmed]=useState(()=>loadConfirmed()&&trip!==initialTrip)
  useEffect(()=>{try{if(confirmed)sessionStorage.setItem(CONFIRMED_KEY,'1');else sessionStorage.removeItem(CONFIRMED_KEY)}catch{/* storage unavailable */}},[confirmed])
  const [data,setData]=useState<Benefit[]>([])
  const [loading,setLoading]=useState(true)
  const [error,setError]=useState('')
  const [retry,setRetry]=useState(0)
  const [selectedId,setSelectedId]=useState<string|null>(null)
  const [programId,setProgramId]=useState<string|null>(null)
  const [compare,setCompare]=useState<string[]>([])
  const [compareOpen,setCompareOpen]=useState(false)
  const [helpOpen,setHelpOpen]=useState(false)
  const [onlyOpen,setOnlyOpen]=useState(true)
  const [search,setSearch]=useState('')
  const [notice,setNotice]=useState('')
  const [interests,setInterests]=useState<string[]>(()=>cleanInterests(readStored('halfroute-interests',null)))
  const [checks,setChecks]=useState<Record<string,boolean>>(()=>readStored('halfroute-checks',{}))
  const [evidenceByTrip,setEvidenceByTrip]=useState<Record<string,Evidence[]>>({})
  const evidenceKey=`${selectedId}:${trip.date}:${trip.type}`
  const hasEvidence=Object.values(evidenceByTrip).some(items=>items.length>0)
  useEffect(()=>{
    if(!hasEvidence)return
    const warn=(event:BeforeUnloadEvent)=>{event.preventDefault();event.returnValue=''}
    window.addEventListener('beforeunload',warn)
    return ()=>window.removeEventListener('beforeunload',warn)
  },[hasEvidence])
  const heading=useRef<HTMLHeadingElement>(null)
  const selectedDestination=destinations.find(row=>row.id===selectedId)
  const programs=regionPrograms(data,selectedDestination?.region_name)
  const selected=pickProgram(programs,programId)
  // Option lists come from GET /api/team/meta; the bundled copies only cover the first paint or a failed call.
  const [,setMetaVersion]=useState(0)
  useEffect(()=>{
    if(import.meta.env.VITE_REVIEW_PREVIEW==='true')return
    const controller=new AbortController()
    fetch('/api/team/meta',{signal:controller.signal}).then(response=>response.ok?response.json():null)
      .then(meta=>{if(meta&&applyMeta(meta))setMetaVersion(value=>value+1)}).catch(()=>{/* bundled copies stay */})
    return ()=>controller.abort()
  },[])
  useEffect(()=>{writeStored('halfroute-trip',trip)},[trip])
  useEffect(()=>{writeStored('halfroute-checks',checks)},[checks])
  useEffect(()=>{writeStored('halfroute-interests',interests)},[interests])
  useEffect(()=>{
    const controller=new AbortController()
    let active=true
    setLoading(true); setError('')
    const timeout=window.setTimeout(()=>controller.abort(),12000)
    const preview=import.meta.env.VITE_REVIEW_PREVIEW==='true'
    fetch(preview?'/review-data/benefits.json':'/api/team/programs',{signal:controller.signal}).then(async response=>{
      if(!response.ok) throw new Error('혜택 정보를 불러오지 못했어요.')
      const body=await response.json()
      const rows=preview?body.items:Array.isArray(body.programs)?benefitsFromPrograms(body.programs):null
      if(!Array.isArray(rows)) throw new Error('혜택 정보 형식을 확인할 수 없어요.')
      if(active)setData(rows)
    }).catch(()=>{if(active)setError('혜택 정보를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.')}).finally(()=>{clearTimeout(timeout);if(active)setLoading(false)})
    return ()=>{active=false;clearTimeout(timeout);controller.abort()}
  },[retry])
  useEffect(()=>{
    const back=()=>{const value=Number(location.hash.replace('#step-',''));setStep(value>=1&&value<=5&&(value<=2||selectedId)?value-1:0)}
    window.addEventListener('popstate',back);return ()=>window.removeEventListener('popstate',back)
  },[selectedId])
  useEffect(()=>{window.scrollTo({top:0,behavior:'instant'}); if(step)heading.current?.focus()},[step])
  const go=(value:number)=>{if(value>0&&(!trip.date||trip.date<today())){setNotice('오늘 이후의 여행 시작일을 선택해 주세요.');setStep(0);return}setNotice('');setStep(value);window.scrollTo({top:0,behavior:'instant'});history.pushState(null,'',`#step-${value+1}`)}
  const choose=(row:Benefit)=>{setSelectedId(row.region_name);setProgramId(row.id);go(2)}

  const matching=data.filter(row=>row.present_in_source&&inPeriod(row,trip)&&row.region_name.includes(search.trim())&&(!onlyOpen||isOpen(row))).sort((a,b)=>Number(isOpen(b))-Number(isOpen(a))||a.region_name.localeCompare(b.region_name,'ko'))
  const toggleCompare=(id:string)=>{if(compare.includes(id))setCompare(compare.filter(value=>value!==id));else if(compare.length<3)setCompare([...compare,id]);else setNotice('지역은 최대 3곳까지 비교할 수 있어요. 선택한 지역을 먼저 해제해 주세요.')}
  const deadlines=selected?deadlineNotes(selected,trip):null
  const tasks = selected ? [
    {title:'신청 조건과 마감일 확인하기',phase:'여행 전',icon:CalendarDays,body:`${deadlines?.apply?`${deadlines.apply}. `:''}거주지 제한·연령·인원 조건과 해당 차수의 사전 신청 기한을 공식 공고에서 확인해 주세요.`},
    {title:'사전 신청하고 승인 확인하기',phase:'여행 전',icon:CheckCircle2,body:`${deadlines?.preApply?`${deadlines.preApply}. `:''}신청 완료와 승인 여부를 확인한 뒤 여행을 준비해 주세요. 지역마다 절차가 다를 수 있어요.`},
    {title:'인정 결제수단 준비하기',phase:'여행 전',icon:Wallet,body:selected.payment_rule||'인정되는 지역화폐와 결제수단을 공고에서 확인해 주세요.'},
    {title:'방문 인증과 영수증 챙기기',phase:'여행 중',icon:Camera,body:selected.conditions||'필수 방문지, 방문 횟수와 증빙 자료를 확인해 주세요.'},
    {title:'정산 기한 확인하고 증빙 제출하기',phase:'여행 후',icon:Receipt,body:deadlines?.settle?`${deadlines.settle}. 제출 후에는 심사 결과와 환급 수령 방법도 확인해 주세요.`:'지역별 정산 기한을 공식 공고에서 확인해 주세요. 제출 후에는 심사 결과와 환급 수령 방법도 확인해 주세요.'},
   ] : selectedDestination ? [
    {title:'방문 일정과 운영시간 확인하기',phase:'여행 전',icon:CalendarDays,body:'축제 공식 안내에서 행사일, 운영시간과 예약 여부를 확인해 주세요.'},
    {title:'방문 사진과 영수증 정리하기',phase:'여행 중',icon:Camera,body:'여행 사진과 결제 내역을 모아 아래 증빙 정리 화면에 기록해 보세요.'},
    {title:'여행 자료 내려받기',phase:'여행 후',icon:Receipt,body:'정리한 사진과 영수증을 내려받아 보관하세요. 파일은 새로고침하면 사라져요.'},
  ] : []
  const checkedCount=tasks.filter((_,i)=>checks[`${selectedId}:${trip.date}:${i}`]).length
  const title=step===1?'나에게 맞는 여행 혜택을 찾아요':step===2?`${selectedDestination?.region_name||''} ${trip.type} 추천 일정`:step===3?'축제도, 여행 혜택도 한곳에서':'놓치는 절차 없이, 차근차근'
  return <div className={`app-shell ${step===0?'dart-home-shell':''}`}>
    <a className="skip-link" href="#main-content">본문으로 바로가기</a>
    <aside className="desktop-rail"><Brand onClick={()=>go(0)}/><div className="rail-copy"><span className="eyebrow">여행하고, 돌려받는</span><h2 className="rail-title">여행의 즐거움은 더하고,<br/>부담은 덜어보세요.</h2><p className="rail-description">광주·전남 여행 혜택부터<br/>놓치기 쉬운 신청 절차까지 함께.</p></div>
      <nav className="rail-nav" aria-label="여행 준비 단계">{steps.map((label,i)=><button key={label} className={`rail-step ${i===step?'active':''} ${i<step?'done':''}`} disabled={i>step&&(i>1&&!selectedDestination)} aria-current={i===step?'step':undefined} onClick={()=>go(i)}><span className="rail-step-number">{i<step?<Check size={16}/>:i+1}</span>{label}</button>)}</nav>
      <div className="rail-support"><ShieldCheck size={22}/><span>공식 출처를 함께 안내해요</span></div><span className="rail-footnote">여행하고, 돌려받는 광주·전남 여행</span>
    </aside>
    <main id="main-content" className="app-main">
      {import.meta.env.VITE_REVIEW_PREVIEW==='true'&&<div className="review-preview-notice">팀 확인용 미리보기 · 2026.10.30 수집 데이터 · 실제 신청·제출은 연결하지 않았어요.</div>}
      <div className={step===0?'dart-home-screen':'content-screen'}>
        <header className="site-header"><Brand onClick={()=>go(0)}/><span className="slogan">작은 준비로, 더 가벼운 여행</span><button className="icon-button" aria-label="이용 안내" onClick={()=>setHelpOpen(true)}><CircleHelp size={21}/></button></header>
        <div className="mobile-step-label">{String(step+1).padStart(2,'0')} / 05 <span>{steps[step]}</span></div>
        {step>0&&<div className="page-header"><button className="back-button" aria-label="이전 단계로" onClick={()=>go(step-1)}><ArrowLeft size={20}/></button><div><span className="page-step">STEP 0{step+1}</span><h1 ref={heading} tabIndex={-1} className="page-title">{title}</h1></div></div>}
        {notice&&<div role="status" className="inline-feedback">{notice}</div>}
        {step===0&&<Suspense fallback={<div className="empty-state" role="status" style={{background:"#18384a",color:"#ececdd",borderColor:"#48626c",marginTop:30}}>여행 지도를 펼치고 있어요.</div>}><DestinationDart data={data} loading={loading} error={error} onRetry={()=>setRetry(value=>value+1)} origin={trip.origin} onChoose={row=>{setSelectedId(row.id);setProgramId(null);go(2)}} onBrowse={()=>{setOnlyOpen(false);setSearch('');go(1)}}/></Suspense>}
        {step===1&&<>
          <div className="condition-scroll">{[trip.type,`${shortDate(trip.date)} 출발`,trip.origin,`${trip.people}명`,trip.transport].map(value=><span className="summary-chip" key={value}>{value}</span>)}<button className="edit-conditions" onClick={openSettings}><SlidersHorizontal size={15}/> 날짜·인원 수정</button></div>
          <Note>운영기간이 여행일과 맞는 혜택을 모았어요. <strong>개인별 환급 자격과 금액은 공고 확인이 필요해요.</strong></Note>
          <div className="result-tools"><label className="search-field"><MapPin size={18}/><input aria-label="지역명 검색" placeholder="지역명으로 찾기" value={search} onChange={e=>setSearch(e.target.value)}/></label><label className="filter-check"><input type="checkbox" checked={onlyOpen} onChange={e=>setOnlyOpen(e.target.checked)}/> 접수중 표기만</label></div>
          <div className="result-summary"><span>여행 혜택 <strong>{matching.length}곳</strong></span><span className="muted-copy">접수중 표기 우선 · 가나다순</span></div>
          {loading?<div role="status" className="empty-state"><RefreshCw className="loading-spin"/><h2>공식 혜택 정보를 불러오고 있어요</h2><p>잠시만 기다려 주세요.</p></div>:error?<div role="alert" className="empty-state"><Info/><h2>잠시 연결이 어려워요</h2><p>{error}</p><Button className="button" onClick={()=>setRetry(value=>value+1)}>다시 불러오기</Button></div>:matching.length===0?<div className="empty-state"><Compass size={32}/><h2>현재 조건에 맞는 혜택이 없어요</h2><p>지역명이나 여행일을 바꾸거나, 마감된 지역도 함께 살펴보세요.</p><Button className="button" onClick={()=>{setOnlyOpen(false);setSearch('')}}>모든 접수 상태 보기</Button><button className="text-button" onClick={openSettings}>여행일 변경하기</button><div className="no-benefit-actions">{selectedDestination?<><Button className="button" onClick={()=>go(2)}>{selectedDestination.region_name} 혜택 없이 일정 보기 <ArrowRight size={17}/></Button><DirectionsLink url={regionDirectionsUrl(trip.origin,selectedDestination.region_name)}>{selectedDestination.region_name} 길찾기</DirectionsLink></>:<Button className="button" onClick={()=>go(0)}>여행지 먼저 고르기 <ArrowRight size={17}/></Button>}</div></div>:<div className="benefit-results">{matching.map((row,i)=><article className={`region-card ${i===0?'featured-region':''}`} key={row.id}>
            {i===0&&<div className="region-photo"><img src={photo} alt="여행 분위기를 보여주는 바다와 섬 참고 이미지" onError={e=>{e.currentTarget.style.display='none'}}/><span>여행 참고 이미지</span><div className="photo-caption"><Waves size={20}/><span>조금 더 가벼운 마음으로<br/><strong>전남으로 떠나요</strong></span></div></div>}
            <div className="region-card-body"><div className="region-heading"><div><span className="rank-label">{row.name}</span><h2 className="region-name">{row.region_name}</h2></div><Tag tone={isOpen(row)?'green':'gray'}>{isStale(row)?'상태 재확인 필요':`공식 표기 · ${row.source_status}`}</Tag></div><p className="region-description">{row.conditions||'자세한 참여 조건은 공식 공고를 확인해 주세요.'}</p><div className="region-facts"><span><CalendarDays size={16}/> {row.trip_start} ~ {row.trip_end}</span><span><Wallet size={16}/> {row.payment_rule||'결제수단 확인 필요'}</span>{rateText(row.refund_rate)&&<span><Ticket size={16}/> 환급률 {rateText(row.refund_rate)} (공고 기준)</span>}</div><div className="review-line"><Info size={16}/><span>환급 자격·금액 확인 필요</span><span className="source-time">{observation(row)} 수집</span></div><div className="region-card-actions"><label className="compare-check"><input type="checkbox" checked={compare.includes(row.id)} onChange={()=>toggleCompare(row.id)}/> 비교 담기</label><Button className="button" onClick={()=>choose(row)}>이 지역 살펴보기 <ArrowRight size={17}/></Button></div></div>
          </article>)}</div>}
          {compare.length>0&&<div className="sticky-action compare-bar"><span><strong>{compare.length}곳</strong> 선택했어요</span><Button className="button" disabled={compare.length<2} onClick={()=>setCompareOpen(true)}>지역 비교하기 <ArrowRight size={18}/></Button></div>}
        </>}
        {selectedDestination&&step>=2&&<>
          {step>=3&&<div className="condition-scroll"><span className="summary-chip"><MapPin size={14}/>{selectedDestination.region_name}</span><span className="summary-chip">{shortDate(trip.date)} · {trip.type}</span><button className="edit-conditions" onClick={openSettings}>여행 정보 수정</button><button className="edit-conditions" onClick={()=>go(0)}>다시 뽑기</button></div>}
          {step===2&&<>{selected&&!inPeriod(selected,trip)&&<Note warning>선택한 여행일이 수집된 혜택 운영기간 밖이에요. 여행 조건을 수정하거나 공식 공고의 운영 일정을 확인해 주세요.</Note>}<CoursePlanner region={selectedDestination.region_name} trip={trip} confirmed={confirmed} programs={programs} interests={interests} residenceOptions={regions} onSave={(nextTrip,nextInterests)=>{setTrip(nextTrip);setInterests(nextInterests);setConfirmed(true)}} onNext={()=>go(3)} onReroll={()=>go(0)}/></>}
          {step===3&&<><FestivalRecommendations key={selectedDestination.id} region={selectedDestination.region_name} code={sigunguCode(selectedDestination.region_name)} trip={trip} confirmed={confirmed}/>{selected?<>{programs.length>1&&<div className="program-switch" role="group" aria-label={`${selectedDestination.region_name} 지원제도 ${programs.length}개`}><p className="muted-copy">이 지역 지원제도 {programs.length}개 · 눌러서 바꿔 볼 수 있어요</p><div className="interest-grid">{programs.map(row=><button type="button" key={row.id} aria-pressed={row.id===selected.id} className={`chip ${row.id===selected.id?'chip-selected':''}`} onClick={()=>setProgramId(row.id)}>{row.name} · {row.source_status}</button>)}</div></div>}<section className="benefit-hero"><div className="benefit-top"><Tag tone="gray">개인별 자격 확인 필요</Tag><Ticket size={26}/></div><span className="benefit-program">{selected.name}</span><h2 className="benefit-amount">{rateText(selected.refund_rate)?`지출의 ${rateText(selected.refund_rate)} 환급`:'얼마나 받을 수 있나요?'}</h2><p className="benefit-help">{rateText(selected.refund_rate)?'인원별 한도·최소 지출 조건에 따라 금액이 달라져요.':'수집된 자료에 환급률이 없어요. 공식 공고에서 확인해 주세요.'}<br/>아래 ‘내 조건으로 받을 수 있는지 확인’에서 예상 금액을 계산해 보세요.</p></section><Note warning><strong>신청 전 꼭 확인해 주세요.</strong> 거주지 {trip.residence} · {trip.people}명 조건의 자격은 아직 판정되지 않았어요. 접수중 표기가 환급 자격을 보장하지는 않아요.</Note><section className="detail-card"><h2><CalendarDays size={20}/> 운영 및 신청 일정</h2><Tag tone={isOpen(selected)?'green':'gray'}>{isStale(selected)?'상태 재확인 필요':selected.source_status}</Tag><p className="source-text">{selected.period_note}{selected.application_note?`\n${selected.application_note}`:''}</p><p className="field-help">{observation(selected)} 수집 · 현재 접수 여부는 신청 페이지에서 확인해 주세요.</p></section><section className="detail-card"><h2><Wallet size={20}/> 결제수단</h2><p className="source-text">{selected.payment_rule||'공식 공고 확인 필요'}</p></section><section className="detail-card"><h2><MapPin size={20}/> 방문 및 증빙 조건</h2><p className="source-text">{selected.conditions||'공식 공고 확인 필요'}</p></section><details className="detail-card"><summary>출처와 문의처 확인하기</summary><p className="source-text">{selected.contact||'문의처는 공식 페이지를 확인해 주세요.'}</p><OfficialLink url={selected.source_url}>한국관광공사 원문 보기</OfficialLink><OfficialLink url={selected.apply_url}>지역별 신청 안내 보기</OfficialLink></details></>:<section className="detail-card"><h2><Ticket size={20}/> 환급 혜택</h2><p>{loading?'혜택 정보를 확인하고 있어요.':error?'혜택 정보를 불러오지 못했어요. 축제와 여행 준비는 계속 이용할 수 있어요.':'이 지역에 연결된 환급 혜택은 아직 없어요. 축제를 둘러보고 여행을 준비해 보세요.'}</p>{error&&<button className="text-button" onClick={()=>setRetry(value=>value+1)}>혜택 다시 불러오기</button>}{!loading&&<div className="no-benefit-actions"><DirectionsLink url={regionDirectionsUrl(trip.origin,selectedDestination.region_name)}>{trip.origin}에서 {selectedDestination.region_name} 길찾기</DirectionsLink></div>}</section>}<EligibilityPanel key={`${selectedDestination.id}:${trip.date}:${trip.type}:${trip.people}:${confirmed?trip.residence:''}`} source={{kind:'trip',region:selectedDestination.region_name}} trip={trip} residence={confirmed?trip.residence:''} programs={programs} residenceOptions={regions}/><div className="sticky-action"><Button className="button full-button" onClick={()=>go(4)}>놓치지 않게 준비하기 <ArrowRight size={18}/></Button></div></>}
          {step===4&&<><section className="check-progress" aria-label={`준비 항목 ${tasks.length}개 중 ${checkedCount}개 완료`}><span><strong>{checkedCount}</strong> / {tasks.length}개 준비했어요</span><progress value={checkedCount} max={tasks.length}/><p>{checkedCount===tasks.length?'잘 준비했어요! 실제 신청·승인 여부는 공식 사이트에서 확인해 주세요.':'완료한 항목을 눌러 표시해 보세요. 이 탭에서 다시 볼 수 있어요.'}</p></section><a className="evidence-jump" href="#evidence-workspace" onClick={event=>{event.preventDefault();const panel=document.getElementById('evidence-workspace');panel?.focus({preventScroll:true});panel?.scrollIntoView({block:'start',behavior:'instant'})}}><span><Camera size={19}/> 사진·영수증으로 증빙 정리하기</span><ChevronRight size={18}/></a><div>{tasks.map(({title,phase,body,icon:Icon},i)=><section key={title}>{(i===0||tasks[i-1].phase!==phase)&&<h2 className="phase-label">{phase}<i/></h2>}<label className={`task-card ${checks[`${selectedId}:${trip.date}:${i}`]?'completed':''}`}><input type="checkbox" checked={!!checks[`${selectedId}:${trip.date}:${i}`]} onChange={e=>setChecks({...checks,[`${selectedId}:${trip.date}:${i}`]:e.target.checked})}/><span className="checklist-icon"><Icon size={21}/></span><span><strong>{title}</strong><span className="task-description">{body}</span></span></label></section>)}</div><EvidenceWorkspace key={evidenceKey} context={{region:selectedDestination.region_name,date:trip.date,endDate:addDays(trip.date,trip.type==='당일'?0:1),people:trip.people}} items={evidenceByTrip[evidenceKey]||[]} onChange={items=>setEvidenceByTrip(current=>({...current,[evidenceKey]:items}))}/>{selected&&<><Note warning>사전 신청·정산 기한은 지역마다 달라요. 공식 공고의 해당 차수 기한을 꼭 확인해 주세요.</Note><div className="sticky-action checklist-actions"><OfficialLink url={selected.apply_url||selected.source_url} primary>공식 신청 안내 열기</OfficialLink><span className="trust-copy">체크 표시는 실제 신청이나 정산을 대신하지 않아요</span></div></>}</>}
        </>}
      </div><div className="mobile-progress" aria-label={`전체 5단계 중 ${step+1}단계`}>{steps.map((label,i)=><span key={label} className={i<=step?'active':''}/>)}</div>
    </main>
    <Dialog open={settingsOpen} onOpenChange={setSettingsOpen}><DialogContent className="trip-edit-dialog"><DialogHeader><DialogTitle>여행 정보 수정</DialogTitle><DialogDescription>먼저 여행지를 고르고, 필요한 정보만 천천히 정해요.</DialogDescription></DialogHeader><form onSubmit={event=>{event.preventDefault();setTrip(tripDraft);setConfirmed(true);setSettingsOpen(false)}}><div className="field-grid"><label className="field"><span className="field-copy"><span className="field-label">여행 시작일</span><input aria-label="여행 시작일" type="date" min={today()} required value={tripDraft.date} onChange={event=>setTripDraft({...tripDraft,date:event.target.value})}/></span></label><label className="field"><span className="field-copy"><span className="field-label">여행 유형</span><select aria-label="여행 유형" value={tripDraft.type} onChange={event=>setTripDraft({...tripDraft,type:event.target.value as Trip['type']})}><option>당일</option><option>1박 2일</option></select></span></label></div><div className="field-grid"><label className="field"><span className="field-copy"><span className="field-label">거주 시군구</span><select aria-label="거주 시군구" value={tripDraft.residence} onChange={event=>setTripDraft({...tripDraft,residence:event.target.value})}>{regions.map(value=><option key={value}>{value}</option>)}</select></span></label><label className="field"><span className="field-copy"><span className="field-label">여행 인원</span><select aria-label="여행 인원" value={tripDraft.people} onChange={event=>setTripDraft({...tripDraft,people:Number(event.target.value)})}>{Array.from({length:10},(_,i)=><option key={i} value={i+1}>{i+1}명</option>)}</select></span></label></div><div className="field-grid"><label className="field"><span className="field-copy"><span className="field-label">출발지</span><select aria-label="출발지" value={tripDraft.origin} onChange={event=>setTripDraft({...tripDraft,origin:event.target.value})}>{ORIGINS.map(row=><option key={row.key}>{row.name}</option>)}</select></span></label><label className="field"><span className="field-copy"><span className="field-label">이동수단</span><select aria-label="이동수단" value={tripDraft.transport} onChange={event=>setTripDraft({...tripDraft,transport:event.target.value as Trip['transport']})}><option>자차</option><option>대중교통</option></select></span></label></div><p className="field-help">임시 여행 일정이에요. 실제 여행일로 바꿔 주세요. 자격은 공식 공고에서 확인해요.</p><Button className="button full-button" type="submit">이 정보로 보기 <Check size={17}/></Button></form></DialogContent></Dialog>
    <Dialog open={helpOpen} onOpenChange={setHelpOpen}><DialogContent className="help-dialog"><DialogHeader><DialogTitle>갈랑가? 이렇게 이용해요</DialogTitle><DialogDescription>여행 혜택을 찾고 필요한 준비를 한곳에서 확인하세요.</DialogDescription></DialogHeader><ol className="help-steps">{steps.map((label,i)=><li key={label}><span>{i+1}</span>{label}</li>)}</ol><Note>접수 상태는 수집 시점의 공식 표기예요. 자격·금액·기한은 신청 전에 공고에서 확인해 주세요.</Note><DialogClose asChild><Button className="button full-button">알겠어요</Button></DialogClose></DialogContent></Dialog>
    <Dialog open={compareOpen} onOpenChange={setCompareOpen}><DialogContent className="compare-dialog"><DialogHeader><DialogTitle>여행 혜택 비교</DialogTitle><DialogDescription>운영기간과 참여 조건을 나란히 살펴보세요. 금액은 공고 확인 전이에요.</DialogDescription></DialogHeader><div className="comparison-grid">{data.filter(row=>compare.includes(row.id)).map(row=><section className="comparison-card" key={row.id}><h2>{row.region_name}</h2><Tag tone={isOpen(row)?'green':'gray'}>{isStale(row)?'상태 재확인 필요':row.source_status}</Tag><h3>운영기간</h3><p>{row.trip_start}<br/>~ {row.trip_end}</p><h3>신청 기간</h3><p>{row.application_note||'확인 필요'}</p><h3>환급률</h3><p>{rateText(row.refund_rate)??'확인 필요'}</p><h3>결제수단</h3><p>{row.payment_rule||'확인 필요'}</p><h3>방문·증빙 조건</h3><p>{row.conditions||'확인 필요'}</p><Button className="button full-button" onClick={()=>{setCompareOpen(false);choose(row)}}>{row.region_name} 선택 <ChevronRight size={16}/></Button></section>)}</div></DialogContent></Dialog>
  </div>
}
