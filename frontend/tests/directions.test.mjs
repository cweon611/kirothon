import test from 'node:test'
import assert from 'node:assert/strict'
import destinations from '../src/datasets/destinations.json' with { type: 'json' }
import { REGION_OFFICES, directionsUrl, regionDirectionsUrl } from '../src/lib/directions.ts'

test('every destination on the map has a directions end point',()=>{
  for (const row of destinations) assert.ok(REGION_OFFICES[row.region_name], row.region_name)
})
test('known origin builds a Kakao from/to link with coordinates',()=>{
  const url=regionDirectionsUrl('광주 북구','무안군')
  assert.equal(url,`https://map.kakao.com/link/from/${encodeURIComponent('광주 북구')},35.174,126.912/to/${encodeURIComponent('무안군청')},34.99045,126.48166`)
})
test('unknown origin falls back to directions from the current location',()=>{
  assert.ok(regionDirectionsUrl('모르는 곳','신안군').startsWith('https://map.kakao.com/link/to/'))
  assert.equal(regionDirectionsUrl('광주 북구','그 외 지역'),null)
})
test('commas and slashes in place names cannot break the link',()=>{
  const url=directionsUrl('광주 북구',{name:'A,B/C',lat:35,lng:126})
  assert.ok(url.endsWith(`/to/${encodeURIComponent('A B C')},35,126`))
})
