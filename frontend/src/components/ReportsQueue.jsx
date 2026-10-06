import { useCallback, useEffect, useState } from 'react'
import { useRole } from '../context/RoleContext.jsx'
import { fetchComplianceReports, fetchMyReports } from '../api.js'

function shortTime(iso) {
  return iso ? `${String(iso).slice(0, 16).replace('T', ' ')}Z` : '—'
}

/**
 * Reports on one screen: what the analyst has written, and — for compliance — what has
 * been handed over and is waiting for review.
 */
export default function ReportsQueue({ onOpenCase }) {
  const { can, role } = useRole()
  const [reports, setReports] = useState([])
  const [loading, setLoading] = useState(true)
  const isReviewer = can('reports:review')
  const isAuthor = can('reports:create')

  const load = useCallback(async () => {
    setLoading(true)
    if (isReviewer) {
      const payload = await fetchComplianceReports('submitted,clarification_requested,reviewed')
      setReports(payload.reports || [])
    } else {
      const payload = await fetchMyReports()
      setReports(payload.reports || [])
    }
    setLoading(false)
  }, [isReviewer])

  useEffect(() => { load() }, [load])

  if (loading) return <div className="loading"><div className="spinner" /> Loading reports…</div>

  return (
    <div className="reports-view">
      <div className="view-head">
        <div>
          <div className="view-title">
            {isReviewer ? 'Reports awaiting review' : 'My investigation reports'}
          </div>
          <div className="view-sub">
            {isReviewer
              ? 'Submitted versions handed to compliance. A version on review cannot be overwritten — the analyst opens a new one.'
              : 'Drafts and submitted versions you own. Drafts are editable; submitted versions are locked.'}
          </div>
        </div>
      </div>

      <div className="card">
        {reports.length === 0 && (
          <div className="vault-empty">
            {isReviewer
              ? 'Nothing has been submitted for review yet.'
              : 'You have no reports yet. Open an assigned case and create one from the case records.'}
          </div>
        )}

        {reports.length > 0 && (
          <table className="admin-table">
            <thead>
              <tr>
                <th>Report</th>
                <th>Case</th>
                <th>Version</th>
                <th>Status</th>
                <th>Analyst</th>
                <th>Submitted</th>
                <th>Updated</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {reports.map((report) => (
                <tr key={report.id}>
                  <td className="mono-muted">{report.id}</td>
                  <td>
                    <button className="link-button" onClick={() => onOpenCase?.(report.case_id)}
                            type="button">
                      {report.case_id?.toUpperCase()}
                    </button>
                    <div className="admin-meta">{report.case_title}</div>
                  </td>
                  <td>v{report.version}</td>
                  <td>
                    <span className={`status-chip ${report.status === 'draft' ? 'warn' : 'ok'}`}>
                      {report.status.replace(/_/g, ' ')}
                    </span>
                  </td>
                  <td>{report.analyst_name}</td>
                  <td>{shortTime(report.submitted_at)}</td>
                  <td>{shortTime(report.updated_at)}</td>
                  <td>
                    <button className="btn btn-ghost btn-sm"
                            onClick={() => onOpenCase?.(report.case_id)} type="button">
                      Open case
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {isAuthor && isReviewer && role === 'admin' && (
        <div className="card vault-empty">
          Administrators may read and correct any report, but the review outcome is recorded
          against the reviewer's identity.
        </div>
      )}
    </div>
  )
}
