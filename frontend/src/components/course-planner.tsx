import { useEffect, useState, type FormEvent } from 'react'
import { ArrowLeft, ArrowRight, CalendarDays, Car, Check, ChevronRight, Clock, House, Info, MapPin, Phone, RefreshCw, RotateCcw, Route, SlidersHorizontal, Sparkles, TrainFront, TriangleAlert, Utensils, Wallet } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { type Benefit, type Trip, today, addDays, shortDate, safeUrl } from '@/lib/benefits'
import { directionsUrl } from '@/lib/directions'
import { DirectionsLink } from '@/components/directions-link'
import { EligibilityPanel } from '@/components/eligibility-panel'
import { type Course, type CourseItem, type PlaceDetail, type ReasonsResponse, type Theme, INTERESTS, ORIGINS, courseRequest, courseSummary, courseThemes, errorMessage, formatKrw, interestLabel, originName, sigunguCode, uniqueCourses } from '@/lib/course'
import './course-planner.css'

type Row = {theme:Theme; course:Course}
type Outcome = {rows:Row[]; error:{code:string; message:string}|null}

// One request set per (region, trip, interests): revisiting the step reuses the courses already made.
const outcomes=new Map<string,Promise<Outcome>>()

async function createCourse(body:object):Promise<Course> {
  const controller=new AbortController()
  const timeout=window.setTimeout(()=>controller.abort(),15000)
  try {
    const response=await fetch('/api/team/courses',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:controller.signal})
    const data=await response.json().catch(()=>null)
    if (!response.ok) throw errorMessage(response.status,data)
    return data as Course
  } catch (error) {
    throw (error as {message?:string;code?:string})?.code ? error : errorMessage(0,null)
  } finally { clearTimeout(timeout) }
}

function loadCourses(region:string, trip:Trip, interests:string[]):Promise<Outcome> {
  const code=sigunguCode(region)
  if (!code) return Promise.resolve({rows:[],error:{code:'unsupported_region',message:'이 지역은 아직 일정 추천을 지원하지 않아요.'}})
  const themes=courseThemes(interests)
  const key=JSON.stringify(themes.map(theme=>courseRequest(trip,theme.interests,code)))
  if (!outcomes.has(key)) {
    const pending=Promise.allSettled(themes.map(theme=>createCourse(courseRequest(trip,theme.interests,code)))).then(results=>{
      const rows=uniqueCourses(results.flatMap((result,i)=>result.status==='fulfilled'?[{theme:themes[i],course:result.value}]:[]))
      const failed=results.find(result=>result.status==='rejected') as PromiseRejectedResult|undefined
      if (!rows.length) outcomes.delete(key)
      return {rows,error:rows.length?null:(failed?.reason ?? {code:'empty',message:'이 조건으로 만들 수 있는 일정이 없어요.'})}
    })
    outcomes.set(key,pending)
  }
  return outcomes.get(key)!
}

const kindIcon={spot:MapPin,meal:Utensils,stay:House}
const mealLabel:Record<string,string>={breakfast:'아침',lunch:'점심',dinner:'저녁'}

