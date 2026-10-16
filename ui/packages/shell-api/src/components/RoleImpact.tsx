/**
 * A role change in ACCESS terms (DEV_UI 13.5).
 *
 * "Before saving, the diff stated in ACCESS TERMS rather than config
 * terms." The grant list says `+ read:Customer.email`; this says "can now
 * read Customer.email", and how many people that is. The server computes
 * it by asking the permission code as it stands and as it would stand
 * (core/role_impact.py), so a grant that opens nothing says so.
 *
 * IN shell-api SINCE A SECOND SCREEN SAYS THE SAME THING: a label or an
 * earlier version put back changes access for several roles at once
 * (ConfigImpact, below), in exactly these words.
 *
 * GAINS AND LOSSES LOOK DIFFERENT, gains marked. Widening access is the
 * rare case DEV_UI 13.6 reserves extra attention for; narrowing is the
 * safe direction.
 */
import type { AccessImpact, RoleImpact as Impact } from '../api'

type Level = 'read' | 'discover' | null

function gainedTypeLine(type: string, to: Level): string {
  return to === 'read' ? `Can now read ${type}` : `Can now know ${type} exists`
}

function lostTypeLine(type: string, to: Level): string {
  return to === 'discover' ? `Can no longer read ${type} (still knows it exists)` : `Can no longer see ${type} at all`
}

function gainedFieldLine(name: string, to: Level): string {
  return to === 'read' ? `Can now read ${name}` : `Can now know ${name} exists`
}

function lostFieldLine(name: string, from: Level, to: Level): string {
  if (from === 'read' && to === 'discover') return `Can no longer read ${name} (still knows it exists)`
  if (from === 'discover') return `Can no longer see that ${name} exists`
  return `Can no longer read ${name}`
}

export function impactLines(impact: Impact): { text: string; widens: boolean }[] {
  return [
    ...impact.types_gained.map((c) => ({ text: gainedTypeLine(c.type, c.to), widens: true })),
    ...impact.fields_gained.map((c) => ({ text: gainedFieldLine(`${c.type}.${c.field}`, c.to), widens: true })),
    ...impact.actions_gained.map((a) => ({ text: `Can now run ${a}`, widens: true })),
    ...impact.other_gained.map((g) => ({ text: `Gains ${g}`, widens: true })),
    ...impact.types_lost.map((c) => ({ text: lostTypeLine(c.type, c.to), widens: false })),
    ...impact.fields_lost.map((c) => ({ text: lostFieldLine(`${c.type}.${c.field}`, c.from, c.to), widens: false })),
    ...impact.actions_lost.map((a) => ({ text: `Can no longer run ${a}`, widens: false })),
    ...impact.other_lost.map((g) => ({ text: `Loses ${g}`, widens: false })),
  ]
}

function people(count: number, role: string): string {
  if (count === 0) return `Nobody holds ${role} yet`
  return `${count} ${count === 1 ? 'person holds' : 'people hold'} ${role}`
}

export default function RoleImpact({ impact }: { impact: Impact }) {
  const lines = impactLines(impact)
  return (
    <div className="roles__impact" aria-label="What this change would do">
      <div className="roles__impact-head">
        In access terms. {people(impact.holders, impact.role)}
        {impact.removes_role ? '; removing the role takes all of this from them.' : '.'}
      </div>
      {lines.length === 0 ? (
        <div className="roles__impact-none">No change to what this role can see or do.</div>
      ) : (
        <ul>
          {lines.map((line) => (
            <li key={line.text} className={line.widens ? 'roles__widens' : 'roles__narrows'}>
              {line.text}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/**
 * A configuration change's effect on every role it touches -- a label,
 * or an earlier version put back (core/role_impact.config_access_impact).
 * Only roles something changes for are listed; none is its own answer.
 *
 * ROLES THE CHANGE TREATS ALIKE ARE SAID ONCE. Taking pii off one field
 * opened it to four roles in the first browser check, and the same line
 * four times under four headings buried the one thing to judge: who,
 * and how many people. A deployment with twenty roles would bury it
 * further.
 */
export function ConfigImpact({ impact }: { impact: AccessImpact }) {
  if (impact.roles.length === 0) {
    return (
      <div className="roles__impact" aria-label="What this change would do">
        <div className="roles__impact-none">No change to what anyone can see or do.</div>
      </div>
    )
  }
  const groups = new Map<string, { roles: Impact[]; lines: { text: string; widens: boolean }[] }>()
  for (const role of impact.roles) {
    const lines = impactLines(role)
    const key = JSON.stringify([role.removes_role, lines])
    const group = groups.get(key)
    if (group) group.roles.push(role)
    else groups.set(key, { roles: [role], lines })
  }
  return (
    <>
      {[...groups.values()].map(({ roles, lines }) => {
        const holders = roles.reduce((sum, role) => sum + role.holders, 0)
        const names = roles.map((role) => role.role).join(', ')
        return (
          <div key={names} className="roles__impact" aria-label={`What this change would do to ${names}`}>
            <div className="roles__impact-head">
              <strong>{names}</strong> —{' '}
              {holders === 0
                ? 'nobody holds ' + (roles.length === 1 ? 'it' : 'these') + ' yet'
                : `${holders} ${holders === 1 ? 'person' : 'people'}`}
              {roles[0]!.removes_role ? '; the role goes, and all of this with it.' : '.'}
            </div>
            <ul>
              {lines.map((line) => (
                <li key={line.text} className={line.widens ? 'roles__widens' : 'roles__narrows'}>
                  {line.text}
                </li>
              ))}
            </ul>
          </div>
        )
      })}
    </>
  )
}
