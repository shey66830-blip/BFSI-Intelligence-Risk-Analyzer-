import { useEffect, useMemo, useState } from 'react'
import { fetchPipelineFlow, submitDecision } from '../api.js'
import { useRole } from '../context/RoleContext.jsx'

const STATUS_ICON = { done: '✓', skipped: '—', pending: '·' }
const ACTOR_LABEL = { system: 'Context Guard', bank: 'Banks', human: 'Human' }

function pct(value) {
  return `${Math.round((value || 0) * 100)}%`
}

function stamp(ts) {
  return ts ? `${ts.slice(0, 16).replace('T', ' ')}Z` : '—'
}

function scoreColor(score) {
  if (score < 0.35) return 'var(--risk-low)'
  if (score <= 0.65) return 'var(--risk-medium)'
  return 'var(--risk-critical)'
}

function KeyValues({ data }) {
  const entries = Object.entries(data || {}).filter(
    ([, value]) => typeof value !== 'object' || value === null
  )
  if (!entries.length) return null
  return (
    <div className="kv-grid">
      {entries.map(([key, value]) => (
        <div key={key} className="kv-row">
          <span className="kv-key">{key.replace(/_/g, ' ')}</span>
          <span className="kv-value">
            {value === true ? 'yes' : value === false ? 'no' : String(value)}
          </span>
        </div>
      ))}
    </div>
  )
}

function ReasonList({ reasons }) {
  if (!reasons?.length) return null
  return (
    <ul className="mini-list">
      {reasons.map((reason, index) => (
        <li key={index} className="mini-item">
          <span className={`severity-dot ${reason.severity}`} />
          <span className="mini-signal">{reason.signal}</span>
          <span className="mini-text">{reason.description}</span>
        </li>
      ))}
    </ul>
  )
}

function BankReportCard({ report }) {
  return (
    <div className="bank-report">
      <div className="bank-report-head">
        <strong>{report.responding_bank_name || report.responding_bank}</strong>
        <span className={`status-chip ${report.status === 'completed' ? 'ok' : 'warn'}`}>
          {report.status}
        </span>
        <span className="mono-muted">{report.request_id}</span>
      </div>
      <KeyValues data={report.data} />
    </div>
  )
}

