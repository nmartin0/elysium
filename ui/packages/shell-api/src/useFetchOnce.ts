/**
 * useFetchOnce -- load something on mount, once, and stop caring if
 * the component goes away first.
 *
 * Every screen that reads one thing from the API wrote the same
 * fifteen lines: a cancelled flag, a then that checks it, a catch that
 * checks it AND routes a session expiry before showing an error, and a
 * cleanup that sets it. DeploymentConfig and Silos were
 * character-for-character identical apart from the call and the type.
 *
 * WHY THE CANCELLED FLAG MATTERS, since it is the part most easily
 * dropped: a fetch that resolves after unmount sets state on a
 * component that no longer exists. React warns rather than crashes, so
 * it survives review easily and shows up as a console full of noise
 * nobody reads.
 *
 * AND WHY SESSION EXPIRY IS HANDLED HERE. An expired session is not an
 * error to display -- it is a redirect to the login screen. Showing
 * "401 Unauthorized" in a red box tells the user something true and
 * useless. Every caller got this right individually; getting it right
 * once is better.
 *
 * NOT A CACHE, and deliberately not. getVisibleActionTypesCached
 * exists for the one thing two screens both need; adding caching here
 * would make every caller's refetch behaviour a question, and most of
 * them have no reason to refetch at all.
 *
 * NOT FOR PARALLEL LOADS. ChartsPanel fetches one aggregate per field
 * and needs Promise.all with its own error handling -- forcing it
 * through this would mean an option nobody else passes.
 */

import { useEffect, useRef, useState } from 'react'

import { getErrorMessage, handleIfSessionExpired } from './api'

export interface FetchOnceResult<T> {
  data: T | null
  error: string | null
}

export function useFetchOnce<T>(
  fetcher: () => Promise<unknown>,
  onSessionExpired: () => void,
): FetchOnceResult<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)

  /**
   * Held in a ref so the effect depends on NEITHER argument.
   *
   * This project has had this bug before: an effect depending on
   * onSessionExpired refetched the schema three times per page load,
   * because the shell passes a new arrow on every render. A caller
   * cannot be expected to memoise a callback to stop a hook called
   * "once" from running repeatedly -- so the hook takes that on.
   */
  const latest = useRef({ fetcher, onSessionExpired })
  latest.current = { fetcher, onSessionExpired }

  useEffect(() => {
    let cancelled = false
    latest.current.fetcher()
      .then((body) => {
        if (!cancelled) setData(body as T)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        if (handleIfSessionExpired(err, latest.current.onSessionExpired)) return
        setError(getErrorMessage(err))
      })
    return () => {
      cancelled = true
    }
    // NO dependencies. "Once" is the contract and the name says so;
    // both arguments are read through the ref above, so a caller
    // passing inline arrows -- which every one of them does -- cannot
    // turn this into a loop.
  }, [])

  return { data, error }
}
