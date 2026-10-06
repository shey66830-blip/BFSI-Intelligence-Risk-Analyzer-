import { useCallback, useEffect, useMemo, useState } from 'react'
import { useRole } from '../context/RoleContext.jsx'
import {
  addEvidence, fetchEvidenceProvenance, fetchEvidenceVault, supersedeEvidence, updateEvidence,
} from '../api.js'
import { shortTime } from '../lib/format.js'

/** Where a record came from, in one line, without having to open anything. */
function originLine(item) {
  const provenance = item.provenance || {}
  if (!provenance.origin) return null
  const who = provenance.filed_by?.name || 'System'
  return `${provenance.origin_label || provenance.origin} · filed by ${who} · ${shortTime(provenance.filed_at)}`
}

const ACCESS_LEVELS = [
  ['case', 'Case — anyone who can see the case'],
  ['compliance_only', 'Compliance only'],
  ['restricted', 'Restricted — authorised reviewers only'],
]

const EVIDENCE_TYPES = [
  'transaction', 'bank_response', 'graph_snapshot', 'analyst_report', 'compliance_note',
  'risk_signal', 'document', 'correspondence', 'subject_information', 'external_reference',
  'timeline_entry',
]

/**
 * The case evidence vault. Nothing here is overwritten: correcting an item files a new
 * version and marks the previous one superseded, and restricted items are listed as
 * locked placeholders until an authorisation covers the reader.
 */
