import test from 'node:test'
import assert from 'node:assert/strict'
import { festivalState, festivalStale, rankFestivals } from '../src/lib/festivals.ts'
const row={id:'one',region_name:'장흥군',title:'축제',start_date:'2026-11-07',end_date:'2026-11-08',source_status:'진행전',collected_at:'2026-10-30T12:00:00Z'}
test('trip overlap includes both ends and single-day festivals',()=>{
 assert.equal(festivalState(row,'2026-11-08','2026-11-09','2026-10-30'),'match')
 assert.equal(festivalState({...row,end_date:row.start_date},'2026-11-06','2026-11-07','2026-10-30'),'match')
 assert.equal(festivalState(row,'2026-11-09','2026-11-10','2026-10-30'),'other')
})
test('ended, cancelled, unknown and stale events never masquerade as upcoming matches',()=>{
 assert.equal(festivalState(row,'2026-11-07','2026-11-08','2026-11-09'),'ended')
 assert.equal(festivalState({...row,source_status:'취소'},'2026-11-07','2026-11-08','2026-10-30'),'unconfirmed')
 assert.equal(festivalState({...row,start_date:null},'2026-11-07','2026-11-08','2026-10-30'),'unknown')
 assert.equal(festivalStale(row,Date.parse('2026-11-07')),true)
 assert.equal(festivalStale(row,Date.parse('2026-10-31')),false)
})
test('rank is scoped to selected destination and prioritizes the travel dates',()=>{
 const past={...row,id:'past',end_date:'2026-10-01',start_date:'2026-10-01'}
 const other={...row,id:'other',start_date:'2026-11-20',end_date:'2026-11-20'}
 const elsewhere={...row,id:'elsewhere',region_name:'순천시'}
 assert.deepEqual(rankFestivals([past,other,elsewhere,row],'장흥군','2026-11-07','2026-11-08','2026-10-30').map(r=>r.id),['one','other','past'])
 assert.deepEqual(rankFestivals([row],'광주 북구','2026-11-07','2026-11-08','2026-10-30'),[])
})
