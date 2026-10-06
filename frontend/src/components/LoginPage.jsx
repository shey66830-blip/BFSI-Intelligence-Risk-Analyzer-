import { useEffect, useRef, useState } from 'react'
import { useRole, ROLES } from '../context/RoleContext.jsx'
import { fetchDemoAccounts } from '../api.js'

const ROLE_ORDER = ['analyst', 'compliance', 'admin']

const NAV = [
  { href: '#product', label: 'Product' },
  { href: '#how', label: 'How it works' },
  { href: '#controls', label: 'Controls' },
  { href: '#access', label: 'Demo access' },
]

/** Queue rows are the seeded demo transactions, not invented figures. */
const QUEUE_ROWS = [
  { id: 'TXN-C8', desc: 'NEFT to unknown account', amount: '₹3,00,000', risk: 91, decision: 'Investigate' },
  { id: 'TXN-C7', desc: 'Cash withdrawal', amount: '₹2,40,000', risk: 87, decision: 'Investigate' },
  { id: 'TXN-H2', desc: 'Apollo Hospitals co-pay', amount: '₹3,00,000', risk: 38, decision: 'Context' },
  { id: 'TXN-N1', desc: 'Salary credit', amount: '₹1,25,000', risk: 5, decision: 'No action' },
]

const STEPS = [
  {
    n: '01',
    title: 'A transaction is scored against its own history',
    body: 'Not against a global threshold. Each account is compared with its own baseline, so a first large payment stands out while a business that moves ₹12 lakh a month does not.',
  },
  {
    n: '02',
    title: 'A gate decides whether anyone needs to look',
    body: 'Below the anomaly threshold nothing happens and no bank is contacted. Above it, the case is opened and the reasons are written down — every one of them.',
  },
  {
    n: '03',
    title: 'The banks involved are asked, in scope',
    body: 'A structured, consent-scoped request goes to each bank that holds a piece of the pattern. Each bank searches its own records and answers with structured findings, not raw customer data.',
  },
  {
    n: '04',
    title: 'Findings are correlated, and a person decides',
    body: 'Two independent sources agreeing is labelled corroborated; a single source is labelled as such. The report separates what happened from why, and states what it does not establish.',
  },
]

const CONTROLS = [
  { title: 'Masking before serialisation', body: 'Identifiers are redacted on the server. A masked session is never sent the values, so there is nothing to reveal in a browser console.' },
  { title: 'Role-scoped case access', body: 'An analyst opens only the cases assigned to them. Anything else is a 403 and an entry in the audit trail.' },
  { title: 'Append-only audit trail', body: 'Sign-ins, views, pipeline runs, decisions, settings changes and refused requests are recorded with the acting identity, and readable only at the scope you hold.' },
  { title: 'Consent as a precondition', body: 'A bank report is only requested for entities with an active consent record. Expired consent is visible on the transaction itself.' },
]

