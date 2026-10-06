# Context Guard

**Consent-driven, privacy-aware financial risk-intelligence and investigation platform** — a demonstration build on synthetic data only, with no live bank, payment, aggregator or government integration connected.

> Status: demonstration build · synthetic data only · banks simulated · no live external integration

Context Guard spots unusual transactions but **never labels them as fraud**. Instead, it:

1. **Flags** unusual patterns for investigation
2. **Sends structured requests** to relevant banks (simulated APIs for demo)
3. **Ingests bank reports** and produces a combined risk assessment
4. **Delivers explainable reasons** and a confidence score

## The Investigation Pipeline

Every case moves through the same twelve explicit stages. Each one reports what it did and on
what evidence, so the dashboard shows its work instead of a verdict:

```
 1. Transaction occurs
 2. Initial AI analysis                     ← scored against the account's own baseline
 3. Meaningful anomaly or pattern?          ← gate: 35% threshold
       │ NO  → stays in routine monitoring, no bank is contacted
       │ YES
 4. Investigation case created
 5. Relevant banks identified               ← after graph expansion: see below
 6. Investigation request sent              ← structured, consent-scoped, per bank
 7. Simulated banks analyze their own data  ← each bank searches only its own records
 8. Structured reports returned             ← findings only, never raw customer data
 9. Context + cross-bank evidence correlation
10. AI-generated investigation report       ← sections, citations, confidence, stated gaps
11. Risk assessment                         ← escalation priority, never a verdict
12. Human / bank investigator decision      ← attributed, with a required rationale
```

### Graph expansion (stage 5)

A case is opened from one transaction on one account. If the pipeline stopped there it would
contact one bank and see a fraction of the pattern — the blind spot the platform exists to close.

So stage 5 walks outward from the entity named on the case, following two link types that are
readable from the transaction record alone:

- **counterparty** — a transaction whose counterparty name resolves to a known entity
- **shared device** — another entity that transacted from a device this one also used

Expansion runs to two hops by default. In the coordinated demo scenario, one entity named on the
case reaches two more and puts **two** banks in scope, where the unexpanded case would have
contacted one.

Every entity added is stored on the case with the link that justified it, and stage 5 states the
reasoning in plain language:

> 1 entity named on the case reached 2 further entities within 2 hops, which puts 2 banks in scope.
> GlobalTrade Exports pays or is paid by Vikram Patel (txn_c5_07d9291e); Sharma & Associates pays or
> is paid by GlobalTrade Exports (txn_c3_60028c07).

Expansion widens *scope*, never *conclusion*. An entity reached by a shared device is an account to
ask about, not an accusation — the report says so in the same sentence that reports the count.

### Routing

| Score | Route | What happens |
|-------|-------|--------------|
| `< 35%` | No action | Gate closes. Nothing is shared. |
| `35–65%` | Context verification | A consent-scoped context request goes to the holding bank. Returned context can **explain the anomaly away** (lowering the score) or **leave it unresolved**. |
| `> 65%` | Investigation | Formal multi-bank investigation, correlation, report, human decision. |

### Confidence is two numbers, not one

- **Pattern confidence** — how well corroborated the observed structure is. Can legitimately be high: the transfers happened, and two banks agree on them.
- **Intent confidence** — how well the *purpose* is understood. Deliberately low whenever nothing explains the money movement.

Neither is a likelihood of wrongdoing. A well-corroborated pattern sitting next to an unexplained
purpose is exactly when a confident-sounding single number does the most damage.

Every report also has a mandatory **"What this report does not establish"** section, and the model
weights signals with a noisy-OR blend so no single signal can ever reach certainty on its own.

## Demo Cases

| Case | Description | Risk Level |
|------|-------------|------------|
| **Case 1** | Routine Spending — Alice Chen's everyday transactions | 🟢 Low (5%) |
| **Case 2** | High-Value Wire — Bob Fitzgerald's $47,500 transfer needs context verification | 🟡 Elevated (42%) |
| **Case 3** | Coordinated Cross-Bank — Multi-entity fund movement with layering pattern | 🔴 Critical (87%) |

## Architecture

