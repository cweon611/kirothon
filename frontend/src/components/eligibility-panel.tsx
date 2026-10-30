import { useState, type FormEvent, type ReactNode } from 'react'
import { CalendarClock, Check, ChevronDown, CircleCheck, CircleHelp, CircleX, ExternalLink, RefreshCw, ShieldCheck, UserRound } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { type Trip, addDays, shortDate, safeUrl } from '@/lib/benefits'
import { formatKrw } from '@/lib/course'
import { type Answer, type CheckResponse, type CheckResult, type Profile, type RefundResponse, OTHER, SIDO, dDay, emptyProfile, refundRequest, refundResults, tripCheckRequest, uniqueLabels, verdictOf } from '@/lib/eligibility'
import './eligibility-panel.css'

type Source = {kind:'course'; courseId:string} | {kind:'trip'; region:string}
type State = {status:'idle'|'loading'} | {status:'error'; message:string} | {status:'done'; results:CheckResult[]; response:CheckResponse}

async function post<T>(url:string, body:object):Promise<T> {
  const controller=new AbortController()
  const timeout=window.setTimeout(()=>controller.abort(),15000)
  try {
    const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:controller.signal})
    if (!response.ok) throw new Error(String(response.status))
    return await response.json() as T
  } finally { clearTimeout(timeout) }
}

export function EligibilityPanel({source,trip,residenceOptions}:{source:Source; trip:Trip; residenceOptions:string[]}) {
  // Personal answers live only in this component: never stored or sent anywhere but the check request.
  const [profile,setProfile]=useState<Profile>(()=>emptyProfile(trip.residence))
  const [state,setState]=useState<State>({status:'idle'})
  const end=addDays(trip.date,trip.type==='당일'?0:1)
  const set=(patch:Partial<Profile>)=>setProfile(current=>({...current,...patch}))

  const run=async(event:FormEvent)=>{
    event.preventDefault()
    setState({status:'loading'})
    try {
      if (source.kind==='course') {
        const response=await post<RefundResponse>(`/api/team/courses/${encodeURIComponent(source.courseId)}/refund`,refundRequest(profile))
        setState({status:'done',results:refundResults(response),response:response.check})
      } else {
        const body=tripCheckRequest(profile,trip,source.region,end)
        if (!body) { setState({status:'error',message:'이 지역은 아직 자격 확인을 지원하지 않아요.'}); return }
        const response=await post<CheckResponse>('/api/benefits/check',body)
        setState({status:'done',results:response.results,response})
      }
    } catch {
      setState({status:'error',message:'자격 확인을 하지 못했어요. 잠시 후 다시 시도해 주세요.'})
    }
  }

  return <section className="eligibility" aria-labelledby="eligibility-title">
    <div className="eligibility-head"><span className="eligibility-icon"><UserRound size={20}/></span><div><h3 id="eligibility-title">내 조건으로 받을 수 있는지 확인</h3><p>{source.kind==='course'?'이 일정의 방문지·숙박·예상 지출로 판정해요.':`${shortDate(trip.date)} ${trip.type} · ${trip.people}명 일정으로 판정해요.`}</p></div></div>
    <form className="eligibility-form" onSubmit={run}>
      <label className="eligibility-field"><span>거주지 <small>주민등록 기준</small></span>
        <select value={profile.residence} onChange={e=>set({residence:e.target.value})}>{[...residenceOptions.filter(v=>v!==OTHER),OTHER].map(v=><option key={v}>{v}</option>)}</select></label>
      {profile.residence===OTHER&&<div className="eligibility-pair">
        <label className="eligibility-field"><span>시·도</span><select value={profile.otherSido} onChange={e=>set({otherSido:e.target.value})}>{SIDO.map(v=><option key={v}>{v}</option>)}</select></label>
        <label className="eligibility-field"><span>시·군·구 <small>선택</small></span><input value={profile.otherSigungu} maxLength={20} placeholder="예: 강남구" onChange={e=>set({otherSigungu:e.target.value})}/></label>
      </div>}
      <label className="eligibility-field"><span>생년월일 <small>선택 · 청년 기준 확인</small></span><input type="date" max={trip.date} value={profile.birthDate} onChange={e=>set({birthDate:e.target.value})}/></label>
      <AnswerField label="가족과 함께 가나요?" value={profile.family} onChange={family=>set({family})}/>
      {profile.family==='yes'&&<AnswerField label="모두 같은 주소에 살아요?" value={profile.sameAddress} onChange={sameAddress=>set({sameAddress})}/>}
      <AnswerField label="이런 지원 사업은 처음이에요?" value={profile.firstTime} onChange={firstTime=>set({firstTime})} yes="처음이에요" no="참여한 적 있어요"/>
      <p className="eligibility-privacy"><ShieldCheck size={14}/>입력한 정보는 이번 확인에만 쓰고 저장하지 않아요.</p>
      <Button className="button full-button" type="submit" disabled={state.status==='loading'}>{state.status==='loading'?<><RefreshCw className="loading-spin" size={16}/> 확인하는 중</>:state.status==='done'?<>이 조건으로 다시 확인 <RefreshCw size={16}/></>:<>자격 확인하기 <Check size={16}/></>}</Button>
    </form>
    {state.status==='error'&&<p className="eligibility-error" role="alert">{state.message}</p>}
    {state.status==='done'&&<Results results={state.results} response={state.response}/>}
  </section>
}

