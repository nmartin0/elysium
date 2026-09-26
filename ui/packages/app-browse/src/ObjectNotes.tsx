/**
 * What people have written about this object.
 *
 * An ontology records facts and has nowhere for judgements -- "we
 * waived the fee because their branch flooded in March". That is
 * exactly what the next operator needs, and today it lives in email.
 *
 * SHARED WITH THE AUTHOR'S ROLE, not private, which is the whole
 * point: a note nobody else can read helps nobody, and remembering it
 * yourself was already an option.
 */

import { useState } from 'react'
import { Button, TextArea } from '@blueprintjs/core'
import AsyncPanel from '@elysium/shell-api/components/AsyncPanel'
import ErrorState from '@elysium/shell-api/components/ErrorState'
import { createObjectNote, getErrorMessage, getObjectNotes, handleIfSessionExpired } from '@elysium/shell-api/api'
import { useFetchOnce } from '@elysium/shell-api/useFetchOnce'
import { formatTimestamp } from '@elysium/shell-api/format'

interface Note {
  id: string
  text: string
  author: string
  created_at: string
}

export default function ObjectNotes({
  objectType,
  objectId,
  onSessionExpired,
}: {
  objectType: string
  objectId: string
  onSessionExpired: () => void
}) {
  const { data, error } = useFetchOnce<Note[]>(() => getObjectNotes(objectType, objectId), onSessionExpired)
  /**
   * Notes added since load, held separately from the fetched list.
   *
   * useFetchOnce does not refetch, deliberately -- so a new note is
   * appended locally rather than re-reading the whole list. The server
   * is still the authority; this only avoids a round trip to display
   * something it just confirmed.
   */
  const [added, setAdded] = useState<Note[]>([])
  const [text, setText] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  async function submit() {
    if (!text.trim()) return
    setSaving(true)
    setSaveError(null)
    try {
      const created = (await createObjectNote(objectType, objectId, text)) as Note
      setAdded([...added, created])
      setText('')
    } catch (err: unknown) {
      // F-31. The READ above routes a 401 through useFetchOnce; this
      // write did not, so an expired session printed "Invalid or
      // expired session" beside the box and left the person there --
      // still typing, already logged out, with nothing telling them
      // to sign in again. Every other write path in app-browse
      // already called this; this was the one that did not.
      if (handleIfSessionExpired(err, onSessionExpired)) return
      setSaveError(getErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <AsyncPanel error={error} data={data}>
      {(notes) => (
        <>
          {[...notes, ...added].map((note) => (
            <div key={note.id} className="object-notes__note">
              <p className="object-notes__text">{note.text}</p>
              {/* The full ISO stays in the title, so the exact moment
                  is one hover away without six digits of microseconds
                  on screen. Formatting is a DISPLAY choice; the data
                  keeps its precision. */}
              <p className="object-notes__meta" title={note.created_at}>
                {note.author} · {formatTimestamp(note.created_at)}
              </p>
            </div>
          ))}

          {notes.length + added.length === 0 && (
            <p className="object-notes__empty">Nothing has been written about this yet.</p>
          )}

          {saveError && <ErrorState>{saveError}</ErrorState>}

          <TextArea
            aria-label="New note"
            placeholder="Why did this happen? What should the next person know?"
            value={text}
            onChange={(e) => setText(e.currentTarget.value)}
            fill
            rows={2}
          />
          <Button
            icon="add"
            onClick={submit}
            loading={saving}
            /* Disabled on whitespace, matching the server's own
               rejection -- a control that submits something the server
               refuses teaches the user nothing. */
            disabled={!text.trim()}
          >
            Add note
          </Button>
        </>
      )}
    </AsyncPanel>
  )
}
