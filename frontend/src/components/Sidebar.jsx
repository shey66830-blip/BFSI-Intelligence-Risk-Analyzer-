import { useEffect, useState } from 'react'
import { useRole } from '../context/RoleContext.jsx'
import { fetchHealth } from '../api.js'

const ICONS = {
  dashboard: (
    <>
      <rect x="3" y="3" width="7.5" height="7.5" rx="1.4" />
      <rect x="13.5" y="3" width="7.5" height="7.5" rx="1.4" />
      <rect x="3" y="13.5" width="7.5" height="7.5" rx="1.4" />
      <rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1.4" />
    </>
  ),
  graph: (
    <>
      <circle cx="6" cy="6" r="2.6" />
      <circle cx="18" cy="8" r="2.6" />
      <circle cx="11" cy="18" r="2.6" />
      <path d="M8.4 7.2 15.4 7.8M7.4 8.4l2.6 7.2M16.6 10.2l-4.4 6" />
    </>
  ),
  reports: (
    <>
      <path d="M6 2.8h8.2L19 7.6V21.2H6z" />
      <path d="M13.6 2.8v5h5.2M9 12.4h7M9 16.2h7" />
    </>
  ),
  updates: (
    <>
      <path d="M3.4 12h3.2l2.4-6 3.4 12 2.6-8 2 2h4" />
    </>
  ),
  access: (
    <>
      <rect x="3.6" y="10.4" width="16.8" height="10.4" rx="2" />
      <path d="M8 10.4V7.2a4 4 0 0 1 8 0v3.2M12 14.6v2.6" />
    </>
  ),
  audit: (
    <>
      <path d="M4.4 4.2h15.2M4.4 9.4h15.2M4.4 14.6h10.4M4.4 19.8h7.2" />
    </>
  ),
  users: (
    <>
      <circle cx="9.4" cy="8" r="3.4" />
      <path d="M2.8 20.4c0-3.4 3-5.6 6.6-5.6s6.6 2.2 6.6 5.6" />
      <path d="M16.6 5.2a3.2 3.2 0 0 1 0 6.2M18 14.9c2.1.6 3.4 2.2 3.4 4.3" />
    </>
  ),
  settings: (
    <>
      <circle cx="12" cy="12" r="3.1" />
      <path d="M12 2.6v2.6M12 18.8v2.6M4.4 12H1.8M22.2 12h-2.6M6.6 6.6 4.8 4.8M19.2 19.2l-1.8-1.8M6.6 17.4l-1.8 1.8M19.2 4.8l-1.8 1.8" />
    </>
  ),
  status: (
    <>
      <rect x="3" y="4" width="18" height="6" rx="1.6" />
      <rect x="3" y="14" width="18" height="6" rx="1.6" />
      <path d="M6.8 7h.01M6.8 17h.01" />
    </>
  ),
}

function Icon({ name }) {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {ICONS[name]}
    </svg>
  )
}

const NAV_ITEMS = [
  { key: 'dashboard', icon: 'dashboard', label: 'Dashboard' },
  { key: 'graph', icon: 'graph', label: 'Network Intelligence', permission: 'graph:view' },
  // Analysts draft reports here; compliance reviews the submitted queue. Either permission
  // is enough to reach the page — the backend still decides what each role may do on it.
  { key: 'reports', icon: 'reports', label: 'Investigation Reports', permission: 'reports:create',
    altPermission: 'reports:review' },
  { key: 'updates', icon: 'updates', label: 'Investigation Updates', permission: 'reports:review',
    altPermission: 'updates:post' },
  { key: 'access', icon: 'access', label: 'Access Requests', permission: 'access:request',
    altPermission: 'access:approve' },
]

const GOVERNANCE_ITEMS = [
  { key: 'audit', icon: 'audit', label: 'Audit Trail' },
]

const ADMIN_ITEMS = [
  { key: 'users', icon: 'users', label: 'Users & Roles', permission: 'users:manage' },
  { key: 'settings', icon: 'settings', label: 'System Settings', permission: 'settings:manage' },
  { key: 'status', icon: 'status', label: 'System Status', permission: 'system:status' },
]

