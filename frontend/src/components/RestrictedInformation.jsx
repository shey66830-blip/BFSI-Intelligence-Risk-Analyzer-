import { useCallback, useEffect, useState } from 'react'
import { useRole } from '../context/RoleContext.jsx'
import { createAccessRequest, fetchRestrictedInformation } from '../api.js'

const DURATIONS = [1, 3, 7, 14, 30]

function shortTime(iso) {
  return iso ? `${String(iso).slice(0, 16).replace('T', ' ')}Z` : '—'
}

function RecordValue({ value }) {
  if (value === null || value === undefined) return <span>—</span>
  if (Array.isArray(value)) return <span>{value.join(', ')}</span>
  if (typeof value === 'object') {
    return (
      <div>
        {Object.entries(value).map(([key, nested]) => (
          <div key={key} className="restricted-field">
            <span className="restricted-field-key">{key.replace(/_/g, ' ')}</span>
            <span className="restricted-field-value">
              {Array.isArray(nested) ? nested.join(', ') : String(nested)}
            </span>
          </div>
        ))}
      </div>
    )
  }
  return <span>{String(value)}</span>
}

/**
 * Restricted subject information: the one area a compliance officer cannot simply open.
 * Reading it needs a request, a justification, an administrator's approval and an
 * authorisation that expires. The panel always shows which of those states applies.
 */
