import test from 'node:test'
import assert from 'node:assert/strict'
import { emptyStateKind, errorMessage, festivalsFromSelected, fieldLabels, originLabel, periodText, regionRequest, requestBody, validateDates } from '../src/lib/date-recommendations.ts'
import { festivalState } from '../src/lib/festivals.ts'

const fest = (id, start, end) => ({content_id:id,title:`축제${id}`,start_date:start,end_date:end,place:null,overview:null,
  source:'한국관광공사 TourAPI',source_url:null,fetched_at:'2026-10-30T14:09:13+00:00'})
const response = (states, festivals = [], undated = [], status = 'ok') => ({
  selected_region: {sigungu_code:'46840',name:'무안군',festivals,festivals_undated:undated,states},
  data_status: {festivals:{status,last_success_at:'2026-10-30T14:09:13+00:00'}}})

test('festival adapter keeps the destination, never invents links, and separates failure from none',()=>{
  const ok = festivalsFromSelected(response({festivals:'found'},[fest('a','2026-10-23','2026-11-21')],[fest('b',null,null)]),'무안군')
  assert.equal(ok.state,'found')
  // Missing place/link/dates stay empty so the card leaves those rows out (no placeholder text).
  assert.deepEqual(ok.rows.map(r=>[r.id,r.region_name,r.source_url,r.location,r.period_note]),
    [['a','무안군','','','2026-10-23 ~ 2026-11-21'],['b','무안군','','','']])
  assert.equal(festivalsFromSelected(response({festivals:'found'},[{...fest('c','2026-11-20','2026-11-20'),place:'  ',source_url:'  '}]),'무안군').rows[0].location,'')
  assert.equal(festivalState(ok.rows[0],'2026-11-20','2026-11-22','2026-10-30'),'match')   // started before the trip, still running
  assert.equal(festivalState(ok.rows[1],'2026-11-20','2026-11-22','2026-10-30'),'unknown')
  assert.equal(ok.usingPrevious,false)
  assert.equal(festivalsFromSelected(response({festivals:'none_in_period'},[],[],'partial'),'무안군').usingPrevious,true)
  const failed = festivalsFromSelected(response({festivals:'unavailable'},[],[],'error'),'무안군')
  assert.equal(failed.state,'unavailable')
  assert.equal(failed.usingPrevious,false)
  assert.equal(festivalsFromSelected({selected_region:null,data_status:{festivals:{status:'ok',last_success_at:null}}},'무안군').state,'unavailable')
})
import { benefitsFromPrograms, inPeriod, tripEnd } from '../src/lib/benefits.ts'

test('slingshot region request carries code and dates, omits missing dialog fields and never sends birth date',()=>{
  assert.deepEqual(requestBody(regionRequest('46810','2026-11-07','2026-11-08')),
    {start_date:'2026-11-07',end_date:'2026-11-08',sigungu_code:'46810'})
  assert.deepEqual(requestBody(regionRequest('46810','2026-11-07','2026-11-08',{residence:null,party_size:null})),
    {start_date:'2026-11-07',end_date:'2026-11-08',sigungu_code:'46810'})
  assert.deepEqual(requestBody(regionRequest('46810','2026-11-07','2026-11-08',{residence:'29170',party_size:2})),
    {start_date:'2026-11-07',end_date:'2026-11-08',sigungu_code:'46810',residence:'29170',party_size:2})
  assert.equal('birth_date' in requestBody(regionRequest('46810','2026-11-07','2026-11-08',{residence:'29170',party_size:2})),false)
})
test('trip end date comes from the dialog trip type',()=>{
  assert.equal(tripEnd({date:'2026-11-07',type:'당일'}),'2026-11-07')
  assert.equal(tripEnd({date:'2026-11-07',type:'1박 2일'}),'2026-11-08')
  assert.equal(tripEnd({date:'2026-12-31',type:'1박 2일'}),'2027-01-01')
})
test('programs adapter never invents periods or check times',()=>{
  const rows=benefitsFromPrograms([{program_id:'kto50:12780-2026-3',name:'강진 3차',sigungu_names:['강진군'],posted_status:'open',
    open_now:true,trip_period:{start:'2026-10-20',end:'2026-11-30'},application_period:null,refund_rate:0.5,data_origin:'kto_tour50',
    verification_status:'unverified',status_checked_at:null,superseded_by:[],official_info_url:null,application_url:null},
    {program_id:'manual:x',name:'x',sigungu_names:['강진군','해남군'],posted_status:null,open_now:null,trip_period:null,
    application_period:null,refund_rate:null,data_origin:'manual_registry',verification_status:'unverified',status_checked_at:null,
    superseded_by:['kto50:12780:2026'],official_info_url:null,application_url:null}])
  assert.equal(rows.length,3)
  assert.equal(rows[0].source_status,'신청접수중')
  assert.equal(inPeriod(rows[0],{date:'2026-11-07',type:'1박 2일'}),true)
  assert.equal(inPeriod(rows[1],{date:'2026-11-07',type:'1박 2일'}),false)
  assert.equal(rows[1].present_in_source,false)
})

