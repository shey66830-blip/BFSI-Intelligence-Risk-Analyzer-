import { useCallback, useEffect, useState } from 'react'
import { useRole } from '../context/RoleContext.jsx'
import {
  amendReport, createAnalystReport, fetchCaseReports, requestReportClarification,
  reviewReport, submitReport, updateReport,
} from '../api.js'

const CLASSIFICATION_ORDER = [
  ['observed_fact', 'Observed facts', 'Values read from stored records.'],
  ['model_inference', 'Model-generated inferences', 'Computed by the behavioural engine.'],
  ['analyst_observation', 'Analyst observations', 'Noted by the investigating analyst.'],
  ['recommended_next_step', 'Recommended next steps', 'Proposed lines of enquiry.'],
]

const SECTION_ORDER = [
  'case_information', 'transaction_summary', 'behavioral_analysis',
  'graph_network_findings', 'contextual_findings', 'investigation_findings',
]

function shortTime(iso) {
  if (!iso) return null
  return `${String(iso).slice(0, 16).replace('T', ' ')}Z`
}

function SourceLine({ finding }) {
  const bits = []
  if (finding.source) bits.push(finding.source)
  if (finding.evidence_ids?.length) bits.push(`evidence ${finding.evidence_ids.join(', ')}`)
  if (finding.transaction_ids?.length) bits.push(finding.transaction_ids.join(', '))
  if (!bits.length) return null
  return <div className="report-source">Source: {bits.join(' · ')}</div>
}

