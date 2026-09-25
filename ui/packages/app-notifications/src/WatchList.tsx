/**
 * WatchList -- the conditions this person asked to be told about.
 *
 * BESIDE THE NOTIFICATIONS THEY PRODUCE, because those are the same
 * question from two ends: "what have I been told" and "what will tell
 * me". Somebody silencing a noisy trigger arrives here from the
 * notice it sent, and a separate screen would make them go looking.
 *
 * DISABLE RATHER THAN DELETE is offered first: somebody quieting a
 * trigger usually wants it back.
 *
 * EVERYTHING HERE IS THIS PERSON'S OWN. A trigger runs as its owner
 * and notifies only its owner, so there is nothing to filter and no
 * grant to check.
 */

import { Button, Card, CardList, NonIdealState, Switch } from '@blueprintjs/core'
import {
  deleteTrigger,
  getErrorMessage,
  getTriggers,
  handleIfSessionExpired,
  setTriggerEnabled,
  type Trigger,
} from '@elysium/shell-api/api'
import ErrorState from '@elysium/shell-api/components/ErrorState'
import LoadingState from '@elysium/shell-api/components/LoadingState'
import { useCallback, useEffect, useRef, useState } from 'react'

interface WatchListProps {
  onSessionExpired: () => void
}

/** What a trigger watches for, and what it does -- in the words it
 *  was made with.
 *
 *  WHAT IT DOES IS SAID, NOT JUST WHAT IT WATCHES. A trigger that
 *  proposes writes looking identical to one that only notifies would
 *  hide the one fact somebody reviewing their list most needs. */
function describe(trigger: Trigger): string {
  let condition = 'watching'
  if (trigger.above !== null) condition = `above ${trigger.above}`
  else if (trigger.gained !== null) condition = `gaining ${trigger.gained} or more`
  else if (trigger.fell !== null) condition = `losing ${trigger.fell} or more`

  const parts = [condition]
  const roles = trigger.recipient_roles ?? []
  if (roles.length > 0) parts.push(`also tells ${roles.join(', ')}`)
  if (trigger.action_type) parts.push(`proposes ${trigger.action_type}`)
  return parts.join(' · ')
}

export default function WatchList({ onSessionExpired }: WatchListProps) {
  const [triggers, setTriggers] = useState<Trigger[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  /**
   * The session callback through a ref, so `load` has NO dependencies
   * and the effect below runs once.
   *
   * MEASURED BEFORE THE FIX: three renders of the parent, three
   * fetches. App.tsx declares handleSessionExpired as a plain function
   * inside the component, so it is a new identity on every render;
   * `load` was built with useCallback([onSessionExpired]) and run from
   * useEffect([load]), so each parent render rebuilt `load` and
   * refired the effect. Exactly the bug useFetchOnce's own notes
   * record -- the schema fetched three times per page load -- in a
   * panel that does not use useFetchOnce because it needs to REFETCH
   * after an action.
   */
  const latestSessionExpired = useRef(onSessionExpired)
  useEffect(() => {
    latestSessionExpired.current = onSessionExpired
  })

  const load = useCallback(async () => {
    try {
      setTriggers(await getTriggers())
      setError(null)
    } catch (caught: unknown) {
      if (handleIfSessionExpired(caught, latestSessionExpired.current)) return
      setError(getErrorMessage(caught))
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function change(action: () => Promise<void>) {
    try {
      await action()
      // RE-READ RATHER THAN PATCH IN PLACE. The server decides; a
      // local edit that disagreed would show one thing here and
      // another after a reload.
      await load()
    } catch (caught: unknown) {
      if (handleIfSessionExpired(caught, latestSessionExpired.current)) return
      setError(getErrorMessage(caught))
    }
  }

  if (error !== null) return <ErrorState>{error}</ErrorState>
  if (triggers === null) return <LoadingState />

  if (triggers.length === 0) {
    return (
      <NonIdealState
        icon="eye-open"
        title="Not watching anything"
        description="Save a search in Browse, then choose Watch to be told when it changes."
      />
    )
  }

  return (
    <CardList>
      {triggers.map((trigger) => (
        <Card key={trigger.trigger_id} className="watch-list__item">
          <Switch
            checked={trigger.enabled}
            label={trigger.name}
            onChange={() => void change(() => setTriggerEnabled(trigger.trigger_id, !trigger.enabled))}
          />
          <span className="watch-list__condition">{describe(trigger)}</span>
          <Button
            minimal
            small
            icon="cross"
            aria-label={`Stop watching ${trigger.name}`}
            onClick={() => void change(() => deleteTrigger(trigger.trigger_id))}
          />
        </Card>
      ))}
    </CardList>
  )
}
