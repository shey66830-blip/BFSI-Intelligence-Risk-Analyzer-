import { useEffect, useState } from 'react'
import { fetchPipelineFlow, ingestTransaction } from '../api.js'

const STATUS_ICON = { done: '✓', skipped: '—', pending: '·' }

function pct(value) {
  return `${Math.round((value || 0) * 100)}%`
}

function scoreColor(score) {
  if (score < 0.35) return 'var(--risk-low)'
  if (score <= 0.65) return 'var(--risk-medium)'
  return 'var(--risk-critical)'
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
          </span>
          <span className="stage-summary">{stage.summary}</span>
        </span>
        <span className="stage-chevron">{expanded ? '−' : '+'}</span>
      </button>
      {expanded && stage.detail && (
        <div className="stage-detail">
          {stage.detail.reasons && (
            <ul className="mini-list">
              {stage.detail.reasons.map((r, i) => (
                <li key={i} className="mini-item">
                  <span className={`severity-dot ${r.severity}`} />
                  <span className="mini-signal">{r.signal}</span>
                  <span className="mini-text">{r.description}</span>
                </li>
              ))}
            </ul>
          )}
          {stage.detail.decision && (
            <div className={`gate ${stage.detail.decision === 'investigate' ? 'gate-open' : 'gate-closed'}`}>
              <div className="gate-verdict">{stage.detail.decision === 'investigate' ? 'YES' : 'NO'}</div>
              <div>
                <div className="gate-score">{pct(stage.detail.score)} vs {pct(stage.detail.threshold)} threshold</div>
                <div className="gate-route">{stage.detail.route}</div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/**
 * Stages 1-4 of the pipeline, driven live: a transaction arrives, the engine
 * analyses it, the gate decides, and a case may be opened.
 */
export default function LiveFeedPanel({ onOpenCase }) {
  const [flow, setFlow] = useState(null)
  const [scenario, setScenario] = useState('coordinated')
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [revealed, setRevealed] = useState(0)
  const [expanded, setExpanded] = useState(() => new Set(['anomaly_gate']))

  useEffect(() => {
    fetchPipelineFlow().then(setFlow)
  }, [])

  useEffect(() => {
    if (!result || revealed >= result.trace.length) return
    const timer = setTimeout(() => setRevealed((count) => count + 1), 140)
    return () => clearTimeout(timer)
  }, [result, revealed])

  const simulate = async () => {
    setBusy(true)
    setResult(null)
    setRevealed(0)
    const body = await ingestTransaction(scenario)
    setResult(body)
    setBusy(false)
  }

  const toggle = (key) => {
    setExpanded((previous) => {
      const next = new Set(previous)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const scenarios = {
    routine: 'Everyday card spend on an established account',
    high_value: 'Large payment with contextual explanation (hospital scenario)',
    coordinated: 'Cross-bank coordinated activity pattern',
  }

  const gate = result?.trace?.find((stage) => stage.key === 'anomaly_gate')

  return (
    <div className="live-panel">
      <div className="live-head">
        <div>
          <div className="pipeline-title">Transaction monitor</div>
          <div className="pipeline-sub">
            Feed a transaction in and watch stages 1–4 run: analysis, then the anomaly gate.
          </div>
        </div>
        <div className="live-controls">
          <div className="scenario-chips">
            {Object.keys(scenarios).map((key) => (
              <button
                key={key}
                type="button"
                className={`scenario-chip ${scenario === key ? 'selected' : ''}`}
                onClick={() => setScenario(key)}
              >
                {key.replace('_', ' ')}
              </button>
            ))}
          </div>
          <button className="btn btn-primary" type="button" onClick={simulate} disabled={busy}>
            {busy ? 'Analysing…' : 'Simulate transaction'}
          </button>
        </div>
      </div>

      {scenarios[scenario] && (
        <div className="live-scenario-desc">{scenarios[scenario]}</div>
      )}

      {result && (
        <>
          <div className="live-result">
            {result.transaction && (
              <div className="live-txn">
                <div className="live-txn-amount">
                  {result.transaction.currency} {result.transaction.amount?.toLocaleString()}
                </div>
                <div className="live-txn-desc">{result.transaction.description}</div>
                <div className="mono-muted">
                  {result.transaction.counterparty} · {result.transaction.type} ·{' '}
                  {result.transaction.bank_id} · {result.context_note}
                </div>
              </div>
            )}
            <div className={`live-verdict ${result.case_created ? 'raised' : 'quiet'}`}>
              <div className="live-verdict-label">
                {result.case_created ? 'Case opened' : 'No case opened'}
              </div>
              <div className="live-verdict-detail">
                {gate?.detail?.decision === 'investigate'
                  ? `Gate opened at ${Math.round((gate.detail.score || 0) * 100)}% — routing to ${String(
                      result.route
                    ).replace(/_/g, ' ')}`
                  : `Gate closed at ${Math.round((gate?.detail?.score || 0) * 100)}% — activity matches the account baseline`}
              </div>
              {result.case_created && (
                <button
                  className="btn btn-ghost"
                  type="button"
                  onClick={() => onOpenCase?.(result.case.id)}
                >
                  Open {result.case.title} →
                </button>
              )}
            </div>
          </div>

          <div className="stage-list compact">
            {result.trace.map((stage, index) => (
              <StageRow
                key={stage.key}
                stage={stage}
                revealed={index < revealed}
                expanded={expanded.has(stage.key)}
                onToggle={() => toggle(stage.key)}
              />
            ))}
          </div>
        </>
      )}
    </div>
  )
}
