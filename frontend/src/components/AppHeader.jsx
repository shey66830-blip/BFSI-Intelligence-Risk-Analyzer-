import { useEffect, useRef, useState, useCallback } from 'react'
import { useRole } from '../context/RoleContext.jsx'
import {
  fetchNotifications, markAllNotificationsRead, markNotificationRead,
} from '../api.js'

const SEVERITY_LABEL = { high: 'Action required', normal: 'For information' }

function BellIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
      <path d="M13.7 21a2 2 0 0 1-3.4 0" />
    </svg>
  )
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

/**
 * The identity strip. Every page states who is signed in, in what role, and for which
 * organisation — plus the structured notifications that arrived for that identity.
 */
export default function AppHeader({ onOpenNotification, onNavigate }) {
  const { user, roleConfig, signOut } = useRole()
  const [open, setOpen] = useState(false)
  const [notifications, setNotifications] = useState([])
  const [unread, setUnread] = useState(0)
  const [error, setError] = useState(null)
  const panelRef = useRef(null)

  // The role label already says what the person is authorised to do, and the seeded job
  // title restates it ("Organisation Admin · Organisation Administrator"), so the header
  // shows the role alone.
  const roleLabel = roleConfig?.label || user?.role_label || user?.role || ''

  const load = useCallback(async () => {
    const payload = await fetchNotifications()
    setNotifications(payload.notifications || [])
    setUnread(payload.unread || 0)
  }, [])

  useEffect(() => {
    load()
    const timer = setInterval(load, 30000)
    return () => clearInterval(timer)
  }, [load, user?.id])

  useEffect(() => {
    function onClick(event) {
      if (panelRef.current && !panelRef.current.contains(event.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [])

  const handleOpen = async (notification) => {
    setOpen(false)
    if (!notification.read_at) {
      const result = await markNotificationRead(notification.id)
      if (result.ok) setUnread(result.body.unread ?? unread)
      load()
    }
    onOpenNotification?.(notification)
  }

  const handleReadAll = async () => {
    const result = await markAllNotificationsRead()
    if (result.ok) {
      setUnread(result.body.unread ?? 0)
      load()
    } else {
      setError(result.body?.error || 'Could not mark everything read.')
    }
  }

  return (
    <header className="app-header">
      <div className="app-header-left">
        <div className="app-header-org">
          {user?.organization || roleConfig?.organization || 'Organisation'}
        </div>
        <div className="app-header-env">
          {user?.environment || 'synthetic'} environment · synthetic data only
        </div>
      </div>

      <div className="app-header-right" ref={panelRef}>
        <button
          className="header-icon-btn"
          onClick={() => setOpen(!open)}
          title="Notifications"
          type="button"
        >
          <span className="header-icon-glyph"><BellIcon /></span>
          <span className="header-icon-label">Notifications</span>
          {unread > 0 && <span className="header-badge">{unread}</span>}
        </button>

        {open && (
          <div className="notification-panel">
            <div className="notification-panel-head">
              <div>
                <div className="notification-panel-title">Notifications</div>
                <div className="notification-panel-sub">
                  {unread > 0 ? `${unread} unread` : 'Nothing unread'}
                </div>
              </div>
              <div className="notification-panel-actions">
                <button className="btn btn-ghost btn-sm" onClick={() => onNavigate?.('updates')}
                        type="button">
                  Update feed
                </button>
                <button className="btn btn-ghost btn-sm" onClick={handleReadAll}
                        disabled={unread === 0} type="button">
                  Mark all read
                </button>
              </div>
            </div>

            {error && <div className="notification-error">{error}</div>}

            <div className="notification-list">
              {notifications.length === 0 && (
                <div className="notification-empty">
                  No notifications yet. Reports, bank responses and access decisions appear here.
                </div>
              )}
              {notifications.map((note) => (
                <button
                  key={note.id}
                  className={`notification-item ${note.read_at ? '' : 'unread'} sev-${note.severity}`}
                  onClick={() => handleOpen(note)}
                  type="button"
                >
                  <span className="notification-dot" />
                  <span className="notification-body">
                    <span className="notification-title">{note.title}</span>
                    <span className="notification-text">{note.body}</span>
                    <span className="notification-meta">
                      {SEVERITY_LABEL[note.severity] || 'For information'} · {relative(note.created_at)}
                      {note.case_id ? ` · ${note.case_id}` : ''}
                    </span>
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="app-header-user">
          <div className="app-header-user-name">{user?.name}</div>
          <div className="app-header-user-role">{roleLabel}</div>
        </div>

        <button className="btn btn-ghost btn-sm" onClick={signOut} type="button">
          Sign out
        </button>
      </div>
    </header>
  )
}
