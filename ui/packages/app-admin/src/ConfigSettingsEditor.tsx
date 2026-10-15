/**
 * Changing config.yaml's settings from here (core/config_editing.py).
 *
 * THE FILE STAYS THE SOURCE OF TRUTH. This edits the YAML itself, line
 * by line, keeping every comment, and the deployment reloads from it --
 * so an operator's editor, an outside program and the agent go on
 * reading the same file this changed.
 *
 * ONLY FOR manage:deployment, which the server decides: anyone else gets
 * a 403 and this renders nothing, the same as a panel they cannot use.
 *
 * REVIEW, THEN APPLY. DEV_UI 13.5: "before saving, the diff". Review
 * shows the exact lines that will change -- only those, because the
 * editor leaves every other byte where it was -- and nothing is written
 * until Apply.
 *
 * ABSENT IS A STATE, not a value: several settings mean something
 * different when missing than when set to their obvious value. So each
 * one says whether it is set, what absent means, and can be unset.
 */

import { Button, HTMLSelect, InputGroup, Switch } from '@blueprintjs/core'
import {
  ApiError,
  applyConfigSettings,
  type ConfigChanges,
  type ConfigSetting,
  type ConfigSettings,
  getConfigSettings,
  getErrorMessage,
  handleIfSessionExpired,
  previewConfigSettings,
} from '@elysium/shell-api/api'
import ErrorState from '@elysium/shell-api/components/ErrorState'
import Notice from '@elysium/shell-api/components/Notice'
import { useEffect, useRef, useState } from 'react'

type Value = boolean | number | string | null

function initialValue(setting: ConfigSetting): Exclude<Value, null> {
  // ON, because a switch is set in order to turn something on: every
  // switch here is off when absent, and writing an explicit `false`
  // was a change that changed nothing (seen in a browser).
  if (setting.kind === 'bool') return true
  if (setting.kind === 'choice') return setting.choices[0] ?? ''
  return setting.minimum ?? 1
}

function shown(value: Value): string {
  if (value === null) return 'not set'
  if (typeof value === 'boolean') return value ? 'on' : 'off'
  return String(value)
}