function initials(name) {
  if (!name) return '—'
  return name.split(/\s+/).slice(0, 2).map((p) => p[0]).join('').toUpperCase()
}

export default function Sidebar({ currentView, onNavigate, collapsed, onToggleCollapse }) {
  const { user, roleConfig, can, signOut } = useRole()

  // The reference keeps a system-health pill at the foot of the rail; this one reads
  // the same /api/health probe the workspace already exposes.
  const [health, setHealth] = useState(null)
  useEffect(() => {
    let live = true
    const ping = async () => {
      const payload = await fetchHealth().catch(() => null)
      if (live) setHealth(payload)
    }
    ping()
    const timer = setInterval(ping, 60000)
    return () => { live = false; clearInterval(timer) }
  }, [])
  const healthy = health?.status === 'ok'

  // `altPermission` is an alternative route to the same screen: an item listing two
  // permissions is reachable with either. Requiring both instead of either hid the
  // access-request page from the compliance officer who raises the requests.
  const permitted = (item) => {
    const required = [item.permission, item.altPermission].filter(Boolean)
    return required.length === 0 || required.some((permission) => can(permission))
  }
  const navItems = NAV_ITEMS.filter(permitted)
  const adminItems = ADMIN_ITEMS.filter(permitted)

  const renderItem = (item) => (
    <button
      key={item.key}
      className={`sidebar-item ${currentView === item.key ? 'active' : ''}`}
      onClick={() => onNavigate(item.key)}
      title={collapsed ? item.label : undefined}
      type="button"
    >
      <span className="sidebar-item-icon"><Icon name={item.icon} /></span>
      {!collapsed && <span className="sidebar-item-label">{item.label}</span>}
    </button>
  )

  return (
    <nav className={`sidebar ${collapsed ? 'collapsed' : ''}`}>
      <div className="sidebar-header">
        <div className="sidebar-logo">CG</div>
        {!collapsed && (
          <div className="sidebar-brand">
            <div className="sidebar-brand-title">Context Guard</div>
            <div className="sidebar-brand-sub">Intelligence Layer</div>
          </div>
        )}
        <button
          className="sidebar-toggle"
          onClick={onToggleCollapse}
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          type="button"
        >
          {collapsed ? '»' : '«'}
        </button>
      </div>

      <div className="sidebar-nav">
        <div className="sidebar-section-label">Navigation</div>
        {navItems.map(renderItem)}

        <div className="sidebar-section-label">Governance</div>
        {GOVERNANCE_ITEMS.map(renderItem)}

        {adminItems.length > 0 && (
          <>
            <div className="sidebar-section-label">Administration</div>
            {adminItems.map(renderItem)}
          </>
        )}
      </div>

      <div className="sidebar-footer">
        {!collapsed && (
          <div className={`sidebar-status ${healthy ? '' : 'off'}`}>
            <span className="sidebar-status-dot" />
            <div className="sidebar-status-text">
              <div className="sidebar-status-title">
                {healthy ? 'All systems operational' : 'Backend unreachable'}
              </div>
              <div className="sidebar-status-sub">
                {healthy ? `${health?.storage || 'storage'} · live` : 'Retrying every minute'}
              </div>
            </div>
          </div>
        )}
        <div className="sidebar-role" title={collapsed ? `${user?.name} — ${roleConfig?.label}` : undefined}>
          <div className="sidebar-role-avatar">{initials(user?.name)}</div>
          {!collapsed && (
            <div className="sidebar-role-info">
              <div className="sidebar-role-name">{user?.name}</div>
              <div className="sidebar-role-title">{roleConfig?.label || user?.title}</div>
            </div>
          )}
        </div>
        {!collapsed && (
          <button className="sidebar-signout" onClick={signOut} type="button">
            Sign out
          </button>
        )}
      </div>
    </nav>
  )
}
