import { useCallback, useEffect, useState } from 'react'
import { useRole } from '../context/RoleContext.jsx'
import { fetchAuditLogs } from '../api.js'

const ACTION_LABELS = {
  view: 'Viewed',
  action: 'Performed',
  decision: 'Decided',
  login: 'Signed in',
  logout: 'Signed out',
  access_denied: 'Blocked',
  login_failed: 'Failed sign-in',
  system: 'System',
}

const FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'view', label: 'Viewed' },
  { key: 'action', label: 'Performed' },
  { key: 'decision', label: 'Decided' },
  { key: 'access_denied', label: 'Blocked' },
]

function formatStamp(ts) {
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ts
  return d.toLocaleString('en-GB', {
    day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

export default function AuditLog() {
  const { roleConfig, user } = useRole()
  const [scope, setScope] = useState(roleConfig?.canSeeAllAudit ? 'all' : 'own')
  const [filter, setFilter] = useState('all')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    const payload = await fetchAuditLogs(scope, filter)
    setData(payload)
    setLoading(false)
  }, [scope, filter])

  useEffect(() => { load() }, [load])

  const entries = data?.entries || []

  return (
    <div>
      <div className="page-head">
        <div>
          <h2 className="page-title">Audit Trail</h2>
          <p className="page-sub">
            {scope === 'all'
              ? 'Every action by every identity, attributed and immutable.'
              : `Activity recorded against ${user?.name} only.`}
          </p>
        </div>
        {roleConfig?.canSeeAllAudit && (
          <div className="scope-toggle">
            <button
              className={`scope-btn ${scope === 'own' ? 'active' : ''}`}
              onClick={() => setScope('own')}
            >
              My activity
            </button>
            <button
              className={`scope-btn ${scope === 'all' ? 'active' : ''}`}
              onClick={() => setScope('all')}
            >
              Organisation
            </button>
          </div>
        )}
      </div>

      <div className="tabs">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            className={`tab ${filter === f.key ? 'active' : ''}`}
            onClick={() => setFilter(f.key)}
          >
            {f.label}
          </button>
        ))}
      </div>

      <div className="card">
        {loading && <div className="pipeline-empty">Loading audit entries…</div>}
        {!loading && entries.length === 0 && (
          <div className="pipeline-empty">No audit entries for this filter yet.</div>
        )}
        {!loading && entries.map((entry) => (
          <div key={entry.id} className="audit-entry">
            <div className={`audit-dot ${entry.action}`} />
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 500 }}>
                <span style={{ color: 'var(--ink)' }}>{entry.user}</span>
                {' — '}
                {ACTION_LABELS[entry.action] || entry.action}
                {entry.target && (
                  <>
                    {' '}
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{entry.target}</span>
                  </>
                )}
              </div>
              <div style={{ color: 'var(--gray-500)', fontSize: 12, marginTop: 2 }}>{entry.detail}</div>
              <div className="audit-meta">
                {formatStamp(entry.timestamp)}
                {' · '}
                <span style={{ textTransform: 'capitalize' }}>{entry.role}</span>
                {entry.username && <> · @{entry.username}</>}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
