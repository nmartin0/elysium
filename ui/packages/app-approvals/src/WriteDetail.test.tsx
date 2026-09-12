/**
 * The diff a reviewer decides on.
 *
 * THE REDACTION IS THE POINT. A field the reviewer may not read is
 * SHOWN, named and marked -- never omitted. Omitting leaks less and is
 * worse: a reviewer seeing three fields cannot tell whether that is
 * the whole change or a fragment, so they approve believing they saw
 * everything. That produces MORE confidence rather than less, which is
 * the rubber-stamp problem in its worst form.
 */

import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return { ...actual, getWriteDetail: vi.fn() }
})

import { getWriteDetail } from '@elysium/shell-api/api'

import WriteDetail from './WriteDetail'

const mockedDetail = vi.mocked(getWriteDetail)

function detail(changes: unknown[], hasRedacted = false) {
  return {
    write_id: 'w1',
    action_type_name: 'RecategorizeTransaction',
    description: 'd',
    proposed_by: 'alice',
    proposed_at: 't',
    expires_at: 't',
    awaiting_your_review: true,
    proposed_by_you: false,
    objects: [
      {
        object_type: 'Transaction',
        object_id: '1',
        operation: 'update',
        changes,
      },
    ],
    has_redacted_fields: hasRedacted,
  }
}

beforeEach(() => vi.clearAllMocks())

describe('WriteDetail', () => {
  it('shows the current and proposed values of a readable field', async () => {
    mockedDetail.mockResolvedValue(
      detail([
        {
          field_name: 'category',
          readable: true,
          current_value: 'subscription',
          proposed_value: 'travel',
        },
      ]) as never,
    )
    render(<WriteDetail writeId="w1" onSessionExpired={vi.fn()} />)

    expect(await screen.findByText('subscription')).toBeInTheDocument()
    expect(screen.getByText('travel')).toBeInTheDocument()
  })

  it('names a redacted field rather than omitting it', async () => {
    // THE PROPERTY. The reviewer must be able to see that a field is
    // being changed even when they cannot see to what.
    mockedDetail.mockResolvedValue(
      detail(
        [
          {
            field_name: 'amount',
            readable: false,
            current_value: null,
            proposed_value: null,
          },
        ],
        true,
      ) as never,
    )
    render(<WriteDetail writeId="w1" onSessionExpired={vi.fn()} />)

    expect(await screen.findByText('amount')).toBeInTheDocument()
    expect(screen.getByText(/Hidden by your permissions/)).toBeInTheDocument()
  })

  it('warns once, prominently, that the view is partial', async () => {
    // As well as marking each row. A reviewer scanning a table can
    // miss a tag; the one thing they must not miss is that they are
    // deciding on a partial view.
    mockedDetail.mockResolvedValue(
      detail(
        [
          {
            field_name: 'amount',
            readable: false,
            current_value: null,
            proposed_value: null,
          },
        ],
        true,
      ) as never,
    )
    render(<WriteDetail writeId="w1" onSessionExpired={vi.fn()} />)

    expect(await screen.findByText(/cannot see all of this change/i)).toBeInTheDocument()
  })

  it('does NOT warn when the reviewer can see everything', async () => {
    // THE CONTROL. A banner shown always is a banner nobody reads, and
    // it would make the real warning worthless rather than merely
    // noisy.
    mockedDetail.mockResolvedValue(
      detail(
        [
          {
            field_name: 'category',
            readable: true,
            current_value: 'a',
            proposed_value: 'b',
          },
        ],
        false,
      ) as never,
    )
    render(<WriteDetail writeId="w1" onSessionExpired={vi.fn()} />)

    await screen.findByText('category')
    expect(screen.queryByText(/cannot see all of this change/i)).toBeNull()
  })

  it('renders an em dash for no value, never a blank cell', async () => {
    // A blank is ambiguous between "null", "empty string" and "this
    // failed to render" -- and in a diff the reviewer is deciding on
    // the difference between two of those.
    mockedDetail.mockResolvedValue(
      detail([
        {
          field_name: 'category',
          readable: true,
          current_value: null,
          proposed_value: 'travel',
        },
      ]) as never,
    )
    render(<WriteDetail writeId="w1" onSessionExpired={vi.fn()} />)

    expect(await screen.findByText('—')).toBeInTheDocument()
  })

  it('distinguishes an empty string from no value', async () => {
    mockedDetail.mockResolvedValue(
      detail([
        {
          field_name: 'category',
          readable: true,
          current_value: '',
          proposed_value: 'travel',
        },
      ]) as never,
    )
    render(<WriteDetail writeId="w1" onSessionExpired={vi.fn()} />)

    expect(await screen.findByText('(empty)')).toBeInTheDocument()
  })
})