function StageDetail({ stage }) {
  const d = stage.detail || {}

  switch (stage.key) {
    case 'transaction': {
      const t = d.transaction
      if (!t) return null
      return (
        <div className="stage-detail">
          <KeyValues
            data={{
              transaction_id: t.id,
              amount: `${t.currency} ${t.amount?.toLocaleString()}`,
              type: t.type,
              entity: d.entity?.name || t.entity_id,
              bank: d.bank?.name || t.bank_id,
              counterparty: t.counterparty,
              device: t.device_id,
              country: t.country,
              history_reviewed: `${d.history_size} prior transactions`,
            }}
          />
        </div>
      )
    }

    case 'initial_analysis':
      return (
        <div className="stage-detail">
          <div className="score-line">
            <span className="score-label">Activity score</span>
            <div className="score-track">
              <div className="score-fill" style={{ width: pct(d.activity_score || d.transaction_score), background: scoreColor(d.activity_score || d.transaction_score) }} />
            </div>
            <span className="score-value" style={{ color: scoreColor(d.activity_score || d.transaction_score) }}>
              {pct(d.activity_score || d.transaction_score)}
            </span>
          </div>
          <ReasonList reasons={d.reasons} />
          {d.method && <div className="stage-note">{d.method}</div>}
        </div>
      )

    case 'anomaly_gate': {
      const open = d.decision === 'investigate'
      return (
        <div className="stage-detail">
          <div className={`gate ${open ? 'gate-open' : 'gate-closed'}`}>
            <div className="gate-verdict">{open ? 'YES' : 'NO'}</div>
            <div>
              <div className="gate-score">
                {pct(d.score)} vs {pct(d.threshold)} threshold
              </div>
              <div className="gate-route">
                {open ? `Routing to ${String(d.route).replace(/_/g, ' ')}` : 'Stays in routine monitoring'}
              </div>
            </div>
          </div>
          <ReasonList reasons={d.top_reasons} />
        </div>
      )
    }

    case 'case_created':
      return (
        <div className="stage-detail">
          <KeyValues
            data={{
              case_id: d.case_id,
              status: d.status,
              trigger_transaction: d.trigger_transaction_id,
              accounts: (d.entity_ids || []).length,
              banks: (d.bank_ids || []).join(', '),
            }}
          />
          <ReasonList reasons={d.why} />
        </div>
      )

    case 'banks_identified':
      return (
        <div className="stage-detail">
          <div className="bank-chips">
            {(d.banks || []).map((bank) => (
              <span key={bank.bank_id || bank.id} className="bank-chip">
                {bank.name}
                {bank.country ? <em>{bank.country}</em> : null}
              </span>
            ))}
          </div>
          <div className="stage-note">{d.basis}</div>
        </div>
      )

    case 'request_sent': {
      const r = d.request || {}
      return (
        <div className="stage-detail">
          <KeyValues
            data={{
              request_id: r.request_id,
              type: r.type,
              sent: stamp(r.timestamp),
              to_bank: r.to_bank || (r.participating_banks || []).join(', '),
              priority: r.priority,
              consent_required: r.consent_required ?? true,
              retention_policy: r.retention_policy,
              legal_basis: r.legal_basis,
            }}
          />
          {(r.requested_data || r.requested_fields) && (
            <div className="chip-row">
              {(r.requested_data || r.requested_fields).map((item) => (
                <span key={item} className="scope-chip">{item.replace(/_/g, ' ')}</span>
              ))}
            </div>
          )}
        </div>
      )
    }

    case 'bank_analysis':
      return (
        <div className="stage-detail">
          <div className="privacy-note">
            Each bank searches only its own records. No bank sees another bank's raw data.
          </div>
        </div>
      )

    case 'reports_returned':
      return (
        <div className="stage-detail">
          {(d.reports || []).map((report, i) => (
            <BankReportCard
              key={`${report.request_id}-${report.responding_bank}-${i}`}
              report={report}
            />
          ))}
        </div>
      )

    case 'correlation':
      return (
        <div className="stage-detail">
          {(d.findings || []).map((finding) => (
            <div key={finding.id} className={`finding ${finding.strength}`}>
              <div className="finding-head">
                <span className="finding-id">{finding.id}</span>
                <span className={`strength-chip ${finding.strength}`}>
                  {finding.strength?.replace('_', ' ')}
                </span>
                <span className="finding-title">{finding.title}</span>
              </div>
            </div>
          ))}
        </div>
      )

    case 'report_generated': {
      const report = d.report || {}
      return (
        <div className="stage-detail">
          <div className="stage-note">{report.headline}</div>
          <div className="stage-note mono-muted">
            {report.report_id} · {stamp(report.generated_at)}
          </div>
        </div>
      )
    }

    case 'risk_assessment': {
      return (
        <div className="stage-detail">
          <div className="stage-note">{d.summary}</div>
        </div>
      )
    }

    case 'decision':
      return (
        <div className="stage-detail">
          <KeyValues
            data={{
              investigator: d.investigator,
              decision: d.label,
              rationale: d.rationale,
              decided_at: stamp(d.decided_at),
              case_status: d.resulting_status,
            }}
          />
        </div>
      )

    default:
      return null
  }
}

function StageRow({ stage, expanded, onToggle, revealed }) {
  return (
    <div className={`stage-row ${stage.status} ${revealed ? '' : 'unrevealed'}`}>
      <button className="stage-head" onClick={onToggle} type="button">
        <span className={`stage-marker ${stage.status}`}>{STATUS_ICON[stage.status] || '·'}</span>
        <span className="stage-order">{String(stage.order).padStart(2, '0')}</span>
        <span className="stage-main">
          <span className="stage-title-line">
            <span className="stage-title">{stage.title}</span>
            <span className={`actor-badge ${stage.actor}`}>{ACTOR_LABEL[stage.actor]}</span>
          </span>
          <span className="stage-summary">{stage.summary}</span>
        </span>
        <span className="stage-chevron">{expanded ? '−' : '+'}</span>
      </button>
      {expanded && <StageDetail stage={stage} />}
    </div>
  )
}

