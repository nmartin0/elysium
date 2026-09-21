/**
 * RolesPanel -- what each role may do, and changes waiting to be decided.
 *
 * A CHANGE IS A PROPOSAL. Editing a role here never changes it: it
 * proposes the new grants, and somebody ELSE with manage:roles must
 * approve before they take effect. Foundry's rule, "approval from a
 * user... other than the change request author". The screen says so
 * at the point of proposing, so nobody believes a change has happened
 * when it has only been asked for.
 *
 * WAITING CHANGES COME FIRST. They are the thing on this screen that
 * somebody else is blocked on; the role list is for starting one.
 *
 * AND IT SAYS WHERE THE ROLES COME FROM. Until the first approved
 * change, policy.yaml is in force; after, the role store is, and
 * editing policy.yaml's roles stops doing anything. Saying which is how
 * an administrator learns that.
 */

import { Button, Callout, Card, Checkbox, H5, HTMLSelect, InputGroup, Tag } from '@blueprintjs/core'
import {
  approveRoleChange,
  getCurrentUser,
  getErrorMessage,
  getRoleChanges,
  getRoles,
  handleIfSessionExpired,
  proposeRoleChange,
  rejectRoleChange,
  type RoleChange,
  type RolesView,
} from '@elysium/shell-api/api'
import ErrorState from '@elysium/shell-api/components/ErrorState'
import LoadingState from '@elysium/shell-api/components/LoadingState'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { groupGrants, summariseChange } from './roleGrants'

interface RolesPanelProps {
  onSessionExpired: () => void
}

const NEW_ROLE = '__new__'

export default function RolesPanel({ onSessionExpired }: RolesPanelProps) {
  const [view, setView] = useState<RolesView | null>(null)
  const [changes, setChanges] = useState<RoleChange[]>([])
  const [me, setMe] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [selected, setSelected] = useState('')
  const [newName, setNewName] = useState('')
  const [draft, setDraft] = useState<Set<string>>(new Set())

  const load = useCallback(async () => {
    try {
      const [roles, pending] = await Promise.all([getRoles(), getRoleChanges()])
      setView(roles)
      setChanges(pending)
      setError(null)
    } catch (caught: unknown) {
      if (handleIfSessionExpired(caught, onSessionExpired)) return
      setError(getErrorMessage(caught))
    }
  }, [onSessionExpired])

  useEffect(() => {
    void load()
    void (async () => {
      try {
        const profile = (await getCurrentUser()) as { username?: string }
        setMe(profile.username ?? null)
      } catch {
        setMe(null)
      }
    })()
  }, [load])

  // THE DRAFT STARTS AS WHAT THE ROLE HOLDS NOW, so an edit is a change
  // to something visible rather than a list typed from memory.
  useEffect(() => {
    if (view === null) return
    setDraft(new Set(selected === NEW_ROLE ? [] : (view.roles[selected] ?? [])))
  }, [selected, view])

  const groups = useMemo(() => (view === null ? [] : groupGrants(view.grantable)), [view])

  async function act(action: () => Promise<unknown>, done: string) {
    setNotice(null)
    try {
      await action()
      setNotice(done)
      await load()
    } catch (caught: unknown) {
      if (handleIfSessionExpired(caught, onSessionExpired)) return
      setError(getErrorMessage(caught))
    }
  }

  if (error !== null && view === null) return <ErrorState>{error}</ErrorState>
  if (view === null) return <LoadingState />

  const roleName = selected === NEW_ROLE ? newName.trim() : selected
  const current = selected === NEW_ROLE ? null : (view.roles[selected] ?? null)
  const proposed = [...draft].sort()
  const unchanged = current !== null && proposed.join() === [...current].sort().join()

  return (
    <div className="roles">
      <Callout intent={view.source === 'role store' ? 'primary' : 'none'}>
        {view.source === 'role store'
          ? 'Roles come from the role store. Editing policy.yaml’s roles has no effect.'
          : 'Roles come from policy.yaml until the first approved change.'}
      </Callout>

      {error !== null && <ErrorState>{error}</ErrorState>}
      {notice !== null && <Callout intent="success">{notice}</Callout>}

      <H5>Waiting for a decision</H5>
      {changes.length === 0 && <p className="roles__empty">Nothing is waiting.</p>}
      {changes.map((change) => {
        const summary = summariseChange(change.before, change.after)
        const own = change.proposed_by === me
        return (
          <Card key={change.change_id} className="roles__change">
            <div className="roles__change-head">
              <strong>{change.role_name}</strong>
              <Tag minimal>
                {summary.kind === 'create' ? 'new role' : summary.kind === 'delete' ? 'delete role' : 'edit'}
              </Tag>
              <span className="roles__by">proposed by {change.proposed_by}</span>
            </div>
            {summary.added.map((grant) => (
              <div key={`+${grant}`} className="roles__added">
                + {grant}
              </div>
            ))}
            {summary.removed.map((grant) => (
              <div key={`-${grant}`} className="roles__removed">
                − {grant}
              </div>
            ))}
            <div className="roles__decide">
              <Button
                intent="primary"
                disabled={own}
                title={own ? 'You proposed this; somebody else must approve it.' : undefined}
                onClick={() => void act(() => approveRoleChange(change.change_id), `Applied ${change.role_name}.`)}
              >
                Approve
              </Button>
              <Button
                onClick={() =>
                  void act(() => rejectRoleChange(change.change_id), `Rejected the change to ${change.role_name}.`)
                }
              >
                {own ? 'Withdraw' : 'Reject'}
              </Button>
            </div>
          </Card>
        )
      })}

      <H5>Propose a change</H5>
      <HTMLSelect
        aria-label="Role to change"
        value={selected}
        onChange={(event) => setSelected(event.currentTarget.value)}
        options={[
          { value: '', label: 'Choose a role…' },
          ...Object.keys(view.roles).map((name) => ({ value: name, label: name })),
          { value: NEW_ROLE, label: 'A new role…' },
        ]}
      />
      {selected === NEW_ROLE && (
        <InputGroup
          aria-label="New role name"
          placeholder="Name the new role"
          value={newName}
          onChange={(event) => setNewName(event.target.value)}
        />
      )}

      {selected !== '' &&
        groups.map((group) => (
          <fieldset key={group.title} className="roles__group">
            <legend>{group.title}</legend>
            {group.grants.map((grant) => (
              <Checkbox
                key={grant}
                label={grant}
                checked={draft.has(grant)}
                onChange={() =>
                  setDraft((now) => {
                    const next = new Set(now)
                    if (next.has(grant)) next.delete(grant)
                    else next.add(grant)
                    return next
                  })
                }
              />
            ))}
          </fieldset>
        ))}

      {selected !== '' && (
        <div className="roles__propose">
          <Button
            intent="primary"
            disabled={roleName === '' || unchanged}
            onClick={() =>
              void act(
                () => proposeRoleChange(roleName, proposed),
                `Proposed a change to ${roleName}. Somebody else must approve it before it takes effect.`,
              )
            }
          >
            Propose
          </Button>
          {current !== null && (
            <Button
              intent="danger"
              onClick={() =>
                void act(
                  () => proposeRoleChange(roleName, null),
                  `Proposed deleting ${roleName}. Somebody else must approve it.`,
                )
              }
            >
              Propose deleting
            </Button>
          )}
        </div>
      )}
    </div>
  )
}
