import test from 'node:test'
import assert from 'node:assert/strict'
import { inPeriod, isOpen, safeUrl, addDays } from '../src/lib/benefits.ts'

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
