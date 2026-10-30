import type { Trip } from './benefits'

// Mirrors backend seeds (regions.json, origins.json, interest_map.json) so the page can build
// requests before /api/team/meta answers. The backend still validates every value.
export const SIGUNGU: Record<string, string> = {
  '광주 동구': '29110', '광주 서구': '29140', '광주 남구': '29155', '광주 북구': '29170', '광주 광산구': '29200',
  '목포시': '46110', '여수시': '46130', '순천시': '46150', '나주시': '46170', '광양시': '46230',
  '담양군': '46710', '곡성군': '46720', '구례군': '46730', '고흥군': '46770', '보성군': '46780',
  '화순군': '46790', '장흥군': '46800', '강진군': '46810', '해남군': '46820', '영암군': '46830',
  '무안군': '46840', '함평군': '46860', '영광군': '46870', '장성군': '46880', '완도군': '46890',
  '진도군': '46900', '신안군': '46910',
}
export const ORIGINS = [
  {key:'gj-dong',name:'광주 동구'},{key:'gj-seo',name:'광주 서구'},{key:'gj-nam',name:'광주 남구'},
  {key:'gj-buk',name:'광주 북구'},{key:'gj-gwangsan',name:'광주 광산구'},{key:'st-gwangjusongjeong',name:'광주송정역'},
  {key:'st-mokpo',name:'목포역'},{key:'st-suncheon',name:'순천역'},{key:'st-yeosuexpo',name:'여수엑스포역'},
]
export const INTERESTS = [
  {key:'nature',label:'자연·바다'},{key:'history',label:'역사·문화'},{key:'food',label:'맛집'},
  {key:'activity',label:'체험·레저'},{key:'healing',label:'힐링·산책'},
]
export const DEFAULT_INTERESTS = ['nature','history']
// Alternative single-theme courses, in the order they are offered.
const THEME_ORDER = ['nature','history','healing','activity']

export type Interest = string
export type CoursePlace = {
  content_id:string; title:string; category?:string; lat?:number|null; lng?:number|null;
  sigungu_code?:string; source?:string; image_url?:string|null
}
export type CourseItem = {
  order:number; start:string; end:string|null; kind:'spot'|'meal'|'stay'|string; meal?:string|null;
  place:CoursePlace|null; move_min_from_prev?:number|null; move_warning?:boolean; transit_note?:string|null;
  label?:string|null; required?:boolean; swappable?:boolean; reason_tags?:string[]; reason_text?:string|null;
  reason_by?:string; in_refund_region?:boolean; refund_note?:string|null; check_before_visit?:boolean;
  check_reasons?:string[]
}
export type CourseDay = {
  day:number; date:string; start_point:string; depart:string; items:CourseItem[];
  return_move_min?:number; return_depart?:string; home_arrival?:string
}
export type SpendItem = {label:string; krw:number; basis?:string}
export type Course = {
  id:string; trip_type:string; start_date:string; end_date:string; origin:string; interests:string[];
  party_size:number; transport:string;
  region:{sigungu_code:string; name:string; refund_program?:{name:string; posted_status?:string|null; rate?:number|null; cap_krw?:number|null; source_url?:string|null}|null};
  days:CourseDay[]; estimated_spend_krw?:number|null;
  spend_breakdown?:{total_krw:number; items:SpendItem[]; fees_not_parsed?:string[]};
  warnings:{code:string; message:string; suggested_date?:string}[]; notes?:unknown[]
}
export type PlaceDetail = {
  content_id:string; title:string; category?:string; addr?:string|null; tel?:string|null; overview?:string|null;
  rest_text?:string|null; opening_window?:{open:string; close:string}|null; fee_krw?:number|null;
  closed_on_visit_date?:boolean|null; check_before_visit?:boolean; image_url?:string|null; image_credit?:string|null;
  evidence?:string[]; source?:string; detail_status?:string
}
export type Theme = {key:string; title:string; interests:Interest[]}

export function sigunguCode(region:string) { return SIGUNGU[region] ?? null }
export function originKey(name:string) { return ORIGINS.find(row=>row.name===name)?.key ?? 'gj-buk' }
export function originName(key:string) { return ORIGINS.find(row=>row.key===key)?.name ?? key }
export function interestLabel(key:string) { return INTERESTS.find(row=>row.key===key)?.label ?? key }

export function cleanInterests(value:unknown):Interest[] {
  if (!Array.isArray(value)) return DEFAULT_INTERESTS
  const known=[...new Set(value.filter(v=>INTERESTS.some(row=>row.key===v)))].slice(0,3)
  return known.length ? known : DEFAULT_INTERESTS
}

/** The user's own mix first, then up to two single-theme alternatives they did not pick. */
export function courseThemes(selected:Interest[]):Theme[] {
  const mine=cleanInterests(selected)
  const themes:Theme[]=[{key:'mine',title:`${mine.map(interestLabel).join(' + ')} 맞춤 코스`,interests:mine}]
  for (const key of THEME_ORDER) {
    if (themes.length>=3) break
    if (mine.length===1 && mine[0]===key) continue
    themes.push({key,title:`${interestLabel(key)} 중심 코스`,interests:[key]})
  }
  return themes
}

export function courseRequest(trip:Trip, interests:Interest[], code:string) {
  return {
    trip_type: trip.type==='당일'?'day':'1N2D', start_date: trip.date, origin: originKey(trip.origin),
    interests: cleanInterests(interests), party_size: Math.min(Math.max(trip.people,1),20),
    transport: trip.transport==='대중교통'?'transit':'car', sigungu_code: code,
  }
}

export const spots = (course:Course) => course.days.flatMap(day=>day.items.filter(item=>item.kind==='spot'&&item.place))
/** Courses that visit the same spots in the same order are the same recommendation. */
export function uniqueCourses<T extends {course:Course}>(rows:T[]):T[] {
  const seen=new Set<string>()
  return rows.filter(row=>{
    const key=spots(row.course).map(item=>item.place!.content_id).join('>')
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

export function courseSummary(course:Course) {
  const visited=spots(course)
  const last=course.days[course.days.length-1]
  return {
    spotCount: visited.length,
    highlights: visited.slice(0,4).map(item=>item.place!.title),
    mealCount: course.days.flatMap(day=>day.items).filter(item=>item.kind==='meal').length,
    stay: course.days.flatMap(day=>day.items).find(item=>item.kind==='stay')?.place?.title ?? null,
    depart: course.days[0]?.depart ?? null,
    homeArrival: last?.home_arrival ?? null,
    spend: course.spend_breakdown?.total_krw ?? course.estimated_spend_krw ?? null,
    longMoves: course.days.flatMap(day=>day.items).filter(item=>item.move_warning).length,
  }
}

export function formatKrw(value:number|null|undefined) {
  return typeof value==='number' && Number.isFinite(value) ? `${value.toLocaleString('ko-KR')}원` : '확인 필요'
}

export function errorMessage(status:number, body:unknown) {
  const code=(body as {code?:string})?.code
  if (code==='tourism_cache_empty') return {code, message:'관광 데이터가 아직 수집되지 않아 일정을 만들 수 없어요.'}
  if (status===422) {
    const detail=(body as {detail?:unknown})?.detail
    const text=typeof detail==='string'?detail:Array.isArray(detail)?String((detail[0] as {msg?:string})?.msg??''):''
    return {code:code??'invalid', message:text.replace(/^Value error, /,'')||'여행 조건을 다시 확인해 주세요.'}
  }
  return {code:code??'error', message:'일정을 불러오지 못했어요. 잠시 후 다시 시도해 주세요.'}
}
