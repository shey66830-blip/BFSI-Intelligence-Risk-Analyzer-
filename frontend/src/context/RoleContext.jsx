import { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react'
import {
  clearToken, fetchMe, getToken, login as loginRequest, logout as logoutRequest,
  setUnauthorizedHandler,
} from '../api.js'

const RoleContext = createContext(null)

/**
 * Presentation details per role. Authority itself comes from the backend —
 * `user.permissions` is the single source of truth for what a session may do.
 */
export const ROLES = {
  analyst: {
    label: 'Analyst',
    short: 'An',
    icon: '👤',
    description: 'Investigates assigned cases. Customer identifiers are masked.',
  },
  compliance: {
    label: 'Compliance Officer',
    short: 'C',
    icon: '🔍',
    description: 'Reviews every case, sees unmasked data, can escalate to the FIU.',
  },
  admin: {
    label: 'Organisation Admin',
    short: 'A',
    icon: '🛡️',
    description: 'Manages users, assignments, risk settings and the audit trail.',
  },
}

export function RoleProvider({ children }) {
  const [user, setUser] = useState(null)
  const [booting, setBooting] = useState(true)
  const [notice, setNotice] = useState(null)

  // A 401 from anywhere ends the session exactly once.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      setUser(null)
      setNotice('Your session ended. Please sign in again.')
    })
  }, [])

  // Restore an existing session on load.
  useEffect(() => {
    let cancelled = false
    async function restore() {
      if (!getToken()) {
        setBooting(false)
        return
      }
      const payload = await fetchMe()
      if (cancelled) return
      if (payload?.user) setUser(payload.user)
      else clearToken()
      setBooting(false)
    }
    restore()
    return () => { cancelled = true }
  }, [])

  const signIn = useCallback(async (username, password) => {
    const result = await loginRequest(username, password)
    if (!result.ok) return result.error
    setNotice(null)
    setUser(result.user)
    return null
  }, [])

  const signOut = useCallback(async () => {
    await logoutRequest()
    setUser(null)
    setNotice('You have been signed out.')
  }, [])

  const can = useCallback(
    (permission) => Boolean(user?.permissions?.includes(permission)),
    [user]
  )

  const roleConfig = useMemo(() => {
    if (!user) return null
    const meta = ROLES[user.role] || {}
    return {
      ...meta,
      label: meta.label || user.role_label,
      description: meta.description,
      dashboard: user.dashboard,
      permissions: user.permissions || [],
      // Kept for the existing components that read these flags.
      canViewRaw: can('txn:view_unmasked'),
      canSeeAllAudit: can('audit:view_all'),
      canManageUsers: can('users:manage'),
      canManageSettings: can('settings:manage'),
      canEscalate: can('cases:decide'),
      canInvestigate: can('cases:investigate'),
      canAssign: can('cases:assign'),
      canViewAllCases: can('cases:view_all'),
    }
  }, [user, can])

  const value = {
    user,
    can,
    role: user?.role || null,
    roleConfig,
    signIn,
    signOut,
    logout: signOut,          // backwards-compatible alias
    notice,
    clearNotice: () => setNotice(null),
    booting,
    needsLogin: !user,
    isAuthenticated: Boolean(user),
  }

  return <RoleContext.Provider value={value}>{children}</RoleContext.Provider>
}

export function useRole() {
  const ctx = useContext(RoleContext)
  if (!ctx) throw new Error('useRole must be used within RoleProvider')
  return ctx
}

export default RoleContext
