import { useEffect, useRef, useState } from 'react'
import { ArrowDown, ArrowRight, Check, ChevronRight, Compass, ExternalLink, Footprints, LocateFixed, MapPin, Navigation, RefreshCw, RotateCcw, Search, SlidersHorizontal, Sparkles, X, Plus, Minus, Info, LoaderCircle, Clock3, Landmark, Trees } from 'lucide-react'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import './App.css'

type Evidence = { month?: string; district?: string; hub_rank?: number; definition?: string; related?: { id: string; name: string; rank: number }[]; hub_source?: string; related_source?: string }
type Place = { evidence?: Evidence; id: string; name: string; lat: number; lon: number; category: string; content_type?: string; address: string; description: string; hours: string; rest: string; fee: string; phone: string; source: string; source_url: string; updated_at: string | null; checked_at?: string; operating_status: string; distance_km: number; reasons: string[] }
type Origin = { lat: number; lon: number; label: string; type: string }
type Result = { places: Place[]; total: number; fetched_at: string; stale: boolean; notice: string; truncated: boolean }
const STARTS: Origin[] = [
  { lat: 35.1466, lon: 126.9198, label: '국립아시아문화전당 주변', type: '수동 위치' },
  { lat: 35.1397, lon: 126.9168, label: '양림동 역사문화마을 주변', type: '수동 위치' },
  { lat: 35.1541, lon: 126.9141, label: '광주 예술의 거리 주변', type: '수동 위치' },
]
const CATEGORIES = ['전체', '관광명소', '문화공간', '야외활동']
function readSession(): { id: string; visited: Place[]; excluded: string[] } {
  try {
    const data = JSON.parse(sessionStorage.getItem('gwangju-trip') || 'null')
    if (data && typeof data.id === 'string' && Array.isArray(data.visited) && Array.isArray(data.excluded)) return data
  } catch { /* Storage can be disabled; in-memory state still works. */ }
  return { id: crypto.randomUUID(), visited: [], excluded: [] }
}
async function api<T>(url: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const res = await fetch('/api/team' + url, { method: body ? 'POST' : 'GET', headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined, signal: signal || AbortSignal.timeout(10000) })
  const value = await res.json().catch(() => null)
  if (!res.ok) throw new Error(typeof value?.detail === 'string' ? value.detail : '서버에 연결하지 못했어요. 잠시 후 다시 시도해 주세요.')
  return value as T
}
function gps(): Promise<Origin> {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) return reject(new Error('이 브라우저에서는 위치를 가져올 수 없어요. 시작 위치를 직접 선택해 주세요.'))
    navigator.geolocation.getCurrentPosition(p => {
      if (p.coords.accuracy > 500) return reject(new Error('위치 정확도가 낮아요. 시작 위치를 직접 선택해 주세요.'))
      resolve({ lat: p.coords.latitude, lon: p.coords.longitude, label: '내 현재 위치', type: '현재 위치' })
    }, () => reject(new Error('위치를 확인하지 못했어요. 권한을 확인하거나 시작 위치를 직접 선택해 주세요.')), { timeout: 7000, maximumAge: 0, enableHighAccuracy: true })
  })
}
function world(lat: number, lon: number, zoom: number) {
  const scale = 256 * 2 ** zoom
  const sin = Math.sin(Math.max(-85, Math.min(85, lat)) * Math.PI / 180)
  return { x: (lon + 180) / 360 * scale, y: (.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * scale }
}
function TripMap({ origin, places, visited, onSelect }: { origin: Origin; places: Place[]; visited: Place[]; onSelect: (p: Place) => void }) {
  const [zoom, setZoom] = useState(14)
  const [failed, setFailed] = useState(false)
  const [size, setSize] = useState({ width: 640, height: 550 })
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const observer = new ResizeObserver(entries => setSize({ width: entries[0].contentRect.width, height: entries[0].contentRect.height }))
    if (ref.current) observer.observe(ref.current)
    return () => observer.disconnect()
  }, [])
  const center = world(origin.lat, origin.lon, zoom)
  const left = center.x - size.width / 2, top = center.y - size.height / 2
  const point = (p: { lat: number; lon: number }) => { const w = world(p.lat, p.lon, zoom); return { x: w.x - left, y: w.y - top } }
  const tiles = []
  for (let x = Math.floor(left / 256); x <= Math.floor((left + size.width) / 256); x++) {
    for (let y = Math.floor(top / 256); y <= Math.floor((top + size.height) / 256); y++) {
      tiles.push(<img key={`${zoom}-${x}-${y}`} alt="" draggable={false} className="map-tile" src={`https://tile.openstreetmap.org/${zoom}/${x}/${y}.png`} style={{ left: x * 256 - left, top: y * 256 - top }} onError={() => setFailed(true)} />)
    }
  }
  return <div className="trip-map" ref={ref} aria-label="추천 장소 및 방문 순서 지도">
    {tiles}
    <svg className="map-lines" width={size.width} height={size.height} aria-hidden="true"><polyline points={visited.map(p => { const v = point(p); return `${v.x},${v.y}` }).join(' ')} fill="none" stroke="#277665" strokeWidth="3" strokeDasharray="7 7" /></svg>
    {visited.map((p, i) => { const pos = point(p); return <button className="map-pin visited-pin" key={p.id} style={{ left: pos.x, top: pos.y }} onClick={() => onSelect(p)} aria-label={`${i + 1}번째 방문 ${p.name}`}><Check size={15} /><span>{i + 1}. {p.name}</span></button> })}
    {places.map((p, i) => { const pos = point(p); return <button className="map-pin" key={p.id} style={{ left: pos.x, top: pos.y }} onClick={() => onSelect(p)} aria-label={`${i + 1}. ${p.name}`}>{i + 1}<span>{p.name}</span></button> })}
    <div className="origin-dot" style={{ left: size.width / 2, top: size.height / 2 }} title={origin.label} />
    <div className="map-label"><span className="green-dot" /> 광주 도심 탐색 <span className="map-live">MAP</span></div>
    <div className="map-controls"><button aria-label="지도 확대" onClick={() => setZoom(z => Math.min(16, z + 1))}><Plus size={18} /></button><button aria-label="지도 축소" onClick={() => setZoom(z => Math.max(12, z - 1))}><Minus size={18} /></button></div>
    <div className="map-key"><i /> 기준 위치 <b /> 추천 장소 <small>연결선은 방문 순서이며 실제 경로가 아닙니다.</small></div>
    {failed && <div className="map-error">지도 일부를 불러오지 못했어요. 장소 목록은 계속 이용할 수 있어요.</div>}
    <a className="map-credit" href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">© OpenStreetMap contributors</a>
  </div>
}
function App() {
  const [session, setSession] = useState(readSession)
  const [origin, setOrigin] = useState<Origin>(STARTS[0])
  const [radius, setRadius] = useState<3 | 5>(3)
  const [category, setCategory] = useState('전체')
  const [result, setResult] = useState<Result | null>(null)
  const [loading, setLoading] = useState(false)
  const [locating, setLocating] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [detail, setDetail] = useState<Place | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState('')
  const [selected, setSelected] = useState<Place | null>(null)
  const [locationOpen, setLocationOpen] = useState(false)
  const [fallback, setFallback] = useState<Place | null>(null)
  const [resetOpen, setResetOpen] = useState(false)
  const [manualLat, setManualLat] = useState('35.1466')
  const [manualLon, setManualLon] = useState('126.9198')
  const requestId = useRef(0)
  const detailId = useRef(0)
  const sectionRef = useRef<HTMLElement>(null)
  useEffect(() => { try { sessionStorage.setItem('gwangju-trip', JSON.stringify(session)) } catch { /* optional persistence */ } }, [session])
  function track(event: string, place_id?: string) {
    void api('/events', { session_id: session.id, event, place_id }).catch(() => {})
  }
  async function recommend(nextOrigin = origin, nextRadius = radius, nextCategory = category, nextSession = session) {
    const id = ++requestId.current
    setLoading(true); setError(''); setResult(null)
    track('request')
    try {
      const value = await api<Result>('/recommendations', { lat: nextOrigin.lat, lon: nextOrigin.lon, radius: nextRadius, category: nextCategory, visited: nextSession.visited.map(p => p.id), excluded: nextSession.excluded })
      if (id !== requestId.current) return
      setResult(value); track('impression')
    } catch (e) {
      if (id === requestId.current) { setError(e instanceof Error && e.name !== 'TimeoutError' ? e.message : '응답 시간이 길어지고 있어요. 다시 시도해 주세요.'); track('error') }
    } finally { if (id === requestId.current) setLoading(false) }
  }
  useEffect(() => { void recommend(); return () => { requestId.current++ } }, []) // Initial manual origin requires no location permission.
  async function locate() {
    setLocating(true); setNotice('')
    try { const pos = await gps(); setOrigin(pos); setLocationOpen(false); await recommend(pos) }
    catch (e) { setNotice((e as Error).message); setLocationOpen(true) }
    finally { setLocating(false) }
  }
  function useOrigin(pos: Origin) { setOrigin(pos); setLocationOpen(false); setNotice(''); void recommend(pos) }
  async function showDetail(place: Place) {
    const id = ++detailId.current
    setDetail(place); setDetailLoading(true); setDetailError(''); track('detail', place.id)
    try { const value = await api<Place>('/places/' + encodeURIComponent(place.id)); if (id === detailId.current) { setDetail({ ...place, ...value }); if (value.operating_status === '운영시간상 방문 불가') { setResult(r => r ? { ...r, places: r.places.filter(p => p.id !== place.id), total: Math.max(0, r.total - 1) } : r); setSelected(p => p?.id === place.id ? null : p) } } }
    catch (e) { if (id === detailId.current) setDetailError((e as Error).message) }
    finally { if (id === detailId.current) setDetailLoading(false) }
  }
  function skip(p: Place) {
    const next = { ...session, excluded: [...new Set([...session.excluded, p.id])] }
    setSession(next); track('skip', p.id); if (selected?.id === p.id) setSelected(null)
    detailId.current++; setDetail(null); void recommend(origin, radius, category, next)
  }
  async function complete(p: Place) {
    if (session.visited.some(v => v.id === p.id)) return
    const next = { ...session, visited: [...session.visited, p] }
    requestId.current++; detailId.current++; setLoading(false); setSession(next); setSelected(null); setDetail(null); setResult(null); track('visit', p.id)
    setLocating(true); setNotice(`${p.name} 방문을 기록했어요. 다음 추천을 위한 위치를 확인합니다.`)
    try { const pos = await gps(); setOrigin(pos); setNotice('방문 완료! 새로운 위치에서 다음 장소를 찾아봤어요.'); track('next'); await recommend(pos, radius, category, next) }
    catch { setFallback(p) }
    finally { setLocating(false) }
  }
  function reset() {
    track('reset'); const next = { ...session, visited: [], excluded: [] }; setSession(next); setSelected(null); setResetOpen(false); setNotice('방문 기록과 건너뛴 장소를 초기화했어요.'); void recommend(origin, radius, category, next)
  }
  return <div className="app-shell">
    <header className="site-header"><a className="brand" href="#"><span className="brand-symbol"><Compass size={24} /></span><span>지금, 광주<small>발길 닿는 대로, 발견하는 여행</small></span></a><nav><a className="active" href="#explore">주변 둘러보기</a><a href="#journey">나의 발자취 <span>{session.visited.length}</span></a></nav><span className="pilot-tag"><span className="green-dot" /> 광주 도심 시범 서비스</span></header>
    <main>
      <section className="hero"><div className="hero-copy"><div className="eyebrow"><span /> A LITTLE CLOSER, A NEW DISCOVERY</div><h1>계획은 가볍게,<br />발견은 <em>가까이.</em></h1><p>지금 있는 곳에서 시작하는 광주 여행.<br />마음이 가는 한 곳을 고르면, 다음 발걸음도 함께할게요.</p><button className="primary" onClick={() => sectionRef.current?.scrollIntoView({ behavior: 'smooth' })}>내 주변 발견하기 <ArrowDown size={17} /></button><div className="hero-note"><MapPin size={14} /> 광주 동구 · 남구 도심 일대</div></div><div className="hero-art" aria-hidden="true"><div className="art-sun" /><div className="art-caption">GWANGJU<br /><b>35.1466° N · 126.9198° E</b></div><svg viewBox="0 0 640 330"><path d="M0 220 Q100 80 230 205 Q350 75 470 180 Q570 90 640 170V330H0" fill="#d4dfc8"/><path d="M0 270 Q170 150 330 260 Q500 150 640 240V330H0" fill="#b5c9ae"/><path d="M0 305 Q180 235 640 300V330H0" fill="#8da98d"/><path d="M290 330 Q380 270 350 230 Q320 195 410 175" fill="none" stroke="#efe6cb" strokeWidth="28"/><g fill="#e9dbc1" stroke="#536d59" strokeWidth="3"><path d="M85 230V163H215V230Z"/><path d="M68 165L150 120L232 165Z" fill="#536d59"/><path d="M99 147L150 109L201 147Z" fill="#536d59"/><path d="M130 230V181H170V230Z" fill="#a1b09a"/><path d="M445 235V162H560V235Z"/><path d="M430 164L503 130L575 164Z" fill="#536d59"/></g><g fill="#66886d"><circle cx="60" cy="230" r="27"/><circle cx="245" cy="230" r="32"/><circle cx="595" cy="220" r="35"/><circle cx="400" cy="250" r="22"/></g><g stroke="#5c7560" strokeWidth="5"><path d="M60 220V280M245 220V285M595 220V290M400 245V285"/></g></svg><div className="floating-note"><span><Footprints size={21}/></span><div>조금 걸으면, 새로운 풍경<small>오늘의 여행은 여기서부터</small></div></div></div></section>
      <section className="explore-section" id="explore" ref={sectionRef}>
        <div className="section-top"><div><div className="eyebrow">EXPLORE NEARBY</div><h2>지금, 어디로 가볼까요?</h2></div><span className="live-source"><span className="green-dot"/> 한국관광공사 관광정보</span></div>
        <div className="location-bar"><div className="location-icon"><MapPin size={22}/></div><div className="location-text"><small>추천 기준 · {origin.type}</small><strong>{origin.label}</strong></div><button className="text-button" onClick={() => setLocationOpen(true)}>위치 변경 <ChevronRight size={16}/></button><div className="bar-divider"/><button className="locate-button" disabled={locating} onClick={() => void locate()}>{locating ? <LoaderCircle className="spin" size={16}/> : <LocateFixed size={16}/>} 현재 위치 사용</button></div>
        <p className="privacy-note">위치는 추천 요청에만 사용하며 분석 로그에 저장하지 않아요. 지도 제공자에게는 표시 구역이 전달됩니다.</p>
        {notice && <div className="notice" role="status"><Info size={17}/>{notice}<button aria-label="알림 닫기" onClick={() => setNotice('')}><X size={15}/></button></div>}
        <div className="filter-row"><div className="category-tabs">{CATEGORIES.map((c, i) => <button key={c} className={category === c ? 'chosen' : ''} onClick={() => { setCategory(c); void recommend(origin, radius, c) }}>{i === 0 ? <Compass size={15}/> : i === 1 ? <MapPin size={15}/> : i === 2 ? <Landmark size={15}/> : <Trees size={15}/>} {c}</button>)}</div><label className="radius"><SlidersHorizontal size={15}/> 검색 반경 <select aria-label="검색 반경" value={radius} onChange={e => { const r = Number(e.target.value) as 3 | 5; setRadius(r); void recommend(origin, r) }}><option value={3}>3 km</option><option value={5}>5 km</option></select></label></div>
        <div className="discovery-grid"><div className="results-panel"><div className="results-title"><h3>가까운 곳부터, 한 걸음 <span>{result?.places.length || 0}</span></h3><span>직선거리 기준</span></div>
          {loading ? <div className="loading-state" role="status"><LoaderCircle className="spin"/><strong>가까운 발견을 찾고 있어요</strong><p>관광정보를 확인하고 있어요. 잠시만 기다려 주세요.</p>{[1,2,3].map(i => <div className="skeleton" key={i}/>)}</div> : error ? <div className="empty-state" role="alert"><Compass size={36}/><h3>잠시 길을 찾고 있어요</h3><p>{error}</p><button className="primary" onClick={() => void recommend()}><RefreshCw size={16}/> 다시 시도</button><button className="text-button" onClick={() => setLocationOpen(true)}>지원 지역에서 시작하기</button></div> : result?.places.length ? <div className="place-list">{result.places.map((p, i) => <article className={`place-card ${selected?.id === p.id ? 'is-selected' : ''}`} key={p.id}><button className="place-main" onClick={() => void showDetail(p)}><div className={`place-illustration type-${p.content_type || '12'}`}><span className="number-badge">0{i + 1}</span>{p.category === '문화공간' ? <Landmark/> : p.category === '야외활동' ? <Trees/> : <MapPin/>}</div><div className="place-info"><div className="place-meta">{p.category}<span>{p.distance_km < 1 ? `${Math.round(p.distance_km * 1000)}m` : `${p.distance_km.toFixed(1)}km`}</span></div><h3>{p.name}</h3><p>{p.address || '주소 정보 없음'}</p><span className="status-chip"><Clock3 size={12}/>{p.operating_status}</span></div><ChevronRight className="card-chevron" size={17}/></button><div className="reason-row"><Sparkles size={13}/><span>{p.reasons[0]}</span><button onClick={() => skip(p)} aria-label={`${p.name} 건너뛰기`}>건너뛰기</button></div></article>)}</div> : <div className="empty-state"><Search size={36}/><h3>{locating ? '다음 발걸음을 준비하고 있어요' : '이 조건의 장소를 모두 둘러봤어요'}</h3><p>방문·건너뛰기·카테고리·검색 반경을 적용한 결과입니다. 위치나 조건을 바꿔보세요.</p>{radius === 3 && <button className="primary" onClick={() => {setRadius(5); void recommend(origin, 5)}}>5km로 넓혀보기</button>}<button className="text-button" onClick={() => setLocationOpen(true)}>다른 위치 선택</button></div>}
          {result && <div className="results-footnote"><Info size={14}/><span>{result.places.length < 3 ? `조건에 맞는 후보가 ${result.places.length}곳입니다. ` : ''}{result.notice}{result.stale ? ' · 이전 캐시 사용' : ''}{result.truncated ? ' · 원천 조회 상한 내 결과' : ''}<br/>조회 {new Date(result.fetched_at).toLocaleString('ko-KR')} · 실제 개장 여부는 방문 전 확인해 주세요.</span></div>}
        </div><div className="map-panel"><TripMap origin={origin} places={result?.places || []} visited={session.visited} onSelect={p => void showDetail(p)}/><div className="map-bottom"><Navigation size={17}/><div><strong>마음에 드는 장소를 눌러보세요</strong><p>상세정보를 확인하고, 외부 지도에서 길을 찾을 수 있어요.</p></div></div></div></div>
      </section>
      {selected && <section className="selected-banner"><span className="selected-icon"><Navigation size={23}/></span><div><small>다음으로 가볼 곳</small><h3>{selected.name}</h3><p>선택만으로는 방문 기록에 추가되지 않아요.</p></div><button className="text-button" onClick={() => void showDetail(selected)}>상세 보기</button><button className="primary" disabled={locating} onClick={() => void complete(selected)}><Check size={17}/> 방문 완료</button><button className="icon-button" aria-label="장소 선택 취소" onClick={() => setSelected(null)}><X size={18}/></button></section>}
      <section className="journey-section" id="journey"><div className="section-top"><div><div className="eyebrow">YOUR LITTLE JOURNEY</div><h2>오늘 남긴 발자취 <span>{session.visited.length}</span></h2></div><button className="text-button" disabled={!session.visited.length && !session.excluded.length} onClick={() => setResetOpen(true)}><RotateCcw size={14}/> 기록 초기화</button></div>{session.visited.length ? <div className="journey-list">{session.visited.map((p, i) => <button key={p.id} onClick={() => void showDetail(p)}><span>{i + 1}</span><div><strong>{p.name}</strong><small>방문 완료 · 직접 확인</small></div><Check size={17}/></button>)}</div> : <div className="journey-empty"><div><Footprints size={27}/></div><p>아직은 비어 있는 오늘의 여행<small>장소를 둘러본 뒤 ‘방문 완료’를 누르면 나만의 발자취가 쌓여요.</small></p><span>어떤 발견이 기다릴까요? <ArrowRight size={16}/></span></div>}</section>
      <div className="how-it-works"><div><b>01</b><span>시작점을 정하고<small>현재 위치 또는 원하는 장소</small></span></div><ChevronRight/><div><b>02</b><span>마음 가는 곳을 고르고<small>거리와 추천 이유 확인</small></span></div><ChevronRight/><div><b>03</b><span>다음 발견으로 이어가요<small>방문 완료 후 새로운 추천</small></span></div></div>
    </main><footer><a className="footer-brand" href="#">지금, 광주</a><p>가까운 곳에서 발견하는, 나만의 광주.</p><small>관광정보 © 한국관광공사 · 익명 이용 이벤트 30일 보관 · 정밀 위치 미저장</small></footer>
    <Dialog open={locationOpen} onOpenChange={setLocationOpen}><DialogContent className="tour-dialog"><DialogHeader><DialogTitle>어디에서 시작할까요?</DialogTitle><DialogDescription>광주 도심 시연 구역 안에서 시작점을 정해 주세요. 현재 위치는 버튼을 누를 때만 요청합니다.</DialogDescription></DialogHeader><button className="primary" disabled={locating} onClick={() => void locate()}><LocateFixed size={17}/> {locating ? '위치 확인 중…' : '현재 위치 사용'}</button>{STARTS.map(pos => <button className="location-option" key={pos.label} onClick={() => useOrigin(pos)}><MapPin size={18}/>{pos.label}<ChevronRight size={16}/></button>)}<form className="coordinate-form" onSubmit={e => { e.preventDefault(); const lat = Number(manualLat), lon = Number(manualLon); if (!Number.isFinite(lat) || !Number.isFinite(lon)) return; useOrigin({ lat, lon, label: '직접 지정한 위치', type: '수동 좌표' }) }}><p>좌표로 직접 지정하기</p><div><label>위도<input required type="number" min="-90" max="90" step="any" value={manualLat} onChange={e => setManualLat(e.target.value)}/></label><label>경도<input required type="number" min="-180" max="180" step="any" value={manualLon} onChange={e => setManualLon(e.target.value)}/></label></div><button className="secondary" type="submit">이 위치에서 추천받기</button><small>지원 범위: 북위 35.115~35.180°, 동경 126.885~126.955°</small></form></DialogContent></Dialog>
    <Dialog open={!!detail} onOpenChange={open => { if (!open) { setDetail(null); detailId.current++ } }}><DialogContent className="tour-dialog detail-dialog">{detail && <><DialogHeader><div className="eyebrow">{detail.category}</div><DialogTitle>{detail.name}</DialogTitle><DialogDescription>{detail.address || '주소 정보 없음'}</DialogDescription></DialogHeader><span className="status-chip">{detail.operating_status} · 실시간 개장 확인 아님</span>{detailLoading && <p role="status">상세정보 확인 중…</p>}{detailError && <p className="detail-error" role="alert">{detailError} <button className="text-button" onClick={() => void showDetail(detail)}>재시도</button></p>}<p className="description">{detail.description || '소개 정보 없음'}</p><dl><div><dt>운영시간</dt><dd>{detail.hours || '정보 없음'}</dd></div><div><dt>휴무일</dt><dd>{detail.rest || '정보 없음'}</dd></div><div><dt>이용요금</dt><dd>{detail.fee || '정보 없음'}</dd></div><div><dt>문의</dt><dd>{detail.phone || '정보 없음'}</dd></div><div><dt>거리</dt><dd>{detail.distance_km?.toFixed(2) || '—'}km · 추천 당시 기준 직선거리</dd></div></dl>{detail.evidence?.hub_rank && <div className="evidence-box"><strong>{detail.evidence.month} · {detail.evidence.district} 중심 관광지 {detail.evidence.hub_rank}위</strong><p>{detail.evidence.definition}</p><p>후보 전체의 비교 가능한 자료가 없어 추천 점수에는 반영하지 않았어요.</p><a href={detail.evidence.hub_source} target="_blank" rel="noreferrer">중심 관광지 자료 출처 ↗</a>{!!detail.evidence.related?.length && <><p>같은 자료에서 연관 관계가 확인된 장소</p><ul>{detail.evidence.related.map(p => <li key={p.id}>{p.name} · 연관 순위 {p.rank}</li>)}</ul><a href={detail.evidence.related_source} target="_blank" rel="noreferrer">연관 관광지 자료 출처 ↗</a></>}</div>}<div className="detail-source"><a href={detail.source_url} target="_blank" rel="noreferrer">{detail.source} <ExternalLink size={12}/></a><small>원천 갱신: {detail.updated_at || '갱신일 미제공'}<br/>상세 확인: {detail.checked_at ? new Date(detail.checked_at).toLocaleString('ko-KR') : '미확인'}</small></div><a className="secondary directions" href={`https://map.kakao.com/link/to/${encodeURIComponent(detail.name)},${detail.lat},${detail.lon}`} target="_blank" rel="noreferrer" onClick={() => track('directions', detail.id)}><Navigation size={17}/> 외부 지도에서 길찾기 <ExternalLink size={14}/></a>{session.visited.some(p => p.id === detail.id) ? <p className="visited-message"><Check size={17}/> 이미 방문한 장소예요.</p> : <div className="dialog-actions"><button className="secondary" onClick={() => skip(detail)}>다른 추천</button><button className="primary" disabled={detail.operating_status === '운영시간상 방문 불가' || detailLoading} onClick={() => { setSelected(detail); track('select', detail.id); detailId.current++; setDetail(null); setNotice('방문할 장소를 선택했어요. 관람 후 방문 완료를 눌러 주세요.') }}>이곳으로 갈래요 <ArrowRight size={16}/></button></div>}</>}</DialogContent></Dialog>
    <Dialog open={!!fallback} onOpenChange={open => { if (!open) { setFallback(null); setLocationOpen(true) } }}><DialogContent className="tour-dialog"><DialogHeader><DialogTitle>다음 추천의 기준 위치</DialogTitle><DialogDescription>현재 위치를 확인하지 못했어요. 방금 방문한 {fallback?.name}을 기준으로 다음 장소를 추천할까요?</DialogDescription></DialogHeader><button className="primary" onClick={() => { if (fallback) { const pos = { lat: fallback.lat, lon: fallback.lon, label: fallback.name, type: '직전 방문지 · 사용자 확인' }; setFallback(null); setNotice('직전 방문지를 기준으로 다음 장소를 추천해요.'); track('next'); useOrigin(pos) } }}>직전 방문지를 기준으로 추천</button><button className="secondary" onClick={() => { setFallback(null); setLocationOpen(true) }}>직접 위치 선택</button></DialogContent></Dialog>
    <Dialog open={resetOpen} onOpenChange={setResetOpen}><DialogContent className="tour-dialog"><DialogHeader><DialogTitle>오늘의 기록을 초기화할까요?</DialogTitle><DialogDescription>방문한 장소와 건너뛴 장소가 모두 다시 추천 대상이 됩니다.</DialogDescription></DialogHeader><div className="dialog-actions"><button className="secondary" onClick={() => setResetOpen(false)}>취소</button><button className="primary" onClick={reset}>초기화</button></div></DialogContent></Dialog>
  </div>
}
export default App

