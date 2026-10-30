import test from 'node:test'
import assert from 'node:assert/strict'
import { applyMeta, sigunguCode, originKey, ORIGINS, INTERESTS } from '../src/lib/course.ts'
import { directionsUrl } from '../src/lib/directions.ts'

test('meta codes replace the bundled ones; unknown labels never add regions',()=>{
  assert.equal(applyMeta({trip_regions:[{sido:'광주광역시',sigungu:[{code:'29170',name:'북구'}]}]}),false)
  assert.equal(applyMeta({trip_regions:[{sido:'전라남도',sigungu:[{code:'46999',name:'곡성군'},{code:'47000',name:'없는군'}]}]}),true)
  assert.equal(sigunguCode('곡성군'),'46999')
  assert.equal(sigunguCode('없는군'),null)
})
test('meta origins and interests replace the lists; known origins keep their coordinates',()=>{
  applyMeta({origins:[{key:'gj-buk',name:'광주 북구'},{key:'new-st',name:'새 역'}],interests:[{key:'nature',label:'자연'}]})
  assert.deepEqual(ORIGINS.map(row=>row.key),['gj-buk','new-st'])
  assert.equal(typeof ORIGINS[0].lat,'number')
  assert.equal(originKey('새 역'),'new-st'); assert.equal(originKey('목포역'),null)
  assert.deepEqual(INTERESTS,[{key:'nature',label:'자연'}])
  // An origin without coordinates links to the destination only (Kakao Map uses the current location).
  assert.match(directionsUrl('새 역',{name:'곡성군청',lat:35.28,lng:127.29}),/^https:\/\/map\.kakao\.com\/link\/to\//)
})