test('date validation allows any range but rejects past, reversed and too long trips',()=>{
  assert.equal(validateDates('2026-11-07','2026-11-07','2026-10-30'),null)
  assert.equal(validateDates('2026-11-07','2026-11-20','2026-10-30'),null)
  assert.match(validateDates('2026-10-29','2026-11-01','2026-10-30'),/오늘 이후/)
  assert.match(validateDates('2026-11-08','2026-11-07','2026-10-30'),/종료일/)
  assert.match(validateDates('2026-11-07','2027-01-10','2026-10-30'),/60일/)
  assert.match(validateDates('','2026-11-07','2026-10-30'),/모두/)
})
test('request body only contains provided optional fields',()=>{
  assert.deepEqual(requestBody({start_date:'2026-11-07',end_date:'2026-11-08'}),{start_date:'2026-11-07',end_date:'2026-11-08'})
  assert.deepEqual(requestBody({start_date:'a',end_date:'b',residence:'29170',party_size:2,birth_date:'1990-01-01'}),
    {start_date:'a',end_date:'b',residence:'29170',party_size:2,birth_date:'1990-01-01'})
})
test('API failures and empty results are not shown as "no benefits"',()=>{
  const base={regions:[],outcome:'source_unavailable'}
  assert.equal(emptyStateKind(base),'unavailable')
  assert.equal(emptyStateKind({...base,outcome:'no_match_in_scope'}),'no_match')
  assert.equal(emptyStateKind({...base,regions:[{}],outcome:'matches_found'}),'none')
  assert.equal(errorMessage(422,{detail:[{msg:'Value error, end_date는 start_date 이후여야 해요'}]}),'end_date는 start_date 이후여야 해요')
  assert.match(errorMessage(500,null),/서버/)
})
test('labels map internal field names and distinguish manual registry data',()=>{
  assert.deepEqual(fieldLabels(['residence','visits[0].nights','birth_date','visits[1].nights']),['주민등록상 거주지','숙박 수','생년월일'])
  assert.match(originLabel({data_origin:'manual_registry',verification_status:'unverified'}),/미검토/)
  assert.match(originLabel({data_origin:'kto_tour50'}),/공식 페이지/)
  assert.equal(periodText(null),'미확인')
  assert.equal(periodText({start:'2026-11-01',end:null}),'2026-11-01 ~ 미확인')
})

import { benefitsFromSelected } from '../src/lib/date-recommendations.ts'
const item = (id, judgment, over = {}) => ({ program_id: id, round_id: null, name: `제도 ${id}`, judgment, posted_status: null,
  application_open: null, trip_period: null, application_period: null, application_start_at: null, application_end_at: null,
  support: null, payout_method: null, conditions_text: null, estimated_amount: null, budget_remaining: null,
  apply_url: null, official_url: null, missing_user_fields: [], needs_official_check: [], reasons: [], data_origin: 'manual_registry',
  source_type: 'news_report', verification_status: 'unverified', review_status: null, last_success_at: null, last_verified_at: null,
  stale: null, sources: [], ...over })
test('step 3 programs come from the period lookup: every program kept, needs_verification never upgraded', () => {
  const data = { selected_region: { sigungu_code: '46810', name: '강진군', festivals: [], festivals_undated: [],
    states: { festivals: 'none_in_period', festivals_stale: false, benefits: 'found', benefits_partial: true, needs_user_info: true },
    benefits: {
      applicable: [],
      needs_verification: [
        item('kto50:12780-2026-3', 'needs_verification', { data_origin: 'kto_tour50', source_type: 'official_webpage',
          trip_period: { start: '2026-10-20', end: '2026-11-30' }, posted_status: 'open',
          apply_url: 'https://www.gangjintour.com/', official_url: 'https://www.gangjintour.com/',
          sources: [{ type: 'official_webpage', title: '한국관광공사 대한민국 반값여행 현황', url: 'https://korean.visitkorea.or.kr/dgtourcard/tour50.do' }] }),
        item('manual:muan', 'needs_verification', { official_url: 'https://news.mtn.co.kr/a',
          sources: [{ type: 'news_report', title: 'MTN 보도', url: 'https://news.mtn.co.kr/a' }] })],
      excluded: [item('kto50:12780-2026-2', 'ineligible', { excluded_reason: '여행 인정 기간 불충족' })] } },
    data_status: { festivals: { status: 'ok', last_success_at: null } } }
  const extra = [{ id: 'kto50:12780-2026-3@강진군', payment_rule: 'chak 앱', conditions: '관광지 2개소 방문', contact: '061-433-3349' }]
  const out = benefitsFromSelected(data, '강진군', extra)
  assert.deepEqual(out.shown.map(b => [b.id, b.judgment]), [['kto50:12780-2026-3@강진군', 'needs_verification'], ['manual:muan@강진군', 'needs_verification']])
  assert.equal(out.excluded[0].excluded_reason, '여행 인정 기간 불충족')
  assert.equal(out.partial, true)
  const [gj, muan] = out.shown
  assert.deepEqual([gj.payment_rule, gj.conditions, gj.contact, gj.source_status], ['chak 앱', '관광지 2개소 방문', '061-433-3349', '신청접수중'])
  assert.equal(gj.period_note, '여행 인정 기간 2026-10-20 ~ 2026-11-30')
  // Unknown period / no official page: card stays, period says 미확인, the news report is not an official link.
  assert.equal(muan.period_note, '여행 인정 기간 미확인')
  assert.deepEqual(muan.source_pages, [])
  assert.equal(benefitsFromSelected({ selected_region: null }, '강진군').state, 'unavailable')
})
