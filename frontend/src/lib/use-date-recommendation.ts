import { useEffect, useRef, useState } from 'react'
import { type DateRecommendResponse, fetchRecommendations, regionRequest, validateDates } from './date-recommendations.ts'
import { today } from './benefits.ts'

export type DateRec = { status: 'idle' | 'loading' | 'done' | 'error'; data: DateRecommendResponse | null; error: string; retry: () => void }

/**
 * One POST /api/team/date-recommendations for the slingshot destination and the confirmed trip dates.
 * Festivals and support programs on step 3/4 both read this result, so they always describe the same
 * region and period. Disabled (idle) until the dates were confirmed in the existing trip inputs.
 * A late response for an older region/period is ignored.
 */
export function useDateRecommendation(code: string | null, start: string, end: string, enabled: boolean): DateRec {
  const [state, setState] = useState<Omit<DateRec, 'retry'>>({ status: 'idle', data: null, error: '' })
  const [attempt, setAttempt] = useState(0)
  const latest = useRef(0)
  useEffect(() => {
    const id = ++latest.current
    const mine = (next: Omit<DateRec, 'retry'>) => { if (id === latest.current) setState(next) }
    const controller = new AbortController()
    if (!enabled) { mine({ status: 'idle', data: null, error: '' }); return () => controller.abort() }
    const invalid = !code ? '선택한 여행지의 지역 코드를 찾지 못했어요.' : validateDates(start, end, today())
    if (invalid) { mine({ status: 'error', data: null, error: invalid }); return () => controller.abort() }
    mine({ status: 'loading', data: null, error: '' })
    const timeout = window.setTimeout(() => controller.abort(), 20000)
    fetchRecommendations(regionRequest(code!, start, end), controller.signal)
      .then(data => mine({ status: 'done', data, error: '' }))
      .catch(e => mine({ status: 'error', data: null,
        error: (e as Error).name === 'AbortError' ? '응답이 늦어 요청을 멈췄어요. 다시 시도해 주세요.' : (e as Error).message }))
      .finally(() => clearTimeout(timeout))
    return () => { clearTimeout(timeout); controller.abort() }
  }, [code, start, end, enabled, attempt])
  return { ...state, retry: () => setAttempt(value => value + 1) }
}
