/**
 * ActiveFilters -- what is narrowing this view, said out loud.
 *
 * THE DEFECT THIS FIXES. A cross-filter was applied and rendered
 * nowhere in table view. Arriving from a link, the panel said "Showing
 * 2 of 2 matches" with no indication a filter was in force -- which
 * reads as "there are 2 transactions in the system". Someone who had
 * just clicked through knew better; someone opening a shared link, or
 * returning tomorrow, did not.
 *
 * A UI stating something false is worse than one stating nothing.
 *
 * FOUNDRY TREATS THIS AS A FIRST-CLASS CONCERN rather than a detail.
 * Object Views ships a dedicated "Active Filters" widget for "a
 * summary of all filters currently applied", and Workshop ships
 * "Exploration Filter Pills" to "visualize and apply filters". A pill
 * row is the established idiom, not an invention.
 *
 * REMOVAL IS THE WAY BACK, and that is Foundry's answer to "how did I
 * get here" too -- their Exploration Search Bar has explicit modes for
 * read-only versus remove-only display, and nothing in Object Explorer
 * offers a breadcrumb trail for search-around. Removing the filter
 * returns you to the unfiltered set, which is where you would have
 * gone anyway.
 *
 * THE RAW VALUE, NOT A FRIENDLY LABEL, and that is a decision rather
 * than a shortcut. A pill on a Transaction list filtered by
 * `customer_id` shows `cust_001`, not "Ada Okafor" -- resolving it
 * would need the CUSTOMER record, which this panel does not have and
 * would cost a request per filter to fetch.
 *
 * The alternative, passing a label through the URL from wherever the
 * filter was built, is worse than unfriendly: it would display
 * CALLER-SUPPLIED TEXT AS FACT, so a shared link could label a filter
 * as one thing while filtering by another. The same reasoning that
 * made the approvals proposer reference system-supplied rather than a
 * parameter.
 *
 * An id is honest. A label that can lie is not, and a label that costs
 * a round trip per pill on hardware this slow is not worth it either.
 *
 * MODE IS SHOWN, NOT ASSUMED. A filter can be `keep` or `exclude`, and
 * a pill reading "Customer: Ada Okafor" for an EXCLUDE filter would
 * describe the exact opposite of the rows on screen.
 */

import { Tag } from '@blueprintjs/core'

import { formatFieldName, pluralise } from '@elysium/shell-api/format'

import type { ChartFilter } from './aggregateCharts'

interface ActiveFiltersProps {
  filters: ChartFilter[]
  /** Removes one filter, by field. */
  onRemove: (field: string) => void
}

export default function ActiveFilters({ filters, onRemove }: ActiveFiltersProps) {
  // NOTHING RENDERED WHEN NOTHING IS FILTERING. An empty row would
  // occupy space to say "no", and the absence already says it.
  if (filters.length === 0) return null

  return (
    <div className="active-filters" aria-label="Active filters">
      {filters.map((filter) => {
        const values = filter.values
        // Two values read as a list; more would grow the pill past
        // what a glance can take in, so beyond that it counts.
        const described = values.length <= 2 ? values.join(', ') : pluralise(values.length, 'value', 'values')

        return (
          <Tag
            key={filter.field}
            minimal
            // NAMED, because Blueprint's remove button is an icon with
            // no accessible name of its own -- a screen reader would
            // announce a row of identical unlabelled buttons and give
            // no way to tell which filter each one drops. Found by a
            // test that could not select one for the same reason.
            onRemove={() => onRemove(filter.field)}
            aria-label={`Remove filter on ${formatFieldName(filter.field)}`}
            intent={filter.mode === 'exclude' ? 'warning' : 'primary'}
          >
            {formatFieldName(filter.field)}
            {filter.mode === 'exclude' ? ' is not ' : ': '}
            {described}
          </Tag>
        )
      })}
    </div>
  )
}
