/**
 * Who can see a type and its fields, by role (DEV_UI 13.3).
 *
 * "THE ADMINISTRATOR'S BURDEN IS NOT WRITING THE POLICY. IT IS NOT
 * KNOWING WHAT THE POLICY DOES." The roles screen shows what each role
 * HOLDS; this answers what people are actually asked -- who can see
 * Customer.email, and why can Bob not see this order.
 *
 * TWO QUESTIONS, ANSWERED APART. Which objects a person sees is their
 * compartment (MAC): one sentence, followed through any chain, because
 * chains are where the surprises have been. Which fields, and which
 * actions, is their role (RBAC): one row per role.
 *
 * Closed by default, as a disclosure: the Object types catalogue shows
 * every type, and a table per card would bury the cards.
 */
import DataTable from '@elysium/shell-api/components/DataTable'
import type { TypeAccess } from '@elysium/shell-api/api'

function compartmentSentence(objectType: string, access: TypeAccess): string {
  const rule = access.compartment
  if (!rule) {
    return `No compartment is declared: anyone whose role can read ${objectType} sees every one.`
  }
  if (rule.path.length === 0) {
    return `A person sees a ${objectType} only when their ${rule.attribute} matches its ${rule.field}.`
  }
  const route = [...rule.path.map((step) => `${step.type}.${step.field}`), `${rule.type}.${rule.field}`].join(' → ')
  return `A person sees a ${objectType} only when their ${rule.attribute} matches its ${rule.type}'s ${rule.field}, followed through ${route}.`
}

/** "all 8", or the ones it reads, the ones it only knows exist, and the rest. */
function fieldsSummary(fields: Record<string, 'read' | 'discover' | null>): string {
  const names = Object.keys(fields)
  const read = names.filter((name) => fields[name] === 'read')
  const known = names.filter((name) => fields[name] === 'discover')
  const hidden = names.filter((name) => fields[name] === null)
  if (read.length === names.length) return `all ${names.length}`
  const parts = [`reads ${read.length} of ${names.length}`]
  if (known.length > 0) parts.push(`knows ${known.join(', ')} exist${known.length === 1 ? 's' : ''}`)
  if (hidden.length > 0) parts.push(`cannot see ${hidden.join(', ')}`)
  return parts.join('; ')
}

export default function WhoCanSee({ objectType, access }: { objectType: string; access: TypeAccess }) {
  return (
    <details className="schema-panel__access">
      <summary>Who can see this</summary>
      <p className="schema-panel__compartment">{compartmentSentence(objectType, access)}</p>
      {access.roles.length > 0 && (
        <DataTable className="schema-panel__access-table">
          <thead>
            <tr>
              <th>Role</th>
              <th>People</th>
              <th>The type</th>
              <th>Fields</th>
              <th>May change it by</th>
            </tr>
          </thead>
          <tbody>
            {access.roles.map((role) => (
              <tr key={role.role}>
                <td>{role.role}</td>
                <td className="numeric">{role.holders ?? '—'}</td>
                <td>{role.type === 'read' ? 'reads it' : 'knows it exists'}</td>
                <td>{fieldsSummary(role.fields)}</td>
                <td>{role.actions.length > 0 ? role.actions.join(', ') : 'no action'}</td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      )}
      <p className="schema-panel__no-access">
        {access.no_access.length > 0
          ? `Cannot know it exists: ${access.no_access.join(', ')}.`
          : 'Every role can at least know it exists.'}
      </p>
    </details>
  )
}
