import test from 'node:test'
import assert from 'node:assert/strict'
import { inPeriod, isOpen, safeUrl, addDays, benefitsFromPrograms, regionPrograms, pickProgram, rateText, deadlineNotes } from '../src/lib/benefits.ts'

const benefit = { trip_start:'2026-11-01', trip_end:'2026-11-07', present_in_source:true,
  collected_at:new Date().toISOString(), source_status:'신청접수중' }

test('overnight trip must fit the entire operating period',()=>{
  assert.equal(inPeriod(benefit,{date:'2026-11-07',type:'당일'}),true)
  assert.equal(inPeriod(benefit,{date:'2026-11-07',type:'1박 2일'}),false)
  assert.equal(inPeriod(benefit,{date:'2026-11-06',type:'1박 2일'}),true)
})
test('clearing a date does not crash filtering',()=>{
  assert.equal(inPeriod(benefit,{date:'',type:'당일'}),false)
  assert.equal(inPeriod(benefit,{date:'bad-date',type:'당일'}),false)
  assert.equal(addDays('2026-12-31',1),'2027-01-01')
})
test('stale, removed, and closed entries never count as open',()=>{
  assert.equal(isOpen(benefit),true)
  assert.equal(isOpen({...benefit,collected_at:'2020-01-01T00:00:00Z'}),false)
  assert.equal(isOpen({...benefit,present_in_source:false}),false)
  assert.equal(isOpen({...benefit,source_status:'마감'}),false)
})
test('external links only allow ordinary HTTP(S) URLs',()=>{
  assert.equal(safeUrl('javascript:alert(1)'),undefined)
  assert.equal(safeUrl('https://user:password@example.com'),undefined)
  assert.equal(safeUrl(null),undefined)
  assert.equal(safeUrl('https://example.go.kr/apply'),'https://example.go.kr/apply')
})
test('program rows carry payment, conditions and contacts; unstated values stay empty',()=>{
  const base={program_id:'p',name:'강진 3차',sigungu_names:['강진군'],posted_status:'open',open_now:true,
    trip_period:null,application_period:null,refund_rate:0.5,data_origin:'collected',verification_status:'unverified',
    status_checked_at:null,superseded_by:[],official_info_url:null,application_url:null}
  const [page]=benefitsFromPrograms([{...base,payment_methods:['chak 앱'],contacts:['061-000-0007','061-000-0008'],
    conditions_text:'관광지 2개소(사진) 방문',visit_rule:null,proof_items:null}])
  assert.equal(page.payment_rule,'chak 앱')
  assert.equal(page.contact,'061-000-0007\n061-000-0008')
  assert.equal(page.conditions,'원문: 관광지 2개소(사진) 방문\n※ 공식 공고로 최종 확인이 필요해요.')
  const [manual]=benefitsFromPrograms([{...base,proof_items:['영수증'],
    visit_rule:{must_include:['무안황토갯벌랜드'],any_of:[],min_any_of:0,min_total_places:2}}])
  assert.equal(manual.conditions,'무안황토갯벌랜드 포함 방문\n관광지 2곳 이상 방문\n증빙: 영수증\n※ 공식 공고로 최종 확인이 필요해요.')
  assert.equal(manual.payment_rule,'')
  const [empty]=benefitsFromPrograms([base])
  assert.deepEqual([empty.payment_rule,empty.conditions,empty.contact],['','',''])
})
test('every program of a region stays reachable; the default is the open one',()=>{
  const row=(id,region,status,present=true)=>({...benefit,id,region_name:region,source_status:status,present_in_source:present})
  const rows=[row('closed','강진군','마감'),row('island','강진군','신청접수중'),row('gone','강진군','신청접수중',false),row('other','장흥군','신청접수중')]
  const gangjin=regionPrograms(rows,'강진군')
  assert.deepEqual(gangjin.map(r=>r.id),['closed','island'])
  assert.equal(pickProgram(gangjin,null).id,'island')
  assert.equal(pickProgram(gangjin,'closed').id,'closed')
  assert.equal(pickProgram(gangjin,'unknown').id,'island')
  assert.equal(pickProgram(regionPrograms(rows,'곡성군'),null),undefined)
  assert.deepEqual(regionPrograms(rows,undefined),[])
})
test('application period, refund rate and stated deadlines reach the screen; unstated ones stay empty',()=>{
  const base={program_id:'manual:island-2026',family_id:'island',name:'섬 반값여행',sigungu_names:['여수시'],posted_status:'open',
    open_now:true,trip_period:{start:'2026-08-29',end:'2026-11-04'},application_period:{start:'2026-08-20',end:null},refund_rate:0.5,
    data_origin:'manual_registry',verification_status:'unverified',status_checked_at:null,superseded_by:[],official_info_url:null,
    application_url:null,pre_apply_days_before_trip:5,settlement_days_after_trip:10}
  const [row]=benefitsFromPrograms([base])
  assert.equal(row.family_id,'island')
  assert.equal(row.application_note,'신청 기간 2026-08-20 ~ 미확인')
  assert.equal(row.application_end,null)
  assert.equal(rateText(row.refund_rate),'50%'); assert.equal(rateText(null),null)
  const notes=deadlineNotes(row,{date:'2026-11-03',type:'1박 2일'})
  assert.equal(notes.apply,null)
  assert.equal(notes.preApply,'여행 시작 5일 전인 2026-10-29까지 사전 신청 (공식 공고로 확인 필요)')
  assert.equal(notes.settle,'여행 종료 후 10일 이내, 2026-11-14까지 증빙 제출 (공식 공고로 확인 필요)')
  const [bare]=benefitsFromPrograms([{...base,application_period:null,pre_apply_days_before_trip:null,settlement_days_after_trip:undefined}])
  assert.equal(bare.application_note,'신청 기간 미확인')
  assert.deepEqual(deadlineNotes(bare,{date:'2026-11-03',type:'당일'}),{apply:null,preApply:null,settle:null})
})
