import { useState, useMemo, useEffect } from 'react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import PipelinePanel from './PipelinePanel.jsx'
import TransactionTable from './TransactionTable.jsx'
import NetworkGraph from './NetworkGraph.jsx'
import AnalystReportPanel from './AnalystReportPanel.jsx'
import EvidenceVault from './EvidenceVault.jsx'
import InvestigationUpdates from './InvestigationUpdates.jsx'
import LockedAccess from './LockedAccess.jsx'
import RestrictedInformation from './RestrictedInformation.jsx'
import CaseTimeline from './CaseTimeline.jsx'
import { MaskedField } from './MaskedField.jsx'
import ConsentBadge from './ConsentBadge.jsx'
import { fetchGraph, runPipeline } from '../api.js'
import { useRole } from '../context/RoleContext.jsx'

function riskLevel(score) {
  if (score < 0.15) return 'low'
  if (score < 0.35) return 'low'
  if (score < 0.6) return 'medium'
  if (score < 0.8) return 'high'
  return 'critical'
}

function riskLabel(score) {
  if (score < 0.15) return 'LOW RISK'
  if (score < 0.35) return 'LOW RISK'
  if (score < 0.6) return 'ELEVATED'
  if (score < 0.8) return 'HIGH RISK'
  return 'CRITICAL'
}

function statusLabel(status) {
  const labels = {
    normal: 'Normal', context_verification: 'Context Verification',
    investigation: 'Investigation', closed: 'Closed', escalated: 'Escalated',
  }
  return labels[status] || status
}

const BANK_COLORS = ['#5b93f8', '#a78bfa', '#d4a843', '#22c58a', '#e8a33d']

