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
 * WHY THE COUNTS CANNOT COME FROM THE ANSWER INSTEAD. A denied read
 * and a genuinely NULL field return the same value, deliberately --
 * `filter_real_data` strips both and the mediator's uniform denial
 * makes them indistinguishable on purpose. A summary derived from what
 * the answer was built from could therefore say "3 values used" but
 * never "2 refused", because counting refusals from that side would
 * reconstruct exactly what uniform denial exists to hide.
 *
 * THE TRACE IS A DIFFERENT MATTER, and this is the distinction worth
 * holding. It reports the caller's OWN accesses during their OWN
 * request, which they are entitled to know: the route returns an empty
 * list for somebody else's request rather than a 403, so the response
 * never distinguishes "no such request" from "not yours". Telling you
 * that YOUR question was refused a field is the trust story. Telling
 * you a field exists that somebody ELSE could read is the leak, and
 * nothing here does that.
 */

import StatusTag from '@elysium/shell-api/components/StatusTag'

interface TraceEntry {
  rbac_allowed: boolean
  mac_allowed: boolean | null
}

export default function TraceSummary({ entries }: { entries: TraceEntry[] }) {
  if (entries.length === 0) return null

  const refused = entries.filter((entry) => !entry.rbac_allowed || entry.mac_allowed === false).length
  const served = entries.length - refused

  return (
    <p className="answer-trace__summary">
      <StatusTag state="granted">{served} served</StatusTag>{' '}
      {refused > 0 && <StatusTag state="refused">{refused} refused</StatusTag>}{' '}
      <span className="answer-trace__summary-note">
        {refused > 0
          ? 'A refusal is a normal answer: the question asked for something your grants do not cover.'
          : 'Every field this answer needed was one you may read.'}
      </span>
    </p>
  )
}
