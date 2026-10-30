import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { REGION_CODES, regionCode } from '../src/lib/region-codes.ts'

const destinations = JSON.parse(readFileSync(new URL('../src/data/destinations.json', import.meta.url), 'utf8'))
const map = JSON.parse(readFileSync(new URL('../src/data/korea-map.json', import.meta.url), 'utf8'))
const seed = JSON.parse(readFileSync(new URL('../../backend/app/team/seeds/regions.json', import.meta.url), 'utf8'))

test('every slingshot destination has the backend sigungu code with the same name',()=>{
  const backend = Object.fromEntries(seed.sigungu.map(s => [s.code, s.sido === '광주광역시' ? `광주 ${s.name}` : s.name]))
  for (const row of [...destinations, ...map.regions]) {
    const code = regionCode(row.region_name)
    assert.ok(code, `no code for ${row.region_name}`)
    assert.equal(backend[code], row.region_name)
  }
  assert.equal(Object.keys(REGION_CODES).length, 27)
  assert.equal(regionCode('그 외 지역'), null)
})
