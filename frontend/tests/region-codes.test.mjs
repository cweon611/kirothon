import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { SIGUNGU, sigunguCode } from '../src/lib/course.ts'

const destinations = JSON.parse(readFileSync(new URL('../src/datasets/destinations.json', import.meta.url), 'utf8'))
const map = JSON.parse(readFileSync(new URL('../src/datasets/korea-map.json', import.meta.url), 'utf8'))
// Backend seed is a Python module (seeds/regions.py) with one {"code", "name", "sido"} row per line.
const seedText = readFileSync(new URL('../../backend/app/team/seeds/regions.py', import.meta.url), 'utf8')
const seed = [...seedText.matchAll(/\{"code": "(\d{5})", "name": "([^"]+)", "sido": "([^"]+)"\}/g)]
  .map(([, code, name, sido]) => ({ code, name, sido }))

// The festival lookup sends the slingshot destination as sigungu_code; it must be the backend code for that name.
test('every slingshot destination has the backend sigungu code with the same name',()=>{
  assert.equal(seed.length, 27)
  const backend = Object.fromEntries(seed.map(s => [s.code, s.sido === '광주광역시' ? `광주 ${s.name}` : s.name]))
  for (const row of [...destinations, ...map.regions]) {
    const code = sigunguCode(row.region_name)
    assert.ok(code, `no code for ${row.region_name}`)
    assert.equal(backend[code], row.region_name)
  }
  assert.equal(Object.keys(SIGUNGU).length, 27)
  assert.equal(sigunguCode('그 외 지역'), null)
})