function AnswerField({label,value,onChange,yes='예',no='아니요'}:{label:string; value:Answer; onChange:(v:Answer)=>void; yes?:string; no?:string}) {
  const options:[Answer,string][]=[['unknown','잘 모르겠어요'],['yes',yes],['no',no]]
  return <fieldset className="eligibility-answer"><legend>{label}</legend><div>{options.map(([key,text])=><button type="button" key={key} aria-pressed={value===key} className={value===key?'active':''} onClick={()=>onChange(key)}>{text}</button>)}</div></fieldset>
}

function Results({results,response}:{results:CheckResult[]; response:CheckResponse}) {
  return <div className="eligibility-results" aria-live="polite">
    {results.length===0?<div className="eligibility-empty"><CircleHelp size={20}/><p>{response.message||'이 일정에 연결된 지원제도를 찾지 못했어요.'}</p></div>
      :results.map((row,i)=><ResultCard key={row.benefit_id} row={row} open={i===0}/>)}
    {response.coverage_note&&<details className="eligibility-note"><summary>조회 범위 안내</summary><p>{response.coverage_note}</p></details>}
    {response.disclaimer&&<p className="eligibility-disclaimer">{response.disclaimer}</p>}
  </div>
}

function ResultCard({row,open}:{row:CheckResult; open:boolean}) {
  const verdict=verdictOf(row.verdict)
  const amount=row.estimate?.amount
  const missing=uniqueLabels(row.missing_user_fields??[])
  const link=safeUrl(row.how_to_apply?.application_url??null) ?? safeUrl(row.how_to_apply?.official_info_url??null)
  return <details className={`eligibility-card tone-${verdict.tone}`} open={open}>
    <summary>
      <span className={`badge badge-${verdict.tone}`}>{verdict.label}</span>
      <strong>{row.name}</strong>
      <span className="eligibility-amount">{typeof amount==='number'?`${row.estimate?.amount_kind==='upper_bound'?'최대 ':''}${formatKrw(amount)}`:'금액 확인 필요'}</span>
      <ChevronDown className="eligibility-chevron" size={18}/>
    </summary>
    {row.can_apply_now===false&&<p className="eligibility-alert">지금은 신청할 수 없어요(마감·예산 소진·사전 신청 기한 경과).</p>}
    {row.verification_status==='unverified'&&<p className="eligibility-hint">공식 공고로 아직 검토되지 않은 자료 기준이에요. 신청 전 공고를 꼭 확인해 주세요.</p>}
    {row.unmet_conditions.length>0&&<ConditionList title="맞지 않는 조건" icon={<CircleX size={15}/>} tone="unmet" rows={row.unmet_conditions}/>}
    {missing.length>0&&<div className="eligibility-missing"><span>더 알려주면 정확해져요</span><ul>{missing.map(text=><li key={text}>{text}</li>)}</ul></div>}
    {row.met_conditions.length>0&&<ConditionList title="맞는 조건" icon={<CircleCheck size={15}/>} tone="met" rows={row.met_conditions}/>}
    {row.estimate&&(row.estimate.notes?.length||row.estimate.unavailable_reasons?.length)?<ul className="eligibility-notes">{[...(row.estimate.unavailable_reasons??[]),...(row.estimate.notes??[])].map(text=><li key={text}>{text}</li>)}</ul>:null}
    {row.steps&&row.steps.length>0&&<ol className="eligibility-steps">{row.steps.map(step=><li key={step.key} className={step.passed?'passed':''}>
      <CalendarClock size={15}/><div><strong>{step.title}</strong><span>{[step.due?`${shortDate(step.due)}까지`:step.period?`${shortDate(step.period.start)} ~ ${shortDate(step.period.end)}`:step.due_text,step.detail].filter(Boolean).join(' · ')}</span></div>{dDay(step)&&<em>{dDay(step)}</em>}
    </li>)}</ol>}
    {!!row.official_checks_needed?.length&&<details className="eligibility-note"><summary>공고에서 확인할 항목 {row.official_checks_needed.length}개</summary><ul>{row.official_checks_needed.map(text=><li key={text}>{text}</li>)}</ul></details>}
    {link&&<a className="eligibility-link" href={link} target="_blank" rel="noopener noreferrer">공식 안내 보기 <ExternalLink size={13}/></a>}
  </details>
}

function ConditionList({title,icon,tone,rows}:{title:string; icon:ReactNode; tone:string; rows:{code:string;label?:string|null;detail?:string|null}[]}) {
  return <div className={`eligibility-conditions ${tone}`}><span>{icon}{title}</span><ul>{rows.map(c=><li key={c.code+(c.detail??'')}><b>{c.label??c.code}</b>{c.detail?` · ${c.detail}`:''}</li>)}</ul></div>
}
