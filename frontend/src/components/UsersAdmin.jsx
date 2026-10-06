import { Fragment, useCallback, useEffect, useState } from 'react'
import { createUser, fetchCases, fetchUsers, updateUser } from '../api.js'
import { ROLES } from '../context/RoleContext.jsx'

const EMPTY_FORM = { username: '', name: '', email: '', role: 'analyst', password: '' }

export default function UsersAdmin() {
  const [users, setUsers] = useState([])
  const [roles, setRoles] = useState([])
  const [cases, setCases] = useState([])
  const [loading, setLoading] = useState(true)
  const [feedback, setFeedback] = useState(null)
  const [expanded, setExpanded] = useState(null)
  const [draftCases, setDraftCases] = useState([])
  const [passwordDraft, setPasswordDraft] = useState('')
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)

  const load = useCallback(async () => {
    setLoading(true)
    const [payload, caseList] = await Promise.all([fetchUsers(), fetchCases()])
    setUsers(payload?.users || [])
    setRoles(payload?.roles || [])
    setCases(caseList || [])
    setLoading(false)
  }, [])

  useEffect(() => { load() }, [load])

  const flash = (type, message) => {
    setFeedback({ type, message })
    setTimeout(() => setFeedback(null), 3500)
  }

  const patch = async (userId, payload, message) => {
    const res = await updateUser(userId, payload)
    if (!res.ok) {
      flash('error', res.body.error || 'Update failed')
      return false
    }
    flash('ok', message)
    await load()
    return true
  }

  const submitForm = async (event) => {
    event.preventDefault()
    const res = await createUser(form)
    if (!res.ok) {
      flash('error', res.body.error || 'Could not create the account')
      return
    }
    flash('ok', `Created ${res.body.user.role} account for ${res.body.user.name}`)
    setForm(EMPTY_FORM)
    setShowForm(false)
    await load()
  }

  const toggleExpand = (user) => {
    if (expanded === user.id) {
      setExpanded(null)
      return
    }
    setExpanded(user.id)
    setDraftCases(user.assigned_case_ids || [])
    setPasswordDraft('')
  }

  const saveAssignments = async (userId) => {
    await patch(userId, { assigned_case_ids: draftCases }, 'Case assignments updated')
    setExpanded(null)
  }

  const resetPassword = async (userId) => {
    if (passwordDraft.length < 8) {
      flash('error', 'Password must be at least 8 characters')
      return
    }
    await patch(userId, { password: passwordDraft }, 'Password reset — existing sessions revoked')
    setPasswordDraft('')
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <h2 className="page-title">Users &amp; Roles</h2>
          <p className="page-sub">
            Synthetic accounts for the demo. Role changes and suspensions take effect immediately and
            revoke that user's sessions.
          </p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowForm((s) => !s)}>
          {showForm ? 'Cancel' : '+ Add user'}
        </button>
      </div>

      {feedback && (
        <div className={`flash flash-${feedback.type === 'ok' ? 'ok' : 'error'}`}>{feedback.message}</div>
      )}

      {showForm && (
        <form className="card admin-form" onSubmit={submitForm}>
          <div className="admin-form-grid">
            <label className="field">
              <span className="field-label">Username</span>
              <input className="field-input" value={form.username} required
                onChange={(e) => setForm({ ...form, username: e.target.value })} />
            </label>
            <label className="field">
              <span className="field-label">Full name</span>
              <input className="field-input" value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </label>
            <label className="field">
              <span className="field-label">Email</span>
              <input className="field-input" type="email" value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })} />
            </label>
            <label className="field">
              <span className="field-label">Role</span>
              <select className="field-input" value={form.role}
                onChange={(e) => setForm({ ...form, role: e.target.value })}>
                {roles.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
              </select>
            </label>
            <label className="field">
              <span className="field-label">Initial password</span>
              <input className="field-input" type="password" value={form.password} required minLength={8}
                onChange={(e) => setForm({ ...form, password: e.target.value })} />
            </label>
          </div>
          <div className="admin-form-actions">
            <span className="field-hint">
              {(roles.find((r) => r.value === form.role) || {}).description}
            </span>
            <button className="btn btn-primary" type="submit">Create account</button>
          </div>
        </form>
      )}

      <div className="card">
        {loading && <div className="pipeline-empty">Loading accounts…</div>}
        {!loading && (
          <table className="admin-table">
            <thead>
              <tr>
                <th>Identity</th>
                <th>Role</th>
                <th>Status</th>
                <th>Cases</th>
                <th>Last sign-in</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <Fragment key={user.id}>
                  <tr>
                    <td>
                      <div className="admin-name">{user.name}</div>
                      <div className="admin-meta">
                        @{user.username}{user.email ? ` · ${user.email}` : ''}
                        {user.is_synthetic === false && <span className="tag tag-new">created</span>}
                      </div>
                    </td>
                    <td>
                      <select
                        className="field-input admin-select"
                        value={user.role}
                        onChange={(e) => patch(user.id, { role: e.target.value },
                          `${user.name} is now ${e.target.value}`)}
                      >
                        {roles.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
                      </select>
                    </td>
                    <td>
                      <button
                        className={`status-pill ${user.status === 'active' ? 'ok' : 'off'}`}
                        onClick={() => patch(user.id,
                          { status: user.status === 'active' ? 'suspended' : 'active' },
                          user.status === 'active' ? `${user.name} suspended` : `${user.name} reactivated`)}
                      >
                        {user.status === 'active' ? 'Active' : 'Suspended'}
                      </button>
                    </td>
                    <td>{user.active_case_count}</td>
                    <td className="admin-meta">
                      {user.last_login ? new Date(user.last_login).toLocaleString('en-GB',
                        { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—'}
                    </td>
                    <td>
                      <button className="btn btn-ghost btn-sm" onClick={() => toggleExpand(user)}>
                        {expanded === user.id ? 'Close' : 'Manage'}
                      </button>
                    </td>
                  </tr>
                  {expanded === user.id && (
                    <tr className="admin-detail-row">
                      <td colSpan={6}>
                        <div className="admin-detail">
                          <div className="admin-detail-block">
                            <div className="admin-detail-title">Assigned cases</div>
                            <div className="admin-detail-sub">
                              Analysts only see cases listed here.
                            </div>
                            <div className="assign-grid">
                              {cases.map((c) => (
                                <label key={c.id} className="assign-option">
                                  <input
                                    type="checkbox"
                                    checked={draftCases.includes(c.id)}
                                    onChange={(e) => setDraftCases((prev) => e.target.checked
                                      ? [...prev, c.id]
                                      : prev.filter((id) => id !== c.id))}
                                  />
                                  <span>{c.title}</span>
                                </label>
                              ))}
                            </div>
                            <button className="btn btn-primary btn-sm" onClick={() => saveAssignments(user.id)}>
                              Save assignments
                            </button>
                          </div>

                          <div className="admin-detail-block">
                            <div className="admin-detail-title">Reset password</div>
                            <div className="admin-detail-sub">
                              Revokes this user's active sessions.
                            </div>
                            <div className="admin-inline">
                              <input
                                className="field-input"
                                type="password"
                                placeholder="New password (min 8)"
                                value={passwordDraft}
                                onChange={(e) => setPasswordDraft(e.target.value)}
                              />
                              <button className="btn btn-ghost btn-sm" onClick={() => resetPassword(user.id)}>
                                Reset
                              </button>
                            </div>
                            <div className="perms-list">
                              {user.permissions?.map((p) => <span key={p} className="perm-chip">{p}</span>)}
                            </div>
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="card role-panel">
        <div className="role-panel-title">What each role may do</div>
        <div className="role-matrix">
          {roles.map((r) => {
            const sample = users.find((u) => u.role === r.value)
            return (
              <div key={r.value} className="role-matrix-col">
                <div className="role-matrix-head">
                  {ROLES[r.value]?.icon} {r.label}
                </div>
                <div className="role-matrix-desc">{r.description}</div>
                <div className="perms-list">
                  {(sample?.permissions || []).map((p) => <span key={p} className="perm-chip">{p}</span>)}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
