import { useEffect, useMemo, useState } from 'react'
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Pie, PieChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { useRole } from '../context/RoleContext.jsx'
import { assignCase, fetchAnalysts, fetchNotifications } from '../api.js'
import LiveFeedPanel from './LiveFeedPanel.jsx'

function riskLevel(score) {
  if (score < 0.35) return 'low'
  if (score < 0.6) return 'medium'
  if (score < 0.8) return 'high'
  return 'critical'
}

function riskLabel(score) {
  if (score < 0.35) return 'LOW'
  if (score < 0.6) return 'MEDIUM'
  if (score < 0.8) return 'HIGH'
  return 'CRITICAL'
}

const RISK_COLORS = { low: '#22c58a', medium: '#e8a33d', high: '#f0665a', critical: '#ff8577' }
const BANK_COLORS = ['#5b93f8', '#d4a843', '#22c58a', '#a78bfa', '#e8a33d']

const STATUS_LABELS = {
  normal: 'Normal', context_verification: 'Context Verification', investigation: 'Investigation',
  closed: 'Closed', escalated: 'Escalated',
}

function statusLabel(status) {
  return STATUS_LABELS[status] || status
}

const AWAITING_DECISION = new Set(['investigation', 'context_verification', 'escalated'])

/** Compact Indian-notation money, so a big number still fits a KPI card. */
function compactValue(value) {
  const n = Number(value) || 0
  if (n >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`
  if (n >= 1e5) return `₹${(n / 1e5).toFixed(1)} L`
  return `₹${n.toLocaleString('en-IN')}`
}

function relative(iso) {
  if (!iso) return ''
  const then = new Date(`${iso}${iso.endsWith('Z') ? '' : 'Z'}`).getTime()
  const seconds = Math.max(0, Math.floor((Date.now() - then) / 1000))
  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

const ICON_PATHS = {
  cases: <><path d="M3 7l9-4 9 4v10l-9 4-9-4z" /><path d="M3 7l9 4 9-4" /><path d="M12 11v10" /></>,
  txns: <path d="M3 12h4l2.5-6 4 12 2.5-6h5" />,
  value: <><rect x="3" y="7" width="18" height="10" rx="2" /><circle cx="12" cy="12" r="2.4" /></>,
  banks: <><path d="M4 10v8M9 10v8M15 10v8M20 10v8" /><path d="M3 19h18" /><path d="M12 4l9 5H3z" /></>,
  entities: <><circle cx="12" cy="6" r="2.6" /><circle cx="6" cy="18" r="2.6" /><circle cx="18" cy="18" r="2.6" /><path d="M12 8.6v3.6M10.8 14.6l-3 1.9M13.2 14.6l3 1.9" /></>,
}

function StatIcon({ name }) {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {ICON_PATHS[name]}
    </svg>
  )
}

/** The movement chip the reference puts in the bottom-right of each KPI card. */
function DeltaChip({ delta }) {
  if (!delta) return null
  const { current, previous, pct } = delta
  if (pct === null || pct === undefined) {
    if (!current && !previous) return null
    return (
      <span className="stat-delta" title="First movement in this period">
        <span className="stat-delta-arrow">↗</span>new
      </span>
    )
  }
  const dir = pct > 0 ? 'up' : pct < 0 ? 'down' : ''
  const arrow = pct > 0 ? '↗' : pct < 0 ? '↘' : '→'
  return (
    <span className={`stat-delta ${dir}`} title="Last 7 days vs the previous 7 days">
      <span className="stat-delta-arrow">{arrow}</span>
      {Math.abs(pct).toFixed(1)}%
    </span>
  )
}

/** Where a role lands, and what its scope actually is. */
function RoleHeader({ roleConfig, stats, caseCount }) {
  // Keyed by dashboard name, which is what the backend returns on the user.
  const copy = {
    my_cases: {
      title: 'My caseload',
      sub: 'Cases assigned to you. Customer identifiers are masked and unassigned cases stay out of view.',
    },
    review_queue: {
      title: 'Review queue',
      sub: 'Every case across all banks, with unmasked identifiers. You can escalate to the FIU.',
    },
    system_overview: {
      title: 'System overview',
      sub: 'Organisation-wide view: caseload, users, risk thresholds and the full audit trail.',
    },
  }[roleConfig?.dashboard] || { title: 'Dashboard', sub: '' }

  return (
    <div className="role-header">
      <div>
        <div className="role-header-title">{copy.title}</div>
        <div className="role-header-sub">{copy.sub}</div>
      </div>
      <div className="role-header-meta">
        <span className="role-chip">{roleConfig?.label}</span>
        <span className="role-chip muted">
          {stats?.scope === 'assigned' ? `${caseCount} assigned case(s)` : `${caseCount} case(s) visible`}
        </span>
      </div>
    </div>
  )
}

/** Compliance: cases that still need a human decision. */
function ReviewQueue({ cases, onSelectCase }) {
  const { can } = useRole()
  const [analysts, setAnalysts] = useState([])
  const [busyCase, setBusyCase] = useState(null)

  useEffect(() => {
    if (can('cases:assign')) fetchAnalysts().then((d) => setAnalysts(d?.analysts || []))
  }, [can])

  const queue = cases
    .filter((c) => AWAITING_DECISION.has(c.status))
    .sort((a, b) => (b.score || 0) - (a.score || 0))

  const assign = async (caseId, userId) => {
    setBusyCase(caseId)
    await assignCase(caseId, userId || null)
    setBusyCase(null)
    window.location.reload()
  }

  return (
    <div className="card role-panel">
      <div className="role-panel-head">
        <div>
          <div className="role-panel-title">Awaiting a human decision</div>
          <div className="role-panel-sub">
            {queue.length === 0
              ? 'Nothing is waiting on a decision right now.'
              : `${queue.length} case(s) open, ranked by risk score.`}
          </div>
        </div>
        <div className="role-panel-note">
          {can('cases:decide')
            ? 'You hold escalation rights (cases:decide).'
            : 'Escalation is restricted to compliance officers.'}
        </div>
      </div>

      {queue.length > 0 && (
        <div className="queue-list">
          {queue.map((c) => (
            <div key={c.id} className="queue-row">
              <div className="queue-main">
                <div className="queue-title">{c.title}</div>
                <div className="queue-meta">
                  <span className={`risk-badge risk-${riskLevel(c.score || 0)}`}>
                    {riskLabel(c.score || 0)} — {((c.score || 0) * 100).toFixed(0)}%
                  </span>
                  <span className={`status-badge status-${c.status}`}>{statusLabel(c.status)}</span>
                  <span className="queue-assignee">
                    {c.assigned_to_name ? `Owner: ${c.assigned_to_name}` : 'Unassigned'}
                  </span>
                </div>
              </div>
              <div className="queue-actions">
                {can('cases:assign') && analysts.length > 0 && (
                  <select
                    className="field-input queue-select"
                    value={c.assigned_to || ''}
                    disabled={busyCase === c.id}
                    onChange={(e) => assign(c.id, e.target.value)}
                  >
                    <option value="">Unassigned</option>
                    {analysts.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name} ({a.active_case_count})
                      </option>
                    ))}
                  </select>
                )}
                <button className="btn btn-ghost btn-sm" onClick={() => onSelectCase(c.id)}>
                  Review →
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/** Analyst: what is on their desk. */
function AnalystCaseload({ cases, onSelectCase, viewer }) {
  const mine = cases.filter((c) => c.assigned_to === viewer?.id)
  const waiting = mine.filter((c) => !c.pipeline_trace && AWAITING_DECISION.has(c.status))

  return (
    <div className="card role-panel">
      <div className="role-panel-head">
        <div>
          <div className="role-panel-title">Your assignments</div>
          <div className="role-panel-sub">
            {mine.length === 0
              ? 'No cases are assigned to you yet — an administrator assigns new cases.'
              : `${mine.length} case(s) assigned to you.`}
          </div>
        </div>
        <div className="role-panel-note">
          {waiting.length > 0
            ? `${waiting.length} awaiting a pipeline run`
            : 'All assigned cases have been processed'}
        </div>
      </div>
      <div className="queue-list">
        {mine.map((c) => (
          <div key={c.id} className="queue-row">
            <div className="queue-main">
              <div className="queue-title">{c.title}</div>
              <div className="queue-meta">
                <span className={`risk-badge risk-${riskLevel(c.score || 0)}`}>
                  {riskLabel(c.score || 0)} — {((c.score || 0) * 100).toFixed(0)}%
                </span>
                <span className={`status-badge status-${c.status}`}>{statusLabel(c.status)}</span>
                <span className="queue-assignee">{c.transaction_count || 0} transactions</span>
              </div>
            </div>
            <div className="queue-actions">
              <button className="btn btn-ghost btn-sm" onClick={() => onSelectCase(c.id)}>
                {c.pipeline_trace ? 'Open report →' : 'Investigate →'}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

/** Admin: governance shortcuts. */
function SystemOverview({ stats, cases, userCount, onNavigate }) {
  return (
    <div className="role-panel-grid">
      <div className="card role-panel">
        <div className="role-panel-title">Governance</div>
        <div className="queue-list">
          <div className="queue-row">
            <div className="queue-main">
              <div className="queue-title">Users &amp; roles</div>
              <div className="queue-sub">
                {userCount == null ? 'Loading accounts…' : `${userCount} accounts`} · create, promote,
                suspend and assign cases
              </div>
            </div>
            <button className="btn btn-ghost btn-sm" onClick={() => onNavigate('users')}>Manage →</button>
          </div>
          <div className="queue-row">
            <div className="queue-main">
              <div className="queue-title">Risk &amp; privacy settings</div>
              <div className="queue-sub">Anomaly gate, investigation threshold, analyst masking policy</div>
            </div>
            <button className="btn btn-ghost btn-sm" onClick={() => onNavigate('settings')}>Configure →</button>
          </div>
          <div className="queue-row">
            <div className="queue-main">
              <div className="queue-title">Audit trail</div>
              <div className="queue-sub">Every sign-in, view, pipeline run and decision, attributed</div>
            </div>
            <button className="btn btn-ghost btn-sm" onClick={() => onNavigate('audit')}>Inspect →</button>
          </div>
        </div>
      </div>

      <div className="card role-panel">
        <div className="role-panel-title">Scope</div>
        <div className="mini-facts">
          <div className="mini-fact"><span>Cases visible</span><strong>{stats?.total_cases ?? cases.length}</strong></div>
          <div className="mini-fact"><span>Transactions</span><strong>{stats?.total_transactions ?? 0}</strong></div>
          <div className="mini-fact"><span>Banks connected</span><strong>{stats?.banks_connected ?? 0}</strong></div>
          <div className="mini-fact"><span>Entities monitored</span><strong>{stats?.entities_monitored ?? 0}</strong></div>
          <div className="mini-fact"><span>Identifiers</span><strong>Unmasked</strong></div>
          <div className="mini-fact"><span>Audit visibility</span><strong>Organisation-wide</strong></div>
        </div>
      </div>
    </div>
  )
}

/** Transactions ingested and value monitored, day by day. */
function ActivityChart({ activity }) {
  const [range, setRange] = useState(14)

  const data = useMemo(
    () => (activity || []).slice(-range).map((day) => ({
      ...day,
      volumeK: Math.round((day.volume || 0) / 1000),
      label: new Date(`${day.date}T00:00:00`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }),
    })),
    [activity, range],
  )

  const hasMovement = data.some((day) => day.transactions > 0)
  const start = data[0]?.label
  const end = data[data.length - 1]?.label

  return (
    <div className="card chart-card activity-card">
      <div className="card-head">
        <div>
          <div className="card-head-title">Transaction activity</div>
          <div className="card-head-sub">
            Ingested volume vs value monitored{start && end ? ` · ${start} – ${end}` : ''}
          </div>
        </div>
        <div className="segmented">
          {[7, 14, 30].map((days) => (
            <button
              key={days}
              className={range === days ? 'active' : ''}
              onClick={() => setRange(days)}
              type="button"
            >
              {days}d
            </button>
          ))}
        </div>
      </div>

      <div className="chart-legend">
        <span className="legend-item"><i className="legend-dot" /> Transactions</span>
        <span className="legend-item"><i className="legend-dash" /> Value (₹K)</span>
      </div>

      {hasMovement ? (
        <div className="chart-frame">
          <ResponsiveContainer width="100%" height={228}>
            <AreaChart data={data} margin={{ top: 6, right: 6, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id="cgActivity" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#e9edf5" stopOpacity={0.20} />
                  <stop offset="100%" stopColor="#e9edf5" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid vertical={false} strokeDasharray="0" />
              <XAxis dataKey="label" tickLine={false} axisLine={false} minTickGap={26} tick={{ fontSize: 11 }} />
              <YAxis yAxisId="tx" width={26} allowDecimals={false} tickLine={false} axisLine={false} tick={{ fontSize: 11 }} />
              <YAxis yAxisId="vol" orientation="right" width={38} tickLine={false} axisLine={false} tick={{ fontSize: 11 }} />
              <Tooltip
                cursor={{ stroke: '#333a49', strokeWidth: 1 }}
                formatter={(value, name) => (
                  name === 'Value (₹K)' ? `₹${Number(value).toLocaleString('en-IN')}K` : value
                )}
              />
              <Area
                yAxisId="tx"
                type="monotone"
                dataKey="transactions"
                name="Transactions"
                stroke="#e9edf5"
                strokeWidth={2}
                fill="url(#cgActivity)"
              />
              <Area
                yAxisId="vol"
                type="monotone"
                dataKey="volumeK"
                name="Value (₹K)"
                stroke="#6d7688"
                strokeWidth={1.6}
                strokeDasharray="5 4"
                fill="transparent"
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div className="pipeline-empty">No transactions in this window</div>
      )}
    </div>
  )
}

/** Recent alerts: what arrived for this identity, ranked newest first. */
function AlertsRail({ onOpenCase, onNavigate }) {
  const [notes, setNotes] = useState([])

  useEffect(() => {
    let live = true
    fetchNotifications().then((payload) => {
      if (live) setNotes((payload?.notifications || []).slice(0, 6))
    })
    return () => { live = false }
  }, [])

  return (
    <div className="card alerts-rail">
      <div className="alerts-head">
        <div className="alerts-title">Recent alerts</div>
        <button className="rail-link" onClick={() => onNavigate('updates')} type="button">
          View all ↗
        </button>
      </div>

      {notes.length === 0 && (
        <div className="rail-empty">Nothing has been raised for you yet.</div>
      )}

      {notes.map((note) => {
        const high = note.severity === 'high'
        return (
          <button
            key={note.id}
            className={`alert-row ${note.read_at ? '' : 'unread'} ${high ? 'sev-high' : ''}`}
            onClick={() => (note.case_id ? onOpenCase?.(note.case_id) : onNavigate('updates'))}
            type="button"
          >
            <span className="alert-dot" />
            <span className="alert-main">
              <span className="alert-title">{note.title}</span>
              <span className="alert-meta">
                {high ? 'High severity' : 'Routine'} · {note.case_id ? `${note.case_id.toUpperCase()} · ` : ''}
                {relative(note.created_at)}
              </span>
            </span>
            <span className={`alert-chip ${high ? 'sev-high' : ''}`}>{high ? 'Action' : 'Info'}</span>
          </button>
        )
      })}
    </div>
  )
}

export default function Dashboard({ stats, cases, onSelectCase, onNavigate, onOpenCase, userCount }) {
  const { user, roleConfig, can } = useRole()

  const riskBreakdown = useMemo(() => {
    const counts = { Low: 0, Medium: 0, High: 0, Critical: 0 }
    cases.forEach((c) => {
      const s = c.score || 0
      if (s < 0.35) counts.Low++
      else if (s < 0.6) counts.Medium++
      else if (s < 0.8) counts.High++
      else counts.Critical++
    })
    return Object.entries(counts).filter(([, v]) => v > 0).map(([name, value]) => ({ name, value }))
  }, [cases])

  const bankVolume = useMemo(() => {
    const vol = {}
    cases.forEach((c) => {
      const names = c.bank_names || []
      names.forEach((bn) => { vol[bn] = (vol[bn] || 0) + (c.total_volume || 0) })
    })
    return Object.entries(vol).map(([name, volume]) => ({
      name: name.replace(' Bank', ''),
      volume: Math.round(volume / 1000),
    }))
  }, [cases])

  const kpis = [
    {
      key: 'cases',
      label: stats?.scope === 'assigned' ? 'My cases' : 'Active cases',
      value: stats?.total_cases ?? 0,
      delta: stats?.deltas?.cases,
      icon: 'cases',
    },
    {
      key: 'transactions',
      label: 'Transactions analysed',
      value: stats?.total_transactions ?? 0,
      delta: stats?.deltas?.transactions,
      icon: 'txns',
    },
    {
      key: 'volume',
      label: 'Value analysed',
      value: compactValue(stats?.total_volume || 0),
      delta: stats?.deltas?.volume,
      icon: 'value',
    },
    {
      key: 'banks',
      label: 'Banks connected',
      value: stats?.banks_connected ?? 0,
      note: 'all reporting',
      icon: 'banks',
    },
    {
      key: 'entities',
      label: 'Entities monitored',
      value: stats?.entities_monitored ?? 0,
      note: 'in your scope',
      icon: 'entities',
    },
  ]

  const dashboard = roleConfig?.dashboard

  return (
    <div>
      <RoleHeader roleConfig={roleConfig} stats={stats} caseCount={cases.length} />

      <div className="stats-grid">
        {kpis.map((kpi) => (
          <div className="stat-card" key={kpi.key}>
            <div className="stat-top">
              <span className="stat-label">{kpi.label}</span>
              <span className="stat-icon"><StatIcon name={kpi.icon} /></span>
            </div>
            <div className="stat-bottom">
              <span className="stat-value">{kpi.value}</span>
              {kpi.delta ? <DeltaChip delta={kpi.delta} /> : <span className="stat-note">{kpi.note}</span>}
            </div>
          </div>
        ))}
      </div>

      <div className="dash-split">
        <ActivityChart activity={stats?.activity} />
        <AlertsRail onOpenCase={onOpenCase} onNavigate={onNavigate} />
      </div>

      {dashboard === 'my_cases' && (
        <AnalystCaseload cases={cases} onSelectCase={onSelectCase} viewer={user} />
      )}
      {dashboard === 'review_queue' && <ReviewQueue cases={cases} onSelectCase={onSelectCase} />}
      {dashboard === 'system_overview' && (
        <SystemOverview stats={stats} cases={cases} userCount={userCount} onNavigate={onNavigate} />
      )}

      <div className="charts-grid">
        <div className="chart-card">
          <div className="chart-title">Case Risk Distribution</div>
          {riskBreakdown.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie data={riskBreakdown} cx="50%" cy="50%" innerRadius={55} outerRadius={85}
                  paddingAngle={3} dataKey="value"
                  label={({ name, value }) => `${name}: ${value}`}>
                  {riskBreakdown.map((entry) => (
                    <Cell key={entry.name} fill={RISK_COLORS[entry.name.toLowerCase()]} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <div className="pipeline-empty">No cases in your scope</div>
          )}
        </div>

        <div className="chart-card">
          <div className="chart-title">Volume by Bank (₹ thousands)</div>
          {bankVolume.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={bankVolume} layout="vertical" margin={{ left: 20, right: 14 }}>
                <XAxis type="number" tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
                <YAxis type="category" dataKey="name" tick={{ fontSize: 11 }} width={92} tickLine={false}
                  axisLine={false} tickMargin={10} />
                <Tooltip formatter={(v) => `₹${v}K`} />
                <Bar dataKey="volume" radius={[0, 4, 4, 0]} maxBarSize={30}>
                  {bankVolume.map((_, i) => (
                    <Cell key={i} fill={BANK_COLORS[i % BANK_COLORS.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="pipeline-empty">No data</div>
          )}
        </div>
      </div>

      {can('cases:investigate') && <LiveFeedPanel onOpenCase={onOpenCase} />}

      <div style={{ marginBottom: 12, marginTop: 24 }}>
        <h2 style={{ fontSize: 18, fontWeight: 700, color: 'var(--ink)' }}>
          {stats?.scope === 'assigned' ? 'Cases assigned to you' : 'All cases'}
        </h2>
        <p style={{ fontSize: 12, color: 'var(--gray-500)' }}>Click a case to investigate</p>
      </div>
      <div className="cases-grid">
        {cases.map((c) => {
          const level = riskLevel(c.score || 0)
          return (
            <div key={c.id} className={`case-card risk-${level}`} onClick={() => onSelectCase(c.id)}>
              <div className="case-card-header">
                <span className="case-id">{c.id.toUpperCase()}</span>
                <span className={`risk-badge risk-${level}`}>
                  {riskLabel(c.score || 0)} — {((c.score || 0) * 100).toFixed(0)}%
                </span>
              </div>
              <div className="case-title">{c.title}</div>
              <div className="case-description">{c.description}</div>
              <div className="case-meta">
                <span className="case-meta-item">{c.transaction_count || 0} txns</span>
                <span className="case-meta-item">{(c.bank_names || []).length} bank(s)</span>
                {c.assigned_to_name && (
                  <span className="case-meta-item">Owner: {c.assigned_to_name}</span>
                )}
                <span className={`status-badge status-${c.status}`}>{statusLabel(c.status)}</span>
              </div>
            </div>
          )
        })}
        {cases.length === 0 && (
          <div className="card pipeline-empty">
            No cases are visible to your role yet. An administrator assigns cases to analysts.
          </div>
        )}
      </div>
    </div>
  )
}
