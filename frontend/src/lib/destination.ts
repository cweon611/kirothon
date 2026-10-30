export const destinationNames = ["광주 동구", "광주 서구", "광주 남구", "광주 북구", "광주 광산구", "목포시", "여수시", "순천시", "나주시", "광양시", "담양군", "곡성군", "구례군", "고흥군", "보성군", "화순군", "장흥군", "강진군", "해남군", "영암군", "무안군", "함평군", "영광군", "장성군", "완도군", "진도군", "신안군"]
export type Destination = { id: string; name: string; region_name: string; province: string; x: number; y: number; shape: string }

export type Point = { x: number; y: number }
export const SLING = { x: 260, y: 510 }
export const MAX_PULL = 86
export const MIN_PULL = 9
export function mapPoint(point: Point): Point {
  return { x: (point.x - 110) * 3 + 30, y: (point.y - 370) * 3 + 40 }
}
export function clampPull(point: Point): Point {
  const y = Math.max(0, point.y)
  const length = Math.hypot(point.x, y)
  const scale = length > MAX_PULL ? MAX_PULL / length : 1
  return { x: point.x * scale, y: y * scale }
}
/** Pull length only grips the pouch; flight distance is chosen after release. */
export function randomLanding(pull: Point, random = Math.random): Point {
  const heading = Math.atan2(-Math.max(5, pull.y), -pull.x)
  const angle = heading + (random() - .5) * .4
  const distance = 100 + random() * 370
  return {
    x: Math.max(25, Math.min(495, SLING.x + Math.cos(angle) * distance)),
    y: Math.max(60, Math.min(450, SLING.y + Math.sin(angle) * distance)),
  }
}
export function nearestDestination<T extends Point>(regions: T[], landing: Point): T | undefined {
  return regions.reduce<T | undefined>((closest, region) => !closest || Math.hypot(region.x - landing.x, region.y - landing.y) < Math.hypot(closest.x - landing.x, closest.y - landing.y) ? region : closest, undefined)
}
export function flightPoint(from: Point, to: Point, t: number): Point {
  const progress = Math.max(0, Math.min(1, t))
  return { x: from.x + (to.x - from.x) * progress, y: from.y + (to.y - from.y) * progress - 90 * 4 * progress * (1 - progress) }
}
