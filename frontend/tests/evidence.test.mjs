import test from 'node:test'
import assert from 'node:assert/strict'
import { fileIssue, fingerprint, MAX_FILE_BYTES, MAX_TOTAL_BYTES, evidenceSummary, parseAmount, buildEvidenceDocument } from '../src/lib/evidence.ts'

const file = { name:'receipt.png', type:'image/png', size:1024, lastModified:123 }
const item = { id:'1', fingerprint:fingerprint(file), name:file.name, size:file.size,
  dataUrl:'data:image/png;base64,aGVsbG8=', kind:'receipt', place:'식당', date:'2026-11-06', amount:'12500', memo:'' }
const context = { region:'강진군', date:'2026-11-06', endDate:'2026-11-07', people:2 }

test('upload rejects unsupported, empty, oversized, duplicate, count and total limits',()=>{
  assert.equal(fileIssue(file,[]),null)
  for (const invalid of [{...file,type:'image/svg+xml'},{...file,type:'application/pdf'},{...file,size:0},{...file,size:MAX_FILE_BYTES+1}]) assert.ok(fileIssue(invalid,[]))
  assert.match(fileIssue(file,[item]),/이미 추가/)
  assert.match(fileIssue(file,Array.from({length:12},(_,i)=>({...item,fingerprint:String(i)}))),/12개/)
  assert.match(fileIssue(file,[{fingerprint:'other',size:MAX_TOTAL_BYTES}]),/32MB/)
  assert.equal(fileIssue({...file,size:MAX_FILE_BYTES},[]),null)
})
test('only valid manually entered expense amounts contribute; photos never contribute',()=>{
  const summary = evidenceSummary([item,{...item,kind:'visit',amount:'9999'},{...item,kind:'stay',amount:'80000'},{...item,amount:''},{...item,amount:'-100'}])
  assert.deepEqual(summary,{total:92500,entered:2,missing:2,invalid:1})
  for (const invalid of ['', '-1', '1,000', '1.5', '1e5', 'Infinity', '1000000000', '<b>']) assert.equal(parseAmount(invalid),null)
  assert.equal(parseAmount('0'),0)
})
test('export embeds images and metadata, escapes user content, and blocks non-image sources',()=>{
  const output=buildEvidenceDocument({...context,region:'<script>alert(1)</script>'},[{...item,name:'" onerror="alert(1)',place:'<img src=x onerror=alert(1)>',memo:'A & B',dataUrl:'javascript:alert(1)'},item])
  assert.ok(output.includes('data:image/png;base64,aGVsbG8='))
  assert.ok(output.includes('&lt;script&gt;'))
  assert.ok(output.includes('&lt;img src=x onerror=alert(1)&gt;'))
  assert.ok(output.includes('&quot; onerror=&quot;alert(1)'))
  assert.ok(output.includes('A &amp; B'))
  assert.ok(!output.includes('javascript:'))
  assert.ok(!output.includes('<script>'))
  assert.ok(output.includes('공식 신청서가 아니며'))
  assert.ok(output.includes('25,000원'))
})
test('missing fields stay explicitly missing in exported packet',()=>{
  const output=buildEvidenceDocument(context,[{...item,place:'',date:'',amount:''}])
  assert.ok(output.includes('장소 미입력'))
  assert.ok(output.includes('날짜 미입력'))
  assert.ok(output.includes('금액 미입력 1건'))
})