export function CoursePlanner({region,trip,confirmed,programs,interests,residenceOptions,onSave,onNext,onReroll}:{
  region:string; trip:Trip; confirmed:boolean; programs:Benefit[]; interests:string[]; residenceOptions:string[];
  onSave:(trip:Trip, interests:string[])=>void; onNext:()=>void; onReroll:()=>void;
}) {
  const [outcome,setOutcome]=useState<Outcome|null>(null)
  const [retry,setRetry]=useState(0)
  const [editing,setEditing]=useState(false)
  const [selectedId,setSelectedId]=useState<string|null>(()=>history.state?.course ?? null)
  const loading=outcome===null
  useEffect(()=>{
    let active=true
    setOutcome(null)
    loadCourses(region,trip,interests).then(result=>{if(active)setOutcome(result)})
    return ()=>{active=false}
  },[region,trip,interests,retry])
  useEffect(()=>{
    const back=()=>setSelectedId(history.state?.course ?? null)
    window.addEventListener('popstate',back)
    return ()=>window.removeEventListener('popstate',back)
  },[])
  const open=(id:string)=>{history.pushState({course:id},'',location.hash);setSelectedId(id);window.scrollTo({top:0,behavior:'instant'})}
  const close=()=>{if(history.state?.course)history.back();else setSelectedId(null)}
  const selected=outcome?.rows.find(row=>row.course.id===selectedId)

  if (selected) return <CourseDetail row={selected} trip={trip} residence={confirmed?trip.residence:''} programs={programs} residenceOptions={residenceOptions} onBack={close} onNext={onNext}/>
  return <div className="course-planner">
    <ConditionPanel region={region} trip={trip} confirmed={confirmed} interests={interests} residenceOptions={residenceOptions} editing={editing} setEditing={setEditing} onReroll={onReroll}
      onSave={(nextTrip,nextInterests)=>{onSave(nextTrip,nextInterests);setEditing(false)}}/>
    <div className="course-list-head"><div><span className="course-eyebrow"><Sparkles size={14}/> {region} 안에서 짠 동선</span><h2>추천 일정</h2></div>{!loading&&outcome.rows.length>0&&<span className="course-count">{outcome.rows.length}개 코스</span>}</div>
    {loading?<div className="course-empty" role="status"><RefreshCw className="loading-spin" size={22}/><p>관광지·식당·숙소를 이어 일정을 짜고 있어요.</p></div>
      :outcome.error?<CourseUnavailable error={outcome.error} trip={trip} onRetry={()=>setRetry(value=>value+1)} onEdit={()=>setEditing(true)}/>
      :<div className="course-cards">{outcome.rows.map((row,i)=><CourseCard key={row.course.id} row={row} best={i===0} onOpen={()=>open(row.course.id)}/>)}</div>}
    <p className="course-footnote">이동시간은 직선거리 기반 추정치예요. 운영시간·휴무는 상세에서 확인하고, 방문 전 공식 안내를 다시 확인해 주세요.</p>
    <div className="sticky-action"><Button className="button full-button" onClick={onNext}>축제·여행 혜택 확인하기 <ArrowRight size={18}/></Button></div>
  </div>
}