function ReportView({ report }) {
  if (!report) return null
  return (
    <div className="report">
      <div className="report-head">
        <div>
          <div className="report-kicker">AI-drafted investigation report</div>
          <div className="report-headline">{report.headline || 'Investigation Report'}</div>
          <div className="mono-muted">
            {report.report_id} · {stamp(report.generated_at)}
          </div>
        </div>
      </div>

      {/* Confidence */}
      {report.confidence && (
        <div className="confidence-block">
          <div className="confidence-overall">
            <span className="confidence-number" style={{ color: scoreColor(report.confidence.overall || 0) }}>
              {pct(report.confidence.overall || 0)}
            </span>
            <span className="confidence-caption">assessment confidence</span>
          </div>
          {report.confidence.pattern !== undefined && (
            <div className="dimension">
              <div className="dimension-head">
                <span>Pattern confidence</span>
                <span className="mono-muted">{pct(report.confidence.pattern)}</span>
              </div>
              <div className="score-track">
                <div className="score-fill" style={{ width: pct(report.confidence.pattern), background: scoreColor(report.confidence.pattern) }} />
              </div>
              <div className="dimension-question">Did the pattern actually happen, backed by multiple sources?</div>
            </div>
          )}
          {report.confidence.intent !== undefined && (
            <div className="dimension">
              <div className="dimension-head">
                <span>Intent confidence</span>
                <span className="mono-muted">{pct(report.confidence.intent)}</span>
              </div>
              <div className="score-track">
                <div className="score-fill" style={{ width: pct(report.confidence.intent), background: scoreColor(report.confidence.intent) }} />
              </div>
              <div className="dimension-question">Can we explain why the money moved?</div>
            </div>
          )}
        </div>
      )}

      {/* Sections */}
      {(report.sections || []).map((section) => (
        <div key={section.title} className="report-section">
          <div className="report-section-title">{section.title}</div>
          {(section.body || []).map((paragraph, index) => (
            <p key={index} className="report-paragraph">{paragraph}</p>
          ))}
          {section.bullets?.length > 0 && (
            <ul className="report-bullets">
              {section.bullets.map((bullet, index) => (
                <li key={index}>{bullet}</li>
              ))}
            </ul>
          )}
        </div>
      ))}

      {report.disclaimer && <div className="report-disclaimer">{report.disclaimer}</div>}
    </div>
  )
}

function DecisionPanel({ caseId, options, decision, onRecorded, canEscalate, roleLabel, user }) {
  const [choice, setChoice] = useState('')
  const [rationale, setRationale] = useState('')
  const [error, setError] = useState(null)
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    setBusy(true)
    setError(null)
    // Attribution is taken from the authenticated session by the backend.
    const result = await submitDecision(caseId, { decision: choice, rationale })
    setBusy(false)
    if (!result.ok) {
      setError(result.body?.error || 'Could not record the decision')
      return
    }
    setEditing(false)
    setChoice('')
    setRationale('')
    onRecorded(result.body.decision)
  }

  if (decision && !editing) {
    return (
      <div className="decision-recorded">
        <div className="decision-recorded-head">
          <span className="status-chip ok">decided</span>
          <strong>{decision.label}</strong>
        </div>
        <KeyValues
          data={{
            investigator: decision.investigator,
            rationale: decision.rationale,
            decided_at: stamp(decision.decided_at),
            case_status: decision.resulting_status,
          }}
        />
        <button className="btn btn-ghost" type="button" onClick={() => setEditing(true)}>
          Record a different decision
        </button>
      </div>
    )
  }

  return (
    <div className="decision-panel">
      <div className="decision-title">Stage 12 — record your decision</div>
      <p className="decision-help">
        Context Guard produced indicators and a draft. The judgement is yours, recorded in
        your name with your reasoning and written to the audit trail.
      </p>
      {canEscalate === false && (
        <div className="decision-restriction">
          Your role ({roleLabel}) may close a case or request more context. Escalation to
          compliance / FIU requires a compliance officer.
        </div>
      )}
      <div className="decision-options">
        {(options || []).map((option) => (
          <button
            key={option.value}
            type="button"
            className={`decision-option ${choice === option.value ? 'selected' : ''}`}
            onClick={() => setChoice(option.value)}
          >
            <span className="decision-option-label">{option.label}</span>
            <span className="decision-option-desc">{option.description}</span>
          </button>
        ))}
      </div>
      <div className="decision-fields">
        <div className="decision-actor">
          <span className="decision-actor-label">Recording as</span>
          <span className="decision-actor-name">{user?.name}</span>
          <span className="decision-actor-role">{roleLabel}</span>
        </div>
        <label className="field">
          <span>Rationale</span>
          <textarea
            value={rationale}
            onChange={(event) => setRationale(event.target.value)}
            rows={3}
            placeholder="Why this decision follows from the report"
          />
        </label>
      </div>
      {error && <div className="decision-error">{error}</div>}
      <div className="decision-actions">
        <button
          className="btn btn-primary"
          type="button"
          disabled={!choice || !rationale || busy}
          onClick={submit}
        >
          {busy ? 'Recording…' : 'Record decision'}
        </button>
        {editing && (
          <button className="btn btn-ghost" type="button" onClick={() => setEditing(false)}>
            Cancel
          </button>
        )}
      </div>
    </div>
  )
}

