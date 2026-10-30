import { useEffect, useRef, useState, type PointerEvent, type KeyboardEvent } from 'react'
import { ArrowRight, ChevronDown, Compass, MapPin, RotateCcw, Sparkles, ExternalLink, MoveDown } from 'lucide-react'
import map from '@/data/korea-map.json'
import { mapPoint, clampPull, randomLanding, nearestDestination, flightPoint, SLING, MIN_PULL, type Point, type Destination } from '@/lib/destination'
import { isOpen, isStale, type Benefit } from '@/lib/benefits'
import './destination-dart.css'

const palette = ['#82b3aa', '#9caac9', '#c9b68c', '#aabda0', '#c69ca8', '#a0b5c5']
const anchors = map.regions.map(region => ({ ...region, ...mapPoint(region) }))
const labelOffsets: Record<string, Point> = {강진군:{x:-24,y:-10},장흥군:{x:25,y:-12},해남군:{x:-22,y:20},완도군:{x:0,y:24},영암군:{x:0,y:-16},고흥군:{x:0,y:-16},영광군:{x:0,y:-16}}

export function DestinationDart({ data, loading, error, onRetry, onChoose, onBrowse }: {
  data: Benefit[]; loading: boolean; error: string; onRetry: () => void;
  onChoose: (row: Destination) => void; onBrowse: () => void;
}) {
  const [result, setResult] = useState<Destination | null>(null)
  const [flying, setFlying] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [pull, setPull] = useState<Point>({x:0,y:0})
  const [ball, setBall] = useState<Point | null>(null)
  const [landing, setLanding] = useState<Point | null>(null)
  const [message, setMessage] = useState('노란 탄환을 아래로 당겼다가 놓아보세요.')
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
    <div className="dart-copy"><span className="dart-eyebrow"><span/> 방향은 내가, 도착은 뜻밖으로</span><h1 id="dart-title">이번 여행은,<br/><em>당겨서 떠나요.</em></h1><p className="dart-description">새총을 당기고, 손을 놓으면.<br/>어디까지 날아갈지는, 작은 우연에 맡겨요.</p><div className="dart-instructions"><span>01 당기고</span><i/><span>02 놓으면</span><i/><span>03 여행 시작</span></div>
      <div className="dart-controls"><div className="sling-guide"><span className="sling-guide-icon"><MoveDown size={25}/></span><div><strong>{flying?'어디에 도착할까요?':result?'이번 여행지는 정해졌어요':'지도 아래 노란 탄환을 당겨보세요'}</strong><small>방향만 골라요 · 날아가는 거리는 랜덤</small></div></div>{result && <button className="sling-reset" onClick={reset}><RotateCcw size={17}/> 다시 당기기</button>}<div className="dart-secondary-actions"><button disabled={!available||flying} aria-expanded={directOpen} aria-controls="direct-destinations" onClick={()=>setDirectOpen(value=>!value)}><MapPin size={15}/> 직접 고를래요 <ChevronDown size={14}/></button><button onClick={onBrowse}>혜택 목록 보기 <ArrowRight size={14}/></button></div>{directOpen && <div id="direct-destinations" className="dart-direct-list" aria-label="직접 여행지 선택">{['광주','전라남도'].map(province=><div className="destination-group" key={province}><h2>{province} <span>{province==='광주'?'5개 구':'22개 시군'}</span></h2><div>{candidates.filter(row=>row.province===province).map(row=><button key={row.id} onClick={()=>select(row)}>{row.region_name.replace('광주 ','')}<ArrowRight size={13}/></button>)}</div></div>)}</div>}
        <p className="dart-scope"><Compass size={14}/>광주 5개 구 · 전남 22개 시군 전체<br/><span>착지한 곳에서 가장 가까운 여행지를 골라요.</span></p>{error&&<div className="dart-error" role="status"><p>혜택 연결이 지연 중이에요. 여행지는 모두 고를 수 있어요.</p><button onClick={onRetry}>혜택 다시 불러오기</button></div>}

      </div>
    </div>
    <div className={`dart-stage sling-stage ${dragging?'is-aiming':''} ${flying?'is-flying':''} ${result?'has-result':''}`}>
      <div className="map-toolbar"><span><span className="map-live-dot"/> TRAVEL SLING</span><span>광주 <i> & </i> 전남</span></div><div className="map-compass" aria-hidden="true">N<span>✦</span></div>
      <svg ref={svg} className="destination-map sling-map" viewBox="0 0 520 650" role="group" aria-label="광주 전남 여행지도와 직접 당기는 새총">
        <defs><radialGradient id="map-ocean"><stop stopColor="#244e66"/><stop offset="1" stopColor="#132e45"/></radialGradient><pattern id="map-grid" width="48" height="48" patternUnits="userSpaceOnUse"><path d="M48 0H0V48" fill="none" stroke="#aecacb" strokeOpacity=".07" strokeWidth=".7"/></pattern><linearGradient id="sling-wood" x1="0" y1="0" x2="1" y2="0"><stop stopColor="#925a34"/><stop offset=".5" stopColor="#d7a46d"/><stop offset="1" stopColor="#b47741"/></linearGradient><radialGradient id="sling-ball" cx=".3" cy=".25"><stop stopColor="#fff0b2"/><stop offset=".6" stopColor="#edbd66"/><stop offset="1" stopColor="#b77b36"/></radialGradient></defs>
        <rect width="520" height="650" fill="url(#map-ocean)"/><rect width="520" height="650" fill="url(#map-grid)"/>
        <g transform="translate(-300 -1070) scale(3)" aria-hidden="true">{map.provinces.map(province=><path key={province.name} d={province.path} fill={province.name==='Gwangju'?'#bd9fb8':'#94b4a4'} stroke="#e1ead8" strokeWidth=".5"/>)}{map.counties.map((county,i)=><path key={`${county.name}-${i}`} className={destination?.shape===county.name?'county selected-county':'county'} d={county.path} fill={palette[i%palette.length]} fillOpacity=".82" stroke="#dfe9dc" strokeWidth=".7" vectorEffect="non-scaling-stroke"/>)}</g>
        <text className="gwangju-label" x="262" y="113" textAnchor="middle">광주</text><text className="sea-label" x="45" y="325">서 해</text><text className="sea-label" x="398" y="469">남 해</text>
        {anchors.map(region=>{const offset=labelOffsets[region.name] || {x:0,y:-15};return <g key={region.name} transform={`translate(${region.x},${region.y})`} className={`sling-destination ${result?.region_name===region.name?'picked':''}`} role="button" tabIndex={flying?-1:0} aria-label={`${region.name} 선택`} onClick={()=>select(region)} onKeyDown={event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();select(region)}}}><circle className="region-pin-halo" r="12"/><circle r="5" fill={result?.region_name===region.name?'#fff1c8':'#efc77f'} stroke="#184255" strokeWidth="2"/><text x={offset.x} y={offset.y} textAnchor="middle">{region.name}</text>{result?.region_name===region.name&&<circle className="landing-ring" r="20"/>}</g>})}
        {aiming && <g className="sling-aim" aria-hidden="true" transform={`translate(${SLING.x},${SLING.y-10}) rotate(${Math.atan2(direction.y,direction.x)*180/Math.PI+90})`}><path d="M0 -32V-76M-6 -68L0 -76L6 -68" fill="none" stroke="#ffe2a5" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" opacity=".8"/></g>}

        {result && landing && destination && <path d={`M${landing.x} ${landing.y}L${destination.x} ${destination.y}`} stroke="#fff0bb" strokeWidth="1.5" strokeDasharray="3 5" opacity=".8"/>}
        <g className="slingshot-art" aria-hidden="true"><ellipse cx="260" cy="618" rx="45" ry="8" fill="#081f31" opacity=".5"/><path d="M260 606L260 551Q236 537 230 493 M260 551Q283 533 290 493" fill="none" stroke="#6f452c" strokeWidth="21" strokeLinecap="round" strokeLinejoin="round"/><path d="M260 606L260 551Q236 537 230 493 M260 551Q283 533 290 493" fill="none" stroke="url(#sling-wood)" strokeWidth="16" strokeLinecap="round" strokeLinejoin="round"/><path d="M252 578H268M252 586H268M252 594H268" stroke="#795032" strokeWidth="3"/><path d={`M230 496L${pouch.x} ${pouch.y}L290 496`} fill="none" stroke="#392f38" strokeWidth={dragging?5:7} strokeLinecap="round"/><path d={`M230 493L${pouch.x} ${pouch.y-3}L290 493`} fill="none" stroke="#d39c72" strokeWidth="3" strokeLinecap="round"/></g>
        {(flying||result) && ball && <g transform={`translate(${projectile.x},${projectile.y})`} aria-hidden="true"><ellipse cy="13" rx="12" ry="4" fill="#071e35" opacity=".3"/><circle r="12" fill="url(#sling-ball)" stroke="#fff0ba" strokeWidth="1.5"/>{result&&<circle r="22" fill="none" stroke="#ffe7b5" opacity=".6" strokeDasharray="3 5"/>}</g>}
        {!flying&&!result&&<g ref={handle} className="sling-projectile" transform={`translate(${pouch.x},${pouch.y})`} role="button" tabIndex={available?0:-1} aria-disabled={!available} aria-label="새총 탄환: 아래로 당겨서 놓으세요. 키보드는 방향키로 당기고 Enter로 발사" onPointerDown={begin} onPointerMove={move} onPointerUp={end} onPointerCancel={cancel} onLostPointerCapture={cancel} onKeyDown={keyboard}><circle className="sling-touch-area" r="42" fill="transparent"/><circle className="sling-grab-ring" r="25" fill="#f3c47715" stroke="#f3c477" strokeDasharray="3 5"/><circle r="16" fill="url(#sling-ball)" stroke="#fff0ba" strokeWidth="2"/><path d="M-5 -4L0 1L5 -4" fill="none" stroke="#8a6637" strokeWidth="2"/></g>}
        {!dragging&&!flying&&!result&&!aiming&&<g className="pull-hint" aria-hidden="true"><path d="M315 530v39m-5-5l5 5 5-5" fill="none" stroke="#d9c293" strokeWidth="1.5" strokeDasharray="3 3"/><text x="330" y="550">당겨요</text></g>}
      </svg>
      <div className="sling-status" role="status" aria-live="polite">{aiming?<><span>{directionLabel}</span><span>거리는 랜덤 · 손을 놓으면 출발!</span></>:<span>{message}</span>}</div>
      {result&&<div className="dart-result sling-result"><div className="result-stamp"><Sparkles size={15}/>{landing?'내가 쏜 곳에서 시작하는 여행':'직접 고른 여행지'}</div><div className="dart-result-title"><div><span>{result.province} · {landing?'착지 지점 근처':'여행 목적지'}</span><h2 tabIndex={-1} ref={resultHeading}>{result.region_name}</h2></div><span className="destination-seal"><MapPin size={24}/></span></div><p>{loading?'혜택 정보를 확인하고 있어요.':error?'혜택 연결이 지연 중이에요. 축제는 따로 살펴볼 수 있어요.':!benefit?'지역 축제를 살펴보세요. 연결된 환급 혜택은 아직 없어요.':isStale(benefit)?'혜택 접수 상태를 다시 확인해 주세요.':isOpen(benefit)?'공식 안내에 접수중으로 표시된 여행 혜택이 있어요.':`수집된 혜택 상태: ${benefit.source_status||'확인 필요'}`}</p><button className="dart-result-cta" onClick={()=>onChoose(result)}>축제·혜택 둘러보기 <ArrowRight size={18}/></button><button className="sling-result-reset" onClick={reset}><RotateCcw size={14}/> 다시 당겨볼래요</button></div>}
    </div>
    <div className="dart-footer"><span>방향은 내가 정하고, 여행은 가볍게.</span><a href="https://www.geoboundaries.org/" target="_blank" rel="noopener noreferrer">지도: geoBoundaries · 가공한 여행 약도 <ExternalLink size={10}/></a></div>
  </section>
}
