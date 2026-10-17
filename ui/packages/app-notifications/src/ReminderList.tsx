/**
 * ReminderList -- the reminders this person set, and making another
 * (17 October).
 *
 * A reminder is a timer that notifies its maker (core/reminders.py):
 * once at a moment, or repeating -- every so many minutes or hours, or
 * on chosen weekdays at a time. BESIDE THE NOTIFICATIONS IT PRODUCES,
 * for the reason the Watching tab is: "what will tell me" next to "what
 * have I been told".
 *
 * IN THE BROWSER'S OWN TIME ZONE, sent with every reminder, so "09:00
 * on weekdays" stays nine on this person's clock when the clocks change
 * -- the server keeps the rule in that zone, not in UTC.
 *
 * WHAT HAPPENS IF ELYSIUM WAS DOWN WHEN IT WAS DUE is asked, not
 * assumed: by default a reminder more than an hour late is reported as
 * missed rather than delivered as if on time; "deliver however late" is
 * the other answer.
 *
 * EVERYTHING HERE IS THIS PERSON'S OWN, and the server's refusals --
 * a time already passed, a repeat too frequent -- are shown in its words.
 */

import { Button, Card, CardList, Checkbox, FormGroup, HTMLSelect, InputGroup, NumericInput } from '@blueprintjs/core'
import {
  cancelReminder,
  createReminder,
  type CreateReminder,
  getErrorMessage,
  getReminders,
  handleIfSessionExpired,
  type Reminder,
} from '@elysium/shell-api/api'
import EmptyState from '@elysium/shell-api/components/EmptyState'
import ErrorState from '@elysium/shell-api/components/ErrorState'
import LoadingState from '@elysium/shell-api/components/LoadingState'
import { formatTimestamp } from '@elysium/shell-api/format'
import { useCallback, useEffect, useRef, useState } from 'react'

interface ReminderListProps {
  onSessionExpired: () => void
}

type When = 'once' | 'every' | 'days'

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

/** The browser's own IANA zone; UTC where it cannot say. */
function browserZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  } catch {
    return 'UTC'
  }
}

