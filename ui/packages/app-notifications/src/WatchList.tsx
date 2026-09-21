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
import { useCallback, useEffect, useState } from 'react'

interface WatchListProps {
  onSessionExpired: () => void
}

/** What a trigger watches for, in the words it was made with. */
function describe(trigger: Trigger): string {
  if (trigger.above !== null) return `above ${trigger.above}`
  if (trigger.gained !== null) return `gaining ${trigger.gained} or more`
  if (trigger.fell !== null) return `losing ${trigger.fell} or more`
  return 'watching'
}

export default function WatchList({ onSessionExpired }: WatchListProps) {
  const [triggers, setTriggers] = useState<Trigger[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setTriggers(await getTriggers())
      setError(null)
    } catch (caught: unknown) {
      if (handleIfSessionExpired(caught, onSessionExpired)) return
      setError(getErrorMessage(caught))
    }
  }, [onSessionExpired])

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
      if (handleIfSessionExpired(caught, onSessionExpired)) return
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
