// Which outbound links a benefit card may show, and what each button is called.
// Only URLs that came from the collected data are used; nothing is guessed or built.
import { safeUrl } from './benefits.ts'

export type LinkKind = 'apply' | 'info' | 'source'
export type ProgramLink = { href: string; label: string; kind: LinkKind }

/** http(s) only, no credentials. Blank, whitespace or malformed values give undefined.
 *  `&amp;` is decoded because some public-API URLs arrive HTML-escaped. */
export function cleanUrl(value: string | null | undefined): string | undefined {
  const text = typeof value === 'string' ? value.trim().replace(/&amp;/g, '&') : ''
  return text ? safeUrl(text) : undefined
}

/** Trimmed text, or '' when the value is missing or only whitespace. */
export function text(value: string | null | undefined): string {
  return typeof value === 'string' ? value.trim() : ''
}

// What the "official info" URL actually is, per collection source:
// - official_webpage (한국관광공사 반값여행 현황): the region's "홈페이지 바로가기" button.
// - gov24_api: the 정부24 service detail page (상세조회URL).
// - official_notice: a notice page.
// Anything else (news reports, project docs) is not shown as an official link.
const INFO_LABEL: Record<string, string> = {
  official_webpage: '지역 반값여행 홈페이지',
  gov24_api: '정부24 서비스 안내 보기',
  official_notice: '공고 보기',
}

export function sourcePageLabel(title: string | null | undefined): string | null {
  const name = text(title)
  if (!name) return null
  if (name.includes('반값여행 현황')) return '한국관광공사 반값여행 현황 보기'
  if (name.includes('공공서비스')) return '정부24 서비스 안내 보기'
  return `${name} 보기`
}

export function programLinks(p: {
  applyUrl?: string | null; infoUrl?: string | null; sourceType?: string | null;
  sourcePages?: { title?: string | null; url?: string | null }[] | null;
}): ProgramLink[] {
  const out: ProgramLink[] = []
  const add = (href: string | undefined, label: string | null, kind: LinkKind) => {
    if (href && label && !out.some(link => link.href === href)) out.push({ href, label, kind })
  }
  add(cleanUrl(p.applyUrl), '신청 페이지로 이동', 'apply')
  add(cleanUrl(p.infoUrl), INFO_LABEL[p.sourceType ?? ''] ?? null, 'info')
  for (const page of p.sourcePages ?? []) add(cleanUrl(page.url), sourcePageLabel(page.title), 'source')
  return out
}