export default function ReminderList({ onSessionExpired }: ReminderListProps) {
  const [reminders, setReminders] = useState<Reminder[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [refused, setRefused] = useState<string | null>(null)

  const [label, setLabel] = useState('')
  const [when, setWhen] = useState<When>('once')
  const [at, setAt] = useState('')
  const [every, setEvery] = useState(1)
  const [unit, setUnit] = useState<'minutes' | 'hours'>('hours')
  const [days, setDays] = useState<number[]>([0, 1, 2, 3, 4])
  const [time, setTime] = useState('09:00')
  const [lateness, setLateness] = useState<'missed' | 'always'>('missed')

  // The session callback through a ref, so `load` has no dependencies
  // and runs once -- the pattern WatchList's own notes explain.
  const latestSessionExpired = useRef(onSessionExpired)
  useEffect(() => {
    latestSessionExpired.current = onSessionExpired
  })

  const load = useCallback(async () => {
    try {
      setReminders(await getReminders())
      setError(null)
    } catch (caught: unknown) {
      if (handleIfSessionExpired(caught, latestSessionExpired.current)) return
      setError(getErrorMessage(caught))
    }
  }, [])

  useEffect(() => {
    // The same false positive WatchList documents: every setState in
    // `load` happens after an await. Fetching on mount.
    // eslint-disable-next-line react/set-state-in-effect
    void load()
  }, [load])

  function request(): CreateReminder | null {
    const base = {
      label: label.trim(),
      timezone: browserZone(),
      late_after_minutes: lateness === 'missed' ? 60 : null,
    }
    if (when === 'once') {
      if (at === '') return null
      // datetime-local is the BROWSER'S wall time; toISOString gives the
      // same instant in UTC with its offset, which the server requires.
      return { ...base, at: new Date(at).toISOString() }
    }
    if (when === 'every') {
      return { ...base, repeat: { every_minutes: unit === 'hours' ? every * 60 : every } }
    }
    if (days.length === 0) return null
    return { ...base, repeat: { days: [...days].sort(), time } }
  }

  const body = request()

  async function make() {
    if (body === null || body.label === '') return
    try {
      await createReminder(body)
      setRefused(null)
      setLabel('')
      await load()
    } catch (caught: unknown) {
      if (handleIfSessionExpired(caught, latestSessionExpired.current)) return
      // THE SERVER'S REASON, in its words: "That time has already
      // passed", "Repeat every 5 minutes to ...".
      setRefused(getErrorMessage(caught))
    }
  }

  async function cancel(reminderId: string) {
    try {
      await cancelReminder(reminderId)
      await load()
    } catch (caught: unknown) {
      if (handleIfSessionExpired(caught, latestSessionExpired.current)) return
      setError(getErrorMessage(caught))
    }
  }

  const toggleDay = (day: number) =>
    setDays((current) => (current.includes(day) ? current.filter((d) => d !== day) : [...current, day]))

  return (
    <div className="reminders">
      <Card className="reminders__new">
        <FormGroup label="Remind me to" labelFor="reminder-label">
          <InputGroup
            id="reminder-label"
            value={label}
            maxLength={200}
            placeholder="e.g. Review overdue invoices"
            onChange={(e) => setLabel(e.currentTarget.value)}
          />
        </FormGroup>
        <div className="reminders__when">
          <HTMLSelect aria-label="When" value={when} onChange={(e) => setWhen(e.currentTarget.value as When)}>
            <option value="once">once, at</option>
            <option value="every">every</option>
            <option value="days">on</option>
          </HTMLSelect>
          {when === 'once' && (
            <InputGroup
              aria-label="At"
              type="datetime-local"
              value={at}
              onChange={(e) => setAt(e.currentTarget.value)}
            />
          )}
          {when === 'every' && (
            <>
              <NumericInput aria-label="Every" min={1} value={every} onValueChange={(value) => setEvery(value)} />
              <HTMLSelect
                aria-label="Every unit"
                value={unit}
                onChange={(e) => setUnit(e.currentTarget.value as 'minutes' | 'hours')}
              >
                <option value="minutes">minutes</option>
                <option value="hours">hours</option>
              </HTMLSelect>
            </>
          )}
          {when === 'days' && (
            <>
              {WEEKDAYS.map((name, day) => (
                <Checkbox key={name} inline label={name} checked={days.includes(day)} onChange={() => toggleDay(day)} />
              ))}
              <InputGroup
                aria-label="At time"
                type="time"
                value={time}
                onChange={(e) => setTime(e.currentTarget.value)}
              />
            </>
          )}
        </div>
        <HTMLSelect
          aria-label="If Elysium was down when it was due"
          value={lateness}
          onChange={(e) => setLateness(e.currentTarget.value as 'missed' | 'always')}
        >
          <option value="missed">if more than an hour late, tell me I missed it</option>
          <option value="always">deliver it however late</option>
        </HTMLSelect>
        <p className="reminders__zone">Times are in {browserZone()}.</p>
        {refused !== null && <ErrorState>{refused}</ErrorState>}
        <Button icon="time" onClick={() => void make()} disabled={body === null || label.trim() === ''}>
          Set reminder
        </Button>
      </Card>

      {error !== null && <ErrorState>{error}</ErrorState>}
      {error === null && reminders === null && <LoadingState />}
      {reminders !== null && reminders.length === 0 && (
        <EmptyState icon="time" title="No reminders" reason="Set one above: once, or on a repeat." />
      )}
      {reminders !== null && reminders.length > 0 && (
        <CardList>
          {reminders.map((reminder) => (
            <Card key={reminder.reminder_id} className="watch-list__item">
              <span>{reminder.label}</span>
              <span className="watch-list__condition">
                {reminder.repeats ?? 'once'} · next {formatTimestamp(reminder.next_at)}
              </span>
              <Button
                minimal
                small
                icon="cross"
                aria-label={`Cancel reminder ${reminder.label}`}
                onClick={() => void cancel(reminder.reminder_id)}
              />
            </Card>
          ))}
        </CardList>
      )}
    </div>
  )
}
