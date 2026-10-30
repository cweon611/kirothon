import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { destinationNames, mapPoint, clampPull, randomLanding, nearestDestination, flightPoint, SLING, MAX_PULL, MIN_PULL } from '../src/lib/destination.ts'
const map=JSON.parse(readFileSync(new URL('../src/datasets/korea-map.json',import.meta.url),'utf8'))
const anchors=map.regions.map(region=>({...region,...mapPoint(region)}))
function seeded(angle,distance){let i=0;return ()=>i++===0?angle:distance}
test('direction is player controlled while pull length does not set distance',()=>{
 assert.ok(randomLanding({x:25,y:30},()=>.5).x<SLING.x)
 assert.ok(randomLanding({x:-25,y:30},()=>.5).x>SLING.x)
 assert.deepEqual(randomLanding({x:10,y:20},()=>.5),randomLanding({x:30,y:60},()=>.5))
 assert.ok(Math.hypot(...Object.values(clampPull({x:1000,y:1000})))<=MAX_PULL+.00001)
 assert.equal(clampPull({x:0,y:-20}).y,0)
})
test('same direction can produce different distances and destinations',()=>{
 const close=randomLanding({x:20,y:40},seeded(.5,0))
 const far=randomLanding({x:20,y:40},seeded(.5,1))
 assert.notDeepEqual(close,far)
 assert.notEqual(nearestDestination(anchors,close)?.name,nearestDestination(anchors,far)?.name)
 const left=randomLanding({x:0,y:40},seeded(0,.5))
 const right=randomLanding({x:0,y:40},seeded(1,.5))
 assert.ok(left.x<SLING.x&&right.x>SLING.x)
})
test('all 27 destinations remain reachable with direction and random distance',()=>{
 for(const region of anchors){
  const dx=SLING.x-region.x,dy=SLING.y-region.y
  const pull=clampPull({x:dx/5.2,y:dy/5.2})
  assert.ok(Math.hypot(pull.x,pull.y)>=MIN_PULL)
  const distance=Math.max(0,Math.min(1,(Math.hypot(dx,dy)-100)/370))
  assert.equal(nearestDestination(anchors,randomLanding(pull,seeded(.5,distance)))?.name,region.name)
 }
 assert.equal(nearestDestination([],SLING),undefined)
})
test('flight starts at the pulled pouch and ends exactly at predicted landing',()=>{
 const from={x:280,y:560},to={x:130,y:250}
 assert.deepEqual(flightPoint(from,to,0),from)
 assert.deepEqual(flightPoint(from,to,1),to)
 assert.ok(flightPoint(from,to,.5).y<(from.y+to.y)/2)
})
test('map contains only Gwangju and Jeonnam and all 27 selectable anchors',()=>{
 assert.deepEqual(map.provinces.map(p=>p.name).sort(),['Gwangju','South Jeolla'])
 assert.deepEqual(map.regions.map(r=>r.name).sort(),[...destinationNames].sort())
 for(const region of anchors)assert.ok(region.x>0&&region.x<520&&region.y>0&&region.y<510)
})


test('all 5 Gwangju districts and 22 Jeonnam cities/counties are independent destinations',()=>{
 assert.equal(map.regions.length,27)
 assert.equal(new Set(map.regions.map(r=>r.id)).size,27)
 assert.equal(map.regions.filter(r=>r.province==='광주').length,5)
 assert.equal(map.regions.filter(r=>r.province==='전라남도').length,22)
 assert.ok(map.counties.some(r=>r.name==='Gwangsan-gu'))
})