function ConditionPanel({region,trip,confirmed,interests,residenceOptions,editing,setEditing,onSave,onReroll}:{
  region:string; trip:Trip; confirmed:boolean; interests:string[]; residenceOptions:string[]; editing:boolean; setEditing:(value:boolean)=>void;
  onSave:(trip:Trip, interests:string[])=>void; onReroll:()=>void;
}) {
  const [draft,setDraft]=useState(trip)
  const [picked,setPicked]=useState(interests)
  useEffect(()=>{if(editing){setDraft(trip);setPicked(interests)}},[editing,trip,interests])
  const toggle=(key:string)=>setPicked(current=>current.includes(key)?(current.length>1?current.filter(v=>v!==key):current):current.length<3?[...current,key]:current)
  const submit=(event:FormEvent)=>{event.preventDefault();if(!draft.date||draft.date<today())return;onSave(draft,picked)}
  const end=addDays(trip.date,trip.type==='당일'?0:1)
  return <section className={`course-conditions ${editing?'is-editing':''}`} aria-labelledby="course-conditions-title">
    <div className="course-conditions-head">
      <div><span className="course-eyebrow"><MapPin size={14}/> {region}</span><h2 id="course-conditions-title">내 여행 조건</h2></div>
      <div className="course-conditions-actions">
        {!editing&&<button className="course-chip-button" onClick={()=>setEditing(true)}><SlidersHorizontal size={15}/> 조건 수정</button>}
        <button className="course-chip-button" onClick={onReroll}><RotateCcw size={15}/> 다시 뽑기</button>
      </div>
    </div>
    {!editing?<dl className="course-condition-grid">
      <div><dt>일정</dt><dd>{trip.type} · {shortDate(trip.date)}{trip.type==='당일'?'':` ~ ${shortDate(end)}`}</dd></div>
      <div><dt>인원</dt><dd>{trip.people}명</dd></div>
      <div><dt>출발지</dt><dd>{trip.origin} · {trip.transport}</dd></div>
      <div><dt>거주지</dt><dd>{confirmed?trip.residence:'아직 입력 전'}</dd></div>
      <div className="wide"><dt>관심 분야</dt><dd>{interests.map(interestLabel).join(', ')}</dd></div>
    </dl>:<form className="course-condition-form" onSubmit={submit}>
      <div className="field-grid">
        <label className="field"><span className="field-copy"><span className="field-label">여행 시작일</span><input type="date" min={today()} required value={draft.date} onChange={e=>setDraft({...draft,date:e.target.value})}/></span></label>
        <label className="field"><span className="field-copy"><span className="field-label">여행 유형</span><select value={draft.type} onChange={e=>setDraft({...draft,type:e.target.value as Trip['type']})}><option>당일</option><option>1박 2일</option></select></span></label>
        <label className="field"><span className="field-copy"><span className="field-label">여행 인원</span><select value={draft.people} onChange={e=>setDraft({...draft,people:Number(e.target.value)})}>{Array.from({length:10},(_,i)=><option key={i} value={i+1}>{i+1}명</option>)}</select></span></label>
        <label className="field"><span className="field-copy"><span className="field-label">이동수단</span><select value={draft.transport} onChange={e=>setDraft({...draft,transport:e.target.value as Trip['transport']})}><option>자차</option><option>대중교통</option></select></span></label>
        <label className="field"><span className="field-copy"><span className="field-label">출발지</span><select value={draft.origin} onChange={e=>setDraft({...draft,origin:e.target.value})}>{ORIGINS.map(row=><option key={row.key}>{row.name}</option>)}</select></span></label>
        <label className="field"><span className="field-copy"><span className="field-label">거주 시군구</span><select value={draft.residence} onChange={e=>setDraft({...draft,residence:e.target.value})}>{residenceOptions.map(value=><option key={value}>{value}</option>)}</select></span></label>
      </div>
      <fieldset className="course-interest-field"><legend>관심 분야 <small>1~3개</small></legend>
        <div>{INTERESTS.map(row=><button type="button" key={row.key} aria-pressed={picked.includes(row.key)} className={picked.includes(row.key)?'active':''} onClick={()=>toggle(row.key)}>{picked.includes(row.key)&&<Check size={14}/>}{row.label}</button>)}</div>
      </fieldset>
      <p className="field-help">거주지는 환급 자격 확인에만 써요. 서버에 저장하지 않아요.</p>
      <div className="course-form-actions"><button type="button" className="text-button" onClick={()=>setEditing(false)}>취소</button><Button className="button" type="submit">이 조건으로 다시 추천 <RefreshCw size={16}/></Button></div>
    </form>}
  </section>
}

function CourseCard({row,best,onOpen}:{row:Row; best:boolean; onOpen:()=>void}) {
  const summary=courseSummary(row.course)
  const cover=row.course.days.flatMap(day=>day.items).map(item=>safeUrl(item.place?.image_url??null)).find(Boolean)
  return <article className={`course-card ${best?'course-card-best':''}`}>
    <button className="course-card-button" onClick={onOpen} aria-label={`${row.theme.title} 상세 보기`}>
      <div className="course-card-cover" aria-hidden="true">{cover?<img src={cover} alt="" onError={e=>{e.currentTarget.style.display='none'}}/>:<Route size={30}/>}</div>
      <div className="course-card-body">
        <span className="course-card-tag">{best?'내 관심사 맞춤':'다른 테마'}</span>
        <h3>{row.theme.title}</h3>
        <ol className="course-card-route">{summary.highlights.map(title=><li key={title}>{title}</li>)}</ol>
        <div className="course-card-facts">
          <span><MapPin size={14}/>관광지 {summary.spotCount}곳</span>
          {summary.stay&&<span><House size={14}/>{summary.stay}</span>}
          <span><Wallet size={14}/>예상 {formatKrw(summary.spend)}</span>
          {summary.homeArrival&&<span><Clock size={14}/>{summary.homeArrival} 귀가</span>}
        </div>
        {row.course.warnings.length>0&&<span className="course-card-warning"><TriangleAlert size={14}/>확인할 점 {row.course.warnings.length}개</span>}
      </div>
      <ChevronRight className="course-card-arrow" size={20}/>
    </button>
  </article>
}