function ShieldIcon({ size = 13 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M8 1.5 2.75 3.6v4.2c0 3.2 2.2 6.1 5.25 7.2 3.05-1.1 5.25-4 5.25-7.2V3.6L8 1.5Z"
        stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
      <path d="m5.9 8 1.5 1.5 2.9-3" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function LockIcon({ size = 12 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <rect x="3.2" y="7" width="9.6" height="7" rx="1.6" stroke="currentColor" strokeWidth="1.3" />
      <path d="M5.6 7V5.2a2.4 2.4 0 0 1 4.8 0V7" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  )
}

/** The product panel: a smaller, truthful view of the high-risk queue screen. */
function ProductPanel() {
  const tabs = ['Live queue', 'Cases', 'Bank requests', 'Evidence', 'Reporting']
  return (
    <div className="lp-window">
      <div className="lp-window-bar">
        <span className="lp-dots"><i /><i /><i /></span>
        <span className="lp-url">app.contextguard.io/queue/high-risk</span>
      </div>
      <div className="lp-window-body">
        <div className="lp-window-rail">
          <div className="lp-rail-label">Monitoring</div>
          {tabs.map((t, i) => (
            <div key={t} className={`lp-rail-item ${i === 0 ? 'active' : ''}`}>{t}</div>
          ))}
        </div>
        <div className="lp-window-main">
          <div className="lp-queue-head">
            <div>
              <div className="lp-queue-title">High-risk queue</div>
              <div className="lp-queue-sub">Scored on ingest · 12 stages recorded</div>
            </div>
            <span className="lp-healthy"><span className="lp-healthy-dot" />Rules current</span>
          </div>

          <div className="lp-tiles">
            <div className="lp-tile">
              <div className="lp-tile-label">Left alone</div>
              <div className="lp-tile-value">5%</div>
              <div className="lp-tile-delta muted">Case 1</div>
            </div>
            <div className="lp-tile">
              <div className="lp-tile-label">Context requested</div>
              <div className="lp-tile-value">42%</div>
              <div className="lp-tile-delta warn">Case 2</div>
            </div>
            <div className="lp-tile">
              <div className="lp-tile-label">Under investigation</div>
              <div className="lp-tile-value">87%</div>
              <div className="lp-tile-delta danger">Case 3</div>
            </div>
          </div>

          <table className="lp-table">
            <thead>
              <tr><th>Transaction</th><th>Amount</th><th>Risk</th><th>Decision</th></tr>
            </thead>
            <tbody>
              {QUEUE_ROWS.map((row) => (
                <tr key={row.id}>
                  <td>
                    <div className="lp-txn-id">{row.id}</div>
                    <div className="lp-txn-desc">{row.desc}</div>
                  </td>
                  <td className="lp-amount">{row.amount}</td>
                  <td>
                    <div className="lp-risk">
                      <span className="lp-risk-track">
                        <span
                          className={`lp-risk-fill ${row.risk > 65 ? 'high' : row.risk > 35 ? 'mid' : 'low'}`}
                          style={{ width: `${row.risk}%` }}
                        />
                      </span>
                      <span className="lp-risk-num">{row.risk}</span>
                    </div>
                  </td>
                  <td>
                    <span className={`lp-chip ${row.decision === 'Investigate' ? 'red' : row.decision === 'Context' ? 'amber' : 'green'}`}>
                      {row.decision}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

export default function LoginPage() {
  const { signIn, notice } = useRole()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [accounts, setAccounts] = useState([])
  const [selected, setSelected] = useState(null)
  const usernameRef = useRef(null)

  useEffect(() => {
    fetchDemoAccounts().then(setAccounts).catch(() => setAccounts([]))
  }, [])

  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    const message = await signIn(username.trim(), password)
    if (message) setError(message)
    setBusy(false)
  }

  const useAccount = (account) => {
    setUsername(account.username)
    setPassword(account.password)
    setSelected(account.username)
    setError(null)
  }

  const focusSignIn = () => {
    document.getElementById('access')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    window.setTimeout(() => usernameRef.current?.focus(), 420)
  }

  const grouped = ROLE_ORDER
    .map((role) => ({ role, items: accounts.filter((a) => a.role === role) }))
    .filter((group) => group.items.length > 0)

  return (
    <div className="lp">
      <header className="lp-nav">
        <div className="lp-nav-inner">
          <a className="lp-brand" href="#top">
            <span className="lp-mark">CG</span>
            <span className="lp-wordmark">Context Guard</span>
          </a>
          <nav className="lp-nav-links">
            {NAV.map((item) => <a key={item.href} href={item.href}>{item.label}</a>)}
          </nav>
          <div className="lp-nav-actions">
            <button className="lp-link-btn" type="button" onClick={focusSignIn}>Sign in</button>
            <button className="lp-btn lp-btn-primary" type="button" onClick={focusSignIn}>Open the demo</button>
          </div>
        </div>
      </header>

      <main className="lp-main" id="top">
        {/* ── Hero ─────────────────────────────────────────────────────── */}
        <section className="lp-hero">
          <div className="lp-hero-copy">
            <div className="lp-badges">
              <span className="lp-badge"><ShieldIcon /> Synthetic data only</span>
              <span className="lp-badge-plain">Consent-scoped requests · append-only audit</span>
            </div>

            <h1 className="lp-h1">
              Catch what a<br />single bank cannot see.
            </h1>

            <p className="lp-sub">
              Context Guard flags an unusual pattern, asks each bank involved for context, correlates
              what they return, and drafts an explainable report for a human decision. It reports
              suspicion. It does not declare fraud.
            </p>

            <div className="lp-ctas">
              <button className="lp-btn lp-btn-primary lp-btn-lg" type="button" onClick={focusSignIn}>
                Open the demo
              </button>
              <a className="lp-btn lp-btn-outline lp-btn-lg" href="#how">See how it works</a>
            </div>

            <div className="lp-metrics">
              <div className="lp-metric">
                <div className="lp-metric-value">12</div>
                <div className="lp-metric-label">pipeline stages, each recording what it did and why</div>
              </div>
              <div className="lp-metric">
                <div className="lp-metric-value">7</div>
                <div className="lp-metric-label">cross-bank checks; corroborated only when two sources agree</div>
              </div>
              <div className="lp-metric">
                <div className="lp-metric-value">100%</div>
                <div className="lp-metric-label">of decisions attributed to a named, authenticated identity</div>
              </div>
            </div>
          </div>

          <div className="lp-hero-panel" id="product">
            <ProductPanel />
          </div>
        </section>

        {/* ── How it works ─────────────────────────────────────────────── */}
        <section className="lp-band" id="how">
          <div className="lp-band-inner">
            <div className="lp-band-head">
              <h2>What happens between the transaction and the decision</h2>
              <p>
                Four steps. The first two run on ingest, the third is where the cross-bank
                intelligence lives, and the fourth is deliberately left to a person.
              </p>
            </div>
            <ol className="lp-steps">
              {STEPS.map((step) => (
                <li key={step.n} className="lp-step">
                  <span className="lp-step-n">{step.n}</span>
                  <div>
                    <div className="lp-step-title">{step.title}</div>
                    <p className="lp-step-body">{step.body}</p>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* ── Controls ─────────────────────────────────────────────────── */}
        <section className="lp-band alt" id="controls">
          <div className="lp-band-inner">
            <div className="lp-band-head">
              <h2>Built for the question a supervisor asks</h2>
              <p>
                Who saw this customer's data, was the request in scope, and why was the person
                entitled to act on it. Each of those is answerable from the system rather than
                from a policy document.
              </p>
            </div>
            <div className="lp-controls">
              {CONTROLS.map((control) => (
                <div key={control.title} className="lp-control">
                  <div className="lp-control-head"><LockIcon /> <span>{control.title}</span></div>
                  <p>{control.body}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ── Access ───────────────────────────────────────────────────── */}
        <section className="lp-band" id="access">
          <div className="lp-band-inner">
            <div className="lp-access">
              <div className="lp-form-col">
                <div className="lp-form-head">
                  <h2>Demo access</h2>
                  <p>
                    Four synthetic accounts, one per role. What you can reach after signing in is
                    decided by your role on the server.
                  </p>
                </div>

                <form className="lp-form" onSubmit={submit}>
                  {notice && !error && <div className="lp-alert info">{notice}</div>}
                  {error && <div className="lp-alert error">{error}</div>}

                  <label className="lp-field">
                    <span className="lp-field-label">Username</span>
                    <input
                      ref={usernameRef}
                      className="lp-input"
                      value={username}
                      autoComplete="username"
                      onChange={(e) => setUsername(e.target.value)}
                      placeholder="analyst"
                    />
                  </label>
                  <label className="lp-field">
                    <span className="lp-field-label">Password</span>
                    <input
                      className="lp-input"
                      type="password"
                      value={password}
                      autoComplete="current-password"
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder="••••••••"
                    />
                  </label>
                  <button className="lp-btn lp-btn-primary lp-submit" type="submit" disabled={busy || !username || !password}>
                    {busy ? 'Signing in…' : 'Sign in'}
                  </button>
                </form>

                {grouped.length > 0 && (
                  <div className="lp-accounts">
                    <div className="lp-accounts-label">Synthetic accounts</div>
                    {grouped.map(({ role, items }) => (
                      <div key={role} className="lp-account-group">
                        <div className="lp-account-role">
                          <span className="lp-account-role-name">{ROLES[role]?.label || role}</span>
                          <span className="lp-account-role-desc">{ROLES[role]?.description}</span>
                        </div>
                        {items.map((account) => (
                          <button
                            key={account.username}
                            type="button"
                            className={`lp-account ${selected === account.username ? 'selected' : ''}`}
                            onClick={() => useAccount(account)}
                          >
                            <span className="lp-account-name">{account.name}</span>
                            <span className="lp-account-creds">{account.username} · {account.password}</span>
                          </button>
                        ))}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="lp-roles-col">
                <div className="lp-roles-title">What changes with the role</div>
                <table className="lp-roles">
                  <thead>
                    <tr><th>Role</th><th>Scope</th><th>Decision rights</th></tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td>Analyst</td>
                      <td>Assigned cases only, identifiers masked</td>
                      <td>Close, or request more context</td>
                    </tr>
                    <tr>
                      <td>Compliance</td>
                      <td>Every case, unmasked</td>
                      <td>All of the above, plus escalate</td>
                    </tr>
                    <tr>
                      <td>Admin</td>
                      <td>Everything, plus administration</td>
                      <td>Users, roles, thresholds, audit</td>
                    </tr>
                  </tbody>
                </table>

                <div className="lp-note">
                  <strong>This is a demonstration build.</strong> The banks are simulated endpoints on
                  localhost and every account, transaction and report is generated. No connection to
                  a live payment system or customer record exists. Replacing the mock handlers with
                  real bank APIs changes the source of evidence, not the workflow.
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* ── Bank strip ───────────────────────────────────────────────── */}
        <section className="lp-partners">
          <div className="lp-partners-inner">
            <div className="lp-partners-label">Simulated bank endpoints in this build</div>
            <div className="lp-partners-row">
              <span>HDFC Bank</span><span>ICICI Bank</span><span>Axis Bank</span>
              <span className="lp-partners-more">plus a national FIU referral path</span>
            </div>
          </div>
        </section>
      </main>

      <footer className="lp-footer">
        <div className="lp-footer-inner">
          <span>Context Guard — financial risk intelligence layer</span>
          <span>Demo environment · synthetic data · 12-stage investigation pipeline</span>
        </div>
      </footer>
    </div>
  )
}