```
┌─────────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   React Dashboard   │────▶│   Flask Backend   │────▶│  Mock Bank APIs │
│   (Vite, port 3000) │◀────│   (port 5000)     │◀────│  (simulated)    │
└─────────────────────┘     └──────────────────┘     └─────────────────┘
                                    │
                                    ▼
                             ┌──────────────┐
                             │   MongoDB    │
                             │ cases, txns, │
                             │ users, audit │
                             └──────────────┘
```

### Tech Stack

- **Frontend**: React 18 + Vite
- **Backend**: Flask (Python)
- **Storage**: MongoDB (cases, transactions, users, sessions, audit trail, settings)
- **Auth**: session tokens in MongoDB, hashed passwords (`werkzeug`), permission-checked routes
- **Visualization**: vis-network for network graphs
- **Data**: Synthetic generation (no real data)

### Demo Flow

1. **Dashboard → Transaction monitor** — Pick a scenario and feed a transaction in. Stages 1–4 run live and show the gate verdict. `coordinated` and `high value` open a case on the spot; `routine` shows the gate refusing to.
2. **Open the case → Pipeline tab** — Press **Run pipeline** and watch stages 5–11 execute: banks identified, requests sent, reports returned, evidence correlated, report drafted, risk assessed.
3. **Read the report** — Headline, pattern vs intent confidence, eight sections including the stated gaps, then the citations.
4. **Record a decision** — Stage 12 requires an investigator name and a rationale. The decision is attributed in the trace and updates the case status.
5. **Case 1 (Low Risk)** — Run the pipeline and watch it *stand down*: the gate closes, no bank is contacted, no report is drafted.
6. **Network Graph tab** — The visual view of the same linked accounts, devices, and suspicion links.

### Key Design Principles

- **No fraud labels** — Only flags for investigation
- **Explainable** — Every risk score has visible, auditable reasons
- **Consent-driven** — All data sharing requires active consent
- **Bank-agnostic** — Mock APIs swap for real ones when partnerships exist
- **Privacy-aware** — Never makes unilateral guilt determinations

## Authentication & Roles

Every `/api` route except `health`, `auth/login` and `auth/demo-accounts` requires a session token
(`Authorization: Bearer <token>`). Authority is a **permission**, not a role name — routes ask for
`cases:decide`, never for "compliance" — so the matrix below is the only place authority is decided.

| Role | Sees | May do | May not |
|------|------|--------|---------|
| **Analyst** | Only cases assigned to them, with customer identifiers redacted server-side | Investigate, run the pipeline, close a case, request context | Escalate, see unassigned cases, view or manage users |
| **Compliance Officer** | Every case, unmasked | Everything an analyst can, plus assign cases and escalate to the FIU | Manage users or settings |
| **Organisation Admin** | Everything, unmasked | All of the above, plus manage users/roles, assignments, risk settings and the full audit trail | — |

### Synthetic accounts (demo mode)

Shown on the login page and clickable to fill the form. `GET /api/auth/demo-accounts` returns
nothing when the org leaves demo mode.

| Username | Password | Identity | Role | Assigned |
|----------|----------|----------|------|----------|
| `analyst` | `analyst123` | Ananya Iyer | Analyst | case_1, case_2 |
| `analyst2` | `analyst123` | Rohit Deshmukh | Analyst | case_3 |
| `compliance` | `compliance123` | Inspector R. Mehta | Compliance Officer | — |
| `admin` | `admin123` | S. Nair | Organisation Admin | — |

### What is enforced where

