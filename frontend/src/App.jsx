import { useCallback, useEffect, useState } from 'react'
import { RoleProvider, useRole } from './context/RoleContext.jsx'
import { fetchCase, fetchCases, fetchDashboardStats, fetchGraph, fetchUsers } from './api.js'
import Sidebar from './components/Sidebar.jsx'
import AppHeader from './components/AppHeader.jsx'
import LoginPage from './components/LoginPage.jsx'
import Dashboard from './components/Dashboard.jsx'
import CaseDetail from './components/CaseDetail.jsx'
import GraphView from './components/GraphView.jsx'
import AuditLog from './components/AuditLog.jsx'
import UsersAdmin from './components/UsersAdmin.jsx'
import SettingsPanel from './components/SettingsPanel.jsx'
import ReportsQueue from './components/ReportsQueue.jsx'
import InvestigationUpdates from './components/InvestigationUpdates.jsx'
import AccessRequests from './components/AccessRequests.jsx'
import SystemStatus from './components/SystemStatus.jsx'

/** Views that require a permission, enforced again by the backend on every request. */
const VIEW_PERMISSIONS = {
  users: 'users:manage',
  settings: 'settings:manage',
  status: 'system:status',
  access: ['access:request', 'access:approve'],
  updates: ['reports:review', 'updates:post'],
  reports: 'reports:create',
  graph: 'graph:view',
}

function NotPermitted({ permission, roleConfig }) {
  return (
    <div className="card permission-denied">
      <div className="permission-denied-title">Not available for your role</div>
      <p>
        {roleConfig?.label} does not hold the <code>{permission}</code> permission. The backend
        enforces this independently of the interface.
      </p>
    </div>
  )
}

