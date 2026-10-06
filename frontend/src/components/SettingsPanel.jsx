import { useEffect, useState } from 'react'
import { applyThresholds, fetchSettings, fetchThresholdBacktest, updateSettings } from '../api.js'

const FIELDS = [
  {
    key: 'anomaly_threshold',
    label: 'Anomaly gate',
    kind: 'number',
    step: '0.01',
    min: 0,
    max: 0.99,
    help: 'Above this activity score a case is opened for context verification. Below it, activity is left alone.',
  },
  {
    key: 'investigation_threshold',
    label: 'Investigation threshold',
    kind: 'number',
    step: '0.01',
    min: 0.01,
    max: 1,
    help: 'Above this score the case routes to a full cross-bank investigation instead of context verification.',
  },
  {
    key: 'session_timeout_minutes',
    label: 'Session timeout (minutes)',
    kind: 'number',
    step: '5',
    min: 5,
    max: 10080,
    help: 'How long a signed-in session stays valid before it must be renewed.',
  },
  {
    key: 'bank_response_seconds',
    label: 'Bank response latency (seconds)',
    kind: 'number',
    step: '1',
    min: 0,
    max: 86400,
    help: 'How long a bank-held request is held before the bank answers. Zero answers at once; anything higher leaves the request pending while the bank responds.',
  },
  {
    key: 'bank_response_deadline_hours',
    label: 'Bank response deadline (hours)',
    kind: 'number',
    step: '1',
    min: 1,
    max: 336,
    help: 'If the bank has not answered within this window the request lapses and nothing is released.',
  },
  {
    key: 'graph_max_hops',
    label: 'Network walk depth (hops)',
    kind: 'number',
    step: '1',
    min: 1,
    max: 5,
    help: 'How far an investigation reaches from its subject. Wider finds more of the pattern and widens the case, so it is bounded rather than open-ended.',
  },
  {
    key: 'bank_failure_rate',
    label: 'Bank transport failure rate',
    kind: 'number',
    step: '0.05',
    min: 0,
    max: 1,
    help: 'Chance a submission to the bank fails in transit. A failure is retried inside the window; zero keeps the demonstration clean.',
  },
]

const TOGGLES = [
  {
    key: 'mask_analyst_pii',
    label: 'Mask customer identifiers for analysts',
    help: 'When on, analysts receive names, counterparties and device handles already redacted by the backend.',
  },
  {
    key: 'require_decision_rationale',
    label: 'Require a rationale on every decision',
    help: 'A decision cannot be recorded without a documented reason.',
  },
  {
    key: 'hospital_context_mitigation',
    label: 'Allow contextual mitigation',
    help: 'Lets an explained category (for example an insurance-covered hospital payment) lower the effective score.',
  },
]

