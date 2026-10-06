import { useCallback, useEffect, useState } from 'react'
import { useRole } from '../context/RoleContext.jsx'
import {
  acknowledgeUpdate, fetchCaseUpdates, fetchComplianceUpdates, postCaseUpdate,
} from '../api.js'

const POSTABLE_TYPES = [
  'finding', 'transaction_identified', 'graph_relationship', 'compliance_note',
]

const TYPE_TONE = {
  analyst_report: 'critical',
  analyst_report_revised: 'high',
  access_request: 'high',
  clarification: 'high',
  bank_report: 'medium',
  evidence_added: 'medium',
  status_change: 'medium',
  risk_change: 'medium',
}

function shortTime(iso) {
  return iso ? `${String(iso).slice(0, 16).replace('T', ' ')}Z` : ''
}

/**
 * The running record of what changed on a case. Structured events, not a chat: each entry
 * states what happened, who recorded it, and whether compliance has seen it.
 */
export default function InvestigationUpdates({ caseId, crossCase = false, onOpenCase, onChanged }) {
  const { can } = useRole()
  const [updates, setUpdates] = useState([])
  const [unacknowledged, setUnacknowledged] = useState(0)
  const [filter, setFilter] = useState('all')
  const [acknowledging, setAcknowledging] = useState(null)
  const [ackNote, setAckNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [flash, setFlash] = useState(null)
  const [composing, setComposing] = useState(false)
  const [draft, setDraft] = useState({ type: 'finding', title: '', description: '' })

  const load = useCallback(async () => {
    if (crossCase) {
      const payload = await fetchComplianceUpdates({ acknowledged: filter === 'unacknowledged' ? 'false' : 'all' })
      if (payload?.error) {
        setError(payload.error)
        setUpdates([])
        return
      }
      setUpdates(payload.updates || [])
      setUnacknowledged(payload.unacknowledged || 0)
      setError(null)
      return
    }
    const payload = await fetchCaseUpdates(caseId)
    if (payload?.error) {
      setError(payload.error)
      return
    }
    setUpdates(payload.updates || [])
    setUnacknowledged(payload.unacknowledged || 0)
    setError(null)
  }, [caseId, crossCase, filter])

  useEffect(() => {
    setUpdates([])
    setError(null)
    load()
  }, [load])

  const handleAcknowledge = async () => {
    setBusy(true)
    const result = await acknowledgeUpdate(acknowledging, ackNote)
    setBusy(false)
    if (!result.ok) {
      setError(result.body?.error || 'Could not acknowledge the update.')
      return
    }
    setAcknowledging(null)
    setAckNote('')
    setFlash('Update acknowledged.')
    await load()
    onChanged?.()
  }

  const handlePost = async () => {
    setBusy(true)
    const result = await postCaseUpdate(caseId, draft)
    setBusy(false)
    if (!result.ok) {
      setError(result.body?.error || 'Could not post the update.')
      return
    }
    setDraft({ type: 'finding', title: '', description: '' })
    setComposing(false)
    setFlash('Update posted and compliance notified.')
    await load()
    onChanged?.()
  }

  const shown = updates.filter((item) => (
    crossCase || filter === 'all' ? true : item.acknowledged_at === null
  ))

  return (
    <div className="updates-panel">
      <div className="updates-head">
        <div>
          <div className="vault-title">
            {crossCase ? 'Investigation updates' : 'Case updates'}
          </div>
          <div className="vault-sub">
            {unacknowledged > 0
              ? `${unacknowledged} update(s) awaiting acknowledgement.`
              : 'Everything recorded has been acknowledged.'}
          </div>
        </div>
        <div className="updates-actions">
          {!crossCase && (
            <div className="segmented">
              <button className={filter === 'all' ? 'active' : ''}
                      onClick={() => setFilter('all')} type="button">All</button>
              <button className={filter === 'unacknowledged' ? 'active' : ''}
                      onClick={() => setFilter('unacknowledged')} type="button">Unacknowledged</button>
            </div>
          )}
          {!crossCase && can('updates:post') && (
            <button className="btn btn-secondary btn-sm" onClick={() => setComposing(!composing)}
                    type="button">
              Post an update
            </button>
          )}
        </div>
      </div>

      {error && <div className="flash flash-error">{error}</div>}
      {flash && <div className="flash flash-ok">{flash}</div>}

      {composing && (
        <div className="card">
          <div className="report-group-title">New update</div>
          <div className="admin-form-grid">
            <label className="field">
              <span className="field-label">Type</span>
              <select className="field-input" value={draft.type}
                      onChange={(e) => setDraft({ ...draft, type: e.target.value })}>
                {POSTABLE_TYPES.map((type) => (
                  <option key={type} value={type}>{type.replace(/_/g, ' ')}</option>
                ))}
              </select>
            </label>
            <label className="field">
              <span className="field-label">Title</span>
              <input className="field-input" value={draft.title}
                     onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
            </label>
            <label className="field vault-add-wide">
              <span className="field-label">What changed</span>
              <textarea className="field-input" rows={2} value={draft.description}
                        onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
            </label>
          </div>
          <button className="btn btn-primary btn-sm" onClick={handlePost}
                  disabled={busy || !draft.title.trim()} type="button">
            Post update
          </button>
        </div>
      )}

      {shown.length === 0 && (
        <div className="card vault-empty">Nothing recorded yet.</div>
      )}

      <div className="updates-list">
        {shown.map((item) => (
          <div key={item.id}
               className={`update-row tone-${TYPE_TONE[item.type] || 'low'} ${item.acknowledged_at ? 'acknowledged' : ''}`}>
            <div className="update-row-main">
              <div className="update-row-head">
                <span className="update-type">{item.type_label || item.type}</span>
                {crossCase && (
                  <button className="update-case-link"
                          onClick={() => onOpenCase?.(item.case_id)} type="button">
                    {item.case_id.toUpperCase()}
                  </button>
                )}
                <span className="update-time">{shortTime(item.created_at)}</span>
              </div>
              <div className="update-row-title">{item.title}</div>
              {item.description && <div className="update-row-desc">{item.description}</div>}
              <div className="update-row-meta">
                {item.submitted_by_name} · {item.submitted_by_role || 'system'}
                {item.acknowledged_at
                  ? ` · acknowledged by ${item.acknowledged_by_name} ${shortTime(item.acknowledged_at)}`
                  : ' · not yet acknowledged'}
                {item.acknowledgement_note ? ` · ${item.acknowledgement_note}` : ''}
              </div>
            </div>

            {!item.acknowledged_at && can('updates:acknowledge') && (
              <div className="update-row-action">
                <button className="btn btn-ghost btn-sm"
                        onClick={() => { setAcknowledging(item.id); setAckNote('') }}
                        type="button">
                  Acknowledge
                </button>
              </div>
            )}
          </div>
        ))}
      </div>

      {acknowledging && (
        <div className="modal-overlay" onClick={() => setAcknowledging(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-title">Acknowledge update</div>
            <p className="modal-text">
              Recording that you have reviewed this keeps the feed honest about what has and
              has not been read.
            </p>
            <label className="field">
              <span className="field-label">Note (optional)</span>
              <textarea className="field-input" rows={2} value={ackNote}
                        onChange={(e) => setAckNote(e.target.value)} />
            </label>
            <div className="modal-actions">
              <button className="btn btn-primary btn-sm" onClick={handleAcknowledge}
                      disabled={busy} type="button">
                Acknowledge
              </button>
              <button className="btn btn-ghost btn-sm" onClick={() => setAcknowledging(null)}
                      type="button">
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