function CourseUnavailable({error,trip,onRetry,onEdit}:{error:{code:string;message:string}; trip:Trip; onRetry:()=>void; onEdit:()=>void}) {
  const empty=error.code==='tourism_cache_empty'
  const slots=[['10:00',`${trip.origin} 출발`],['오전','첫 번째 관광지'],['점심','지역 식당에서 점심'],['오후','두 번째 관광지'],['저녁',trip.type==='당일'?'귀가':'숙소 체크인']]
  return <div className="course-unavailable" role={empty?'status':'alert'}>
    <TriangleAlert size={22}/><h3>{error.message}</h3>
    <p>{empty?'운영자가 관광 데이터를 수집하면 이 지역의 실제 장소로 일정을 추천해 드려요. 그동안은 아래 시간표를 참고해 주세요.':'조건을 바꾸거나 잠시 후 다시 시도해 주세요.'}</p>
    <div className="course-form-actions">{!empty&&<button className="text-button" onClick={onEdit}>조건 수정</button>}<Button className="button" onClick={onRetry}>다시 시도 <RefreshCw size={16}/></Button></div>
    {empty&&<ol className="course-generic">{slots.map(([time,title])=><li key={time}><span>{time}</span>{title}</li>)}</ol>}
  </div>
}

function CourseDetail({row,trip,residence,programs,residenceOptions,onBack,onNext}:{row:Row; trip:Trip; residence:string; programs:Benefit[]; residenceOptions:string[]; onBack:()=>void; onNext:()=>void}) {
  const {course,theme}=row
  const [day,setDay]=useState(0)
  const [placeId,setPlaceId]=useState<string|null>(null)
  const summary=courseSummary(course)
  const current=course.days[day]??course.days[0]
  // AI sentences for the day on screen (the backend caps AI at 2 calls per course and reuses stored ones).
  const [aiReasons,setAiReasons]=useState<Record<string,string>>({})
  const currentDay=current?.day
  useEffect(()=>{
    if(currentDay===undefined)return
    let active=true
    const controller=new AbortController()
    fetch(`/api/team/courses/${encodeURIComponent(course.id)}/reasons`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({day:currentDay}),signal:controller.signal})
      .then(async response=>{if(!response.ok)throw new Error();const body=await response.json() as ReasonsResponse
        if(active)setAiReasons(prev=>({...prev,...Object.fromEntries(body.items.filter(i=>i.reason_text).map(i=>[`${body.day}:${i.order}`,i.reason_text as string]))}))})
      .catch(()=>{/* keep the course's rule sentences */})
    return ()=>{active=false;controller.abort()}
  },[course.id,currentDay])
  const placeDate=current?.date??course.start_date
  return <div className="course-detail">
    <button className="course-back" onClick={onBack}><ArrowLeft size={17}/> 추천 일정 목록</button>
    <section className="course-detail-hero">
      <span className="course-eyebrow light"><Sparkles size={14}/> {course.region.name} · {theme.interests.map(interestLabel).join(', ')}</span>
      <h2>{theme.title}</h2>
      <p>{shortDate(course.start_date)}{course.end_date!==course.start_date?` ~ ${shortDate(course.end_date)}`:''} · {course.party_size}명 · {originName(course.origin)}에서 {course.transport==='car'?'자차':'대중교통'}</p>
      <dl>
        <div><dt>관광지</dt><dd>{summary.spotCount}곳</dd></div>
        <div><dt>식사</dt><dd>{summary.mealCount}끼</dd></div>
        <div><dt>예상 지출</dt><dd>{formatKrw(summary.spend)}</dd></div>
        <div><dt>귀가 예정</dt><dd>{summary.homeArrival??'확인 필요'}</dd></div>
      </dl>
    </section>
    {course.warnings.length>0&&<section className="course-warnings" aria-label="확인할 점"><h3><TriangleAlert size={17}/> 출발 전에 확인해 주세요</h3><ul>{course.warnings.map(w=><li key={w.code+w.message}>{w.message}{w.suggested_date&&<small> 추천 출발일: {shortDate(w.suggested_date)}</small>}</li>)}</ul></section>}
    {course.days.length>1&&<div className="day-tabs" role="group" aria-label="여행 날짜">{course.days.map((d,i)=><button key={d.day} aria-pressed={day===i} className={day===i?'active':''} onClick={()=>setDay(i)}>{d.day}일차 · {shortDate(d.date)}</button>)}</div>}
    {current&&<ol className="course-timeline">
      <li className="course-stop course-stop-start"><span className="course-time">{current.depart}</span><span className="course-dot">{trip.transport==='자차'?<Car size={16}/>:<TrainFront size={16}/>}</span><div className="course-stop-card plain"><strong>{current.start_point} 출발</strong></div></li>
      {current.items.map(item=><CourseStop key={item.order} item={item} reason={aiReasons[`${current.day}:${item.order}`]} onPlace={setPlaceId}/>)}
      {current.home_arrival&&<li className="course-stop course-stop-end"><span className="course-time">{current.return_depart}</span><span className="course-dot"><House size={16}/></span><div className="course-stop-card plain"><strong>귀가 출발</strong><span className="course-move"><Route size={13}/>약 {current.return_move_min}분 · {current.home_arrival} 도착 예정</span></div></li>}
    </ol>}
    {course.spend_breakdown&&course.spend_breakdown.items.length>0&&<details className="course-spend"><summary><Wallet size={17}/> 예상 지출 {formatKrw(course.spend_breakdown.total_krw)} 내역 보기</summary><ul>{course.spend_breakdown.items.map(item=><li key={item.label}><span>{item.label}</span><strong>{formatKrw(item.krw)}</strong></li>)}</ul><p>식비·숙박비 기본값이 들어간 추정치예요. 실제 금액은 장소마다 달라요.</p></details>}
    <EligibilityPanel key={`${course.id}:${residence}`} source={{kind:'course',courseId:course.id}} trip={trip} residence={residence} programs={programs} residenceOptions={residenceOptions}/>
    <div className="sticky-action course-detail-actions"><button className="text-button" onClick={onBack}>다른 일정 보기</button><Button className="button" onClick={onNext}>이 일정의 혜택 확인하기 <ArrowRight size={18}/></Button></div>
    <PlaceDialog contentId={placeId} date={placeDate} origin={trip.origin} onClose={()=>setPlaceId(null)}/>
  </div>
}

