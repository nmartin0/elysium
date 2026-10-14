/**
 * What people asked Elysium to remember about this object (E-14).
 *
 * NOT NOTES, though it looks like them. A note is for the next PERSON
 * and is never shown to the agent; a memory is for the next QUESTION:
 * when Query reads this object, the fresh memories go with it. That
 * difference is why this has its own section and its own wording.
 *
 * WRITTEN HERE AND ONLY HERE, by a person. The owner's rule (14 Oct):
 * nothing is remembered because the model judged it worth keeping.
 *
 * STALE ONES ARE SHOWN, marked. A field it was written from has changed
 * since, so the agent no longer receives it -- and this page is where a
 * person sees that and forgets it, or writes it again.
 */

import { useState } from 'react'
import { Button, Tag, TextArea } from '@blueprintjs/core'
import AsyncPanel from '@elysium/shell-api/components/AsyncPanel'
import ErrorState from '@elysium/shell-api/components/ErrorState'
import {
  forgetMemory,
  getErrorMessage,
  getObjectMemories,
  handleIfSessionExpired,
  rememberAboutObject,
  type ObjectMemory,
} from '@elysium/shell-api/api'
import { useFetchOnce } from '@elysium/shell-api/useFetchOnce'
import { formatTimestamp } from '@elysium/shell-api/format'

/** The server's own limit (core/memory/store.MAX_TEXT): a fact, not a document. */
const MAX_TEXT = 500

export default function ObjectMemories({
  objectType,
  objectId,
  onSessionExpired,
}: {
  objectType: string
  objectId: string
  onSessionExpired: () => void
}) {
  const { data, error } = useFetchOnce<ObjectMemory[]>(() => getObjectMemories(objectType, objectId), onSessionExpired)
  // Changes since load, applied over the fetched list -- the same
  // reasoning as ObjectNotes: useFetchOnce does not refetch, and the
  // server has just confirmed each one.
  const [added, setAdded] = useState<ObjectMemory[]>([])
  const [forgotten, setForgotten] = useState<Set<string>>(new Set())
  const [text, setText] = useState('')
  const [saving, setSaving] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  async function remember() {
    if (!text.trim()) return
    setSaving(true)
    setActionError(null)
    try {
      const created = await rememberAboutObject(objectType, objectId, text)
      setAdded([...added, created])
      setText('')
    } catch (err: unknown) {
      if (handleIfSessionExpired(err, onSessionExpired)) return
      setActionError(getErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  async function forget(memory: ObjectMemory) {
    setActionError(null)
    try {
      await forgetMemory(memory.id)
      setForgotten(new Set([...forgotten, memory.id]))
    } catch (err: unknown) {
      if (handleIfSessionExpired(err, onSessionExpired)) return
      setActionError(`Could not forget "${memory.text}": ${getErrorMessage(err)}`)
    }
  }

  return (
    <AsyncPanel error={error} data={data}>
      {(memories) => {
        const shown = [...memories, ...added].filter((memory) => !forgotten.has(memory.id))
        return (
          <>
            <p className="object-memories__explainer">
              Facts Query is given whenever it reads this object. One goes stale, and stops being given, when a field it
              was written from changes.
            </p>

            {shown.map((memory) => (
              <div
                key={memory.id}
                className={`object-memories__memory${memory.stale ? ' object-memories__memory--stale' : ''}`}
              >
                <div className="object-memories__line">
                  <p className="object-memories__text">{memory.text}</p>
                  {memory.stale && (
                    <Tag
                      minimal
                      intent="warning"
                      title="A field this was written from has changed since. Query is no longer given it."
                    >
                      stale
                    </Tag>
                  )}
                </div>
                <p className="object-memories__meta" title={memory.created_at}>
                  {memory.author} · {formatTimestamp(memory.created_at)}
                  {memory.may_forget && (
                    <Button
                      small
                      minimal
                      icon="trash"
                      aria-label={`Forget "${memory.text}"`}
                      onClick={() => forget(memory)}
                    >
                      Forget
                    </Button>
                  )}
                </p>
              </div>
            ))}

            {shown.length === 0 && <p className="object-memories__empty">Nothing is remembered about this yet.</p>}

            {actionError && <ErrorState>{actionError}</ErrorState>}

            <TextArea
              aria-label="Something to remember"
              placeholder="A fact Query should know about this, e.g. “disputed two charges in March”"
              value={text}
              onChange={(e) => setText(e.currentTarget.value)}
              maxLength={MAX_TEXT}
              fill
              rows={2}
            />
            <Button icon="lightbulb" onClick={remember} loading={saving} disabled={!text.trim()}>
              Remember
            </Button>
          </>
        )
      }}
    </AsyncPanel>
  )
}