export default function PipelinePanel({ caseData, onRunPipeline, running }) {
  const { user, roleConfig, can } = useRole()
  const [flow, setFlow] = useState(null)
  const [trace, setTrace] = useState(caseData.pipeline_trace || null)
  const [report, setReport] = useState(caseData.pipeline_report || null)
  const [decision, setDecision] = useState(caseData.decision || null)
  const [revealed, setRevealed] = useState(trace ? trace.length : 0)
  const [expanded, setExpanded] = useState(() => new Set(['anomaly_gate', 'correlation']))

  useEffect(() => {
    fetchPipelineFlow().then(setFlow)
  }, [])

  useEffect(() => {
    setTrace(caseData.pipeline_trace || null)
    setReport(caseData.pipeline_report || null)
    setDecision(caseData.decision || null)
    setRevealed(caseData.pipeline_trace ? caseData.pipeline_trace.length : 0)
  }, [caseData.id, caseData.pipeline_trace, caseData.pipeline_report, caseData.decision])

  const rows = useMemo(() => {
    if (!flow) return []
    const byKey = Object.fromEntries((trace || []).map((stage) => [stage.key, stage]))
    return flow.stages.map(
      (meta) =>
        byKey[meta.key] || {
          ...meta,
          status: 'pending',
          summary: 'Not run yet',
          detail: {},
        }
    )
  }, [flow, trace])

  const toggle = (key) => {
    setExpanded((previous) => {
      const next = new Set(previous)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  // Reveal stages one at a time
  useEffect(() => {
    if (!trace || running) return
    if (revealed >= trace.length) return
    const timer = setTimeout(() => setRevealed((count) => count + 1), 110)
    return () => clearTimeout(timer)
  }, [trace, revealed, running])

  if (!flow) {
    return (
      <div className="loading">
        <div className="spinner" />
        Loading pipeline…
      </div>
    )
  }

  const hasReport = Boolean(report)

  return (
    <div className="pipeline">
      <div className="pipeline-bar">
        <div>
          <div className="pipeline-title">Investigation pipeline</div>
          <div className="pipeline-sub">
            Anomaly threshold {pct(flow.anomaly_threshold)} · investigation threshold{' '}
            {pct(flow.investigation_threshold)}. Every stage records what it did and why.
          </div>
        </div>
        <button className="btn btn-primary" type="button" onClick={() => onRunPipeline?.(caseData.id)} disabled={running || !can('cases:investigate')}>
          {running ? 'Running…' : hasReport ? 'Re-run pipeline' : 'Run pipeline'}
        </button>
      </div>

      <div className="stage-list">
        {rows.map((stage, index) => (
          <StageRow
            key={stage.key}
            stage={stage}
            revealed={index < revealed}
            expanded={expanded.has(stage.key)}
            onToggle={() => toggle(stage.key)}
          />
        ))}
      </div>

      {hasReport ? (
        <>
          <ReportView report={report} />
          <DecisionPanel
            caseId={caseData.id}
            options={flow.decision_options}
            decision={decision}
            canEscalate={flow.can_escalate ?? can('cases:decide')}
            roleLabel={roleConfig?.label || user?.role}
            user={user}
            onRecorded={(recorded) => {
              setDecision(recorded)
              setTrace((current) =>
                (current || []).map((stage) =>
                  stage.key === 'decision'
                    ? {
                        ...stage,
                        status: 'done',
                        summary: `${recorded.investigator} decided: ${recorded.label}`,
                        detail: { ...recorded },
                      }
                    : stage
                )
              )
              setExpanded((previous) => new Set(previous).add('decision'))
            }}
          />
        </>
      ) : (
        <div className="pipeline-empty">
          No report yet. Run the pipeline to identify banks, request reports, correlate evidence, and draft the report.
        </div>
      )}
    </div>
  )
}