export default function CaseDetail({ caseData, onBack, onRunPipeline }) {
  const { can, roleConfig } = useRole()
  const [activeTab, setActiveTab] = useState('pipeline')
  const [data, setData] = useState(caseData)
  const [runningPipeline, setRunningPipeline] = useState(false)
  const [pipelineError, setPipelineError] = useState(null)
  const [network, setNetwork] = useState(null)
  const [networkError, setNetworkError] = useState(null)

  // Follow the parent's selection (re-loading a case after a decision, for instance).
  useEffect(() => { setData(caseData) }, [caseData])

  // The case's network comes from the graph engine, scoped to this case's entities, so
  // restricted subjects are marked by the backend rather than redrawn in the browser.
  useEffect(() => {
    const entityIds = caseData?.entity_ids || []
    if (!entityIds.length) {
      setNetwork(null)
      return
    }
    let cancelled = false
    setNetwork(null)
    setNetworkError(null)
    fetchGraph(entityIds).then((payload) => {
      if (cancelled) return
      if (!payload || payload.error) {
        setNetworkError(payload?.error || 'The graph could not be loaded for this case.')
        return
      }
      setNetwork(payload)
    })
    return () => { cancelled = true }
  }, [caseData?.id, caseData?.entity_ids])

  const { id, title, description, status, score, transactions, reports, decision,
          pipeline_trace, pipeline_report, pipeline_findings, bank_names, entity_ids, bank_ids,
          privacy, assigned_to_name } = data

  const handleRunPipeline = async () => {
    setRunningPipeline(true)
    setPipelineError(null)
    const result = await runPipeline(id)
    if (!result.ok) {
      setPipelineError(result.body?.error || 'The pipeline could not be run on this case.')
      setRunningPipeline(false)
      return
    }
    setData((prev) => ({
      ...prev,
      pipeline_trace: result.body.trace,
      pipeline_report: result.body.report,
      pipeline_findings: result.body.findings,
    }))
    setRunningPipeline(false)
    onRunPipeline?.(id)
  }

  const level = riskLevel(score || 0)

  // Transaction timeline chart data
  const timelineData = useMemo(() => {
    if (!transactions?.length) return []
    return transactions.map((t) => ({
      name: (t.description || '').substring(0, 15) + ((t.description || '').length > 15 ? '…' : ''),
      amount: t.amount || 0,
      bank: t.bank_name || t.bank_id,
    }))
  }, [transactions])

  // Bank names with colors
  const bankColorMap = useMemo(() => {
    const map = {}
    ;(bank_names || []).forEach((bn, i) => { map[bn] = BANK_COLORS[i % BANK_COLORS.length] })
    return map
  }, [bank_names])

  return (
    <div>
      {/* Breadcrumb */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16, fontSize: 12, color: 'var(--gray-500)' }}>
        <button className="btn btn-ghost btn-sm" onClick={onBack}>Dashboard</button>
        <span>/</span>
        <span style={{ color: 'var(--ink)', fontWeight: 600 }}>{id.toUpperCase()}</span>
      </div>

      {/* Case Header */}
      <div className="card" style={{ marginBottom: 20 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <div className="case-id" style={{ marginBottom: 4 }}>
              {id.toUpperCase()}
              {assigned_to_name && <span className="case-owner">Owner: {assigned_to_name}</span>}
            </div>
            <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--gray-700)' }}>{title}</div>
            <p style={{ color: 'var(--gray-500)', marginTop: 6, fontSize: 13 }}>{description}</p>
            <div style={{ display: 'flex', gap: 10, marginTop: 10, alignItems: 'center', flexWrap: 'wrap' }}>
              <span className={`risk-badge risk-${level}`}>
                {riskLabel(score || 0)} — {((score || 0) * 100).toFixed(0)}%
              </span>
              <span className={`status-badge status-${status}`}>{statusLabel(status)}</span>
              <span style={{ fontSize: 12, color: 'var(--gray-400)' }}>
                Banks: {(bank_names || []).join(', ')}
              </span>
            </div>
          </div>
        </div>
      </div>

      {privacy && (
        <div className={`privacy-banner ${privacy.level}`}>
          <span className="privacy-icon">{privacy.level === 'masked' ? '🔒' : '🔓'}</span>
          <div>
            <div className="privacy-title">
              {privacy.level === 'masked'
                ? `Identifiers masked for ${roleConfig?.label || 'your role'}`
                : `Full identifiers visible to ${roleConfig?.label || 'your role'}`}
            </div>
            <div className="privacy-note">
              {privacy.note}
              {privacy.redacted_fields?.length > 0 &&
                ` Redacted: ${privacy.redacted_fields.join(', ')}.`}
              {' '}Enforced by the backend before the response leaves the server.
            </div>
          </div>
        </div>
      )}

      {pipelineError && <div className="flash flash-error">{pipelineError}</div>}

      {/* Tabs */}
      <div className="tabs">
        <button className={`tab ${activeTab === 'pipeline' ? 'active' : ''}`}
          onClick={() => setActiveTab('pipeline')}>
          Pipeline {pipeline_trace ? '✓' : ''}
        </button>
        <button className={`tab ${activeTab === 'transactions' ? 'active' : ''}`}
          onClick={() => setActiveTab('transactions')}>
          Transactions ({(transactions || []).length})
        </button>
        <button className={`tab ${activeTab === 'reports' ? 'active' : ''}`}
          onClick={() => setActiveTab('reports')}>
          Bank Reports ({(reports || []).length})
        </button>
        <button className={`tab ${activeTab === 'network' ? 'active' : ''}`}
          onClick={() => setActiveTab('network')}>
          Network Graph
        </button>
        <button className={`tab ${activeTab === 'report' ? 'active' : ''}`}
          onClick={() => setActiveTab('report')}>
          Analyst Report
        </button>
        <button className={`tab ${activeTab === 'evidence' ? 'active' : ''}`}
          onClick={() => setActiveTab('evidence')}>
          Evidence Vault
          {(data.evidence?.count || 0) > 0 ? ` (${data.evidence.count})` : ''}
        </button>
        <button className={`tab ${activeTab === 'updates' ? 'active' : ''}`}
          onClick={() => setActiveTab('updates')}>
          Updates
          {(data.updates?.unacknowledged || 0) > 0 ? ` (${data.updates.unacknowledged})` : ''}
        </button>
        <button className={`tab ${activeTab === 'timeline' ? 'active' : ''}`}
          onClick={() => setActiveTab('timeline')}>
          Timeline
        </button>
        <button className={`tab ${activeTab === 'restricted' ? 'active' : ''}`}
          onClick={() => setActiveTab('restricted')}>
          {data.evidence?.authorization_state === 'authorized' ? '🔓 Restricted Info' : '🔒 Restricted Info'}
        </button>
      </div>

      {/* Tab Content */}
      {activeTab === 'pipeline' && (
        <PipelinePanel
          caseData={data}
          onRunPipeline={handleRunPipeline}
          running={runningPipeline}
        />
      )}

      {activeTab === 'transactions' && (
        <div>
          {/* Transaction Timeline Chart */}
          {timelineData.length > 0 && (
            <div className="chart-card" style={{ marginBottom: 16 }}>
              <div className="chart-title">Transaction Amounts</div>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={timelineData} margin={{ left: 10, right: 10 }}>
                  <XAxis dataKey="name" tick={{ fontSize: 10 }} angle={-30} textAnchor="end" height={50} />
                  <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `₹${(v / 1000).toFixed(0)}K`} />
                  <Tooltip formatter={(v) => `₹${v.toLocaleString()}`} />
                  <Bar dataKey="amount" radius={[4, 4, 0, 0]}>
                    {timelineData.map((entry, i) => (
                      <Cell key={i} fill={bankColorMap[entry.bank] || '#5b93f8'} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
          <TransactionTable transactions={transactions || []} />
        </div>
      )}

      {activeTab === 'reports' && (
        <div className="card">
          <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 12 }}>Bank Reports</div>
          {(reports || []).length === 0 ? (
            <div className="pipeline-empty">
              No bank reports yet. Run the pipeline to generate requests and collect reports.
            </div>
          ) : (
            reports.map((report, i) => (
              <div key={report._id || i} className="bank-report" style={{ marginBottom: 10 }}>
                <div className="bank-report-head">
                  <strong>{report.responding_bank_name || report.responding_bank}</strong>
                  <span className={`status-chip ${report.status === 'completed' ? 'ok' : 'warn'}`}>
                    {report.status}
                  </span>
                  <span className="mono-muted">{report.request_id}</span>
                </div>
                {report.data && (
                  <div style={{ fontSize: 12, color: 'var(--gray-500)', marginTop: 6 }}>
                    {Object.entries(report.data).filter(([, v]) => typeof v === 'string').map(([k, v]) => (
                      <div key={k} style={{ marginBottom: 3 }}>
                        <span style={{ color: 'var(--gray-400)', textTransform: 'capitalize' }}>{k.replace(/_/g, ' ')}: </span>
                        {v}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      )}

      {activeTab === 'network' && (
        <div>
          {networkError && <div className="flash flash-error">{networkError}</div>}
          {network ? (
            <>
              {network.restricted?.masked > 0 && network.restricted?.authorized === 0 && (
                <div className="flash flash-warn">
                  {network.restricted.masked} node(s) are restricted subject information and
                  are shown as locked placeholders. An approved authorisation is required to
                  open them.
                </div>
              )}
              <NetworkGraph network={network} />
            </>
          ) : (
            !networkError && <div className="loading"><div className="spinner" /> Loading the graph…</div>
          )}
        </div>
      )}

      {activeTab === 'report' && (
        <AnalystReportPanel caseId={id} onChanged={() => onRunPipeline?.(id)} />
      )}

      {activeTab === 'evidence' && (
        <EvidenceVault caseId={id} onChanged={() => onRunPipeline?.(id)} />
      )}

      {activeTab === 'updates' && (
        <InvestigationUpdates caseId={id} onChanged={() => onRunPipeline?.(id)} />
      )}

      {activeTab === 'timeline' && <CaseTimeline caseId={id} />}

      {activeTab === 'restricted' && (
        <LockedAccess caseId={id} onChanged={() => onRunPipeline?.(id)} />
      )}

      {activeTab === 'restricted' && (
        <RestrictedInformation
          caseId={id}
          onRequested={() => onRunPipeline?.(id)}
          onOpenAccessRequests={() => onRunPipeline?.(id)}
        />
      )}
    </div>
  )
}
