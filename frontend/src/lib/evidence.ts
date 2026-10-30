export const evidenceKinds = {
  visit: { label: '방문 사진', hint: '여행지에서 찍은 인증 사진' },
  receipt: { label: '결제 영수증', hint: '식사·체험·쇼핑 결제 내역' },
  stay: { label: '숙박 증빙', hint: '숙소 영수증·예약 확인서' },
} as const
export type EvidenceKind = keyof typeof evidenceKinds
export type Evidence = {
  id: string; fingerprint: string; name: string; size: number; dataUrl: string;
  kind: EvidenceKind; place: string; date: string; amount: string; memo: string;
}
export type EvidenceContext = { region: string; date: string; endDate: string; people: number }
export const MAX_FILES = 12
export const MAX_FILE_BYTES = 8 * 1024 * 1024
export const MAX_TOTAL_BYTES = 32 * 1024 * 1024
export function fingerprint(file: Pick<File, 'name' | 'size' | 'lastModified'>) {
  return JSON.stringify([file.name, file.size, file.lastModified])
}
export function fileIssue(file: Pick<File, 'name' | 'size' | 'lastModified' | 'type'>, existing: Pick<Evidence, 'size' | 'fingerprint'>[]) {
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) return 'JPG, PNG, WebP 이미지로 추가해 주세요. HEIC·PDF는 이미지로 변환해 주세요.'
  if (file.size === 0) return '내용이 없는 파일이에요.'
  if (file.size > MAX_FILE_BYTES) return '파일 한 개는 8MB까지 추가할 수 있어요.'
  if (existing.some(item => item.fingerprint === fingerprint(file))) return '이미 추가한 파일이에요.'
  if (existing.length >= MAX_FILES) return '파일은 최대 12개까지 추가할 수 있어요.'
  if (existing.reduce((sum, item) => sum + item.size, 0) + file.size > MAX_TOTAL_BYTES) return '전체 파일 용량은 32MB까지 가능해요.'
  return null
}
export function parseAmount(value: string): number | null {
  if (!/^\d{1,9}$/.test(value)) return null
  return Number(value)
}
export function evidenceSummary(items: Evidence[]) {
  const expenses = items.filter(item => item.kind !== 'visit')
  return {
    total: expenses.reduce((sum, item) => sum + (parseAmount(item.amount) ?? 0), 0),
    entered: expenses.filter(item => parseAmount(item.amount) !== null).length,
    missing: expenses.filter(item => parseAmount(item.amount) === null).length,
    invalid: expenses.filter(item => item.amount !== '' && parseAmount(item.amount) === null).length,
  }
}
export function escapeHtml(value: unknown) {
  return String(value).replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]!))
}
export function imageSource(value: string) {
  return /^data:image\/(jpeg|png|webp);base64,[A-Za-z0-9+/]+={0,2}$/.test(value) ? value : ''
}
export function buildEvidenceDocument(context: EvidenceContext, items: Evidence[]) {
  const e = escapeHtml
  const summary = evidenceSummary(items)
  const amount = (item: Evidence) => item.kind === 'visit' ? '해당 없음' : parseAmount(item.amount) === null ? '미입력' : `${parseAmount(item.amount)!.toLocaleString('ko-KR')}원`
  return `<!doctype html><html lang="ko"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"><title>${e(context.region)} 여행 증빙 정리본</title><style>
  *{box-sizing:border-box}body{margin:0;background:#eef2ef;color:#193744;font:15px/1.75 'Malgun Gothic',sans-serif}main{max-width:850px;margin:32px auto;padding:48px;background:white}h1{font-size:30px;line-height:1.4}h2{font-size:21px}p{white-space:pre-wrap;overflow-wrap:anywhere}.brand{color:#087f76;letter-spacing:.14em;font-size:12px;font-weight:bold}.note{padding:16px;background:#eff7f3;border-left:3px solid #087f76;font-size:13px}dl{display:grid;grid-template-columns:110px 1fr;gap:8px}dt{color:#536b68}dd{margin:0;overflow-wrap:anywhere;white-space:pre-wrap}article{border-top:1px solid #dce5e1;margin-top:32px;padding-top:24px;break-before:page}article img{display:block;max-width:100%;max-height:210mm;object-fit:contain;margin:24px auto}small{color:#526862}ol{padding-left:24px}li{padding:8px 0;overflow-wrap:anywhere}.print-help{text-align:center;padding:16px;font-size:13px}@media(max-width:600px){main{padding:24px;margin:0}h1{font-size:25px}dl{grid-template-columns:80px 1fr}}@page{size:A4;margin:18mm}@media print{body{background:white}main{padding:0;margin:0;max-width:none}.print-help{display:none}article img{max-height:180mm}a{color:inherit}}
  </style></head><body><div class="print-help">이 파일에는 첨부 이미지가 포함되어 있어요. 브라우저의 인쇄 메뉴로 인쇄할 수 있어요.</div><main><span class="brand">반값루트 · MY TRAVEL FILE</span><h1>${e(context.region)}<br>여행 증빙 정리본</h1><p>${e(context.date)} ~ ${e(context.endDate)} · ${e(context.people)}명 · 자료 ${items.length}개</p><div class="note">사용자가 직접 작성한 자료 정리본입니다. 지자체 공식 신청서가 아니며, 증빙 인정·환급액·제출 완료를 보장하지 않습니다. 공식 공고의 제출 양식과 원본 첨부 요건을 확인해 주세요.</div><h2>입력한 지출 합계 ${summary.total.toLocaleString('ko-KR')}원</h2><p>금액 입력 ${summary.entered}건 · 금액 미입력 ${summary.missing}건<br>방문 사진은 합계에서 제외됩니다. 이 금액은 환급 예상액이 아닙니다.</p><h2>첨부 자료 목록</h2><ol>${items.map(item => `<li>${e(evidenceKinds[item.kind].label)} · ${e(item.place || '장소 미입력')} · ${e(item.date || '날짜 미입력')} · ${e(amount(item))}<br><small>${e(item.name)}</small></li>`).join('')}</ol>${items.map((item, index) => `<article><span class="brand">첨부 ${String(index + 1).padStart(2, '0')} · ${e(evidenceKinds[item.kind].label)}</span><h2>${e(item.place || '장소 미입력')}</h2><dl><dt>방문·사용일</dt><dd>${e(item.date || '미입력')}</dd><dt>입력 금액</dt><dd>${e(amount(item))}</dd><dt>파일명</dt><dd>${e(item.name)}</dd><dt>메모</dt><dd>${e(item.memo || '없음')}</dd></dl><img src="${imageSource(item.dataUrl)}" alt="${e(item.name)}"></article>`).join('')}</main></body></html>`
}
