/**
 * What this deployment is actually running.
 *
 * READ-ONLY, and the screen you want when something behaves
 * unexpectedly -- "why did that query stop after eight steps" has no
 * answer today short of reading a YAML file on the server.
 *
 * It lives in Admin because the endpoint is gated on manage:users:
 * configuration discloses deployment shape, and while none of it is
 * object data, it is what an attacker maps a system with.
 *
 * NOTHING HERE IS EDITABLE, deliberately. Runtime config editing needs
 * a per-request snapshot first, or a change mid-flight leaves one
 * request disagreeing with itself.
 */

import { HTMLTable, Tag } from '@blueprintjs/core'
import { getDeploymentConfig } from '@elysium/shell-api/api'
import AsyncPanel from '@elysium/shell-api/components/AsyncPanel'
import { useFetchOnce } from '@elysium/shell-api/useFetchOnce'

interface DeploymentConfigBody {
  llm_provider: string
  step_model: string
  synthesis_model: string
  max_hops: number
  max_consecutive_duplicates: number
  max_consecutive_invalid_steps: number
  max_concurrent_requests: number
  security_attribute: string
  read_from_mirror: boolean
  enabled_tools: string[]
  silo_names: string[]
  object_type_count: number
  action_type_count: number
  role_names: string[]
}

export default function DeploymentConfig({ onSessionExpired }: { onSessionExpired: () => void }) {
  const { data: config, error } = useFetchOnce<DeploymentConfigBody>(
    () => getDeploymentConfig(),
    onSessionExpired,
  )

  return (
    <AsyncPanel error={error} data={config}>
      {(config) => {
      // Grouped by what a reader is looking for, not by the order the
      // config happens to declare them.
      const groups: [string, [string, React.ReactNode][]][] = [
        ['Model', [
          ['Provider', config.llm_provider],
          ['Step model', config.step_model],
          ['Synthesis model', config.synthesis_model],
        ]],
        ['Agent bounds', [
          ['Max hops', config.max_hops],
          ['Max consecutive duplicates', config.max_consecutive_duplicates],
          ['Max consecutive invalid steps', config.max_consecutive_invalid_steps],
          ['Max concurrent requests', config.max_concurrent_requests],
        ]],
        ['Ontology', [
          ['Object types', config.object_type_count],
          ['Action types', config.action_type_count],
          ['Security attribute', config.security_attribute],
          ['Reading from mirror', config.read_from_mirror ? 'yes' : 'no'],
        ]],
        ['Configured', [
          // NAMES only. The endpoint deliberately does not send silo
          // connection details or role grants -- names answer "what is
          // configured", contents would answer "what could I attack".
          ['Silos', config.silo_names.join(', ') || '—'],
          ['Roles', config.role_names.join(', ') || '—'],
          ['Tools', config.enabled_tools.length > 0
            ? config.enabled_tools.map((tool) => <Tag key={tool} minimal>{tool}</Tag>)
            : '—'],
        ]],
      ]
        return (
        <div className="deployment-config">
          {groups.map(([heading, rows]) => (
            <section key={heading}>
              <h3>{heading}</h3>
              <HTMLTable compact striped className="deployment-config__table">
                <tbody>
                  {rows.map(([label, value]) => (
                    <tr key={label}>
                      <td className="deployment-config__label">{label}</td>
                      <td>{value}</td>
                    </tr>
                  ))}
                </tbody>
              </HTMLTable>
            </section>
          ))}
        </div>
        )
      }}
    </AsyncPanel>
  )
}