export default function ConfigSettingsEditor({
  onApplied,
  onSessionExpired,
}: {
  onApplied: (generation: number) => void
  onSessionExpired: () => void
}) {
  const [loaded, setLoaded] = useState<ConfigSettings | null>(null)
  const [hidden, setHidden] = useState(false)
  const [changes, setChanges] = useState<ConfigChanges>({})
  const [preview, setPreview] = useState<string[] | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const latestSessionExpired = useRef(onSessionExpired)
  useEffect(() => {
    latestSessionExpired.current = onSessionExpired
  })

  const load = () => {
    getConfigSettings()
      .then((settings) => {
        setLoaded(settings)
        setChanges({})
        setPreview(null)
      })
      .catch((caught: unknown) => {
        if (handleIfSessionExpired(caught, latestSessionExpired.current)) return
        // NOT THEIRS TO CHANGE, or not reachable: the read-only panel
        // above is still the answer to "what is it running".
        setHidden(true)
      })
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, [])

  if (hidden || loaded === null) return null

  const valueOf = (setting: ConfigSetting): Value =>
    setting.key in changes ? changes[setting.key]! : setting.present ? setting.value : null
  const change = (key: string, value: Value) => {
    setPreview(null)
    setProblem(null)
    setChanges((current) => {
      const original = loaded.settings.find((setting) => setting.key === key)!
      const next = { ...current }
      const originalValue = original.present ? original.value : null
      if (value === originalValue) delete next[key]
      else next[key] = value
      return next
    })
  }

  const failed = (caught: unknown) => {
    if (handleIfSessionExpired(caught, latestSessionExpired.current)) return
    setProblem(
      caught instanceof ApiError && caught.status === 409
        ? `${caught.message} Your changes are still here; load the file again to apply them to it.`
        : getErrorMessage(caught),
    )
  }

  const review = () => {
    setBusy(true)
    previewConfigSettings(loaded.digest, changes)
      .then(setPreview)
      .catch(failed)
      .finally(() => setBusy(false))
  }

  const apply = () => {
    setBusy(true)
    applyConfigSettings(loaded.digest, changes)
      .then((result) => onApplied(result.to_generation))
      .catch(failed)
      .finally(() => setBusy(false))
  }

  const pending = Object.keys(changes).length

  return (
    <section className="config-editor" aria-label="Change settings">
      <h3>Change settings</h3>
      <p className="config-editor__lede">
        These are written to config.yaml, keeping its comments, and the deployment reloads from it. Review shows the
        exact lines before anything is written.
      </p>
      <div className="config-editor__rows">
        {loaded.settings.map((setting) => {
          const value = valueOf(setting)
          const id = `setting-${setting.key}`
          return (
            <div key={setting.key} className="config-editor__row">
              <div>
                <label htmlFor={id} className="config-editor__label">
                  {setting.label}
                </label>
                <p className="config-editor__description">{setting.description}</p>
                {value === null && <p className="config-editor__absent">Not set: {setting.when_absent}</p>}
              </div>
              <div className="config-editor__control">
                {value === null ? (
                  // NOT the setting's id: a <label for> names whatever it
                  // points at, and this button read as the setting itself.
                  <Button
                    small
                    aria-label={`Set ${setting.label}`}
                    onClick={() => change(setting.key, initialValue(setting))}
                  >
                    Set
                  </Button>
                ) : (
                  <>
                    {setting.kind === 'bool' && (
                      <Switch
                        id={id}
                        checked={value === true}
                        label={value === true ? 'On' : 'Off'}
                        onChange={() => change(setting.key, !(value === true))}
                      />
                    )}
                    {setting.kind === 'int' && (
                      <InputGroup
                        id={id}
                        type="number"
                        min={setting.minimum ?? undefined}
                        value={String(value)}
                        onChange={(event) => {
                          const parsed = Number.parseInt(event.target.value, 10)
                          if (!Number.isNaN(parsed)) change(setting.key, parsed)
                        }}
                      />
                    )}
                    {setting.kind === 'choice' && (
                      <HTMLSelect
                        id={id}
                        value={String(value)}
                        onChange={(event) => change(setting.key, event.target.value)}
                      >
                        {setting.choices.map((choice) => (
                          <option key={choice} value={choice}>
                            {choice}
                          </option>
                        ))}
                      </HTMLSelect>
                    )}
                    <Button
                      small
                      minimal
                      onClick={() => change(setting.key, null)}
                      aria-label={`Unset ${setting.label}`}
                    >
                      Unset
                    </Button>
                  </>
                )}
                {setting.key in changes && (
                  <span className="config-editor__was">was {shown(setting.present ? setting.value : null)}</span>
                )}
              </div>
            </div>
          )
        })}
      </div>

      {problem && <ErrorState>{problem}</ErrorState>}

      {preview ? (
        <div className="config-editor__review">
          <p className="config-editor__lede">These lines of config.yaml will change:</p>
          <pre className="config-editor__diff" aria-label="Changes to config.yaml">
            {preview.map((line, index) => (
              <span
                key={index}
                className={
                  line.startsWith('+') && !line.startsWith('+++')
                    ? 'config-editor__added'
                    : line.startsWith('-') && !line.startsWith('---')
                      ? 'config-editor__removed'
                      : undefined
                }
              >
                {line}
                {'\n'}
              </span>
            ))}
          </pre>
          <Button intent="primary" loading={busy} onClick={apply}>
            Apply and reload
          </Button>{' '}
          <Button minimal onClick={() => setPreview(null)}>
            Back
          </Button>
        </div>
      ) : (
        <div className="config-editor__actions">
          <Button disabled={pending === 0} loading={busy} onClick={review}>
            {pending === 0 ? 'Review changes' : `Review ${pending === 1 ? '1 change' : `${pending} changes`}`}
          </Button>
          {pending > 0 && (
            <Button minimal onClick={() => setChanges({})}>
              Discard
            </Button>
          )}
          {problem && (
            <Button minimal onClick={load}>
              Load config.yaml again
            </Button>
          )}
        </div>
      )}
    </section>
  )
}

/** Shown above the panel after an edit, which remounts the panel so its
 * figures are the new generation's. */
export function AppliedNotice({ generation }: { generation: number }) {
  return (
    <Notice state="granted" title="Applied">
      config.yaml was changed and the deployment reloaded as generation {generation}.
    </Notice>
  )
}