function AppContent() {
  const { user, booting, roleConfig, can } = useRole()
  const [view, setView] = useState('dashboard')
  const [stats, setStats] = useState(null)
  const [cases, setCases] = useState([])
  const [selectedCase, setSelectedCase] = useState(null)
  const [graphData, setGraphData] = useState(null)
  const [userCount, setUserCount] = useState(null)
  const [loading, setLoading] = useState(true)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [demoBannerDismissed, setDemoBannerDismissed] = useState(false)
  const [error, setError] = useState(null)
  const [flash, setFlash] = useState(null)

  const loadWorkspace = useCallback(async () => {
    setLoading(true)
    const [s, c] = await Promise.all([fetchDashboardStats(), fetchCases()])
    setStats(s)
    setCases(c)
    if (can('users:manage')) {
      const payload = await fetchUsers()
      setUserCount(payload?.users?.length ?? null)
    }
    setLoading(false)
  }, [can])

  // A different identity must never inherit the previous session's view or data.
  useEffect(() => {
    setView('dashboard')
    setSelectedCase(null)
    setGraphData(null)
    setError(null)
    setFlash(null)
    setStats(null)
    setCases([])
  }, [user?.id])

  useEffect(() => {
    if (user) loadWorkspace()
  }, [user, loadWorkspace])

  const handleSelectCase = useCallback(async (caseId) => {
    setLoading(true)
    setError(null)
    const data = await fetchCase(caseId)
    if (data?.forbidden || data?.error) {
      setError(data.error || 'That case is outside your scope.')
      setLoading(false)
      return
    }
    setSelectedCase(data)
    setView('case')
    setLoading(false)
  }, [])

  const handleViewGraph = async () => {
    setLoading(true)
    const data = await fetchGraph()
    setGraphData(data)
    setView('graph')
    setLoading(false)
  }

  const handleNavigate = (next) => {
    setError(null)
    if (next === 'dashboard' || next === 'cases') {
      setView('dashboard')
      setSelectedCase(null)
      loadWorkspace()
      return
    }
    if (next === 'graph') {
      handleViewGraph()
      return
    }
    setView(next)
  }

  /** Notifications carry a link, so clicking one lands on the thing it is about. */
  const handleNotification = (notification) => {
    const link = notification.link || ''
    if (link.startsWith('case:')) {
      handleSelectCase(link.slice(5))
      return
    }
    if (link.startsWith('restricted:')) {
      handleSelectCase(link.slice('restricted:'.length))
      return
    }
    if (link.startsWith('access:')) {
      setView('access')
      return
    }
    if (notification.case_id) handleSelectCase(notification.case_id)
  }

  const handleBack = () => {
    setView('dashboard')
    setSelectedCase(null)
    loadWorkspace()
  }

  const handleRunPipeline = async (caseId) => {
    const data = await fetchCase(caseId)
    if (!data?.forbidden && !data?.error) setSelectedCase(data)
    const [s, c] = await Promise.all([fetchDashboardStats(), fetchCases()])
    setStats(s)
    setCases(c)
  }

  const handleCaseFromAnotherView = (caseId) => handleSelectCase(caseId)

  if (booting) {
    return (
      <div className="app-boot">
        <div className="spinner" />
        <div>Restoring your session…</div>
      </div>
    )
  }

  if (!user) return <LoginPage />

  const requirement = VIEW_PERMISSIONS[view]
  const required = Array.isArray(requirement) ? requirement : requirement ? [requirement] : null
  const blocked = required && !required.some((permission) => can(permission))

  return (
    <div className="app">
      <Sidebar
        currentView={view}
        onNavigate={handleNavigate}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
      />
      <div className={`main-wrapper ${sidebarCollapsed ? 'sidebar-collapsed' : ''}`}>
        <AppHeader onOpenNotification={handleNotification} onNavigate={handleNavigate} />
        {!demoBannerDismissed && (
          <div className="demo-banner">
            <span className="demo-banner-icon">⚠</span>
            <span>
              <strong>DEMO MODE</strong> — synthetic data and demonstration accounts · no live
              payment, aggregator or government integration is connected.
            </span>
            <button className="demo-banner-dismiss" onClick={() => setDemoBannerDismissed(true)}>
              Dismiss
            </button>
          </div>
        )}
        <div className="main">
          {error && (
            <div className="flash flash-error">
              {error}
              <button className="flash-close" onClick={() => setError(null)}>×</button>
            </div>
          )}
          {flash && (
            <div className="flash flash-ok">
              {flash}
              <button className="flash-close" onClick={() => setFlash(null)}>×</button>
            </div>
          )}

          {blocked ? (
            <NotPermitted permission={required.join(' or ')} roleConfig={roleConfig} />
          ) : (
            <>
              {view === 'dashboard' && (
                <Dashboard
                  stats={stats}
                  cases={cases}
                  userCount={userCount}
                  onSelectCase={handleSelectCase}
                  onNavigate={handleNavigate}
                  onOpenCase={handleSelectCase}
                />
              )}
              {view === 'case' && selectedCase && (
                <CaseDetail
                  caseData={selectedCase}
                  onBack={handleBack}
                  onRunPipeline={handleRunPipeline}
                />
              )}
              {view === 'graph' && <GraphView graphData={graphData} onBack={handleBack} />}
              {view === 'reports' && <ReportsQueue onOpenCase={handleCaseFromAnotherView} />}
              {view === 'updates' && (
                <UpdatesView onOpenCase={handleCaseFromAnotherView} />
              )}
              {view === 'access' && <AccessRequests onOpenCase={handleCaseFromAnotherView} />}
              {view === 'audit' && <AuditLog />}
              {view === 'users' && <UsersAdmin />}
              {view === 'settings' && <SettingsPanel />}
              {view === 'status' && <SystemStatus />}
            </>
          )}

          {loading && view === 'dashboard' && !stats && (
            <div className="loading"><div className="spinner" /> Loading your workspace…</div>
          )}
        </div>
      </div>
    </div>
  )
}

/** The cross-case feed on its own screen, for compliance and administrators. */
function UpdatesView({ onOpenCase }) {
  return <InvestigationUpdates crossCase onOpenCase={onOpenCase} />
}

export default function App() {
  return (
    <RoleProvider>
      <AppContent />
    </RoleProvider>
  )
}
