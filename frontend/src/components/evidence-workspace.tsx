import { useEffect, useRef, useState } from 'react'
import { ArrowDownToLine, ArrowRight, Camera, Check, FileCheck2, FileImage, Files, House, ImagePlus, Info, LoaderCircle, Receipt, ShieldCheck, Trash2, Upload, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { buildEvidenceDocument, evidenceKinds, evidenceSummary, fileIssue, fingerprint, parseAmount, type Evidence, type EvidenceContext, type EvidenceKind } from '@/lib/evidence'
import './evidence-workspace.css'

const kindIcons = { visit: Camera, receipt: Receipt, stay: House }
const kinds = Object.keys(evidenceKinds) as EvidenceKind[]

function readImage(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('파일을 읽지 못했어요. 다시 선택해 주세요.'))
    reader.onload = () => {
      const image = new Image()
      image.onerror = () => reject(new Error('열 수 없는 이미지예요. 다른 이미지로 추가해 주세요.'))
      image.onload = () => image.naturalWidth * image.naturalHeight > 50_000_000
        ? reject(new Error('이미지 해상도가 너무 커요. 5천만 화소 이하로 줄여 주세요.'))
        : resolve(String(reader.result))
      image.src = String(reader.result)
    }
    reader.readAsDataURL(file)
  })
}

