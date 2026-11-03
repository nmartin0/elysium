/**
 * What the trace adds up to, in one line, above the table.
 *
 * WHY A SUMMARY AND NOT AN EAGER FETCH. The obvious move was to load
 * the trace with the answer and show its headline always. AnswerTrace
 * deliberately does not: "a trace is read rarely and costs a log scan;
 * fetching one for every answer would make the common case pay for the
 * uncommon one." That reasoning still holds, so the trace stays lazy
 * and this summarises it once somebody has asked for it.
 *
 * THE TRACE LISTS WHAT WAS GRANTED AND NOTHING ELSE. It used to count
 * refusals too, and each refused read carried the object it was
 * refused. That was a way to read back which of a caller's guesses
 * touched something hidden from them, so the route no longer returns a
 * refusal in any form. A denied read and a genuinely NULL field return
 * the same value, deliberately, and a summary must not undo that: it
 * says how many reads were served and nothing about what was not.
 */

import StatusTag from '@elysium/shell-api/components/StatusTag'

export default function TraceSummary({ count }: { count: number }) {
  if (count === 0) return null

  return (
    <p className="answer-trace__summary">
      <StatusTag state="granted">{count} served</StatusTag>{' '}
      <span className="answer-trace__summary-note">
        Only the reads you were granted are listed. A field your grants do not cover is simply absent.
      </span>
    </p>
  )
}
