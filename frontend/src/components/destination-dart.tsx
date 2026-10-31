import { useEffect, useRef, useState, type PointerEvent, type KeyboardEvent } from 'react'
import { ArrowRight, ChevronDown, Compass, MapPin, RotateCcw, Sparkles, ExternalLink } from 'lucide-react'
import map from '@/datasets/korea-map.json'
import { mapPoint, clampPull, randomLanding, nearestDestination, flightPoint, SLING, MIN_PULL, type Point, type Destination } from '@/lib/destination'
import { isOpen, isStale, type Benefit } from '@/lib/benefits'
import { regionDirectionsUrl } from '@/lib/directions'
import { DirectionsLink } from '@/components/directions-link'
import slingshotImage from '@/assets/slingshot-front.png'
import './destination-dart.css'

const palette = ['#719568', '#93ad7c', '#b1bb8d', '#819e73', '#a2b581', '#88a57c']
const anchors = map.regions.map(region => ({ ...region, ...mapPoint(region) }))
const labelOffsets: Record<string, Point> = {강진군:{x:-24,y:-10},장흥군:{x:25,y:-12},해남군:{x:-22,y:20},완도군:{x:0,y:24},영암군:{x:0,y:-16},고흥군:{x:0,y:-16},영광군:{x:0,y:-16}}
// Front-facing sprite: collars sit at 19% / 81% of the square, 15% from its top.
const slingFrame = { x: SLING.x - 77, y: SLING.y - 44, size: 154 }
const slingForks = {
  left: { x: slingFrame.x + slingFrame.size * .19, y: slingFrame.y + slingFrame.size * .15 },
  right: { x: slingFrame.x + slingFrame.size * .81, y: slingFrame.y + slingFrame.size * .15 },
}

function TravelToken() {
  return <g aria-hidden="true">
    <ellipse cy="19" rx="13" ry="3" fill="#a96b48" opacity=".12"/>
    <circle r="18" fill="url(#sling-ball)" stroke="#fffaf0" strokeWidth="2.5"/>
    <path d="M-11 -8Q-7 -13 -1 -13" fill="none" stroke="#ffe6d2" strokeWidth="2.5" strokeLinecap="round"/>
    <path d="M-9 -2L10 -8L4 10L0 3Z" fill="#fffdf5" stroke="#fffdf5" strokeWidth="1.5" strokeLinejoin="round"/>
    <path d="M0 3L5 -3" stroke="#df916d" strokeWidth="1.3" strokeLinecap="round"/>
  </g>
}

