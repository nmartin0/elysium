/**
 * Live updates: "a <Type> was <verb>", from GET /api/events.
 *
 * A HINT CARRIES NO DATA, by design (core/change_hints.py). It says a
 * type changed; the screen then refetches through the same authorised
 * routes it always uses. Nothing here ever displays a value it was sent,
 * because none is sent.
 *
 * ONE CONNECTION PER TAB, shared. Every screen that cares subscribes to
 * the same EventSource, opened on the first subscriber and closed after
 * the last -- a browser allows only six HTTP/1.1 connections per origin,
 * and one stream per component would spend them.
 *
 * THE SERVER ENDS EACH STREAM after a few minutes so that the reconnect
 * re-authenticates; EventSource reconnects on its own, so nothing here
 * has to. A 401 is a failed connection, which EventSource does NOT
 * retry -- so an expired session goes quiet rather than hammering.
 *
 * AND "YOUR INBOX CHANGED" (16 October): an `inbox` event, sent only to
 * the person whose inbox it is, with no content. The badge and the
 * notifications list re-read through their own routes when it arrives,
 * so an alert shows when it is written rather than at the next poll.
 */

import { useCallback, useEffect, useState } from 'react'

export interface ChangeHint {
  object_type: string
  change: 'created' | 'updated' | 'deleted'
}

type Listener = (hint: ChangeHint) => void

const listeners = new Set<Listener>()
const inboxListeners = new Set<() => void>()
let source: EventSource | null = null

function open(): void {
  if (source !== null || typeof EventSource === 'undefined') return
  source = new EventSource('/api/events', { withCredentials: true })
  source.addEventListener('change', (event) => {
    let hint: ChangeHint
    try {
      hint = JSON.parse((event as MessageEvent<string>).data) as ChangeHint
    } catch {
      return
    }
    for (const listener of listeners) listener(hint)
  })
  source.addEventListener('inbox', () => {
    for (const listener of inboxListeners) listener()
  })
}

function closeIfUnused(): void {
  if (listeners.size === 0 && inboxListeners.size === 0) close()
}

function close(): void {
  source?.close()
  source = null
}

/** Called for every hint while subscribed. Returns the unsubscribe. */
export function subscribeToChanges(listener: Listener): () => void {
  listeners.add(listener)
  open()
  return () => {
    listeners.delete(listener)
    closeIfUnused()
  }
}

/** Called whenever the server says this person's inbox changed.
 *  Shares the one connection. Returns the unsubscribe. */
export function subscribeToInbox(listener: () => void): () => void {
  inboxListeners.add(listener)
  open()
  return () => {
    inboxListeners.delete(listener)
    closeIfUnused()
  }
}

/**
 * Whether `objectType` has changed since the screen last showed it.
 *
 * A FLAG, NOT AN AUTOMATIC REFETCH. Results that reorder under somebody's
 * cursor while they read are worse than results a click away from
 * current -- so the screen offers a refresh, and `acknowledge` clears the
 * flag when it has taken it.
 */
export function useChangedSince(objectType: string | null): { changed: boolean; acknowledge: () => void } {
  // WHICH TYPE was flagged, not a boolean: moving to another type then
  // reads as unchanged without an effect having to reset anything.
  const [changedType, setChangedType] = useState<string | null>(null)

  useEffect(() => {
    if (!objectType) return undefined
    return subscribeToChanges((hint) => {
      if (hint.object_type === objectType) setChangedType(objectType)
    })
  }, [objectType])

  const acknowledge = useCallback(() => setChangedType(null), [])
  return { changed: objectType !== null && changedType === objectType, acknowledge }
}