export function EvidenceWorkspace({ context, items, onChange }: {
  context: EvidenceContext; items: Evidence[]; onChange: (items: Evidence[]) => void;
}) {
  const [kind, setKind] = useState<EvidenceKind>('visit')
  const [busy, setBusy] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [messages, setMessages] = useState<string[]>([])
  const [feedback, setFeedback] = useState('')
  const [previewOpen, setPreviewOpen] = useState(false)
  const [imageItem, setImageItem] = useState<Evidence | null>(null)
  const [removed, setRemoved] = useState<Evidence | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const previewButton = useRef<HTMLButtonElement>(null)
  const imageTrigger = useRef<HTMLButtonElement | null>(null)
  const locked = useRef(false)
  const alive = useRef(true)
  const dragDepth = useRef(0)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  const summary = evidenceSummary(items)
  const incomplete = items.filter(item => !item.place.trim() || !item.date).length
  const update = (id: string, patch: Partial<Evidence>) => onChange(items.map(item => item.id === id ? { ...item, ...patch } : item))
  async function addFiles(files: File[]) {
    if (locked.current || !files.length) return
    locked.current = true; setBusy(true); setMessages([]); setFeedback(''); setRemoved(null)
    const next = [...items]
    const errors: string[] = []
    for (const file of files) {
      const issue = fileIssue(file, next)
      if (issue) { errors.push(`${file.name}: ${issue}`); continue }
      try {
        const dataUrl = await readImage(file)
        if (!alive.current) return
        next.push({ id: crypto.randomUUID(), fingerprint: fingerprint(file), name: file.name, size: file.size, dataUrl, kind, place: '', date: '', amount: '', memo: '' })
      } catch (error) { errors.push(`${file.name}: ${error instanceof Error ? error.message : '추가하지 못했어요.'}`) }
    }
    if (alive.current) {
      onChange(next); setMessages(errors); setBusy(false)
      setFeedback(next.length > items.length ? `${next.length - items.length}개 자료를 추가했어요. 아래에서 내용을 확인해 주세요.` : '')
    }
    locked.current = false
  }
  function download() {
    try {
      const url = URL.createObjectURL(new Blob([buildEvidenceDocument(context, items)], { type: 'text/html;charset=utf-8' }))
      const link = document.createElement('a')
      link.href = url; link.download = `반값루트_${context.region}_${context.date}_증빙정리본.html`
      document.body.appendChild(link); link.click(); link.remove()
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
      setFeedback('정리본 다운로드를 요청했어요. 다운로드 목록에서 파일을 확인해 주세요.')
    } catch { setFeedback('정리본을 저장하지 못했어요. 잠시 후 다시 시도해 주세요.') }
  }
  return <section className="evidence-workspace" id="evidence-workspace" tabIndex={-1} aria-labelledby="evidence-title">
    <div className="evidence-intro">
      <div><span className="evidence-eyebrow"><Files size={14}/> 나의 여행 증빙함</span><h2 id="evidence-title">여행의 기록이,<br/>한 장의 준비가 되도록.</h2><p>사진과 영수증만 모아두세요.<br/>제출 전 확인하기 쉬운 정리본으로 묶어드려요.</p></div>
      <div className="evidence-paper-art" aria-hidden="true"><div className="paper-photo"><span/><Camera size={20}/></div><div className="paper-receipt"><Receipt size={22}/><i/><i/><i/><b>TRAVEL</b></div><span className="paper-check"><Check size={21}/></span></div>
    </div>
    <ol className="evidence-steps" aria-label="증빙 정리 순서"><li><span>1</span>자료 추가</li><ArrowRight size={14} aria-hidden="true"/><li><span>2</span>내용 확인</li><ArrowRight size={14} aria-hidden="true"/><li><span>3</span>정리본 저장</li></ol>
    <div className="evidence-local-note"><ShieldCheck size={18}/><p><strong>파일은 내 기기에만 머물러요.</strong> 새로고침하거나 탭을 닫으면 자료가 사라져요. 작업 후 정리본을 저장해 주세요.</p></div>
    <div className="evidence-upload-panel">
      <div className="evidence-section-heading"><h3><span>01</span> 어떤 자료를 추가할까요?</h3><span>{items.length} / 12개</span></div>
      <div className="evidence-kind-picker" role="group" aria-label="추가할 자료 종류">{kinds.map(value => { const Icon = kindIcons[value]; return <button key={value} disabled={busy} className={kind === value ? 'active' : ''} aria-pressed={kind === value} onClick={() => setKind(value)}><Icon size={22}/><strong>{evidenceKinds[value].label}</strong><span>{items.filter(item => item.kind === value).length}개 보관</span></button> })}</div>
      <div className={`evidence-dropzone ${dragging ? 'dragging' : ''}`} onDragEnter={event => { event.preventDefault(); dragDepth.current++; setDragging(true) }} onDragOver={event => event.preventDefault()} onDragLeave={event => { event.preventDefault(); if (--dragDepth.current <= 0) setDragging(false) }} onDrop={event => { event.preventDefault(); dragDepth.current = 0; setDragging(false); void addFiles(Array.from(event.dataTransfer.files)) }}>
        <span className="upload-symbol">{busy ? <LoaderCircle className="loading-spin" size={26}/> : <ImagePlus size={27}/>}</span><strong>{busy ? '이미지를 확인하고 있어요' : `${evidenceKinds[kind].label}을 추가해 주세요`}</strong><p>{evidenceKinds[kind].hint}<br/>파일을 끌어놓거나 아래 버튼을 눌러 주세요.</p><input ref={fileInput} type="file" accept="image/jpeg,image/png,image/webp" multiple hidden onChange={event => { void addFiles(Array.from(event.target.files || [])); event.target.value = '' }}/><Button className="button evidence-upload-button" disabled={busy || items.length >= 12} onClick={() => fileInput.current?.click()}><Upload size={17}/>{evidenceKinds[kind].label} 선택</Button><small>JPG · PNG · WebP / 파일당 8MB / 전체 32MB</small>
      </div>
      <div className="evidence-status" role="status" aria-live="polite">{feedback}</div>
      {messages.length > 0 && <div className="evidence-errors" role="alert"><strong>추가하지 못한 자료가 있어요</strong><ul>{messages.map((message, index) => <li key={index}>{message}</li>)}</ul><button onClick={() => setMessages([])} aria-label="파일 오류 안내 닫기"><X size={18}/></button></div>}
    </div>
    <div className="evidence-section-heading evidence-list-heading"><h3><span>02</span> 모은 자료 확인하기</h3><span>{items.length}개</span></div>
    {items.length === 0 ? <div className="evidence-empty"><FileImage size={30}/><strong>첫 여행 기록을 기다리고 있어요</strong><p>여행 사진 한 장부터 가볍게 시작해 보세요.<br/>추가한 자료는 여기에서 수정할 수 있어요.</p></div> : <><p className="evidence-hint">이미지를 눌러 크게 확인해 보세요. 장소·날짜·금액은 직접 입력하며, 자동으로 읽어오지 않아요.</p><div className="evidence-file-list">{items.map((item, index) => {
      const Icon = kindIcons[item.kind]
      const invalid = item.kind !== 'visit' && item.amount !== '' && parseAmount(item.amount) === null
      const outOfRange = item.date && (item.date < context.date || item.date > context.endDate)
      return <article className="evidence-file-card" key={item.id}><div className="evidence-file-top"><span><Icon size={16}/>{evidenceKinds[item.kind].label}<b>{String(index + 1).padStart(2, '0')}</b></span><button disabled={busy} className="evidence-remove" aria-label={`${item.name} 삭제`} onClick={() => { onChange(items.filter(row => row.id !== item.id)); setRemoved(item); setFeedback('자료를 삭제했어요.') }}><Trash2 size={17}/> 삭제</button></div><div className="evidence-file-body"><button className="evidence-thumbnail" onClick={event => { imageTrigger.current = event.currentTarget; setImageItem(item) }} aria-label={`${item.name} 크게 보기`}><img src={item.dataUrl} alt={item.name}/><span>크게 보기</span></button><fieldset className="evidence-fields" disabled={busy}><legend className="sr-only">자료 {index + 1} 내용</legend><label className="evidence-wide">장소·상호명<input maxLength={80} placeholder="예: 방문한 여행지, 식당 이름" value={item.place} onChange={event => update(item.id, { place: event.target.value })}/></label><label>자료 종류<select value={item.kind} onChange={event => update(item.id, { kind: event.target.value as EvidenceKind })}>{kinds.map(value => <option value={value} key={value}>{evidenceKinds[value].label}</option>)}</select></label><label>방문·사용일<input type="date" value={item.date} onChange={event => update(item.id, { date: event.target.value })}/></label>{outOfRange && <p className="evidence-field-note evidence-wide">선택한 여행기간 밖의 날짜예요. 예약 결제일인지 확인해 주세요.</p>}{item.kind !== 'visit' && <label className="evidence-wide">결제 금액 <span className="evidence-optional">선택</span><div className="evidence-money-input"><input inputMode="numeric" placeholder="영수증에 적힌 금액" maxLength={12} value={item.amount} aria-invalid={invalid} aria-describedby={invalid ? `amount-error-${item.id}` : undefined} onChange={event => update(item.id, { amount: event.target.value })}/><span>원</span></div>{invalid && <small className="evidence-field-error" id={`amount-error-${item.id}`}>쉼표 없이 0~999,999,999 사이의 정수를 입력해 주세요.</small>}</label>}<label className="evidence-wide">메모 <span className="evidence-optional">선택</span><input maxLength={200} placeholder="예: 2인 식사, 방문 인증 사진" value={item.memo} onChange={event => update(item.id, { memo: event.target.value })}/></label></fieldset></div><p className="evidence-file-name">{item.name} · {(item.size / 1024 / 1024).toFixed(1)}MB</p></article>
    })}</div></>}
    {removed && <div className="evidence-undo" role="status"><span>자료 1개를 삭제했어요.</span><button disabled={busy} onClick={() => { onChange([...items, removed]); setRemoved(null); setFeedback('삭제한 자료를 복원했어요.') }}>되돌리기</button></div>}
    <div className="evidence-export"><div className="evidence-section-heading"><h3><span>03</span> 증빙 정리본 만들기</h3><FileCheck2 size={21}/></div><div className="evidence-total"><span>입력한 지출 합계<small>환급 예상액이 아니에요</small></span><strong>{summary.total.toLocaleString('ko-KR')}<span>원</span></strong></div><p className="evidence-hint">금액 입력 {summary.entered}건{summary.missing > 0 ? ` · 미입력 ${summary.missing}건` : ''} · 방문 사진은 합계에서 제외</p>{summary.invalid > 0 && <p className="evidence-field-error" role="alert">금액 형식을 확인해 주세요. 잘못 입력된 금액은 합계에서 제외되며 수정 후 정리본을 만들 수 있어요.</p>}<Button ref={previewButton} className="button full-button" disabled={!items.length || busy || summary.invalid > 0} onClick={() => setPreviewOpen(true)}><Files size={18}/> 정리본 미리보기 <ArrowRight size={18}/></Button><p className="evidence-export-help">사진과 입력 내용을 묶은 HTML 문서로 저장해요.<br/>공식 제출 양식과 필요한 원본은 지자체 공고에서 확인해 주세요.</p></div>
    <Dialog open={previewOpen} onOpenChange={setPreviewOpen}><DialogContent className="evidence-preview-dialog" onCloseAutoFocus={event => { event.preventDefault(); previewButton.current?.focus() }}><DialogHeader><DialogTitle>증빙 정리본 미리보기</DialogTitle><DialogDescription>아래 내용을 확인한 뒤 이미지가 포함된 정리본을 저장하세요.</DialogDescription></DialogHeader><div className="evidence-document"><span className="evidence-eyebrow">반값루트 · MY TRAVEL FILE</span><h2>{context.region}<br/>여행 증빙 정리본</h2><p>{context.date} ~ {context.endDate} · {context.people}명</p><div className="document-stats"><span>첨부 자료<strong>{items.length}개</strong></span><span>입력한 지출 합계<strong>{summary.total.toLocaleString('ko-KR')}원</strong></span></div>{(incomplete > 0 || summary.missing > 0) && <div className="evidence-preview-note"><Info size={17}/><span>장소·날짜 확인 {incomplete}건 · 금액 미입력 {summary.missing}건<br/>빈 항목은 ‘미입력’으로 저장돼요. 뒤로 돌아가 보완할 수 있어요.</span></div>}<ol className="document-attachments">{items.map(item => <li key={item.id}><img src={item.dataUrl} alt={item.name}/><div><span>{evidenceKinds[item.kind].label}</span><strong>{item.place || '장소 미입력'}</strong><p>{item.date || '날짜 미입력'}{item.kind !== 'visit' ? ` · ${parseAmount(item.amount) === null ? '금액 미입력' : `${parseAmount(item.amount)!.toLocaleString('ko-KR')}원`}` : ''}</p>{item.memo && <p>{item.memo}</p>}<small>{item.name}</small></div></li>)}</ol><p className="document-disclaimer">직접 작성한 증빙 정리본이며 지자체 공식 양식이 아닙니다.<br/>자료의 인정 여부와 제출 방법은 공식 공고를 확인해 주세요.</p></div><div className="evidence-preview-actions"><Button className="evidence-secondary" onClick={() => setPreviewOpen(false)}>내용 수정</Button><Button className="button" onClick={download}><ArrowDownToLine size={18}/> 정리본 다운로드</Button></div><p className="evidence-export-help">HTML 파일을 브라우저에서 열면 원본 이미지까지 확인하고 인쇄할 수 있어요.</p><p className="sr-only" role="status">{feedback}</p></DialogContent></Dialog>
    <Dialog open={!!imageItem} onOpenChange={open => { if (!open) setImageItem(null) }}><DialogContent className="evidence-image-dialog" onCloseAutoFocus={event => { event.preventDefault(); imageTrigger.current?.focus() }}><DialogHeader><DialogTitle>첨부 이미지 확인</DialogTitle><DialogDescription>{imageItem?.name}</DialogDescription></DialogHeader>{imageItem && <img src={imageItem.dataUrl} alt={imageItem.name}/>}</DialogContent></Dialog>
  </section>
}