export default function SettingsPanel() {
  const [settings, setSettings] = useState(null)
  const [draft, setDraft] = useState(null)
  const [feedback, setFeedback] = useState(null)
  const [busy, setBusy] = useState(false)
  const [backtest, setBacktest] = useState(null)
  const [backtestBusy, setBacktestBusy] = useState(false)
  const [backtestMsg, setBacktestMsg] = useState(null)

  useEffect(() => {
    fetchSettings().then((payload) => {
      setSettings(payload)
      setDraft(payload)
    })
  }, [])

  if (!draft) return <div className="pipeline-empty">Loading settings…</div>

  const apply = async (pair) => {
    setBacktestBusy(true)
    setBacktestMsg(null)
    const res = await applyThresholds(pair)
    setBacktestBusy(false)
    if (!res.ok) {
      setBacktestMsg(res.body?.error || 'Those thresholds could not be applied.')
      return
    }
    const updated = res.body.settings
    setSettings((prev) => ({ ...prev, ...updated }))
    setDraft((prev) => ({ ...prev, ...updated }))
    setBacktestMsg(
      `Applied ${Number(updated.anomaly_threshold).toFixed(2)} / `
      + `${Number(updated.investigation_threshold).toFixed(2)} — ` 
      + `${res.body.backtest.agreed} of ${res.body.backtest.subjects} subjects route as designed.`,
    )
    const payload = await fetchThresholdBacktest()
    if (payload && !payload.error) setBacktest(payload)
  }

  const runBacktest = async () => {
    setBacktestBusy(true)
    setBacktestMsg(null)
    const payload = await fetchThresholdBacktest()
    setBacktestBusy(false)
    if (payload && !payload.error) setBacktest(payload)
  }

  const changed = JSON.stringify(draft) !== JSON.stringify(settings)

  const set = (key, value) => setDraft((prev) => ({ ...prev, [key]: value }))

  const save = async () => {
    setBusy(true)
    const res = await updateSettings({
      anomaly_threshold: Number(draft.anomaly_threshold),
      investigation_threshold: Number(draft.investigation_threshold),
      session_timeout_minutes: Number(draft.session_timeout_minutes),
      bank_response_seconds: Number(draft.bank_response_seconds),
      bank_response_deadline_hours: Number(draft.bank_response_deadline_hours),
      bank_failure_rate: Number(draft.bank_failure_rate),
      graph_max_hops: Number(draft.graph_max_hops),
      mask_analyst_pii: draft.mask_analyst_pii,
      require_decision_rationale: draft.require_decision_rationale,
      hospital_context_mitigation: draft.hospital_context_mitigation,
    })
    setBusy(false)
    if (!res.ok) {
      setFeedback({ type: 'error', message: res.body.error || 'Could not save settings' })
      return
    }
    setSettings(res.body)
    setDraft(res.body)
    setFeedback({ type: 'ok', message: 'Settings saved — they apply to new activity immediately.' })
    setTimeout(() => setFeedback(null), 3500)
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <h2 className="page-title">Risk &amp; Privacy Settings</h2>
          <p className="page-sub">
            These values drive the live gate and the analyst privacy policy — they are not cosmetic.
          </p>
        </div>
        <div className="page-head-actions">
          {settings?.updated_by && (
            <span className="field-hint">Last changed by {settings.updated_by}</span>
          )}
          <button className="btn btn-primary" onClick={save} disabled={!changed || busy}>
            {busy ? 'Saving…' : changed ? 'Save changes' : 'Saved'}
          </button>
        </div>
      </div>

      {feedback && (
        <div className={`flash flash-${feedback.type === 'ok' ? 'ok' : 'error'}`}>{feedback.message}</div>
      )}

      <div className="card settings-card">
        {FIELDS.map((field) => (
          <div key={field.key} className="setting-row">
            <div className="setting-copy">
              <div className="setting-label">{field.label}</div>
              <div className="setting-help">{field.help}</div>
            </div>
            <input
              className="field-input setting-input"
              type="number"
              step={field.step}
              min={field.min}
              max={field.max}
              value={draft[field.key] ?? ''}
              onChange={(e) => set(field.key, e.target.value)}
            />
          </div>
        ))}

        {TOGGLES.map((toggle) => (
          <div key={toggle.key} className="setting-row">
            <div className="setting-copy">
              <div className="setting-label">{toggle.label}</div>
              <div className="setting-help">{toggle.help}</div>
            </div>
            <button
              type="button"
              className={`switch ${draft[toggle.key] ? 'on' : 'off'}`}
              onClick={() => set(toggle.key, !draft[toggle.key])}
              aria-pressed={Boolean(draft[toggle.key])}
            >
              <span className="switch-knob" />
            </button>
          </div>
        ))}
      </div>

      <div className="card">
        <div className="role-panel-title">Threshold backtest</div>
        <p className="setting-help">
          A threshold silently decides which cases a person ever sees. Replay every scenario and
          seeded case through the live gate at candidate thresholds before changing one — the
          scoring here is the same scoring the gate runs.
        </p>

        <div className="setting-row">
          <div className="setting-copy">
            <div className="setting-label">Shipped thresholds</div>
            <div className="setting-help">
              {settings
                ? `Anomaly ${Number(settings.anomaly_threshold).toFixed(2)} · investigation `
                  + `${Number(settings.investigation_threshold).toFixed(2)}`
                : '—'}
            </div>
          </div>
          <button className="btn btn-secondary" onClick={runBacktest}
                  disabled={backtestBusy}>
            {backtestBusy ? 'Replaying…' : backtest ? 'Run again' : 'Run backtest'}
          </button>
        </div>

        {backtestMsg && <div className="flash flash-ok">{backtestMsg}</div>}

        {backtest && (
          <>
            <table className="admin-table">
              <thead>
                <tr>
                  <th>subject</th>
                  <th>score</th>
                  <th>expected</th>
                  <th>at current</th>
                </tr>
              </thead>
              <tbody>
                {backtest.current.result?.predictions?.map((row) => (
                  <tr key={row.subject}>
                    <td>{row.label || row.subject}</td>
                    <td>{(row.score * 100).toFixed(0)}%</td>
                    <td>{String(row.expected_route).replace(/_/g, ' ')}</td>
                    <td>
                      <span className={`status-chip ${row.agrees ? 'ok' : 'warn'}`}>
                        {String(row.route).replace(/_/g, ' ')}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            <p className="setting-help">
              At the current gate, {backtest.current.result?.agreed} of
              {' '}{backtest.current.result?.subjects} subjects route as designed.
              {backtest.results?.length
                ? ` ${backtest.results.length} threshold pairs replayed.`
                : ''}
            </p>

            {backtest.best && (
              <div className="setting-row">
                <div className="setting-copy">
                  <div className="setting-label">Highest agreement on this grid</div>
                  <div className="setting-help">
                    {Number(backtest.best.anomaly_threshold).toFixed(2)} / {' '}
                    {Number(backtest.best.investigation_threshold).toFixed(2)} — {' '}
                    {backtest.best.agreed}/{backtest.best.subjects} subjects
                    {backtest.best.misrouted?.length
                      ? ` (misses ${backtest.best.misrouted.join(', ')})`
                      : ''}
                  </div>
                </div>
                <button
                  className="btn btn-secondary"
                  disabled={backtestBusy}
                  onClick={() => apply({
                    anomaly_threshold: backtest.best.anomaly_threshold,
                    investigation_threshold: backtest.best.investigation_threshold,
                  })}
                >
                  Apply
                </button>
              </div>
            )}

            <p className="field-hint">{backtest.note}</p>
          </>
        )}
      </div>

      <div className="card role-panel">
        <div className="role-panel-title">Why this matters</div>
        <p className="role-panel-body">
          Raising the anomaly gate above a scenario's score is the fastest way to see the routing change:
          a hospital payment that opens a context-verification case at a 35% gate will be left alone at a
          98% gate. Turning off analyst masking shows how the backend redaction is enforced — the browser
          simply never receives the raw values when it is on.
        </p>
      </div>
    </div>
  )
}
