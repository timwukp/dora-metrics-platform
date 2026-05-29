import { useEffect, useRef, useState } from 'react'

/**
 * useApi(fetchFn, deps)
 *
 * - `fetchFn` is captured in a ref so callers can pass an inline arrow
 *   without forcing a refetch every render. Refetches happen only when
 *   `deps` actually change.
 * - 503 is treated as a transient state ("backend not ready") and surfaced
 *   to the caller as `notReady: true` so the UI can render a friendly
 *   "warming up" hint and retry once after a short delay rather than
 *   showing a hard error toast.
 */
const RETRY_AFTER_MS = 4000

export function useApi(fetchFn, deps = []) {
  const fnRef = useRef(fetchFn)
  fnRef.current = fetchFn

  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [notReady, setNotReady] = useState(false)

  useEffect(() => {
    let cancelled = false
    let retryHandle = null

    const run = () => {
      setLoading(true)
      fnRef.current()
        .then((result) => {
          if (cancelled) return
          setData(result)
          setError(null)
          setNotReady(false)
        })
        .catch((err) => {
          if (cancelled) return
          if (err?.status === 503) {
            setNotReady(true)
            setError(null)
            retryHandle = setTimeout(run, RETRY_AFTER_MS)
          } else {
            setError(err?.message || 'Unknown error')
            setNotReady(false)
          }
        })
        .finally(() => {
          if (!cancelled) setLoading(false)
        })
    }
    run()

    return () => {
      cancelled = true
      if (retryHandle) clearTimeout(retryHandle)
    }
    // We deliberately do not include `fetchFn` in deps — it's read via the
    // ref so a new function identity every render does not refetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return { data, loading, error, notReady }
}
