import test from 'node:test'
import assert from 'node:assert/strict'
import { emptyProfile, userConditions, refundRequest, tripCheckRequest, refundResults, fieldLabel, uniqueLabels, dDay, regionOf, conditionGroups, conditionReviewLabel, OTHER } from '../src/lib/eligibility.ts'

const trip={type:'1박 2일',date:'2026-11-10',origin:'광주 북구',residence:'광주 북구',people:2,transport:'자차'}

test('API met list does not present exempt or unverified rules as fulfilled',()=>{
  const groups=conditionGroups({met_conditions:[
    {code:'trip_period',status:'met',rule_confirmed:true},
    {code:'family',status:'not_applicable',rule_confirmed:true},
    {code:'age',status:'met',rule_confirmed:false},
    {code:'pre_apply',status:'not_applicable',rule_confirmed:false},
  ],unmet_conditions:[]})
  assert.deepEqual(groups.met.map(c=>c.code),['trip_period'])
  assert.deepEqual(groups.notApplicable.map(c=>c.code),['family'])
  assert.deepEqual(groups.review.map(c=>c.code),['age','pre_apply'])
})

test('unverified failures and unresolved checks stay visible as review items',()=>{
  const groups=conditionGroups({met_conditions:[],unmet_conditions:[
    {code:'party_size',status:'unmet',rule_confirmed:true},
    {code:'posted_status',status:'unmet',rule_confirmed:false},
  ],unresolved_conditions:[
    {code:'residence',status:'missing_user_info',rule_confirmed:true},
    {code:'source',status:'conflict',rule_confirmed:false},
  ]})
  assert.deepEqual(groups.unmet.map(c=>c.code),['party_size'])
  assert.deepEqual(groups.review.map(c=>c.code),['posted_status','residence','source'])
  assert.equal(conditionReviewLabel(groups.review[1]),'정보 입력 필요')
  assert.equal(conditionReviewLabel(groups.review[2]),'출처 불일치')
})

test('partial responses without rule confirmation cannot claim a confirmed match',()=>{
  const groups=conditionGroups({met_conditions:[{code:'age',status:'met'}]})
  assert.equal(groups.met.length,0)
  assert.equal(groups.review.length,1)
})

test('unknown answers are left out instead of guessed',()=>{
  assert.deepEqual(userConditions(emptyProfile('광주 북구')),{residence:{sido:'광주광역시',sigungu:'북구'}})
  const p={...emptyProfile('무안군'),birthDate:'1999-01-01',family:'yes',sameAddress:'no',firstTime:'yes'}
  assert.deepEqual(userConditions(p),{residence:{sido:'전라남도',sigungu:'무안군'},birth_date:'1999-01-01',is_family:true,same_address:false,prior_participated_program_ids:[]})
  assert.equal('same_address' in userConditions({...p,family:'no'}),false)
  assert.equal('prior_participated_program_ids' in userConditions({...p,firstTime:'no'}),false)
})
test('course check sends Gwangju·Jeonnam residence as a code, others by name',()=>{
  assert.deepEqual(refundRequest(emptyProfile('광주 북구')),{residence_code:'29170',benefit_conditions:{}})
  const other={...emptyProfile(OTHER),otherSido:'서울특별시',otherSigungu:' 강남구 '}
  assert.deepEqual(refundRequest(other),{benefit_conditions:{residence:{sido:'서울특별시',sigungu:'강남구'}}})
})
test('trip check builds one visit with nights from the trip type',()=>{
  const body=tripCheckRequest(emptyProfile('광주 북구'),trip,'무안군','2026-11-11')
  assert.deepEqual(body.visits,[{region:{sido:'전라남도',sigungu:'무안군'},start_date:'2026-11-10',end_date:'2026-11-11',nights:1}])
  assert.equal(tripCheckRequest(emptyProfile('광주 북구'),{...trip,type:'당일'},'광주 동구','2026-11-10').visits[0].nights,0)
  assert.equal(tripCheckRequest(emptyProfile('광주 북구'),trip,'그 외 지역','2026-11-11'),null)
  assert.deepEqual(regionOf('광주 광산구'),{sido:'광주광역시',sigungu:'광산구'})
})
test('course program comes first and keeps its dated steps',()=>{
  const a={benefit_id:'a',name:'A',verdict:'needs_verification'},b={benefit_id:'b',name:'B',verdict:'ineligible'}
  const rows=refundResults({selected:{benefit_id:'b',steps:[{key:'settle'}]},check:{results:[a,b]}})
  assert.deepEqual(rows.map(r=>r.benefit_id),['b','a']); assert.equal(rows[0].steps.length,1); assert.equal(rows[0].name,'B')
  assert.deepEqual(refundResults({selected:null,check:{results:[a]}}),[a])
})
test('missing fields read as plain words and d-day labels',()=>{
  assert.equal(fieldLabel('birth_date'),'생년월일')
  assert.equal(uniqueLabels(['visits[0].places','visits[1].places']).length,1)
  assert.equal(dDay({d_day:18,passed:false}),'D-18'); assert.equal(dDay({d_day:0}),'D-DAY')
  assert.equal(dDay({d_day:-2,passed:true}),'기한 지남'); assert.equal(dDay({d_day:null}),null)
})

import { resultVerdict, refundResults as mergeRefund } from '../src/lib/eligibility.ts'
import { programKind } from '../src/lib/benefits.ts'
test('group-limited travel support is labelled apart from general support and never shown as eligible', () => {
  const row = (id, audience, verdict = 'needs_verification') => ({ benefit_id: id, name: id, verdict, audience, can_apply_now: null,
    met_conditions: [], unmet_conditions: [], missing_user_fields: [], estimate: null })
  const targeted = row('gov24:장애인가족여행', 'targeted'), travel = row('kto50:12780-2026-3', 'general')
  assert.equal(resultVerdict(targeted).label, '특정 대상 전용 · 확인 필요')
  assert.equal(resultVerdict(travel).label, '추가 확인 필요')   // needs_verification is never upgraded
  assert.equal(resultVerdict(row('x', 'targeted', 'ineligible')).label, '미충족 조건 있음')
  // Order is the server's; nothing is moved to the back on the client.
  assert.deepEqual(mergeRefund({ selected: null, check: { results: [targeted, travel] } }).map(r => r.benefit_id), ['gov24:장애인가족여행', 'kto50:12780-2026-3'])
  assert.equal(programKind({ data_origin: 'gov24_api', audience: 'targeted' }), '특정 대상 전용 관광지원')
  assert.equal(programKind({ data_origin: 'gov24_api', audience: 'general' }), '공공서비스')
})