export default function EvidenceVault({ caseId, onChanged }) {
  const { can } = useRole()
  const [vault, setVault] = useState(null)
  const [folder, setFolder] = useState('all')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [flash, setFlash] = useState(null)
  const [form, setForm] = useState({
    folder: 'supporting_documents', type: 'document', title: '', description: '',
    source: '', access_level: 'case',
  })
  const [editing, setEditing] = useState(null)
  const [superseding, setSuperseding] = useState(null)
  const [replacement, setReplacement] = useState({ title: '', description: '', reason: '' })
  const [lineage, setLineage] = useState({})
  const [lineageBusy, setLineageBusy] = useState(null)

  const showLineage = async (item) => {
    if (lineage[item.id]) {
      setLineage((prev) => ({ ...prev, [item.id]: null }))
      return
    }
    setLineageBusy(item.id)
    const payload = await fetchEvidenceProvenance(item.id)
    setLineageBusy(null)
    if (payload && !payload.error) {
      setLineage((prev) => ({ ...prev, [item.id]: payload }))
    }
  }

  const load = useCallback(async () => {
    const payload = await fetchEvidenceVault(caseId)
    setVault(payload)
  }, [caseId])

  useEffect(() => { setFolder('all'); setVault(null); load() }, [caseId, load])

  const items = useMemo(() => {
    const all = vault?.items || []
    return folder === 'all' ? all : all.filter((item) => item.folder === folder)
  }, [vault, folder])

  const run = async (fn, successMessage) => {
    setBusy(true)
    setError(null)
    setFlash(null)
    const result = await fn()
    setBusy(false)
    if (!result.ok) {
      setError(result.body?.error || 'The request was refused.')
      return false
    }
    if (successMessage) setFlash(successMessage)
    await load()
    onChanged?.()
    return true
  }

  const handleAdd = async () => {
    const done = await run(() => addEvidence(caseId, form), 'Evidence filed.')
    if (done) {
      setForm({ ...form, title: '', description: '', source: '' })
      setFolder(form.folder)
    }
  }

  const handleOrganise = (item, patch) => run(
    () => updateEvidence(item.id, patch), `'${item.title}' updated.`)

  const handleSupersede = async () => {
    const done = await run(() => supersedeEvidence(superseding.id, {
      title: replacement.title || superseding.title,
      description: replacement.description || superseding.description,
      note: replacement.reason,
    }), 'New version filed. The previous version is marked superseded.')
    if (done) {
      setSuperseding(null)
      setReplacement({ title: '', description: '', reason: '' })
    }
  }

  if (!vault) return <div className="loading"><div className="spinner" /> Loading the evidence vault…</div>

  const folders = vault.folders || []

  return (
    <div className="vault">
      <div className="vault-head">
        <div>
          <div className="vault-title">Case evidence vault</div>
          <div className="vault-sub">
            {vault.summary?.total || 0} item(s) filed across {folders.length} folder(s). Items are
            append-only: a correction files a new version.
          </div>
        </div>
        <div className="vault-state">
          {vault.authorization_state === 'authorized'
            ? '🔓 Restricted information authorised'
            : vault.authorization_state === 'expired'
              ? '🔒 Authorisation expired'
              : '🔒 Restricted information locked'}
        </div>
      </div>

      {error && <div className="flash flash-error">{error}</div>}
      {flash && <div className="flash flash-ok">{flash}</div>}

      <div className="vault-body">
        <div className="vault-folders">
          <button className={`vault-folder ${folder === 'all' ? 'active' : ''}`}
                  onClick={() => setFolder('all')} type="button">
            <span>All evidence</span>
            <span className="vault-folder-count">{vault.summary?.total || 0}</span>
          </button>
          {folders.map((entry) => (
            <button key={entry.key}
                    className={`vault-folder ${folder === entry.key ? 'active' : ''}`}
                    onClick={() => setFolder(entry.key)}
                    title={entry.description} type="button">
              <span>{entry.label}</span>
              <span className="vault-folder-count">
                {entry.total}
                {entry.restricted > 0 ? ` · ${entry.restricted} 🔒` : ''}
              </span>
            </button>
          ))}
        </div>

        <div className="vault-items">
          {vault.can_add && (
            <div className="card vault-add">
              <div className="report-group-title">File new evidence</div>
              <div className="vault-add-grid">
                <label className="field">
                  <span className="field-label">Folder</span>
                  <select className="field-input" value={form.folder}
                          onChange={(e) => setForm({ ...form, folder: e.target.value })}>
                    {folders.map((entry) => (
                      <option key={entry.key} value={entry.key}>{entry.label}</option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span className="field-label">Type</span>
                  <select className="field-input" value={form.type}
                          onChange={(e) => setForm({ ...form, type: e.target.value })}>
                    {EVIDENCE_TYPES.map((type) => (
                      <option key={type} value={type}>{type.replace(/_/g, ' ')}</option>
                    ))}
                  </select>
                </label>
                <label className="field vault-add-wide">
                  <span className="field-label">Title</span>
                  <input className="field-input" value={form.title}
                         onChange={(e) => setForm({ ...form, title: e.target.value })} />
                </label>
                <label className="field vault-add-wide">
                  <span className="field-label">Description</span>
                  <textarea className="field-input" rows={2} value={form.description}
                            onChange={(e) => setForm({ ...form, description: e.target.value })} />
                </label>
                <label className="field">
                  <span className="field-label">Source</span>
                  <input className="field-input" value={form.source}
                         placeholder="Where did this come from?"
                         onChange={(e) => setForm({ ...form, source: e.target.value })} />
                </label>
                {can('evidence:manage') && (
                  <label className="field">
                    <span className="field-label">Access level</span>
                    <select className="field-input" value={form.access_level}
                            onChange={(e) => setForm({ ...form, access_level: e.target.value })}>
                      {ACCESS_LEVELS.map(([value, label]) => (
                        <option key={value} value={value}>{label}</option>
                      ))}
                    </select>
                  </label>
                )}
              </div>
              <button className="btn btn-primary btn-sm" onClick={handleAdd}
                      disabled={busy || !form.title.trim()} type="button">
                File evidence
              </button>
            </div>
          )}

          {items.length === 0 && (
            <div className="card vault-empty">
              Nothing filed in this folder yet.
            </div>
          )}

          {items.map((item) => (
            <div key={item.id} className={`card vault-item ${item.locked ? 'locked' : ''} ${item.status !== 'active' ? 'superseded' : ''}`}>
              <div className="vault-item-head">
                <div>
                  <div className="vault-item-title">
                    {item.locked && <span className="vault-lock">🔒 </span>}
                    {item.title}
                  </div>
                  <div className="vault-item-meta">
                    <span className="mono-muted">{item.id}</span>
                    <span>{item.type?.replace(/_/g, ' ')}</span>
                    <span>v{item.version}</span>
                    <span className={`status-chip ${item.status === 'active' ? 'ok' : 'warn'}`}>
                      {item.status}
                    </span>
                    <span className="vault-access-level">{item.access_level.replace(/_/g, ' ')}</span>
                  </div>
                </div>
                <div className="vault-item-right">
                  <span className="vault-item-by">{item.created_by_name}</span>
                  <span className="vault-item-at">{shortTime(item.created_at)}</span>
                </div>
              </div>

              {item.locked ? (
                <div className="vault-locked-note">
                  Content withheld. Redacted: {(item.redacted || []).join(', ')}. An approved
                  authorisation covering this case is required to read it.
                </div>
              ) : (
                <>
                  {item.description && <div className="vault-item-desc">{item.description}</div>}
                  <div className="vault-item-source">Source: {item.source}</div>
                  {originLine(item) && (
                    <div className="vault-item-origin">{originLine(item)}</div>
                  )}
                  <button className="btn btn-ghost btn-sm" type="button"
                          onClick={() => showLineage(item)}>
                    {lineage[item.id] ? 'Hide chain of custody'
                      : lineageBusy === item.id ? 'Opening…' : 'Chain of custody'}
                  </button>
                  {lineage[item.id] && (
                    <div className="vault-lineage">
                      <div className="vault-lineage-block">
                        <div className="vault-lineage-title">Custody</div>
                        <ul className="vault-lineage-list">
                          {(lineage[item.id].custody || []).map((step, index) => (
                            <li key={index}>
                              <span className="vault-lineage-step">{step.step}</span>
                              {' '}{step.actor} · {shortTime(step.at)} — {step.detail}
                            </li>
                          ))}
                        </ul>
                      </div>
                      <div className="vault-lineage-block">
                        <div className="vault-lineage-title">Where it came from</div>
                        <div className="vault-lineage-meta">
                          {lineage[item.id].provenance?.source || 'no external source recorded'}
                          {lineage[item.id].provenance?.request_id
                            && ` · request ${lineage[item.id].provenance.request_id}`}
                        </div>
                        {(lineage[item.id].links || []).length === 0 ? (
                          <div className="vault-lineage-meta">No linked records.</div>
                        ) : (
                          <ul className="vault-lineage-list">
                            {lineage[item.id].links.map((link, index) => (
                              <li key={index}>
                                <span className="vault-lineage-step">{link.relation}</span>
                                {' '}{link.id}
                                {link.title ? ` — ${link.title}` : ''}
                                {link.exists === false && ' (missing)'}
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                    </div>
                  )}
                </>
              )}

              {!item.locked && vault.can_manage && (
                <div className="vault-item-actions">
                  <label className="vault-inline">
                    <span>Folder</span>
                    <select className="field-input" value={item.folder}
                            onChange={(e) => handleOrganise(item, { folder: e.target.value })}>
                      {folders.map((entry) => (
                        <option key={entry.key} value={entry.key}>{entry.label}</option>
                      ))}
                    </select>
                  </label>
                  <label className="vault-inline">
                    <span>Access</span>
                    <select className="field-input" value={item.access_level}
                            onChange={(e) => handleOrganise(item, { access_level: e.target.value })}>
                      {ACCESS_LEVELS.map(([value, label]) => (
                        <option key={value} value={value}>{label}</option>
                      ))}
                    </select>
                  </label>
                  {item.status === 'active' && (
                    <button className="btn btn-ghost btn-sm"
                            onClick={() => { setSuperseding(item); setReplacement({ title: '', description: '', reason: '' }) }}
                            type="button">
                      File corrected version
                    </button>
                  )}
                </div>
              )}

              {superseding?.id === item.id && (
                <div className="vault-supersede">
                  <label className="field">
                    <span className="field-label">Corrected description</span>
                    <textarea className="field-input" rows={2}
                              value={replacement.description}
                              onChange={(e) => setReplacement({ ...replacement, description: e.target.value })} />
                  </label>
                  <label className="field">
                    <span className="field-label">Why it is being corrected</span>
                    <input className="field-input" value={replacement.reason}
                           onChange={(e) => setReplacement({ ...replacement, reason: e.target.value })} />
                  </label>
                  <div className="report-review-actions">
                    <button className="btn btn-secondary btn-sm" onClick={handleSupersede}
                            disabled={busy} type="button">
                      File version {(item.version || 1) + 1}
                    </button>
                    <button className="btn btn-ghost btn-sm" onClick={() => setSuperseding(null)}
                            type="button">
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
