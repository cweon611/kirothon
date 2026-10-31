import type { Trip } from './benefits'
import { SIGUNGU } from './course.ts'

// Shapes from POST /api/benefits/check and POST /api/team/courses/{id}/refund (docs/benefits-api.md).
export type Condition = {code:string; label?:string|null; status:string; detail?:string|null}
export type Estimate = {
  benefit_type?:string|null; amount:number|null; amount_kind?:string|null; recognized_spend?:number|null;
  refund_rate?:number|null; cap_amount?:number|null; min_spend?:number|null; shortfall_to_min_spend?:number|null;
  unavailable_reasons?:string[]; notes?:string[]
}
export type Step = {
  key:string; title:string; due:string|null; d_day:number|null; due_text?:string|null; passed?:boolean|null;
  period?:{start:string; end:string}|null; detail?:string|null; action_url?:string|null
}
export type CheckResult = {
  benefit_id:string; name:string; verdict:'potentially_eligible'|'ineligible'|'needs_verification'|string;
  can_apply_now:boolean|null; verification_status?:string|null;
  met_conditions:Condition[]; unmet_conditions:Condition[]; unresolved_conditions?:Condition[];
  missing_user_fields:string[]; official_checks_needed?:string[]; estimate:Estimate|null;
  how_to_apply?:{application_url?:string|null; official_info_url?:string|null}|null; steps?:Step[]
  /** Collection source (official_webpage, gov24_api, news_report, …); decides how the info link is labelled. */
  source_type?:string|null
  /** general = 일반 관광객 대상, targeted = 특정 대상 전용 관광지원 */
  audience?:'general'|'targeted'
}
export type CheckResponse = {
  outcome:string; message?:string|null; missing_fields:string[]; results:CheckResult[];
  coverage_note?:string|null; disclaimer?:string|null
}
export type RefundResponse = {selected:(Partial<CheckResult>&{benefit_id:string; steps?:Step[]})|null; check:CheckResponse}

export type Answer = 'unknown'|'yes'|'no'
export type Profile = {
  residence:string;            // one of the 27 destination names, or OTHER
  otherSido:string; otherSigungu:string;
  birthDate:string;            // '' when not given
  family:Answer; sameAddress:Answer;
  firstTime:Answer;            // 'yes' = never joined these programs before
}
export const OTHER = '그 외 지역'
export const SIDO = ['서울특별시','부산광역시','대구광역시','인천광역시','광주광역시','대전광역시','울산광역시','세종특별자치시','경기도','강원특별자치도','충청북도','충청남도','전북특별자치도','전라남도','경상북도','경상남도','제주특별자치도']

export function emptyProfile(residence:string):Profile {
  return {residence, otherSido:'서울특별시', otherSigungu:'', birthDate:'', family:'unknown', sameAddress:'unknown', firstTime:'unknown'}
}

/** '광주 동구' → 광주광역시/동구, '무안군' → 전라남도/무안군 (the 27 destinations). */
export function regionOf(name:string) {
  if (name.startsWith('광주 ')) return {sido:'광주광역시', sigungu:name.slice(3)}
  return SIGUNGU[name] ? {sido:'전라남도', sigungu:name} : null
}

function residenceRegion(profile:Profile) {
  if (profile.residence!==OTHER) return regionOf(profile.residence)
  const sigungu=profile.otherSigungu.trim()
  return profile.otherSido ? {sido:profile.otherSido, ...(sigungu?{sigungu}:{})} : null
}

/** User conditions in the benefits-engine input format. Unknown answers are left out, never guessed. */
export function userConditions(profile:Profile) {
  const out:Record<string,unknown>={}
  const residence=residenceRegion(profile)
  if (residence) out.residence=residence
  if (/^\d{4}-\d{2}-\d{2}$/.test(profile.birthDate)) out.birth_date=profile.birthDate
  if (profile.family!=='unknown') out.is_family=profile.family==='yes'
  if (profile.family==='yes' && profile.sameAddress!=='unknown') out.same_address=profile.sameAddress==='yes'
  if (profile.firstTime==='yes') out.prior_participated_program_ids=[]
  return out
}

/** Body for POST /api/team/courses/{id}/refund. Gwangju·Jeonnam residents go by code, others by name. */
export function refundRequest(profile:Profile) {
  const code=profile.residence!==OTHER ? SIGUNGU[profile.residence] : undefined
  const conditions=userConditions(profile)
  if (code) delete conditions.residence
  return {...(code?{residence_code:code}:{}), benefit_conditions:conditions}
}

/** Body for POST /api/benefits/check when there is no course yet: one visit to the chosen region. */
export function tripCheckRequest(profile:Profile, trip:Trip, region:string, end:string) {
  const visitRegion=regionOf(region)
  if (!visitRegion) return null
  return {
    ...userConditions(profile), trip_start:trip.date, trip_end:end, party_size:trip.people,
    visits:[{region:visitRegion, start_date:trip.date, end_date:end, nights:trip.type==='당일'?0:1}],
  }
}

export const VERDICT = {
  potentially_eligible:{label:'받을 가능성이 있어요',tone:'green'},
  needs_verification:{label:'확인이 더 필요해요',tone:'orange'},
  ineligible:{label:'이번 조건으로는 어려워요',tone:'gray'},
} as Record<string,{label:string;tone:string}>
export const verdictOf = (value:string) => VERDICT[value] ?? {label:'판정 정보 없음',tone:'gray'}
/** Non-travel services never arrive (the server drops them). Travel support limited to a group (`audience:
 *  'targeted'`) keeps its own verdict, which can never be 'eligible' while the group is unknown, and is labelled
 *  separately from general tourist support. */
export const resultVerdict = (row:Pick<CheckResult,'verdict'|'audience'>) =>
  row.audience==='targeted' && row.verdict!=='ineligible' ? {label:'특정 대상 전용 · 확인 필요',tone:'orange'} : verdictOf(row.verdict)

const FIELD_LABELS:Record<string,string> = {
  residence:'거주지', birth_date:'생년월일', age:'나이', is_family:'가족 여행 여부', same_address:'같은 주소 여부',
  prior_participated_program_ids:'이전 참여 이력', party_size:'여행 인원', expected_spend_total:'전체 예상 지출',
  audience:'지원 대상 해당 여부 (공고에서 확인)',
}
/** Readable names for missing fields; course-only fields point the user to the itinerary step. */
export function fieldLabel(field:string) {
  if (/^visits\[\d+\]\.expected_spend/.test(field)) return '지역별 예상 지출 (추천 일정을 고르면 자동으로 채워져요)'
  if (/^visits\[\d+\]\.places/.test(field)) return '방문 장소 (추천 일정을 고르면 자동으로 채워져요)'
  return FIELD_LABELS[field] ?? field
}
export const uniqueLabels = (fields:string[]) => [...new Set(fields.map(fieldLabel))]

/** Course mode: merge the course program's dated steps into the matching full result, course program first. */
export function refundResults(response:RefundResponse):CheckResult[] {
  const results=response.check?.results ?? []
  const selected=response.selected
  if (!selected) return results
  const full=results.find(row=>row.benefit_id===selected.benefit_id)
  const first={...(full ?? selected as CheckResult), steps:selected.steps}
  return [first, ...results.filter(row=>row.benefit_id!==selected.benefit_id)]
}

export function dDay(step:Step) {
  if (step.d_day===null || step.d_day===undefined) return null
  return step.passed ? '기한 지남' : step.d_day===0 ? 'D-DAY' : step.d_day>0 ? `D-${step.d_day}` : `D+${-step.d_day}`
}
