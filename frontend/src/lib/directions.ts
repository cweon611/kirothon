import { ORIGINS } from './course.ts'

type Point = {name:string; lat:number; lng:number}

// City/county/district office of each destination, used as the directions end point.
// Coordinates from OpenStreetMap (Nominatim), looked up 2026-10-31.
export const REGION_OFFICES: Record<string, Point> = {
  '광주 동구': {name:'광주 동구청',lat:35.14619,lng:126.92301}, '광주 서구': {name:'광주 서구청',lat:35.15205,lng:126.89017},
  '광주 남구': {name:'광주 남구청',lat:35.13279,lng:126.90246}, '광주 북구': {name:'광주 북구청',lat:35.17437,lng:126.91261},
  '광주 광산구': {name:'광주 광산구청',lat:35.14099,lng:126.79385},
  '목포시': {name:'목포시청',lat:34.81182,lng:126.39224}, '여수시': {name:'여수시청',lat:34.76221,lng:127.6631},
  '순천시': {name:'순천시청',lat:34.95066,lng:127.48728}, '나주시': {name:'나주시청',lat:35.01607,lng:126.71084},
  '광양시': {name:'광양시청',lat:34.94065,lng:127.69595}, '담양군': {name:'담양군청',lat:35.32119,lng:126.98824},
  '곡성군': {name:'곡성군청',lat:35.28202,lng:127.29198}, '구례군': {name:'구례군청',lat:35.20252,lng:127.4629},
  '고흥군': {name:'고흥군청',lat:34.60452,lng:127.27552}, '보성군': {name:'보성군청',lat:34.77128,lng:127.07958},
  '화순군': {name:'화순군청',lat:35.06432,lng:126.9865}, '장흥군': {name:'장흥군청',lat:34.68164,lng:126.9071},
  '강진군': {name:'강진군청',lat:34.64197,lng:126.76701}, '해남군': {name:'해남군청',lat:34.57392,lng:126.5994},
  '영암군': {name:'영암군청',lat:34.80023,lng:126.69683}, '무안군': {name:'무안군청',lat:34.99045,lng:126.48166},
  '함평군': {name:'함평군청',lat:35.06597,lng:126.51668}, '영광군': {name:'영광군청',lat:35.27728,lng:126.51204},
  '장성군': {name:'장성군청',lat:35.30193,lng:126.78478}, '완도군': {name:'완도군청',lat:34.31099,lng:126.75512},
  '진도군': {name:'진도군청',lat:34.48683,lng:126.26353}, '신안군': {name:'신안군청',lat:34.83356,lng:126.35141},
}

// Kakao Map's own link format; ',' and '/' would break the path segments.
const segment = (point:Point) => `${encodeURIComponent(point.name.replace(/[,/]/g,' ').trim())},${point.lat},${point.lng}`

/** Kakao Map directions from the trip's origin (or the user's current location if unknown) to a point. */
export function directionsUrl(originName:string, destination:Point) {
  const row=ORIGINS.find(item=>item.name===originName)
  const origin=row && typeof row.lat==='number' && typeof row.lng==='number' ? {name:row.name,lat:row.lat,lng:row.lng} : null
  const to=`to/${segment(destination)}`
  return origin ? `https://map.kakao.com/link/from/${segment(origin)}/${to}` : `https://map.kakao.com/link/${to}`
}

export function regionDirectionsUrl(originName:string, region:string) {
  const office=REGION_OFFICES[region]
  return office ? directionsUrl(originName, office) : null
}
