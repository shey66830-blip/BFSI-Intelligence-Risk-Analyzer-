import { useCallback, useEffect, useMemo, useState } from 'react'
import { useRole } from '../context/RoleContext.jsx'
import { createAccessRequest, fetchLockedResources } from '../api.js'
import {
  LOCKED_STATE_LABEL as STATE_LABEL,
  countWords,
  meetsStatementMinimum,
  shortTime,
} from '../lib/format.js'

const DURATIONS = [1, 3, 7, 14, 30]

/**
 * Locked features and information.
 *
 * Some capabilities and some records are withheld from an analyst and a compliance
 * officer alike. Releasing them is not a role privilege: the item names who has to be
 * asked — the bank that holds the record, or an administrator acting for the
 * organisation — and the request does not move without a written statement of why it
 * is needed. Whatever is said, by whoever says it, is recorded even when nothing here
 * displays it.
 */
export default function LockedAccess({ caseId, onChanged }) {
  const { can } = useRole()
  const [state, setState] = useState(null)
  const [selected, setSelected] = useState([])
  const [form, setForm] = useState({ statement: '', duration_days: 7 })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [flash, setFlash] = useState(null)
  const [decision, setDecision] = useState(null)

  const load = useCallback(async () => {
    const payload = await fetchLockedResources(caseId)
    setState(payload)
  }, [caseId])

  useEffect(() => {
    setState(null); setSelected([]); setError(null); setFlash(null); setDecision(null)
    load()
  }, [caseId, load])

  const resources = state?.resources || []
  const open = resources.filter((r) => r.state !== 'granted')

  const groups = useMemo(() => {
    const by = { bank: [], admin: [] }
    for (const item of resources) by[item.track]?.push(item)
    return by
  }, [resources])

  const selectedTrack = resources.find((r) => selected.includes(r.key))?.track || null
  const minimum = state?.min_statement_words || 25
  const wordCount = countWords(form.statement)

  const toggle = (item) => {
    setSelected((previous) => {
      if (previous.includes(item.key)) return previous.filter((k) => k !== item.key)
      // Bank-held records and organisation-held capabilities are decided by different
      // parties, so they are not requested in one breath.
      if (item.track !== selectedTrack && selectedTrack) return previous
      return [...previous, item.key]
    })
  }

  const submit = async () => {
    setBusy(true)
    setError(null)
    const result = await createAccessRequest({
      case_id: caseId, resource_keys: selected, ...form,
    })
    setBusy(false)
    if (!result.ok) {
      setError(result.body?.error || 'The request was refused.')
      return
    }
    const body = result.body || {}
    const decided = body.bank_decision
    const awaiting = body.bank_state === 'awaiting' || body.bank_state === 'failed'
    setFlash(
      decided
        ? `Request ${body.request?.id} answered by ${decided.bank_name}.`
        : awaiting
          ? `Request ${body.request?.id} is with the bank; it has until `
            + `${shortTime(body.request?.response_deadline)} to answer.`
          : `Request ${body.request?.id} submitted to ${body.request?.decider || 'an administrator'}.`
    )
    setDecision(decided || null)
    setSelected([])
    setForm({ statement: '', duration_days: 7 })
    await load()
    onChanged?.()
  }

  if (!state) return <div className="loading"><div className="spinner" /> Checking what is locked…</div>

  const released = state.released || []
  const unlocks = state.active_unlocks || []

  return (
    <div className="locked">
      <div className="locked-head">
        <div>
          <div className="report-group-title">Locked features and information</div>
          <p className="locked-help">
            Held back from every role, not just yours. Each item names who has to be asked,
            and a request is not considered until it states why the item is needed.
          </p>
        </div>
        {unlocks.length > 0 && (
          <span className="locked-unlocks">released to you: {unlocks.join(', ')}</span>
        )}
      </div>

      {flash && <div className="flash flash-ok">{flash}</div>}
      {decision && (
        <div className={`locked-answer ${decision.outcome}`}>
          <div className="locked-answer-head">
            <span>{decision.bank_name}</span>
            <span className="status-chip">{decision.outcome.replace(/_/g, ' ')}</span>
          </div>
          <div className="locked-answer-body">{decision.statement}</div>
          {(decision.refused_keys || []).length > 0 && (
            <div className="locked-answer-meta">
              released: {(decision.approved_keys || []).join(', ') || 'nothing'}
              {' '}· refused: {decision.refused_keys.join(', ')}
            </div>
          )}
          <div className="locked-answer-meta">
            reviewed by {decision.reviewer} · {shortTime(decision.reviewed_at)}
            {' '}· {decision.consent_records?.length || 0} consent record(s) checked
          </div>
        </div>
      )}

      {['bank', 'admin'].map((track) => (
        <div className="card" key={track}>
          <div className="report-group-title">
            {track === 'bank'
              ? 'Held by the bank — the bank decides'
              : 'Held by the organisation — an administrator decides'}
          </div>
          <div className="locked-grid">
            {(groups[track] || []).map((item) => (
              <label
                key={item.key}
                className={`locked-item ${item.state}${selected.includes(item.key) ? ' selected' : ''}${
                  selectedTrack && selectedTrack !== item.track ? ' disabled' : ''
                }`}
              >
                <input
                  type="checkbox"
                  checked={selected.includes(item.key)}
                  disabled={item.state === 'granted' || item.state === 'pending'
                    || item.state === 'awaiting_bank'
                    || Boolean(selectedTrack && selectedTrack !== item.track)}
                  onChange={() => toggle(item)}
                />
                <span className="locked-item-body">
                  <span className="locked-item-top">
                    <span className="locked-item-label">{item.label}</span>
                    <span className={`locked-chip ${item.state}`}>
                      {STATE_LABEL[item.state] || item.state}
                    </span>
                  </span>
                  <span className="locked-item-desc">{item.description}</span>
                  <span className="locked-item-meta">
                    releases {item.unlock_label}
                    {item.remaining ? ` · ${item.remaining}` : ''}
                    {item.request_id ? ` · ${item.request_id} ${item.request_status || ''}` : ''}
                    {item.response_deadline && item.state !== 'granted'
                      ? ` · bank has until ${shortTime(item.response_deadline)}` : ''}
                  </span>
                  {item.bank_error && (
                    <span className="locked-item-refusal">
                      The submission failed in transit: {item.bank_error}
                    </span>
                  )}
                  {item.decision_reason && item.state === 'rejected' && (
                    <span className="locked-item-refusal">
                      Refused by {item.decided_by || item.decider}: {item.decision_reason}
                    </span>
                  )}
                </span>
              </label>
            ))}
          </div>
        </div>
      ))}

      {released.map((record) => (
        <div className="card locked-released" key={record.resource}>
          <div className="locked-released-head">
            <div className="report-group-title">{record.title}</div>
            <div className="locked-released-meta">
              {record.released_by} · {record.request_id} · until {shortTime(record.expires_at)}
            </div>
          </div>
          <div className="locked-released-note">{record.note}</div>
          {record.provenance && (
            <div className="locked-released-prov">
              {record.provenance.origin_label}
              {record.provenance.bank ? ` · ${record.provenance.bank}` : ''}
              {record.provenance.authorization_id ? ` · ${record.provenance.authorization_id}` : ''}
              {record.provenance.released_to ? ` · released to ${record.provenance.released_to}` : ''}
            </div>
          )}
          {(record.rows || []).length === 0 && (
            <div className="locked-released-note">The bank returned no rows for this case.</div>
          )}
          <table className="admin-table">
            <thead>
              <tr>
                {Object.keys(record.rows?.[0] || {}).map((key) => (
                  <th key={key}>{key.replace(/_/g, ' ')}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(record.rows || []).map((row, index) => (
                <tr key={index}>
                  {Object.values(row).map((value, cell) => (
                    <td key={cell}>{value === null || value === undefined ? '—' : String(value)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}

      {state.can_request ? (
        <div className="card">
          <div className="report-group-title">Ask for access</div>
          <p className="locked-help">
            Select the items you need and state why. A request without a statement is refused
            before it reaches anybody: the statement is what the decision is made on, and it is
            recorded in the audit trail whether or not it is ever displayed again.
          </p>

          {error && <div className="flash flash-error">{error}</div>}

          <label className="field">
            <span className="field-label">
              Statement — {wordCount} of {minimum} words minimum
            </span>
            <textarea
              className="field-input"
              rows={4}
              value={form.statement}
              placeholder="What is needed, what it is needed for, and why it cannot be established from what you already have."
              onChange={(event) => setForm({ ...form, statement: event.target.value })}
            />
          </label>

          <div className="locked-form-row">
            <label className="field">
              <span className="field-label">Requested for</span>
              <select
                className="field-input"
                value={form.duration_days}
                onChange={(event) => setForm({ ...form, duration_days: Number(event.target.value) })}
              >
                {DURATIONS.map((days) => (
                  <option key={days} value={days}>{days} day(s)</option>
                ))}
              </select>
            </label>
            <div className="locked-form-target">
              {selected.length === 0
                ? 'Nothing selected yet.'
                : selectedTrack === 'bank'
                  ? 'Goes to the bank holding the record.'
                  : 'Goes to an organisation administrator.'}
              {open.length === 0 && ' Every item on this case has already been released.'}
            </div>
            <button
              className="btn btn-primary"
              type="button"
              disabled={busy || selected.length === 0 || !meetsStatementMinimum(form.statement, minimum)
                || (selectedTrack === 'admin' && !can('access:request'))}
              onClick={submit}
            >
              {busy ? 'Submitting…' : 'Submit request'}
            </button>
          </div>
        </div>
      ) : (
        <div className="card vault-empty">
          Your role cannot raise access requests.
        </div>
      )}
    </div>
  )
}