/** A section renders whatever the backend put in it: lines in `body`, rows in `items`. */
function Section({ section }) {
  if (!section) return null
  const body = section.body || []
  const items = section.items || []
  if (!body.length && !items.length) return null
  return (
    <div className="report-section">
      <div className="report-section-title">{section.title}</div>
      {body.map((line, i) => (
        <div key={`b${i}`} className="report-line">{line}</div>
      ))}
      {items.map((item, i) => (
        <div key={`i${i}`} className="report-item">
          {Object.entries(item).map(([key, value]) => (
            <div key={key} className="report-item-row">
              <span className="report-item-key">{key.replace(/_/g, ' ')}</span>
              <span className="report-item-value">
                {Array.isArray(value) ? value.join(', ') : String(value ?? '—')}
              </span>
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

/**
 * The analyst's product: a versioned report whose every statement is classified, which
 * is submitted to compliance rather than silently shared, and which is never overwritten
 * once submitted — amending opens the next version.
 */
export default function AnalystReportPanel({ caseId, onChanged }) {
  const { can, user } = useRole()
  const [versions, setVersions] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [flash, setFlash] = useState(null)
  const [summary, setSummary] = useState('')
  const [observation, setObservation] = useState('')
  const [note, setNote] = useState('')
  const [amendReason, setAmendReason] = useState('')

  const load = useCallback(async () => {
    const payload = await fetchCaseReports(caseId)
    const list = payload.versions || []
    setVersions(list)
    setSelectedId((current) => current || list[0]?.id || null)
  }, [caseId])

  useEffect(() => {
    setSelectedId(null)
    setVersions([])
    setError(null)
    setFlash(null)
    load()
  }, [caseId, load])

  const report = versions.find((v) => v.id === selectedId) || versions[0] || null
  const isDraft = report?.status === 'draft'
  const isMine = report?.analyst_id === user?.id

  useEffect(() => {
    setSummary(report?.summary || '')
    setError(null)
  }, [report?.id, report?.summary])

  const run = async (fn, successMessage) => {
    setBusy(true)
    setError(null)
    setFlash(null)
    const result = await fn()
    setBusy(false)
    if (!result.ok) {
      setError(result.body?.error || 'The request was refused.')
      return null
    }
    if (successMessage) setFlash(successMessage)
    await load()
    onChanged?.()
    return result.body
  }

  const handleCreate = () => run(async () => {
    const result = await createAnalystReport(caseId)
    if (result.ok) setSelectedId(result.body.report?.id || null)
    return result
  }, 'Draft built from the case records. Review it, then submit.')

  const handleSaveSummary = () => run(
    () => updateReport(report.id, { summary }), 'Draft updated.')

  const handleAddObservation = () => run(async () => {
    const result = await updateReport(report.id, {
      append_finding: {
        classification: 'analyst_observation',
        statement: observation,
        section: 'investigation_findings',
        source: `analyst note, ${user?.name}`,
      },
    })
    if (result.ok) setObservation('')
    return result
  }, 'Observation recorded against the draft.')

  const handleAddNextStep = () => run(async () => {
    const result = await updateReport(report.id, {
      append_finding: {
        classification: 'recommended_next_step',
        statement: note,
        section: 'investigation_findings',
        source: 'analyst recommendation',
      },
    })
    if (result.ok) setNote('')
    return result
  }, 'Next step recorded against the draft.')

  const handleSubmit = () => run(
    () => submitReport(report.id), 'Submitted to compliance. This version is now locked.')

  const handleAmend = () => run(async () => {
    const result = await amendReport(report.id, amendReason)
    if (result.ok) {
      setAmendReason('')
      setSelectedId(result.body.report?.id || null)
    }
    return result
  }, 'Next version opened. The submitted version is preserved.')

  const handleReview = (outcome) => run(
    () => reviewReport(report.id, outcome, note),
    outcome === 'accepted' ? 'Report accepted and recorded.' : 'Returned to the analyst.')

  const handleClarification = () => run(
    () => requestReportClarification(report.id, note), 'Clarification requested.')

  return (
    <div className="report-panel">
      <div className="report-toolbar">
        <div>
          <div className="report-toolbar-title">Analyst investigation report</div>
          <div className="report-toolbar-sub">
            Every statement is classified as a fact, an inference, an observation or a next
            step, and no version overwrites another.
          </div>
        </div>
        <div className="report-toolbar-actions">
          {can('reports:create') && (
            <button className="btn btn-primary btn-sm" onClick={handleCreate}
                    disabled={busy || (isDraft && isMine)} type="button">
              {isDraft && isMine ? 'Draft in progress' : 'Create investigation report'}
            </button>
          )}
          {report && isDraft && isMine && (
            <button className="btn btn-secondary btn-sm" onClick={handleSubmit}
                    disabled={busy} type="button">
              Submit to compliance
            </button>
          )}
        </div>
      </div>

      {error && <div className="flash flash-error">{error}</div>}
      {flash && <div className="flash flash-ok">{flash}</div>}

      {versions.length > 1 && (
        <div className="report-versions">
          <span className="report-versions-label">Versions</span>
          {versions.map((version) => (
            <button
              key={version.id}
              className={`report-version ${version.id === report?.id ? 'active' : ''} ${version.locked ? 'locked' : ''}`}
              onClick={() => setSelectedId(version.id)}
              type="button"
            >
              v{version.version} · {version.status.replace(/_/g, ' ')}
            </button>
          ))}
        </div>
      )}

      {!report && (
        <div className="card report-empty">
          No analyst report exists for this case yet.
          {can('reports:create')
            ? ' Create one and it will be prefilled from the stored case records.'
            : ' Your role can read a submitted report but not draft one.'}
        </div>
      )}

      {report && (
        <>
          <div className="card report-header">
            <div className="report-header-main">
              <div className="report-title">{report.title}</div>
              <div className="report-meta">
                <span className={`status-chip ${report.locked ? 'ok' : 'warn'}`}>
                  v{report.version} · {report.status.replace(/_/g, ' ')}
                  {report.locked ? ' · locked' : ''}
                </span>
                <span className="mono-muted">{report.id}</span>
                <span className="report-meta-item">Analyst: {report.analyst_name}</span>
                {report.submitted_at && (
                  <span className="report-meta-item">Submitted {shortTime(report.submitted_at)}</span>
                )}
                {report.supersedes && (
                  <span className="report-meta-item">Supersedes {report.supersedes}</span>
                )}
              </div>
              {report.amendment_reason && (
                <div className="report-amendment">Amendment reason: {report.amendment_reason}</div>
              )}
            </div>

            {report.status === 'draft' && isMine ? (
              <div className="report-summary-edit">
                <label className="field">
                  <span className="field-label">Summary</span>
                  <textarea className="field-input" rows={3} value={summary}
                            onChange={(e) => setSummary(e.target.value)} />
                </label>
                <button className="btn btn-secondary btn-sm" onClick={handleSaveSummary}
                        disabled={busy} type="button">
                  Save summary
                </button>
              </div>
            ) : (
              report.summary && <p className="report-summary">{report.summary}</p>
            )}
          </div>

          {report.clarification && (
            <div className="flash flash-warn">
              Clarification requested by {report.clarification.requested_by_name} at{' '}
              {shortTime(report.clarification.requested_at)}: {report.clarification.note}
            </div>
          )}

          {report.review && (
            <div className={`flash ${report.review.outcome === 'accepted' ? 'flash-ok' : 'flash-warn'}`}>
              Reviewed by {report.review.reviewed_by_name} ({report.review.outcome}) at{' '}
              {shortTime(report.review.reviewed_at)}
              {report.review.note ? ` — ${report.review.note}` : ''}
            </div>
          )}

          <div className="card">
            <div className="report-group-title">Findings by classification</div>
            {CLASSIFICATION_ORDER.map(([key, label, description]) => {
              const group = (report.findings || []).filter((f) => f.classification === key)
              return (
                <div key={key} className="report-group">
                  <div className="report-group-head">
                    <span className="report-group-label">{label}</span>
                    <span className="report-group-count">{group.length}</span>
                  </div>
                  <div className="report-group-desc">{description}</div>
                  {group.map((finding) => (
                    <div key={finding.id} className="report-finding">
                      <div className="report-finding-statement">{finding.statement}</div>
                      <SourceLine finding={finding} />
                    </div>
                  ))}
                  {group.length === 0 && (
                    <div className="report-group-empty">Nothing recorded in this class yet.</div>
                  )}
                </div>
              )
            })}
          </div>

          {SECTION_ORDER.map((key) => (
            <div className="card" key={key}>
              <Section section={report.sections?.[key]} />
            </div>
          ))}

          <div className="card report-notice">
            <div className="report-notice-title">Standing notice</div>
            <p>{report.notice}</p>
          </div>

          {report.status === 'draft' && isMine && (
            <div className="card">
              <div className="report-group-title">Add to this draft</div>
              <div className="report-add-grid">
                <label className="field">
                  <span className="field-label">Your observation</span>
                  <textarea className="field-input" rows={2} value={observation}
                            placeholder="What did you check, and what did you find?"
                            onChange={(e) => setObservation(e.target.value)} />
                </label>
                <button className="btn btn-secondary btn-sm" onClick={handleAddObservation}
                        disabled={busy || !observation.trim()} type="button">
                  Add observation
                </button>
                <label className="field">
                  <span className="field-label">Recommended next step</span>
                  <textarea className="field-input" rows={2} value={note}
                            placeholder="What should happen next?"
                            onChange={(e) => setNote(e.target.value)} />
                </label>
                <button className="btn btn-secondary btn-sm" onClick={handleAddNextStep}
                        disabled={busy || !note.trim()} type="button">
                  Add next step
                </button>
              </div>
            </div>
          )}

          {!isDraft && (
            <div className="card">
              <div className="report-group-title">
                {report.status === 'submitted' ? 'Compliance review' : 'Further action'}
              </div>

              {can('reports:clarify') && report.status === 'submitted' && (
                <>
                  <label className="field">
                    <span className="field-label">Note to the analyst</span>
                    <textarea className="field-input" rows={2} value={note}
                              placeholder="Required when returning a report or asking for clarification."
                              onChange={(e) => setNote(e.target.value)} />
                  </label>
                  <div className="report-review-actions">
                    <button className="btn btn-gold btn-sm" onClick={() => handleReview('accepted')}
                            disabled={busy} type="button">
                      Accept report
                    </button>
                    <button className="btn btn-secondary btn-sm" onClick={handleClarification}
                            disabled={busy || !note.trim()} type="button">
                      Request clarification
                    </button>
                    <button className="btn btn-danger btn-sm" onClick={() => handleReview('returned')}
                            disabled={busy || !note.trim()} type="button">
                      Return to analyst
                    </button>
                  </div>
                </>
              )}

              {can('reports:create') && (
                <>
                  <label className="field">
                    <span className="field-label">Reason for amending</span>
                    <textarea className="field-input" rows={2} value={amendReason}
                              placeholder="Recorded against the new version, so the change is auditable."
                              onChange={(e) => setAmendReason(e.target.value)} />
                  </label>
                  <button className="btn btn-secondary btn-sm" onClick={handleAmend}
                          disabled={busy || !amendReason.trim()} type="button">
                    Open next version
                  </button>
                </>
              )}

              {!can('reports:clarify') && !can('reports:create') && (
                <div className="report-group-empty">
                  Your role can read this report but not act on it.
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}
