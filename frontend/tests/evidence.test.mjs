import test from 'node:test'
import assert from 'node:assert/strict'
import { fileIssue, fingerprint, MAX_FILE_BYTES, MAX_TOTAL_BYTES, evidenceSummary, parseAmount, buildEvidenceDocument } from '../src/lib/evidence.ts'

const file = { name:'receipt.png', type:'image/png', size:1024, lastModified:123 }
const item = { id:'1', fingerprint:fingerprint(file), name:file.name, size:file.size,
  dataUrl:'data:image/png;base64,aGVsbG8=', kind:'receipt', place:'식당', date:'2026-11-06', amount:'12500', memo:'' }
const context = { region:'강진군', date:'2026-11-06', endDate:'2026-11-07', people:2 }

test('upload rejects unsupported, empty, oversized, duplicate, count and total limits',()=>{
  assert.equal(fileIssue(file,[]),null)
  for (const invalid of [{...file,name:'a.svg',type:'image/svg+xml'},{...file,name:'a.heic',type:'image/heic'},{...file,size:0},{...file,size:MAX_FILE_BYTES+1}]) assert.ok(fileIssue(invalid,[]))
  assert.match(fileIssue(file,[item]),/이미 추가/)
  assert.match(fileIssue(file,Array.from({length:12},(_,i)=>({...item,fingerprint:String(i)}))),/12개/)
  assert.match(fileIssue(file,[{fingerprint:'other',size:MAX_TOTAL_BYTES}]),/60MB/)
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

test('evidence ids work without crypto.randomUUID (http team server)',async()=>{
  const { newId } = await import('../src/lib/evidence.ts')
  const insecure={getRandomValues:array=>{array.fill(171);return array}}
  assert.equal(newId(insecure),'ab'.repeat(16))
  assert.equal(newId({getRandomValues:()=>{throw new Error('unused')},randomUUID:()=>'uuid'}),'uuid')
})

test('formats come from type or extension, and the real bytes decide',async()=>{
  const { claimedFormat, sniffFormat, withMime, isPdf } = await import('../src/lib/evidence.ts')
  assert.equal(claimedFormat({name:'IMG_0001.JPG',type:''}),'jpeg')
  assert.equal(claimedFormat({name:'photo',type:'image/jpg'}),'jpeg')
  assert.equal(claimedFormat({name:'영수증.PDF',type:''}),'pdf')
  assert.equal(claimedFormat({name:'a.png',type:'image/png'}),'png')
  assert.equal(claimedFormat({name:'a.heic',type:'image/heic'}),null)
  assert.equal(fileIssue({...file,name:'IMG.JPG',type:''},[]),null)
  assert.equal(fileIssue({...file,name:'r.pdf',type:'application/pdf'},[]),null)
  assert.equal(sniffFormat(new Uint8Array([0xff,0xd8,0xff,0xe0])),'jpeg')
  assert.equal(sniffFormat(new Uint8Array([0x89,0x50,0x4e,0x47,0x0d,0x0a,0x1a,0x0a])),'png')
  assert.equal(sniffFormat(new TextEncoder().encode('%PDF-1.7')),'pdf')
  assert.equal(sniffFormat(new TextEncoder().encode('RIFF\0\0\0\0WEBP')),'webp')
  assert.equal(sniffFormat(new TextEncoder().encode('<svg')),null)
  assert.equal(withMime('data:application/octet-stream;base64,AAAA','jpeg'),'data:image/jpeg;base64,AAAA')
  assert.equal(withMime('data:;base64,AAAA','pdf'),'data:application/pdf;base64,AAAA')
  assert.ok(isPdf({dataUrl:'data:application/pdf;base64,AAAA'}))
})
test('PDF evidence exports as a download link, not an image',()=>{
  const output=buildEvidenceDocument(context,[{...item,name:'숙박.pdf',dataUrl:'data:application/pdf;base64,JVBERi0='}])
  assert.ok(output.includes('href="data:application/pdf;base64,JVBERi0=" download="숙박.pdf"'))
  assert.ok(!output.includes('<img src=""'))
})
