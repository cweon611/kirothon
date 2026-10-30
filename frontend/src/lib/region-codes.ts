// Stable 5-digit sigungu codes used by the backend (backend/app/team/seeds/regions.json).
// Map labels are display names; requests always send the code, never the name.
export const REGION_CODES: Record<string, string> = {
  '광주 동구': '29110', '광주 서구': '29140', '광주 남구': '29155', '광주 북구': '29170', '광주 광산구': '29200',
  목포시: '46110', 여수시: '46130', 순천시: '46150', 나주시: '46170', 광양시: '46230',
  담양군: '46710', 곡성군: '46720', 구례군: '46730', 고흥군: '46770', 보성군: '46780', 화순군: '46790',
  장흥군: '46800', 강진군: '46810', 해남군: '46820', 영암군: '46830', 무안군: '46840', 함평군: '46860',
  영광군: '46870', 장성군: '46880', 완도군: '46890', 진도군: '46900', 신안군: '46910',
}
export function regionCode(regionName: string | null | undefined): string | null {
  return regionName ? REGION_CODES[regionName] ?? null : null
}