export default function RestrictedInformation({ caseId, onRequested, onOpenAccessRequests }) {
  const { can, user } = useRole()
  const [state, setState] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [flash, setFlash] = useState(null)
  const [form, setForm] = useState({
    categories: [], reason: '', necessity: '', related_finding: '', duration_days: 7,
  })

  const load = useCallback(async () => {
    const payload = await fetchRestrictedInformation(caseId)
    setState(payload)
  }, [caseId])

  useEffect(() => { setState(null); setError(null); setFlash(null); load() }, [caseId, load])

  const toggleCategory = (key) => {
    setForm((prev) => ({
      ...prev,
      categories: prev.categories.includes(key)
        ? prev.categories.filter((c) => c !== key)
        : [...prev.categories, key],
    }))
  }

  const handleRequest = async () => {
    setBusy(true)
    setError(null)
    const result = await createAccessRequest({ case_id: caseId, ...form })
    setBusy(false)
    if (!result.ok) {
      setError(result.body?.error || 'The request was refused.')
      return
    }
    setFlash(`Request ${result.body.request?.id} submitted for administrator approval.`)
    setForm({ categories: [], reason: '', necessity: '', related_finding: '', duration_days: 7 })
    await load()
    onRequested?.()
  }

  if (!state) return <div className="loading"><div className="spinner" /> Checking authorisation…</div>

  if (state.locked) {
    const matrix = state.matrix || {}
    return (
      <div className="restricted">
        <div className="restricted-lock">
          <div className="restricted-lock-icon">🔒</div>
          <div>
            <div className="restricted-lock-title">
              {state.state === 'pending'
                ? 'Awaiting administrator approval'
                : state.state === 'expired'
                  ? 'Authorisation expired'
                  : 'Restricted subject information'}
            </div>
            <div className="restricted-lock-reason">{state.reason}</div>
            {state.pending_request && (
              <div className="restricted-lock-meta">
                Request {state.pending_request.id} · {state.pending_request.status} ·{' '}
                {shortTime(state.pending_request.created_at)} ·{' '}
                {(state.pending_request.category_labels || []).join(', ')}
              </div>
            )}
            {state.expired_authorization && (
              <div className="restricted-lock-meta">
                Previous authorisation {state.expired_authorization.id} expired{' '}
                {shortTime(state.expired_authorization.expires_at)}. A new request is required.
              </div>
            )}
          </div>
        </div>

        <div className="card">
          <div className="report-group-title">What exists for this case</div>
          <div className="restricted-matrix">
            {(matrix.categories || []).map((category) => (
              <div key={category.key} className="restricted-matrix-row">
                <div>
                  <div className="restricted-matrix-label">{category.label}</div>
                  <div className="restricted-matrix-desc">{category.description}</div>
                </div>
                <div className={category.records ? 'restricted-matrix-count has' : 'restricted-matrix-count'}>
                  {category.records ? `${category.records} record(s)` : 'none held'}
                </div>
              </div>
            ))}
          </div>
          <div className="restricted-notice">{matrix.notice}</div>
        </div>

        {state.can_request && (
          <div className="card">
            <div className="report-group-title">Request restricted access</div>
            <p className="restricted-help">
              A request is reviewed by an organisation administrator. If approved it carries a
              scope and an expiry, and every read is recorded in the audit trail.
            </p>

            {error && <div className="flash flash-error">{error}</div>}
            {flash && <div className="flash flash-ok">{flash}</div>}

            <div className="restricted-categories">
              {(matrix.categories || []).map((category) => (
                <label key={category.key} className="restricted-category">
                  <input type="checkbox"
                         checked={form.categories.includes(category.key)}
                         onChange={() => toggleCategory(category.key)} />
                  <span>
                    <span className="restricted-category-label">{category.label}</span>
                    <span className="restricted-category-count">
                      {category.records ? `${category.records} held` : 'none held'}
                    </span>
                  </span>
                </label>
              ))}
            </div>

            <div className="admin-form-grid">
              <label className="field">
                <span className="field-label">Reason for the request</span>
                <textarea className="field-input" rows={2} value={form.reason}
                          placeholder="Why is this information being sought?"
                          onChange={(e) => setForm({ ...form, reason: e.target.value })} />
              </label>
              <label className="field">
                <span className="field-label">Why it is necessary</span>
                <textarea className="field-input" rows={2} value={form.necessity}
                          placeholder="What gap does it close in the investigation?"
                          onChange={(e) => setForm({ ...form, necessity: e.target.value })} />
              </label>
              <label className="field">
                <span className="field-label">Relevant finding</span>
                <input className="field-input" value={form.related_finding}
                       placeholder="Which finding prompted this?"
                       onChange={(e) => setForm({ ...form, related_finding: e.target.value })} />
              </label>
              <label className="field">
                <span className="field-label">Requested duration</span>
                <select className="field-input" value={form.duration_days}
                        onChange={(e) => setForm({ ...form, duration_days: Number(e.target.value) })}>
                  {DURATIONS.map((days) => (
                    <option key={days} value={days}>{days} day(s)</option>
                  ))}
                </select>
              </label>
            </div>

            <button className="btn btn-primary btn-sm" onClick={handleRequest}
                    disabled={busy || form.categories.length === 0
                      || !form.reason.trim() || !form.necessity.trim()} type="button">
              Submit request
            </button>
          </div>
        )}

        {!state.can_request && (
          <div className="card vault-empty">
            Your role cannot request restricted information
            {user?.role === 'admin' ? ' — an administrator approves these requests but does not raise them.' : '.'}
          </div>
        )}
      </div>
    )
  }

  const authorization = state.authorization || {}

  return (
    <div className="restricted">
      <div className="restricted-banner">
        <div className="restricted-banner-head">
          <span className="restricted-badge">🔓 Authorised information</span>
          <span className="restricted-remaining">{state.remaining} before expiry</span>
        </div>
        <div className="restricted-banner-grid">
          <div><span>Authorised under</span><strong>{authorization.request_id}</strong></div>
          <div><span>Authorisation</span><strong>{authorization.id}</strong></div>
          <div><span>Approved by</span><strong>{authorization.approved_by_name}</strong></div>
          <div><span>Approved at</span><strong>{shortTime(authorization.approved_at)}</strong></div>
          <div><span>Expires</span><strong>{shortTime(authorization.expires_at)}</strong></div>
          <div><span>Scope</span><strong>{(authorization.scope_labels || []).join(', ')}</strong></div>
        </div>
        <div className="restricted-banner-reason">
          Reason on the request: {authorization.reason}
        </div>
        <div className="restricted-banner-conditions">{authorization.conditions}</div>
        <button className="btn btn-ghost btn-sm" onClick={onOpenAccessRequests} type="button">
          View the authorisation record
        </button>
      </div>

      <div className="restricted-notice">{state.notice}</div>

      {(state.records || []).map((record) => (
        <div key={record.id} className="card restricted-record">
          <div className="restricted-record-head">
            <div>
              <div className="restricted-record-title">{record.title}</div>
              <div className="restricted-record-meta">
                <span className="mono-muted">{record.id}</span>
                <span>{record.category.replace(/_/g, ' ')}</span>
                <span>{record.subject_label} · {record.subject_id}</span>
                <span>source: {record.source}</span>
              </div>
            </div>
            <span className="restricted-record-key">
              {record.authorization?.request_id}
            </span>
          </div>
          <RecordValue value={record.value} />
          <div className="restricted-notice">{record.notice}</div>
        </div>
      ))}
    </div>
  )
}
