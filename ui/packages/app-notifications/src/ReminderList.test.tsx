/**
 * The Reminders tab (17 October): what a person asks for reaches the
 * server in the shape it takes, in their own time zone, and the
 * server's refusal is shown in its words.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return { ...actual, getReminders: vi.fn(), createReminder: vi.fn(), cancelReminder: vi.fn() }
})

import { ApiError, cancelReminder, createReminder, getReminders } from '@elysium/shell-api/api'
import ReminderList from './ReminderList'

// A ZONE THAT IS NOT THE TEST MACHINE'S, so sending UTC regardless
// would fail here rather than pass by coincidence on a UTC runner.
const ZONE = 'America/Chicago'

beforeEach(() => {
  vi.clearAllMocks()
  const real = Intl.DateTimeFormat.prototype.resolvedOptions
  vi.spyOn(Intl.DateTimeFormat.prototype, 'resolvedOptions').mockImplementation(function (this: Intl.DateTimeFormat) {
    return { ...real.call(this), timeZone: ZONE }
  })
  vi.mocked(getReminders).mockResolvedValue([])
  vi.mocked(cancelReminder).mockResolvedValue(undefined)
  vi.mocked(createReminder).mockResolvedValue({} as never)
})

function setUp() {
  render(<ReminderList onSessionExpired={() => {}} />)
  fireEvent.change(screen.getByLabelText('Remind me to'), { target: { value: 'Stand-up' } })
}

describe('making one', () => {
  it("weekdays at a time, in the browser's zone", async () => {
    setUp()
    fireEvent.change(screen.getByLabelText('When'), { target: { value: 'days' } })
    fireEvent.change(screen.getByLabelText('At time'), { target: { value: '09:30' } })
    fireEvent.click(screen.getByRole('button', { name: /Set reminder/ }))

    await waitFor(() =>
      expect(createReminder).toHaveBeenCalledWith({
        label: 'Stand-up',
        timezone: ZONE,
        late_after_minutes: 60,
        repeat: { days: [0, 1, 2, 3, 4], time: '09:30' },
      }),
    )
  })

  it('every N hours, sent in minutes', async () => {
    setUp()
    fireEvent.change(screen.getByLabelText('When'), { target: { value: 'every' } })
    fireEvent.change(screen.getByLabelText('Every'), { target: { value: '2' } })
    fireEvent.change(screen.getByLabelText('If Elysium was down when it was due'), { target: { value: 'always' } })
    fireEvent.click(screen.getByRole('button', { name: /Set reminder/ }))

    await waitFor(() =>
      expect(createReminder).toHaveBeenCalledWith(
        expect.objectContaining({ repeat: { every_minutes: 120 }, late_after_minutes: null }),
      ),
    )
  })

  it('once, as an instant with its offset', async () => {
    setUp()
    fireEvent.change(screen.getByLabelText('At'), { target: { value: '2030-01-02T09:00' } })
    fireEvent.click(screen.getByRole('button', { name: /Set reminder/ }))

    await waitFor(() =>
      expect(createReminder).toHaveBeenCalledWith(
        expect.objectContaining({ at: new Date('2030-01-02T09:00').toISOString() }),
      ),
    )
  })

  it("shows the server's refusal in its words", async () => {
    vi.mocked(createReminder).mockRejectedValue(new ApiError(400, 'That time has already passed.'))
    setUp()
    fireEvent.change(screen.getByLabelText('At'), { target: { value: '2001-01-01T09:00' } })
    fireEvent.click(screen.getByRole('button', { name: /Set reminder/ }))

    expect(await screen.findByText(/already passed/)).toBeTruthy()
  })
})

it('lists them and cancels one', async () => {
  vi.mocked(getReminders).mockResolvedValue([
    {
      reminder_id: 'r1',
      label: 'Stand-up',
      next_at: '2030-01-02T09:00:00+00:00',
      timezone: 'UTC',
      repeats: 'weekdays at 09:00 (UTC)',
      late_after_minutes: 60,
    },
  ])
  render(<ReminderList onSessionExpired={() => {}} />)

  expect(await screen.findByText(/weekdays at 09:00/)).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Cancel reminder Stand-up' }))

  await waitFor(() => expect(cancelReminder).toHaveBeenCalledWith('r1'))
})
