import test from 'node:test'
import assert from 'node:assert/strict'
import { courseRequest, courseThemes, cleanInterests, uniqueCourses, courseSummary, errorMessage, sigunguCode } from '../src/lib/course.ts'

const trip = {type:'1박 2일',date:'2026-11-10',origin:'광주 북구',residence:'광주 북구',people:2,transport:'자차'}
const spot = (id, title=id) => ({order:1,start:'10:00',end:'11:00',kind:'spot',place:{content_id:id,title}})
const course = (id, ids) => ({id,days:[{day:1,date:'2026-11-10',start_point:'광주 북구',depart:'09:00',items:ids.map(x=>spot(x)),home_arrival:'17:00'}],warnings:[],spend_breakdown:{total_krw:50000,items:[]}})

test('destination names map to backend sigungu codes',()=>{
  assert.equal(sigunguCode('무안군'),'46840')
  assert.equal(sigunguCode('광주 동구'),'29110')
  assert.equal(sigunguCode('그 외 지역'),null)
})
test('request uses backend keys and clamps party size',()=>{
  const body=courseRequest({...trip,type:'당일',transport:'대중교통',people:30},['nature'],'46840')
  assert.deepEqual(body,{trip_type:'day',start_date:'2026-11-10',origin:'gj-buk',interests:['nature'],party_size:20,transport:'transit',sigungu_code:'46840'})
  // An unknown origin is not silently replaced by 광주 북구: the backend rejects it instead.
  assert.equal(courseRequest({...trip,origin:'모르는 곳'},['nature'],'46840').origin,null)
})
test('themes start with the user mix and never repeat a single picked theme',()=>{
  const themes=courseThemes(['nature'])
  assert.equal(themes.length,3)
  assert.deepEqual(themes[0].interests,['nature'])
  assert.ok(themes.slice(1).every(t=>t.interests[0]!=='nature'))
  assert.deepEqual(courseThemes(['nature','history'])[1].interests,['nature'])
})
test('unknown or empty interests fall back to defaults, max three kept',()=>{
  assert.deepEqual(cleanInterests(null),['nature','history'])
  assert.deepEqual(cleanInterests(['x']),['nature','history'])
  assert.deepEqual(cleanInterests(['food','food','healing','nature','activity']),['food','healing','nature'])
})
test('courses with the same spots in order are shown once',()=>{
  const rows=[{course:course('a',['1','2'])},{course:course('b',['1','2'])},{course:course('c',['2','1'])}]
  assert.deepEqual(uniqueCourses(rows).map(r=>r.course.id),['a','c'])
})
test('summary counts spots and reads spend and arrival',()=>{
  const s=courseSummary(course('a',['1','2','3','4','5']))
  assert.equal(s.spotCount,5); assert.equal(s.highlights.length,4); assert.equal(s.spend,50000); assert.equal(s.homeArrival,'17:00')
})
test('empty tourism cache and validation errors get readable messages',()=>{
  assert.equal(errorMessage(503,{code:'tourism_cache_empty'}).code,'tourism_cache_empty')
  assert.equal(errorMessage(422,{detail:[{msg:'Value error, 여행 시작일은 오늘 이후여야 해요'}]}).message,'여행 시작일은 오늘 이후여야 해요')
  assert.equal(errorMessage(500,null).code,'error')
})
