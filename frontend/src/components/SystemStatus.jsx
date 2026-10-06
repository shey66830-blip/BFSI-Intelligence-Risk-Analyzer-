import { useEffect, useState } from 'react'
import { fetchSystemStatus } from '../api.js'

function Numeric({ label, value, sub }) {
  return (
    <div className="stat-card">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value ?? '—'}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  )
}

/**
 * Operational snapshot for the administrator: identity, caseload, access approvals and
 * which integrations are real versus simulated. Stating the simulated ones plainly is the
 * point — an administrator should never have to guess what is connected.
 */
export default function SystemStatus() {
  const [status, setStatus] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    fetchSystemStatus().then((payload) => {
      if (cancelled) return
      if (!payload || payload.error) setError(payload?.error || 'System status is unavailable.')
      else setStatus(payload)
    })
    return () => { cancelled = true }
  }, [])

  if (error) return <div className="flash flash-error">{error}</div>
  if (!status) return <div className="loading"><div className="spinner" /> Reading system status…</div>

  const users = status.users || {}
  const access = status.access_control || {}
  const integrations = status.integrations || {}
  const settings = status.configuration || {}
  const workload = status.workload || {}
  const securityEvents = status.audit?.recent_security_events || []

  return (
    <div className="status-view">
      <div className="view-head">
        <div>
          <div className="view-title">System status</div>
          <div className="view-sub">
            Configuration and integration state for this environment. Nothing here is a live
            payment connection.
          </div>
        </div>
      </div>

      <div className="stats-grid">
        <Numeric label="Active users" value={users.active} sub={`${users.total ?? 0} provisioned`} />
        <Numeric label="Suspended" value={users.suspended} sub="Accounts without access" />
        <Numeric label="Pending access requests" value={access.pending_requests}
                 sub={`${access.rejected ?? 0} rejected · ${access.expired ?? 0} lapsed`} />
        <Numeric label="Active authorisations" value={access.active_authorizations}
                 sub={`${access.restricted_records ?? 0} restricted record(s) held`} />
        <Numeric label="Open cases" value={workload.open_cases}
                 sub={`${workload.reports_awaiting_review ?? 0} report(s) awaiting review`} />
        <Numeric label="Active sessions" value={users.active_sessions}
                 sub={`${workload.evidence_items ?? 0} evidence item(s) filed`} />
      </div>

      <div className="card">
        <div className="report-group-title">Users by role</div>
        <div className="kv-grid">
          {Object.entries(users.by_role || {}).map(([role, count]) => (
            <div className="kv-row" key={role}>
              <span className="kv-key">{role.replace(/_/g, ' ')}</span>
              <span className="kv-value">{count}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="card">
        <div className="report-group-title">Cases by status</div>
        <div className="kv-grid">
          {Object.entries(workload.cases_by_status || {}).map(([state, count]) => (
            <div className="kv-row" key={state}>
              <span className="kv-key">{state.replace(/_/g, ' ')}</span>
              <span className="kv-value">{count}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="card">
        <div className="report-group-title">Integrations</div>
        <div className="integration-list">
          {(integrations.banks || []).map((bank) => (
            <div className="integration-row" key={bank.id}>
              <span>{bank.name || bank.id}</span>
              <span className={`status-chip ${bank.mode === 'live' ? 'ok' : 'warn'}`}>
                {bank.mode === 'live' ? 'live endpoint' : 'simulated endpoint'}
              </span>
            </div>
          ))}
          {!integrations.banks?.length && (
            <div className="vault-empty">No bank endpoints configured.</div>
          )}
        </div>
        <div className="integration-note">
          Live payment-system integration: {integrations.live_payment_integration ? 'yes' : 'no'}.
          Government and account-aggregator connections: none. Every record in this environment
          is synthetic, and adapters exist so an authorised connection can replace a simulated
          endpoint without changing the investigation workflow.
        </div>
      </div>

      <div className="card">
        <div className="report-group-title">Configuration</div>
        <div className="kv-grid">
          {Object.entries(settings).map(([key, value]) => (
            <div className="kv-row" key={key}>
              <span className="kv-key">{key.replace(/_/g, ' ')}</span>
              <span className="kv-value">{String(value)}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="card">
        <div className="report-group-title">Recent security events</div>
        {securityEvents.length === 0 && (
          <div className="vault-empty">No authentication or authorisation events recorded.</div>
        )}
        {securityEvents.map((event) => (
          <div key={event.id} className="audit-entry">
            <div className="audit-meta">
              <span className="mono-muted">{String(event.timestamp).slice(0, 16).replace('T', ' ')}</span>
              <span>{event.action_label || event.action}</span>
              <span>{event.user}</span>
              <span className={`status-chip ${event.result === 'denied' ? 'warn' : 'ok'}`}>
                {event.result}
              </span>
            </div>
            <div className="admin-meta">
              {event.detail}
              {event.reason ? ` — ${event.reason}` : ''}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
