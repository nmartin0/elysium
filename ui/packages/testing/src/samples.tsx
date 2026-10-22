/**
 * PAGES BUILT TO PASS AND TO FAIL the conformance checks, for
 * conformance.test.tsx. Each broken page breaks exactly one thing, the
 * way a real module most plausibly would, so each check is shown to
 * catch the mistake it exists for -- and to pass the page that makes
 * none.
 */
import { getCurrentUser, getErrorMessage } from '@elysium/shell-api/api'
import AsyncPanel from '@elysium/shell-api/components/AsyncPanel'
import { useHostValues } from '@elysium/shell-api/host'
import { useFetchOnce } from '@elysium/shell-api/useFetchOnce'
import { useEffect, useState } from 'react'

/** What a page should be: the kit's fetch hook and panel, and a
 *  listener it takes away again. */
export function GoodPage() {
  const { onSessionExpired } = useHostValues()
  const { data, error } = useFetchOnce<unknown>(getCurrentUser, onSessionExpired)
  useEffect(() => {
    const onResize = () => {}
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])
  return (
    <AsyncPanel data={data} error={error}>
      {() => <p>signed in</p>}
    </AsyncPanel>
  )
}

/** Renders nothing at all. */
export function BlankPage() {
  return null
}

/** Fetches, and shows nothing until the answer comes. */
export function SilentWhileLoadingPage() {
  const [data, setData] = useState<unknown>(null)
  useEffect(() => {
    getCurrentUser().then(setData, () => {})
  }, [])
  return <p>{data === null ? '' : 'signed in'}</p>
}

/** Shows a failure, but as plain text nobody is told about. */
export function UnannouncedErrorPage() {
  const { onSessionExpired } = useHostValues()
  const { data, error } = useFetchOnce<unknown>(getCurrentUser, onSessionExpired)
  if (error !== null) return <p>{error}</p>
  return (
    <AsyncPanel data={data} error={null}>
      {() => <p>signed in</p>}
    </AsyncPanel>
  )
}

/** Treats an expired session as one more error to display. */
export function IgnoresSessionExpiryPage() {
  const [error, setError] = useState<string | null>(null)
  const [data, setData] = useState<unknown>(null)
  useEffect(() => {
    getCurrentUser().then(setData, (e: unknown) => setError(getErrorMessage(e)))
  }, [])
  return (
    <AsyncPanel data={data} error={error}>
      {() => <p>signed in</p>}
    </AsyncPanel>
  )
}

/** Polls, and never stops. */
export function LeavesAnIntervalPage() {
  useEffect(() => {
    window.setInterval(() => {}, 60_000)
  }, [])
  return <GoodPage />
}

/** Listens on the document, and never stops. */
export function LeavesAListenerPage() {
  useEffect(() => {
    document.addEventListener('keydown', () => {})
  }, [])
  return <GoodPage />
}