function CourseStop({item,reason,onPlace}:{item:CourseItem; reason?:string; onPlace:(id:string)=>void}) {
  const Icon=kindIcon[item.kind as keyof typeof kindIcon]??MapPin
  const label=item.kind==='meal'?`${mealLabel[item.meal??'']??''} 식사`.trim():item.kind==='stay'?'숙소':item.place?.category??'관광지'
  return <li className={`course-stop course-stop-${item.kind}`}>
    <span className="course-time">{item.start}{item.end&&<small>~{item.end}</small>}</span>
    <span className="course-dot"><Icon size={16}/></span>
    <div className="course-stop-card">
      {typeof item.move_min_from_prev==='number'&&<span className={`course-move ${item.move_warning?'warn':''}`}><Route size={13}/>이전 장소에서 약 {item.move_min_from_prev}분{item.move_warning?' · 이동이 길어요':''}{item.transit_note?` · ${item.transit_note}`:''}</span>}
      <span className="course-stop-kind">{label}{item.required&&<em>필수 방문</em>}{item.place?.source==='demo'&&<em className="muted">시연 데이터</em>}</span>
      {item.place?<button className="course-place" onClick={()=>onPlace(item.place!.content_id)}>{item.place.title}<ChevronRight size={16}/></button>:<strong>{item.label??'장소 미정'}</strong>}
      {(reason??item.reason_text)&&<p>{reason??item.reason_text}</p>}
      {!!item.reason_tags?.length&&<div className="course-reason-tags">{item.reason_tags.map(tag=><span key={tag}>{tag}</span>)}</div>}
      {(item.check_before_visit||item.refund_note)&&<div className="course-stop-notes">
        {item.check_before_visit&&<span className="warn"><Info size={13}/>방문 전 확인{item.check_reasons?.length?`: ${item.check_reasons.join(', ')}`:''}</span>}
        {item.refund_note&&<span><Wallet size={13}/>{item.refund_note}</span>}
      </div>}
    </div>
  </li>
}