- **Case scoping** — `visible_case_ids()` filters lists; opening or acting on someone else's case is a 403 (and an `access_denied` audit entry).
- **Identifier masking** — redaction happens in `services/privacy.py` *before* serialisation, so a masked session never receives the raw values. Free-text fields (case descriptions, transaction descriptions) are scrubbed too, using the entity name list.
- **Decision rights** — analysts get a restricted option set (`close`, `request context`, `continue`); escalation requires `cases:decide` and is refused with a 403 otherwise.
- **Attribution** — the investigator on a decision comes from the session. A form field that names someone else is refused with a 403 (`attribution_mismatch`) and written to the trail, so a decision cannot be signed in another person's name.
- **A report before a decision** — stage 12 is refused with a 409 (`report_required`) while the case has no pipeline report. A decision has to rest on an investigation, so the ordering is enforced by the API and not only by the interface.
- **Settings that bind** — the anomaly gate, investigation threshold, analyst masking policy, mandatory-rationale rule and contextual mitigation are admin-editable (`/api/settings`) and applied by the live gate.
- **Locked features and information** — some capabilities and records are withheld from the analyst *and* the compliance officer alike, because releasing them is not a role privilege. `GET /api/locked-resources` lists each one with the party who can release it — the bank that holds the record, or an administrator acting for the organisation. A request carries a written statement of at least 25 words and is refused before it reaches anybody without one.
- **The bank gateway** — bank-held records are decided by the bank (`services/bank_review.py`) through a channel (`services/bank_gateway.py`) that does what a real consent desk does: it holds the request until the answer is due rather than pretending the bank replied at once, retries a submission that fails in transit, releases *part* of a request when the bank will not defend all of it, and lapses the request if the bank does not answer within its response deadline (48 hours by default). Latency, deadline and failure rate are admin-editable.
- **A release is a capability, not a role** — an approved request produces a time-limited authorisation that is resolved per request. It starts, it expires by itself, and every use of the released capability is recorded. Nothing here is ever added to a role's permissions.
- **Statements are recorded even when not shown** — every statement, and the bank's answer, is written to the request and to the audit trail marked `recorded_only`, readable in the trail and nowhere else.

## Getting Started

The backend is Flask (Python) and the frontend is Vite (Node). They live in two directories and run
on two runtimes, so start them from the **repository root** — `npm run dev` there launches both and
prefixes each line of output with `[api]` or `[web]`:

```bash
npm run install:web      # first time only — installs the frontend
pip install -r backend/requirements.txt   # first time only — installs the API
npm run dev              # both servers, Ctrl-C stops both
```

Open `http://127.0.0.1:3000`. Flask listens on `http://localhost:5000`.

Running `npm run dev` from inside `backend/` fails with `ENOENT ... backend/package.json` — that
directory is Python, not Node.

### Starting them separately

```bash
npm run dev:api          # cd backend && python app.py
npm run dev:web          # cd frontend && vite --host 127.0.0.1 --port 3000
```

Vite proxies `/api` to Flask. `--host 127.0.0.1` is not optional: the default `vite` binds IPv6
loopback only, so `http://127.0.0.1:3000` fails to connect.