export function DestinationDart({ data, loading, error, origin, onRetry, onChoose, onBrowse }: {
  data: Benefit[]; loading: boolean; error: string; origin: string; onRetry: () => void;
  onChoose: (row: Destination) => void; onBrowse: () => void;
}) {
  const [result, setResult] = useState<Destination | null>(null)
  const [flying, setFlying] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [pull, setPull] = useState<Point>({x:0,y:0})
  const [ball, setBall] = useState<Point | null>(null)
  const [landing, setLanding] = useState<Point | null>(null)
  const [message, setMessage] = useState('살구빛 공을 당겨, 오늘의 여행지를 만나보세요.')
  const [directOpen, setDirectOpen] = useState(false)
  const svg = useRef<SVGSVGElement>(null)
  const handle = useRef<SVGGElement>(null)
  const resetFocus = useRef(false)
  const frame = useRef<number | null>(null)
  const pulling = useRef(false)
  const currentPull = useRef<Point>({x:0,y:0})
  const busy = useRef(false)
  const resultHeading = useRef<HTMLHeadingElement>(null)
  const candidates = map.regions
  const activeAnchors = anchors
  const available = candidates.length > 0
  const benefit = data.find(row => row.region_name === result?.region_name && row.present_in_source)
  const destination = anchors.find(region => region.name === result?.region_name)
  const strength = Math.hypot(pull.x,pull.y)
  const aiming = !flying && !result && strength >= MIN_PULL
  const direction = {x:-pull.x/(strength||1),y:-pull.y/(strength||1)}
  const directionLabel = direction.x<-.25?'왼쪽 방향':direction.x>.25?'오른쪽 방향':'앞쪽 방향'
  const pouch = {x:SLING.x + pull.x,y:SLING.y + pull.y}
  const projectile = ball || pouch
  useEffect(() => () => { if (frame.current !== null) cancelAnimationFrame(frame.current) }, [])
  useEffect(() => { if (result) resultHeading.current?.focus({preventScroll:true}); else if(resetFocus.current){handle.current?.focus({preventScroll:true});resetFocus.current=false} }, [result])
  function setAim(next: Point) { const value=clampPull(next); currentPull.current=value; setPull(value) }
  function reset() {
    if (busy.current) return
    resetFocus.current=true; setResult(null); setLanding(null); setBall(null); setAim({x:0,y:0}); setMessage('방향만 골라 다시 당겨보세요. 거리는 랜덤이에요.')
  }
  function release() {
    if (busy.current || !available || result) return
    const held = currentPull.current
    if (Math.hypot(held.x,held.y)<MIN_PULL || held.y<5) { setAim({x:0,y:0}); setMessage('탄환을 아래쪽으로 조금 더 당긴 뒤 놓아주세요.'); return }
    const end = randomLanding(held)
    const closest = nearestDestination(activeAnchors,end)
    const row = candidates.find(item => item.region_name === closest?.name)
    if (!row) return
    const start = {x:SLING.x+held.x,y:SLING.y+held.y}
    busy.current=true; setFlying(true); setDirectOpen(false); setBall(start); setLanding(end); setAim({x:0,y:0}); setMessage('탄환이 날아가고 있어요.')
    const finish=()=>{setBall(end);setResult(row);setFlying(false);busy.current=false;setMessage(`착지 지점 근처의 ${row.region_name}을 골랐어요.`)}
    if(window.matchMedia('(prefers-reduced-motion: reduce)').matches){finish();return}
    const started=performance.now()
    const animate=(now:number)=>{const t=Math.min(1,(now-started)/850);setBall(flightPoint(start,end,t));if(t<1)frame.current=requestAnimationFrame(animate);else finish()}
    frame.current=requestAnimationFrame(animate)
  }
  function point(event: PointerEvent<SVGGElement>) {
    const matrix=svg.current?.getScreenCTM()
    if(!matrix)return {x:SLING.x,y:SLING.y}
    return new DOMPoint(event.clientX,event.clientY).matrixTransform(matrix.inverse())
  }
  function begin(event: PointerEvent<SVGGElement>) {
    if(!available || busy.current || result || (event.pointerType==='mouse' && event.button!==0))return
    event.preventDefault();event.currentTarget.setPointerCapture(event.pointerId);pulling.current=true;setDragging(true);setMessage('당긴 반대 방향으로 출발해요. 얼마나 멀리 갈지는 놓은 뒤에 정해져요.')
  }
  function move(event: PointerEvent<SVGGElement>) {
    if(!pulling.current)return
    event.preventDefault();const p=point(event);setAim({x:p.x-SLING.x,y:p.y-SLING.y})
  }
  function end(event: PointerEvent<SVGGElement>) {
    if(!pulling.current)return
    event.preventDefault();const p=point(event);setAim({x:p.x-SLING.x,y:p.y-SLING.y});pulling.current=false;setDragging(false);event.currentTarget.releasePointerCapture(event.pointerId);release()
  }
  function cancel() { if(pulling.current){pulling.current=false;setDragging(false);setAim({x:0,y:0});setMessage('조준을 취소했어요. 다시 당길 수 있어요.')} }
  function keyboard(event: KeyboardEvent<SVGGElement>) {
    if(!available || busy.current || result)return
    const delta:Record<string,Point>={ArrowLeft:{x:-8,y:0},ArrowRight:{x:8,y:0},ArrowUp:{x:0,y:-8},ArrowDown:{x:0,y:8}}
    if(delta[event.key]){event.preventDefault();setAim({x:currentPull.current.x+delta[event.key].x,y:currentPull.current.y+delta[event.key].y})}
    if(event.key==='Enter'||event.key===' '){event.preventDefault();release()}
    if(event.key==='Escape'){event.preventDefault();setAim({x:0,y:0})}
  }
  function select(row: Destination) { if(busy.current)return;setResult(row);setBall(null);setLanding(null);setDirectOpen(false);setAim({x:0,y:0});setMessage(`${row.region_name}을 직접 선택했어요.`) }
  return <section className="dart-experience sling-experience" aria-labelledby="dart-title">
    <h1 id="dart-title" className="sr-only">광주·전남 여행지도</h1>
    <div className="map-region-summary"><Compass size={15}/><span>광주 · 전남</span><small>27개 여행지</small></div>
    <div className="dart-controls">
      <div className="dart-secondary-actions"><button disabled={!available||flying} aria-expanded={directOpen} aria-controls="direct-destinations" onClick={()=>setDirectOpen(value=>!value)}><MapPin size={16}/> 지역 선택 <ChevronDown size={14}/></button><button onClick={onBrowse}>혜택 목록 <ArrowRight size={15}/></button></div>
      {directOpen && <div id="direct-destinations" className="dart-direct-list" aria-label="직접 여행지 선택">{['광주','전라남도'].map(province=><div className="destination-group" key={province}><h2>{province} <span>{province==='광주'?'5개 구':'22개 시군'}</span></h2><div>{candidates.filter(row=>row.province===province).map(row=><button key={row.id} onClick={()=>select(row)}>{row.region_name.replace('광주 ','')}<ArrowRight size={13}/></button>)}</div></div>)}</div>}
      {error&&<div className="dart-error" role="status"><p>여행지는 모두 선택할 수 있어요.</p><button onClick={onRetry}>혜택 다시 불러오기</button></div>}
    </div>
    <div className={`dart-stage sling-stage ${dragging?'is-aiming':''} ${flying?'is-flying':''} ${result?'has-result':''}`}>
      <div className="map-compass" aria-hidden="true">N<span>✦</span></div>
      <svg ref={svg} className="destination-map sling-map" viewBox="0 0 520 650" role="group" aria-label="광주 전남 여행지도와 직접 당기는 새총">
        <defs><radialGradient id="sling-ball" cx=".3" cy=".2" r=".85"><stop stopColor="#ffc9a5"/><stop offset=".65" stopColor="#f39c76"/><stop offset="1" stopColor="#dc805d"/></radialGradient></defs>

        <g transform="translate(-300 -1070) scale(3)" aria-hidden="true">{map.provinces.map(province=><path key={province.name} d={province.path} fill={province.name==='Gwangju'?'#a6b57c':'#7e9e73'} stroke="#f7f5ed" strokeWidth=".5"/>)}{map.counties.map((county,i)=><path key={`${county.name}-${i}`} className={destination?.shape===county.name?'county selected-county':'county'} d={county.path} fill={palette[i%palette.length]} fillOpacity="1" stroke="#fffdf3" strokeWidth="1.2" vectorEffect="non-scaling-stroke"/>)}</g>
        <text className="gwangju-label" x="262" y="113" textAnchor="middle">광주</text><text className="sea-label" x="45" y="325">서 해</text><text className="sea-label" x="398" y="469">남 해</text>
        {anchors.map(region=>{const offset=labelOffsets[region.name] || {x:0,y:-15};return <g key={region.name} transform={`translate(${region.x},${region.y})`} className={`sling-destination ${region.province==='전라남도'?'labeled-destination':''} ${result?.region_name===region.name?'picked':''}`} role="button" tabIndex={flying?-1:0} aria-label={`${region.name} 선택`} onClick={()=>select(region)} onKeyDown={event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();select(region)}}}><circle className="region-pin-halo" r="12"/><circle r="5.5" fill={result?.region_name===region.name?'#c76437':'#fff8e8'} stroke="#466a43" strokeWidth="2"/><text x={offset.x} y={offset.y} textAnchor="middle">{region.name}</text>{result?.region_name===region.name&&<circle className="landing-ring" r="20"/>}</g>})}
        {aiming && <g className="sling-aim" aria-hidden="true" transform={`translate(${SLING.x},${SLING.y-10}) rotate(${Math.atan2(direction.y,direction.x)*180/Math.PI+90})`}><path d="M0 -32V-76M-6 -68L0 -76L6 -68" fill="none" stroke="#bc7850" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" opacity=".8"/></g>}

        {result && landing && destination && <path d={`M${landing.x} ${landing.y}L${destination.x} ${destination.y}`} stroke="#b97851" strokeWidth="1.5" strokeDasharray="3 5" opacity=".8"/>}
        <g className="slingshot-art" aria-hidden="true">
          <ellipse cx={SLING.x} cy="615" rx="31" ry="5" fill="#9a8060" opacity=".14"/>
          <image href={slingshotImage} x={slingFrame.x} y={slingFrame.y} width={slingFrame.size} height={slingFrame.size}/>
          <path d={`M${slingForks.left.x} ${slingForks.left.y}L${pouch.x} ${pouch.y}L${slingForks.right.x} ${slingForks.right.y}`} fill="none" stroke="#b78332" strokeWidth={aiming?5:7} strokeLinecap="round" strokeLinejoin="round"/>
          <path d={`M${slingForks.left.x} ${slingForks.left.y-1}L${pouch.x} ${pouch.y-1}L${slingForks.right.x} ${slingForks.right.y-1}`} fill="none" stroke="#ffe09a" strokeWidth={aiming?2:3} strokeLinecap="round" strokeLinejoin="round"/>
          <rect x={pouch.x-18} y={pouch.y-7} width="36" height="19" rx="8" fill="#946035" stroke="#d29a59" strokeWidth="2"/>
        </g>
        {(flying||result) && ball && <g transform={`translate(${projectile.x},${projectile.y}) scale(.8)`} aria-hidden="true"><TravelToken/>{result&&<circle r="28" fill="none" stroke="#bc7951" opacity=".6" strokeDasharray="3 5"/>}</g>}
        {!flying&&!result&&<g ref={handle} className="sling-projectile" transform={`translate(${pouch.x},${pouch.y})`} role="button" tabIndex={available?0:-1} aria-disabled={!available} aria-label="새총 탄환: 아래로 당겨서 놓으세요. 키보드는 방향키로 당기고 Enter로 발사" onPointerDown={begin} onPointerMove={move} onPointerUp={end} onPointerCancel={cancel} onLostPointerCapture={cancel} onKeyDown={keyboard}><circle className="sling-touch-area" r="42" fill="transparent"/><circle className="sling-grab-ring" r="26" fill="#f5b48c18" stroke="#df9f7770" strokeWidth="1.5"/><TravelToken/></g>}
        {!dragging&&!flying&&!result&&!aiming&&<g className="pull-hint" aria-hidden="true"><path d="M330 530v39m-5-5l5 5 5-5" fill="none" stroke="#8b9275" strokeWidth="1.5" strokeDasharray="3 3"/><text x="345" y="550">당겨요</text></g>}
      </svg>
      <div className="sling-status" role="status" aria-live="polite">{aiming?<><span>{directionLabel}</span><span>거리는 랜덤 · 손을 놓으면 출발!</span></>:<span>{message}</span>}</div>
      {result&&<div className="dart-result sling-result"><div className="result-stamp"><Sparkles size={15}/>{landing?'내가 쏜 곳에서 시작하는 여행':'직접 고른 여행지'}</div><div className="dart-result-title"><div><span>{result.province} · {landing?'착지 지점 근처':'여행 목적지'}</span><h2 tabIndex={-1} ref={resultHeading}>{result.region_name}</h2></div><span className="destination-seal"><MapPin size={24}/></span></div><p>{loading?'혜택 정보를 확인하고 있어요.':error?'혜택 연결이 지연 중이에요. 축제는 따로 살펴볼 수 있어요.':!benefit?'지역 축제를 살펴보세요. 연결된 환급 혜택은 아직 없어요.':isStale(benefit)?'혜택 접수 상태를 다시 확인해 주세요.':isOpen(benefit)?'공식 안내에 접수중으로 표시된 여행 혜택이 있어요.':`수집된 혜택 상태: ${benefit.source_status||'확인 필요'}`}</p><button className="dart-result-cta" onClick={()=>onChoose(result)}>이 지역 일정 추천받기 <ArrowRight size={18}/></button>{!loading&&!benefit&&<DirectionsLink url={regionDirectionsUrl(origin,result.region_name)}>혜택 없이 바로 길찾기</DirectionsLink>}<button className="sling-result-reset" onClick={reset}><RotateCcw size={14}/> 다시 당겨볼래요</button></div>}
    </div>
    <div className="dart-footer"><a href="https://www.geoboundaries.org/" target="_blank" rel="noopener noreferrer">지도: geoBoundaries · 가공한 여행 약도 <ExternalLink size={10}/></a></div>
  </section>
}
