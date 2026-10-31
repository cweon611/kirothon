import test from 'node:test'
import assert from 'node:assert/strict'
import { cleanUrl, programLinks, sourcePageLabel } from '../src/lib/links.ts'
import { benefitsFromPrograms, pickRegionBenefit, programKind } from '../src/lib/benefits.ts'

const TOUR50 = 'https://korean.visitkorea.or.kr/dgtourcard/tour50.do'
const row = (over = {}) => ({
  program_id: 'kto50:12780-2026-3', name: '강진 3차', sigungu_names: ['강진군'], posted_status: 'open', open_now: true,
  trip_period: { start: '2026-10-20', end: '2026-11-30' }, application_period: null, refund_rate: 0.5,
  data_origin: 'kto_tour50', source_type: 'official_webpage', verification_status: 'unverified',
  status_checked_at: '2026-10-30T15:02:10+00:00', superseded_by: [],
  official_info_url: 'https://www.gangjintour.com/', application_url: 'https://www.gangjintour.com/',
  payment_methods: ['강진사랑상품권'], contacts: ['061-433-3349'], notes: '지정관광지 2개소 방문',
  source_pages: [{ title: '한국관광공사 대한민국 반값여행 현황', url: TOUR50 }], ...over,
})

test('only http(s) URLs survive; blank, whitespace, malformed and script URLs do not', () => {
  for (const bad of [null, undefined, '', '   ', 'not a url', 'javascript:alert(1)', 'ftp://x.kr/a', 'https://user:pw@x.kr/'])
    assert.equal(cleanUrl(bad), undefined, String(bad))
  assert.equal(cleanUrl('  https://www.haenam50.kr/index '), 'https://www.haenam50.kr/index')
  assert.equal(cleanUrl('https://a.go.kr/x.do?p=1&amp;q=2'), 'https://a.go.kr/x.do?p=1&q=2')
})

test('apply and homepage links are named for what they are, and the same URL is shown once', () => {
  const same = programLinks({ applyUrl: 'https://www.gangjintour.com/', infoUrl: 'https://www.gangjintour.com/',
    sourceType: 'official_webpage', sourcePages: [{ title: '한국관광공사 대한민국 반값여행 현황', url: TOUR50 }] })
  assert.deepEqual(same.map(l => [l.kind, l.label]), [['apply', '신청 페이지로 이동'], ['source', '한국관광공사 반값여행 현황 보기']])
  const homeOnly = programLinks({ applyUrl: null, infoUrl: 'https://www.haenam50.kr/index', sourceType: 'official_webpage' })
  assert.deepEqual(homeOnly.map(l => l.label), ['지역 반값여행 홈페이지'])
  const gov = programLinks({ applyUrl: '  ', infoUrl: 'https://plus.gov.kr/portal/x?svcId=1', sourceType: 'gov24_api' })
  assert.deepEqual(gov.map(l => l.label), ['정부24 서비스 안내 보기'])
  assert.deepEqual(programLinks({ infoUrl: 'https://notice.example.go.kr/1', sourceType: 'official_notice' }).map(l => l.label), ['공고 보기'])
})

test('news reports and unknown sources never become official links; nothing at all gives an empty list', () => {
  assert.deepEqual(programLinks({ infoUrl: 'https://news.mtn.co.kr/a', sourceType: 'news_report' }), [])
  assert.deepEqual(programLinks({ applyUrl: null, infoUrl: null, sourceType: null, sourcePages: [] }), [])
  assert.deepEqual(programLinks({ sourcePages: [{ title: '', url: TOUR50 }, { title: '현황', url: 'bad' }] }), [])
  assert.equal(sourcePageLabel('   '), null)
})

test('programs fill the existing card fields only with collected text', () => {
  const [b] = benefitsFromPrograms([row()])
  assert.equal(b.payment_rule, '강진사랑상품권')
  assert.equal(b.conditions, '지정관광지 2개소 방문')
  assert.equal(b.contact, '061-433-3349')
  const [empty] = benefitsFromPrograms([row({ payment_methods: null, contacts: ['  '], notes: '   ', source_pages: undefined })])
  assert.deepEqual([empty.payment_rule, empty.conditions, empty.contact, empty.source_pages], ['', '', '', []])
  // A card with no optional details still exists (status/period stay), it just has no extra rows.
  assert.equal(empty.source_status, '신청접수중')
  assert.equal(empty.period_note, '여행 인정 기간 2026-10-20 ~ 2026-11-30')
})

test('the featured program for a destination prefers 반값여행 rounds over public services', () => {
  const rows = benefitsFromPrograms([
    row({ program_id: 'gov24:1', name: '기초생활수급자 수학여행비', sigungu_names: ['영광군'], data_origin: 'gov24_api', source_type: 'gov24_api', open_now: null, posted_status: null }),
    row({ program_id: 'kto50:12830-2026-7', name: '영광 7차', sigungu_names: ['영광군'], posted_status: 'closed', open_now: false }),
    row({ program_id: 'kto50:x', name: '무안 반값', sigungu_names: ['무안군'], superseded_by: ['kto50:y'] }),
  ])
  assert.equal(pickRegionBenefit(rows, '영광군').name, '영광 7차')
  assert.equal(pickRegionBenefit(rows, '무안군'), undefined)      // superseded rows are not featured
  assert.equal(pickRegionBenefit(rows, undefined), undefined)
  assert.equal(programKind(rows[0]), '공공서비스')
  assert.equal(programKind({ data_origin: 'manual_registry' }), '여행 지원제도 · 보도 기준')
  assert.equal(programKind({}), '지역사랑 휴가지원')
})
