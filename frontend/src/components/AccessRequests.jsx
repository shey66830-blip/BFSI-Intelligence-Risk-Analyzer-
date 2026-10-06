import { useCallback, useEffect, useState } from 'react'
import { useRole } from '../context/RoleContext.jsx'
import {
  approveAccessRequest, clarifyAccessRequest, fetchAccessRequests, fetchAuthorizations,
  rejectAccessRequest, revokeAuthorization,
} from '../api.js'

const STATUS_FILTERS = ['all', 'pending', 'clarification_requested', 'approved', 'rejected', 'expired']

function shortTime(iso) {
  return iso ? `${String(iso).slice(0, 16).replace('T', ' ')}Z` : '—'
}

function StatusChip({ status }) {
  const tone = status === 'approved' ? 'ok'
    : status === 'rejected' || status === 'expired' ? 'warn'
      : status === 'pending' ? 'info' : 'warn'
  return <span className={`status-chip ${tone}`}>{status.replace(/_/g, ' ')}</span>
}

/**
 * The authorisation loop. A compliance officer raises a request with a reason and a
 * duration; an administrator approves, rejects or asks for clarification; an approval
 * creates a time-limited authorisation that the register below tracks.
 */
export default function AccessRequests({ onOpenCase }) {
  const { can, role } = useRole()
  const [requests, setRequests] = useState([])
  const [authorizations, setAuthorizations] = useState([])
  const [filter, setFilter] = useState('all')
  const [selected, setSelected] = useState(null)
  const [decision, setDecision] = useState({ duration_days: 7, note: '', reason: '' })
  const [scope, setScope] = useState([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [flash, setFlash] = useState(null)

  const isApprover = can('access:approve')

  const load = useCallback(async () => {
    const [requestPayload, authPayload] = await Promise.all([
      fetchAccessRequests(filter),
      fetchAuthorizations(),
    ])
    setRequests(requestPayload.requests || [])
    setAuthorizations(authPayload.authorizations || [])
  }, [filter])

  useEffect(() => { load() }, [load])

  const open = (request) => {
    setSelected(request)
    setScope(request.categories || [])
    setDecision({ duration_days: request.duration_days || 7, note: '', reason: '' })
    setError(null)
    setFlash(null)
  }

  const decide = async (kind) => {
    setBusy(true)
    setError(null)
    let result
    if (kind === 'approve') {
      result = await approveAccessRequest(selected.id, {
        duration_days: Number(decision.duration_days), scope, note: decision.note,
      })
    } else if (kind === 'reject') {
      result = await rejectAccessRequest(selected.id, decision.reason)
    } else {
      result = await clarifyAccessRequest(selected.id, decision.note)
    }
    setBusy(false)

    if (!result.ok) {
      setError(result.body?.error || 'The decision was refused.')
      return
    }
    setFlash(
      kind === 'approve'
        ? `${selected.id} approved. ${selected.requested_by_name} has been notified.`
        : kind === 'reject'
          ? `${selected.id} rejected.`
          : `${selected.id} returned for clarification.`,
    )
    setSelected(null)
    await load()
  }

  const revoke = async (authorization) => {
    setBusy(true)
    const result = await revokeAuthorization(authorization.id, 'Revoked from the register')
    setBusy(false)
    if (!result.ok) {
      setError(result.body?.error || 'Could not revoke the authorisation.')
      return
    }
    setFlash(`${authorization.id} revoked.`)
    await load()
  }

  return (
    <div className="access-view">
      <div className="view-head">
        <div>
          <div className="view-title">Restricted information access</div>
          <div className="view-sub">
            {isApprover
              ? 'Requests for subject information are reviewed here. Approving creates a scoped, expiring authorisation.'
              : 'Requests you have raised, and the authorisations that were granted or have lapsed.'}
          </div>
        </div>
        <div className="segmented">
          {STATUS_FILTERS.map((status) => (
            <button key={status} className={filter === status ? 'active' : ''}
                    onClick={() => setFilter(status)} type="button">
              {status.replace(/_/g, ' ')}
            </button>
          ))}
        </div>
      </div>

      {error && <div className="flash flash-error">{error}</div>}
      {flash && <div className="flash flash-ok">{flash}</div>}

      <div className="card">
        <div className="report-group-title">
          {isApprover ? 'Request queue' : 'My requests'}
        </div>
        {requests.length === 0 && (
          <div className="vault-empty">No requests in this state.</div>
        )}
        {requests.length > 0 && (
          <table className="admin-table">
            <thead>
              <tr>
                <th>Request</th>
                <th>Case</th>
                <th>Requested by</th>
                <th>Information</th>
                <th>Duration</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {requests.map((request) => (
                <tr key={request.id}>
                  <td className="mono-muted">{request.id}</td>
                  <td>
                    <button className="link-button"
                            onClick={() => onOpenCase?.(request.case_id)} type="button">
                      {request.case_id?.toUpperCase()}
                    </button>
                  </td>
                  <td>
                    <div>{request.requested_by_name}</div>
                    <div className="admin-meta">{request.requested_by_role}</div>
                  </td>
                  <td>{(request.category_labels || []).join(', ')}</td>
                  <td>{request.duration_days} day(s)</td>
                  <td>
                    <StatusChip status={request.status} />
                    {request.expires_at && request.status === 'approved' && (
                      <div className="admin-meta">expires {shortTime(request.expires_at)}</div>
                    )}
                  </td>
                  <td>
                    <button className="btn btn-ghost btn-sm" onClick={() => open(request)}
                            type="button">
                      {isApprover && ['pending', 'clarification_requested'].includes(request.status)
                        ? 'Review'
                        : 'Details'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="card">
        <div className="report-group-title">Authorisation register</div>
        {authorizations.length === 0 && (
          <div className="vault-empty">No authorisations have been issued.</div>
        )}
        {authorizations.length > 0 && (
          <table className="admin-table">
            <thead>
              <tr>
                <th>Authorisation</th>
                <th>Request</th>
                <th>Case</th>
                <th>Granted to</th>
                <th>Scope</th>
                <th>Approved by</th>
                <th>Expires</th>
                <th>State</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {authorizations.map((authorization) => (
                <tr key={authorization.id}>
                  <td className="mono-muted">{authorization.id}</td>
                  <td className="mono-muted">{authorization.request_id}</td>
                  <td>{authorization.case_id?.toUpperCase()}</td>
                  <td>{authorization.granted_to_name}</td>
                  <td>{(authorization.scope_labels || []).join(', ')}</td>
                  <td>{authorization.approved_by_name}</td>
                  <td>{shortTime(authorization.expires_at)}</td>
                  <td>
                    <span className={`status-chip ${authorization.is_active ? 'ok' : 'warn'}`}>
                      {authorization.revoked_at ? 'revoked' : authorization.is_active ? 'active' : 'expired'}
                    </span>
                  </td>
                  <td>
                    {isApprover && authorization.is_active && (
                      <button className="btn btn-ghost btn-sm" onClick={() => revoke(authorization)}
                              disabled={busy} type="button">
                        Revoke
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {selected && (
        <div className="modal-overlay" onClick={() => setSelected(null)}>
          <div className="modal modal-wide" onClick={(e) => e.stopPropagation()}>
            <div className="modal-title">
              {selected.id} — {(selected.category_labels || []).join(', ')}
            </div>
            <div className="access-detail">
              <div><span>Case</span><strong>{selected.case_id?.toUpperCase()}</strong></div>
              <div><span>Requested by</span><strong>{selected.requested_by_name} ({selected.requested_by_role})</strong></div>
              <div><span>Raised</span><strong>{shortTime(selected.created_at)}</strong></div>
              <div><span>Status</span><strong>{selected.status.replace(/_/g, ' ')}</strong></div>
              <div className="access-detail-wide">
                <span>Reason</span><strong>{selected.reason}</strong>
              </div>
              <div className="access-detail-wide">
                <span>Necessity</span><strong>{selected.necessity}</strong>
              </div>
              {selected.related_finding && (
                <div className="access-detail-wide">
                  <span>Related finding</span><strong>{selected.related_finding}</strong>
                </div>
              )}
              {selected.decision && (
                <div className="access-detail-wide">
                  <span>Previous decision</span>
                  <strong>
                    {selected.decision.outcome} by {selected.decision.by_name} at{' '}
                    {shortTime(selected.decision.at)}
                    {selected.decision.reason ? ` — ${selected.decision.reason}` : ''}
                    {selected.decision.note ? ` — ${selected.decision.note}` : ''}
                  </strong>
                </div>
              )}
            </div>

            <div className="access-notice">{selected.notice}</div>

            {isApprover && ['pending', 'clarification_requested'].includes(selected.status) && (
              <>
                <div className="access-scope">
                  <div className="field-label">Approved scope</div>
                  <div className="restricted-categories">
                    {(selected.categories || []).map((key) => {
                      const label = (selected.category_labels || [])[selected.categories.indexOf(key)] || key
                      return (
                        <label key={key} className="restricted-category">
                          <input type="checkbox" checked={scope.includes(key)}
                                 onChange={() => setScope((prev) => prev.includes(key)
                                   ? prev.filter((c) => c !== key)
                                   : [...prev, key])} />
                          <span>
                            <span className="restricted-category-label">{label}</span>
                          </span>
                        </label>
                      )
                    })}
                  </div>
                </div>

                <div className="admin-form-grid">
                  <label className="field">
                    <span className="field-label">Access duration (days)</span>
                    <input className="field-input" type="number" min={1} max={30}
                           value={decision.duration_days}
                           onChange={(e) => setDecision({ ...decision, duration_days: e.target.value })} />
                  </label>
                  <label className="field">
                    <span className="field-label">Note</span>
                    <input className="field-input" value={decision.note}
                           placeholder="Recorded on the authorisation."
                           onChange={(e) => setDecision({ ...decision, note: e.target.value })} />
                  </label>
                  <label className="field vault-add-wide">
                    <span className="field-label">Rejection reason (required to reject)</span>
                    <input className="field-input" value={decision.reason}
                           onChange={(e) => setDecision({ ...decision, reason: e.target.value })} />
                  </label>
                </div>

                <div className="modal-actions">
                  <button className="btn btn-primary btn-sm" onClick={() => decide('approve')}
                          disabled={busy || scope.length === 0} type="button">
                    Approve access
                  </button>
                  <button className="btn btn-secondary btn-sm" onClick={() => decide('clarify')}
                          disabled={busy || !decision.note.trim()} type="button">
                    Request clarification
                  </button>
                  <button className="btn btn-danger btn-sm" onClick={() => decide('reject')}
                          disabled={busy || !decision.reason.trim()} type="button">
                    Reject
                  </button>
                  <button className="btn btn-ghost btn-sm" onClick={() => setSelected(null)}
                          type="button">
                    Close
                  </button>
                </div>
              </>
            )}

            {(!isApprover || !['pending', 'clarification_requested'].includes(selected.status)) && (
              <div className="modal-actions">
                <button className="btn btn-ghost btn-sm" onClick={() => setSelected(null)}
                        type="button">
                  Close
                </button>
              </div>
            )}

            {isApprover && selected.requested_by === undefined && null}
            {role === 'admin' && selected.requested_by_role === 'admin' && (
              <div className="flash flash-warn">
                This request was raised by an administrator. Self-approval is refused by the
                backend, so a different administrator must decide it.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