function PlaceDialog({contentId,date,origin,onClose}:{contentId:string|null; date:string; origin:string; onClose:()=>void}) {
  const [place,setPlace]=useState<PlaceDetail|null>(null)
  const [failed,setFailed]=useState(false)
  useEffect(()=>{
    if(!contentId)return
    let active=true
    const controller=new AbortController()
    setPlace(null);setFailed(false)
    fetch(`/api/team/places/${encodeURIComponent(contentId)}?date=${date}`,{signal:controller.signal})
      .then(async response=>{if(!response.ok)throw new Error();const body=await response.json();if(active)setPlace(body)})
      .catch(()=>{if(active)setFailed(true)})
    return ()=>{active=false;controller.abort()}
  },[contentId,date])
  const image=safeUrl(place?.image_url??null)
  return <Dialog open={!!contentId} onOpenChange={value=>{if(!value)onClose()}}>
    <DialogContent className="place-dialog">
      <DialogHeader><DialogTitle>{place?.title??'장소 정보'}</DialogTitle><DialogDescription>{place?`${place.category??'장소'}${place.addr?` · ${place.addr}`:''}`:failed?'장소 정보를 불러오지 못했어요.':'장소 정보를 불러오고 있어요.'}</DialogDescription></DialogHeader>
      {!place&&!failed&&<div className="course-empty" role="status"><RefreshCw className="loading-spin" size={20}/></div>}
      {place&&<div className="place-detail">
        {image&&<figure><img src={image} alt={`${place.title} 사진`} onError={e=>{e.currentTarget.parentElement!.style.display='none'}}/>{place.image_credit&&<figcaption>사진 {place.image_credit}</figcaption>}</figure>}
        {place.closed_on_visit_date===true&&<p className="place-alert"><TriangleAlert size={15}/>{shortDate(date)}은 쉬는 날일 수 있어요.</p>}
        {place.overview&&<p className="place-overview">{place.overview}</p>}
        <dl>
          {place.opening_window&&<div><dt><Clock size={14}/>이용시간</dt><dd>{place.opening_window.open} ~ {place.opening_window.close}</dd></div>}
          {place.rest_text&&<div><dt><CalendarDays size={14}/>쉬는 날</dt><dd>{place.rest_text}</dd></div>}
          {typeof place.fee_krw==='number'&&<div><dt><Wallet size={14}/>이용요금</dt><dd>{place.fee_krw===0?'무료':`1인 ${formatKrw(place.fee_krw)}`}</dd></div>}
          {place.tel&&<div><dt><Phone size={14}/>문의</dt><dd>{place.tel}</dd></div>}
        </dl>
        {!!place.evidence?.length&&<div className="place-evidence"><span>추천 근거</span>{place.evidence.map(text=><em key={text}>{text}</em>)}</div>}
        {typeof place.lat==='number'&&typeof place.lng==='number'&&<div className="no-benefit-actions"><DirectionsLink url={directionsUrl(origin,{name:place.title,lat:place.lat,lng:place.lng})}>{origin}에서 길찾기</DirectionsLink></div>}
        <p className="field-help">{place.source==='demo'?'시연용 데이터예요. 실제 정보와 다를 수 있어요.':place.detail_status==='not_fetched'||place.detail_status==='unavailable'?'상세 정보를 아직 받지 못해 목록 정보만 보여요.':'한국관광공사 관광정보 기준이에요.'} 방문 전 운영 여부를 확인해 주세요.</p>
      </div>}
    </DialogContent>
  </Dialog>
}