Ports are configurable — `FLASK_PORT=5001 VITE_PORT=3100 npm run dev`.

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
All endpoints below except `/api/health`, `/api/auth/login` and `/api/auth/demo-accounts`
require a bearer token. Permission requirements are shown in brackets.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/login` | Sign in; returns a session token |
| POST | `/api/auth/logout` | Revoke the current session |
| GET | `/api/auth/me` | The signed-in identity and its permissions |
| GET | `/api/auth/demo-accounts` | Synthetic accounts (demo mode only) |
| GET | `/api/users` | List accounts [`users:manage`] |
| POST | `/api/users` | Create an account [`users:manage`] |
| PATCH | `/api/users/:id` | Role, status, assignment, password [`users:manage`] |
| GET | `/api/users/analysts` | Analyst roster for assignment [`cases:assign`] |
| POST | `/api/cases/:id/assign` | Assign a case owner [`cases:assign`] |
| GET | `/api/settings` | Organisation settings |
| PUT | `/api/settings` | Update settings [`settings:manage`] |
| GET | `/api/audit-logs` | Own activity, or all with `?scope=all` [`audit:view_all`] |
| GET | `/api/health` | Health check (public) |
| GET | `/api/dashboard-stats` | Aggregate stats, scoped to the caller |
| GET | `/api/cases` | Cases visible to the caller |
| GET | `/api/cases/:id` | Case details with transactions and risk |
| GET | `/api/transactions` | Transactions, scoped to the caller |
| POST | `/api/context-request` | Send context verification to a bank |
| POST | `/api/investigation-request` | Initiate formal investigation |
| GET | `/api/mock-bank-endpoints` | List mock bank API info |
| GET | `/api/requests` | All bank requests sent |
| GET | `/api/pipeline/flow` | Stage list, thresholds, scenarios, decision options |
| POST | `/api/pipeline/ingest` | Stages 1–4: analyse an incoming transaction, maybe open a case |
| POST | `/api/pipeline/run` | Stages 5–11: investigate a case and draft the report |
| GET | `/api/cases/:id/report` | The drafted report |
| POST | `/api/cases/:id/decision` | Stage 12: record the investigator's decision |
| GET | `/api/locked-resources` | Locked items, their state and decider, and any released rows |
| POST | `/api/access-requests` | Raise a request — restricted information, or a locked item with its statement |
| GET | `/api/access-requests` | The approval queue, or the caller's own requests |
| POST | `/api/access-requests/:id/approve` | Approve (administrator; self-approval refused) [`access:approve`] |
| POST | `/api/access-requests/:id/reject` | Refuse [`access:approve`] |
| POST | `/api/access-requests/:id/clarification` | Ask the requester to clarify [`access:approve`] |
| GET | `/api/access-requests/:id/statements` | The statements recorded against a request, in full |

## Tests

```bash
npm test                # all six suites
npm run test:rbac       # one suite at a time
npm run test:pipeline
npm run test:workflow
npm run test:security
npm test -- controls    # the application-layer security controls
```

Equivalent to running the suites directly, with `PYTHONIOENCODING=utf-8` applied so the ₹ and
box-drawing characters survive the Windows console:

```bash
cd backend && python test_pipeline.py   # pipeline stages and gate branches
cd backend && python test_rbac.py       # authentication, roles and scoping (81 checks)
cd backend && python test_workflow.py   # reports, evidence, access, audit and the bank gateway (209 checks)
cd backend && python test_security.py   # credential, session, authorisation and audit invariants (62 checks)
cd backend && python test_security_controls.py  # hardening, origin trust, throttling, validation, posture, privacy (52 checks)
```

`test_pipeline.py` exercises every stage and both branches of the gate for all scenarios and demo
cases, including the validation that a decision cannot be recorded without a name, a rationale, or a
report — and that an unexplained pattern keeps *intent* confidence low.

`test_rbac.py` drives the real app against MongoDB and resets the demo dataset first, so it is
repeatable. It signs in as each synthetic account and asserts that analysts see only their assigned
cases with identifiers masked, compliance sees everything unmasked and can escalate, admins manage
users and settings, role changes revoke sessions, suspended accounts cannot sign in, denied access
is audited, and the hospital scenario still works end to end under scoping.

`test_workflow.py` walks the full lifecycle — analyst report, compliance review, administrator
approval — and then the access model itself: the 25-word statement gate, the two decision tracks,
statements recorded in full whether or not a screen shows them, capability grants that lapse on
expiry, and the bank gateway (held requests, retried transport failures, partial releases, and a
request that lapses when the bank misses its response deadline).

`test_security.py` asserts the security invariants the platform claims: passwords and session tokens
are stored hashed and never echoed, authority comes from the permission matrix rather than the
request, no role reaches a route outside its set, masking happens before serialisation, the audit
trail is append-only over the API and names the actor, and the account lifecycle (lockout,
reinstatement, session revocation on role change) behaves. It is the regression floor for the
production plan in [SECURITY.md](SECURITY.md) — when a gap listed there is closed, its assertion
belongs in this suite.

`test_security_controls.py` asserts the application-layer controls installed by
[`backend/security/`](backend/security/__init__.py): every API response carries the hardening header
set (refusals and errors included), an unlisted origin is granted no CORS access, the request past a
rate budget is refused with 429 and `Retry-After` while a legitimate sign-in is unaffected, MongoDB
operator and prototype-pollution keys are rejected along with over-deep and oversized payloads, a
production environment refuses to boot with debug on or synthetic accounts present, and personal
data is scrubbed out of log output by value and by field name. Every check asserts that a control
*blocks something*, not merely that it is installed.

## Production Path

This is a demonstration build, and the gap between it and a production deployment is written down
rather than implied: see **[SECURITY.md](SECURITY.md)** for the threat model, the controls that are
already enforced (and tested), the gap register, and the phased roadmap mapped to the DPDP Act 2023,
RBI directions and FIU-IND reporting.

When you have bank partnerships, swap the mock APIs:
1. Replace the `services/mock_banks.py` handlers with real API calls — and the bank gateway's lazy
   sweep with a durable queue, mutual TLS and signed payloads (G-14)
2. Swap `/api/auth/login` for your identity provider (OIDC/SAML) and map roles to the existing
   permission matrix — `services/users.py` is the only file that would change
3. Close the blocking gaps in SECURITY.md §6 before any real customer data is processed
4. Keep the same case workflow and explainability layer
