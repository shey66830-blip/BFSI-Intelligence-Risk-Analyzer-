import { useCallback, useEffect, useState } from 'react'
import { fetchCaseTimeline } from '../api.js'

const KIND_LABEL = {
  case: 'Case',
  transaction: 'Transaction',
  bank_report: 'Bank response',
  pipeline: 'Pipeline stage',
  analyst_report: 'Analyst report',
  evidence: 'Evidence',
  update: 'Update',
  access_request: 'Access request',
  access_decision: 'Authorisation decision',
  audit: 'Audit event',
}

function when(iso) {
  return iso ? String(iso).slice(0, 16).replace('T', ' ') : '—'
}

/**
 * The case in sequence, newest first, rebuilt from the records that exist: transactions,
 * bank responses, pipeline stages, reports, evidence, updates, authorisations and the
 * audit trail itself.
 */
export default function CaseTimeline({ caseId }) {
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    const payload = await fetchCaseTimeline(caseId)
    setEvents(payload?.events || [])
    setLoading(false)
  }, [caseId])

  useEffect(() => { load() }, [load])

  if (loading) return <div className="loading"><div className="spinner" /> Rebuilding the timeline…</div>

  return (
    <div className="timeline">
      <div className="view-head">
        <div>
          <div className="view-title">Case timeline</div>
          <div className="view-sub">
            {events.length} reconstructed event(s). Each entry names the record it came from.
          </div>
        </div>
      </div>

      <div className="timeline-list">
        {events.map((event, index) => (
          <div key={`${event.at}-${index}`} className={`timeline-row kind-${event.kind}`}>
            <div className="timeline-time">{when(event.at)}</div>
            <div className="timeline-marker" />
            <div className="timeline-body">
              <div className="timeline-head">
                <span className="timeline-kind">{KIND_LABEL[event.kind] || event.kind}</span>
                <span className="timeline-title">{event.title}</span>
              </div>
              {event.detail && <div className="timeline-detail">{event.detail}</div>}
              <div className="timeline-meta">
                {event.actor ? `${event.actor}` : 'Context Guard'}
                {event.ref ? ` · ${event.ref}` : ''}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
