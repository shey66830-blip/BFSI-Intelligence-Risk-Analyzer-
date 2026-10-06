# Context Guard — Architecture

**What this is:** a single reference for how the system is put together — the stack, the
runtime topology, every data store, every integration, the security layer, the test matrix,
and what each module exists for. Read it alongside
[`SECURITY.md`](SECURITY.md) (the gap register) and
[`ROADMAP.md`](ROADMAP.md) (what is delivered vs. planned).

**Audience:** anyone who needs to land a change without guessing where it lives — an
engineer, a reviewer, or a future you.

**How to read it:** start at §1–§3 for the whole shape, then jump to the layer you are
touching. Every module lists *what it is for* and *what it is not for*, so a new file does
not silently duplicate a decision that already exists somewhere else.


## 1. The stack in one paragraph

Context Guard is a **consent-driven, privacy-aware financial risk-intelligence and
investigation platform**. It scores and routes transactions, runs a 12-stage investigation
pipeline, produces explainable analyst reports for compliance review, governs access to
restricted subject information through time-limited authorisations, and keeps a tamper-evident
audit trail.

It is built as **two processes that speak JSON over HTTP**:

| Layer | Technology | Role |
|---|---|---|
| Backend | Python 3 + **Flask** 3.0.0, **pymongo** 4.6.1, **python-dotenv**, **python-dateutil**, **flask-cors** 4.0.0, **bson** | API authority: identity, permissions, scoring, pipeline, reports, access governance, audit |
| Frontend | **React** 18.2, **Vite** 5.0.8, **recharts** 3.10.1, **vis-network** 9.1.9 / **vis-data** 7.1.9 | The console: dashboard, case workbench, graph, reports queue, access requests, admin |
| Database | **MongoDB** on `localhost:27017`, database `context_guard` | Document store for everything — transactions, cases, users, sessions, evidence, audit |
| Task runner | Node scripts: `scripts/test.mjs`, `scripts/dev.mjs`; root `package.json` is only a task runner | Runs the suites; starts the dev servers |

There is **no backend `package.json`** — the backend is plain Python. The root
`package.json` is a thin task runner; the real frontend manifest is `frontend/package.json`.
`python-dateutil` is listed in the known deps; the actual `requirements.txt` is not present
in the repo, so the Python environment is assumed to be installed by hand or by an external
pinning step.


## 2. Runtime topology

```
                     ┌─────────────────────────────────────────────┐
                     │                  Browser                      │
                     │  React 18 · Vite dev server (:3000)          │
                     │  recharts (KPIs, area chart, bar chart)      │
                     │  vis-network (entity network graph)          │
                     │  RoleContext (session + permissions in RAM)   │
                     └────────────────────┬────────────────────────┘
                                          │  fetch("/api/…")  JSON
                                          │  Bearer token     (localStorage, cg_token)
                                          ▼
                     ┌─────────────────────────────────────────────┐
                     │                 Flask API  (:5000)           │
                     │  app.py  →  create_app()                    │
                     │  middleware.py  →  session + authority       │
                     │  security/     →  install(app)  (L1–L6)     │
                     │  routes/       →  12 blueprints              │
                     │  services/     →  domain + privacy + audit   │
                     │  models/       →  collection CRUD            │
                     │  security/     →  classification + logguard  │
                     └────────────────────┬────────────────────────┘
                                          │  pymongo
                                          ▼
                     ┌─────────────────────────────────────────────┐
                     │                  MongoDB                      │
                     │  host: localhost:27017                        │
                     │  db:    context_guard                         │
                     │  20 collections (see §4)                      │
                     └─────────────────────────────────────────────┘

A third, simulated partner sits outside the platform:

   Flask  ──>  bank_gateway.submit()  ──>  (simulated bank consent desk)
                                            services/mock_banks.py
                                            services/bank_review.py
                                            bank_reports / access_requests collections
```


## 3. The two processes

### 3.1 Backend — `backend/`

Single Flask app, created once by `create_app()` in `app.py`. On startup it:

1. Builds the app, registers the **12 route blueprints** (§5.1).
2. Calls `security.install(app)` — one line that wires every application-layer control
   (§7.1).
3. Lazy-opens MongoDB via `get_db()` in `config.py` (a singleton; indexes created on first
   call).
4. Seeds demo data if the database is empty (`services.seed`, `services.seed_access`).
5. Asserts boot posture (`security.posture.assert_posture`) — refuses to start in production
   with debug on, an unauthenticated local DB, or synthetic accounts present.

Entry points:

- `backend/app.py` — the app. Also the boot sequence and the one place blueprints are
  registered.
- `backend/config.py` — MongoDB URI/DB, port, debug flag, organisation name, bank-gateway
  defaults, risk thresholds (`ANOMALY_THRESHOLD=0.35`,
  `INVESTIGATION_THRESHOLD=0.65`), the three simulated banks.
- `backend/middleware.py` — the authority layer: session extraction, `@login_required`,
  `@requires_permission`, `can()`, `case_access()`, `load_case()`, scope enforcement.
- `backend/jobs.py` — a lazy sweep (bank-response-deadline expiry). Documented as such; the
  roadmap wants a real job runner instead.

### 3.2 Frontend — `frontend/`

A React 18 single-page app, built by Vite.

- **Entry:** `frontend/src/main.jsx` mounts `<App />` into `#root`, imports the global styles.
- **App shell:** `frontend/src/App.jsx` owns the view state (`view` string), the session
  restoration side-effect, the case-selection and graph-loading handlers, and the permission
  gate that renders `<NotPermitted>` when a view's required permission is missing.
- **Role context:** `frontend/src/context/RoleContext.jsx` — `RoleProvider` holds `user`,
  `booting`, `notice`; exposes `can(permission)`, `signIn`, `signOut`, and a `roleConfig`
  with presentation metadata per role. Authority itself comes from the backend; this context
  only drives the *interface* (which views to offer, which labels to show).
- **API layer:** `frontend/src/api.js` — one `request()` helper, `get()`/`send()` wrappers,
  and one named function per workflow. All calls go to `API_BASE = '/api'`, which Vite proxies
  to Flask during dev. 401s are handled centrally by `setUnauthorizedHandler`.
- **Components:** 26 components under `frontend/src/components/`. See §6.1 for the view map.
- **Lib:** `frontend/src/lib/format.js` + `format.test.js` — shared formatting helpers, the
  only frontend unit test file.
- **Styles:** `frontend/src/styles/global.css` — the entire visual theme, dark by default.
- **Shell:** `frontend/index.html` (Vite entry, with a no-referrer meta for case URLs),
  `frontend/vite.config.js`.

The frontend has **no dedicated router library** — navigation is a `view` state string in
`App.jsx`. Each view is one component; case detail is one component with tabbed sub-views.


## 4. Data — MongoDB collections

All persistence is in one MongoDB database, `context_guard`. The indexes in `config.py` are
the real schema hints. The collections:

| Collection | What it holds | Who writes it | Notes |
|---|---|---|---|
| `users` | Accounts: username, email, hashed password, role, status, `is_synthetic` | `services.users.ensure_users`, admin user management | Unique on username and (sparse) email; role drives the permission matrix |
| `sessions` | Opaque 32-byte token → SHA-256 digest, user_id, expiry | auth login/logout | Unique index on `token_hash`; expiry enforced in middleware |
| `settings` | Org settings doc (`id: "org_settings"`): demo_mode, bank latency/deadline/failure rate, thresholds | settings routes, seed | Reads by `services.settings.get_settings` |
| `cases` | Investigations: id, title, description, status, score, assigned_to, bank_ids, entity_ids, total_volume, transaction_count, pipeline_trace | pipeline, case routes, seed | Indexed on status, assigned_to, id; the spine of the product |
| `transactions` | Financial transactions: case_id, entity_id, bank_id, amount, timestamp, and PII-bearing fields | seed, models | PII-masked on release; indexed on case_id, entity_id, bank_id, timestamp |
| `entities` | People/organisations involved: id, name, bank_id, identifiers | seed, models | Upserted; graph engine and entity profile read from here |
| `devices` | Device records tied to entities | seed | |
| `bank_reports` | Bank-held context released through the gateway | bank_gateway, models | Indexed on case_id; released per authorisation, not stored in bulk |
| `decisions` | Case decisions recorded at the decision stage | pipeline, models | Latest decision per case is the one that matters |
| `graph_edges` | Relationships between entities (source, target, edge_type, weight) | graph_engine | Indexed on (source, target), edge_type; the network graph reads from here |
| `case_evidence` | Per-case vault items: folders, versions, access_level | evidence routes, seed | access_level gates visibility; restricted/compliance-only items protected |
| `analyst_reports` | Report drafts: versions, status, analyst_id, case_id | reports routes | Versioned; submit/amend/review workflow |
| `investigation_updates` | Case updates: title, description, type, acknowledged_at | investigation routes, updates service | Indexed on case_id + created_at; acknowledgement workflow |
| `case_notes` | Internal notes on a case, resolvable | investigation routes, notes service | |
| `case_transaction_relevance` | One relevance flag per (case, transaction) | investigation routes | Unique on (case_id, transaction_id); the relevance screen writes here |
| `access_requests` | Requests for restricted subject information or bank-held records | access routes, bank_gateway | Status lifecycle: requested → awaiting_bank / approved / rejected / clarified; indexed on case_id, status, requested_by |
| `access_authorizations` | Time-limited grants to view restricted information | access_service | Indexed on granted_to, expires_at; revoked early via `/revoke`; admin is not exempt from the gate |
| `restricted_subject_information` | Unmasked PII about investigation subjects | admin-only add route, access_service release | Indexed on case_id; **the most sensitive collection** — released only via an active authorisation, masked otherwise |
| `notifications` | Per-user notifications: type, title, body, link, case_id, read_at | updates service, notify_roles | Indexed on user_id; link drives case/navigation jumps in the frontend |
| `audit_log` | Every consequential action: who, what, target, result, timestamp, case_id, resource_type, hashed | `services.audit.record` (called by almost every route) | The accountability backbone; append-only over the API; hashed into a chain |
| `audit_chain` | One doc (`_id: "audit"`) holding seq, head, genesis — the chain anchor | `_append_to_chain`, `_ensure_chain` | Updated by compare-and-swap; `verify()` recomputes against it |

There is no separate "transaction" collection beyond `transactions`; `models/__init__.py`
is the CRUD layer for the core domain objects (transactions, entities, cases, bank_reports,
decisions, graph_edges), and each route blueprint layers its own workflow on top.


## 5. Backend — the API

### 5.1 The 12 blueprints

Registered in `app.py` in this order:

| Blueprint | Module | What it is for |
|---|---|---|
| `auth_bp` | `backend/routes/auth.py` | Sign-in, sign-out, `/me`, demo-accounts. The identity surface. |
| `cases_bp` | `backend/routes/cases.py` | Case list/detail, status change, transactions, entities, banks, **dashboard stats**, health. The core read surface plus the KPI feed. |
| `pipeline_bp` | `backend/routes/pipeline.py` | Pipeline flow definition, run a case, record a decision. The 12-stage engine's API face. |
| `graph_bp` | `backend/routes/graph.py` | Entity graph, entity detail + profile + anomalies, path, clusters. What the graph view asks for. |
| `ingest_bp` | `backend/routes/ingest.py` | `/pipeline/ingest` — submit a scenario to seed a case through the pipeline. |
| `admin_bp` | `backend/routes/admin.py` | Users, settings, audit-logs, system-status, audit-integrity, threshold backtest. The privileged surface. |
| `audit_bp` | `backend/routes/audit.py` | `/api/audit-logs` — the trail read surface (paged, filtered). |
| `reports_bp` | `backend/routes/reports.py` | Analyst/compliance report lists, per-case reports, submit/amend/clarification/review. The report lifecycle. |
| `evidence_bp` | `backend/routes/evidence.py` | Per-case evidence vault: list, add, baseline, get, provenance, update, supersede, timeline. |
| `access_bp` | `backend/routes/access.py` | Access requests, authorisations, restricted reads, subject-information submission, locked-resources, statements. The access-governance surface. |
| `notifications_bp` | `backend/routes/notifications.py` | Notifications, mark-read, read-all, compliance updates, case updates, acknowledge. |
| `investigation_bp` | `backend/routes/investigation.py` | Notes, resolve-note, relevant-transactions, relevance. The investigation note/relevance surface. |

Plus one standalone route in `app.py`: `GET /api/health` (the health check).

### 5.2 What the API actually does, by workflow

- **Identity:** login exchanges credentials for an opaque token (stored only as a SHA-256
  digest); `/me` restores the session; logout deletes it; demo-accounts is a dev-only convenience
  that is refused at boot in production.
- **Cases:** list is scoped by role — analysts see assigned cases only, compliance sees all,
  admin sees all; detail includes score, status, bank/entity assignment, transaction count,
  volume, pipeline trace, restricted-category count.
- **Pipeline:** a read-only flow definition (12 stages, each with actor, title, description) and
  a run action that advances a case through identification → bank requests → correlation →
  network expansion → drafting → risk assessment → decision.
- **Graph:** an entity-level behavioural graph (nodes = entities + devices + counterparties,
  edges = co-occurrence/relationships), per-entity profile, per-entity anomalies, shortest path,
  clusters.
- **Reports:** analysts draft and submit; compliance reviews, amends, requests clarification;
  reports are versioned; compliance-only and restricted evidence levels are protected.
- **Evidence:** a per-case vault with folders, versions, access levels; provenance tracks origin/
  actor/source; restricted and compliance-only items are gated.
- **Access governance:** a request for restricted subject information names categories; it is
  approved/rejected/clarified; an approval creates a time-limited authorisation; the actual read
  at `/api/restricted/<case_id>` checks that authorisation and releases masked-or-unmasked data
  accordingly. **Admin is not exempt** — `restricted:view` is not in any role, and reading
  restricted data always needs a live, case-scoped, expiring authorisation.
- **Bank channel:** a request for bank-held records is submitted to the simulated consent desk
  (`bank_gateway.submit` + `mock_banks`), held with a response deadline, retried on transient
  failure, and lapses when the window closes. The decision itself is the bank's
  (`bank_review.review`); the gateway only carries it and records every step in the audit trail.
- **Notifications:** per-user, with a `link` field that the frontend turns into a navigation jump
  (case:, restricted:, access:).
- **Admin:** user CRUD, role/scenario assignment, settings, the audit trail read, the
  **audit-integrity verification endpoint** (`/api/admin/audit-integrity` → recomputes the chain),
  the threshold backtest (replay demo scenarios at candidate thresholds, apply the chosen one).


## 6. Frontend — the console

### 6.1 View map (`App.jsx` → component → what you do there)

| View (`view` string) | Component | Permission gate (`VIEW_PERMISSIONS`) | What it is for |
|---|---|---|---|
| `dashboard` | `Dashboard.jsx` | none (everyone) | KPI cards (delta + movement chips), dual-series area chart with 24h/7d/30d control, Recent Alerts rail, case cards; the landing workspace |
| `case` | `CaseDetail.jsx` | none (scope-gated by backend) | Tabbed case workbench: Pipeline, Transactions, Bank Reports, Network Graph, Analyst Report, Evidence Vault, Updates, Timeline, Restricted Info; score + status + assignment header |
| `graph` | `GraphView.jsx` | `graph:view` | Entity network graph (vis-network), entity detail, path, clusters, anomalies |
| `reports` | `ReportsQueue.jsx` | `reports:create` | Report list, draft/submit/ review workflow |
| `updates` | `InvestigationUpdates.jsx` | `['reports:review', 'updates:post']` | Cross-case investigation update feed (compliance/admin) |
| `access` | `AccessRequests.jsx` | `['access:request', 'access:approve']` | Access request list, create/request, approve/reject/clarify, authorisations, restricted read |
| `audit` | `AuditLog.jsx` | (admin/compliance surface) | Paged, filtered audit trail read |
| `users` | `UsersAdmin.jsx` | `users:manage` | User CRUD, role/scenario assignment |
| `settings` | `SettingsPanel.jsx` | `settings:manage` | Org settings: bank gateway behaviour, risk thresholds, demo mode |
| `status` | `SystemStatus.jsx` | `system:status` | System-status dashboard (security posture, audit-integrity, queue depth) |

The permission gate is **defence-in-depth, not the authority**: `App.jsx` hides the view from
the interface; `middleware.py` enforces the same permission on every backend call. A caller
cannot reach the data by skipping the UI.

### 6.2 What the frontend uses, and what for

| Tool | Used by | For |
|---|---|---|
| **React 18** | everything | Component tree, state, effects |
| **Vite 5** | build + dev server | Bundling, HMR, `/api` proxy to Flask in dev |
| **recharts** | `Dashboard.jsx`, `CaseDetail.jsx` | KPI area chart (solid + dashed dual series), bar chart (bank volume), chart legend/controls |
| **vis-network 9 + vis-data 7** | `NetworkGraph.jsx`, `GraphView.jsx` | Interactive entity network graph (nodes/edges, physics, hover) |
| **RoleContext** | every view component | Session identity, `can()` permission checks, role presentation metadata; drives the view gate and labels |
| **api.js** | every data component | One `fetch`-based client; central 401 handling; one function per workflow |
| **global.css** | everything | The entire dark theme, component chrome, status chips, badges, flash messages, KPI/table styles |

The frontend stores the session token in **`localStorage` under the key `cg_token`** — this is
the documented residual behind **G-08** (an XSS becomes full session takeover). The response
hardening (strict CSP on every API response) and the document policy (static-host config) are
the partial mitigation; the full fix is httpOnly/SameSite cookies + CSRF, which is still open.


## 7. Security layer

### 7.1 Application-layer controls — `backend/security/`

All wired by one call: `security.install(app)` in `app.py`. Order is deliberate: CORS first
(so preflights are answered), validation next (cheap structural rejection before budget is spent),
rate-limit after, headers last (so they decorate every response above), logguard output-side.

| Layer | Module | What it enforces | What gap it closes |
|---|---|---|---|
| L1 | `headers.py` | After-request hardening on every API response: nosniff, frame-deny, strict CSP (`default-src 'none'`), no-referrer, COOP/COEP, Permissions-Policy, no-store on personal data, HSTS only in production, strip `X-Powered-By` | G-08 (partial — token still in localStorage; full fix is cookies+CSRF) |
| L2 | `cors.py` | Explicit origin allowlist via flask-cors; never `*`; denied origins get **no** CORS headers; credentials never allowed from an untrusted origin; production must name origins or boot is refused | **G-01 (Closed)** |
| L3 | `ratelimit.py` | Sliding-window per-IP, per-auth, per-account, and per-write budgets; 429 + `Retry-After`; `X-RateLimit-*` advisory headers; `X-Forwarded-For` only when `TRUST_PROXY_HEADERS=true` | **G-07 (Partly)** — closes lockout-as-DoS; residual is per-process counters (G-18) |
| L3 | `validation.py` | Central rejection of `$`-prefixed keys (MongoDB operators), `__proto__`/`constructor`/`prototype` (prototype pollution), depth > 12, strings > 200k, body > 1 MiB (Flask 413) | G-10 (Partly) — closes the exploitable half; residual is per-route unknown-field rejection |
| L3 | `posture.py` | **Refuses to boot** production with debug on, unauthenticated local MongoDB, unset `ALLOWED_ORIGINS`, demo_mode on, or synthetic accounts present | G-02 (Partly), G-04 (Partly) |
| L6 | `classification.py` | Data-class registry (`PII_FIELDS` + `RETENTION_DAYS`), field classifier, `assert_registry_intact` so a new field is a reviewed act | G-11 (Partly) — policy declared; residual is the sweeper + data-principal path |
| L6 | `logguard.py` | Scrubs PII from logs by value (email, PAN, phone, long-digit runs, IPv4) and by declared field name; handles deferred `%s` messages without breaking `msg % args` | G-11 (Partly) — closes "PII in logs"; residual is backup classification + erasure |

The package deliberately **does not** re-implement credential hashing, hashed sessions, the
permission matrix, capability grants, separation of duties, response masking, or the audit chain —
those live in `services/` and are guarded by `test_security.py`. Duplicating them here would create
two sources of truth for one decision, which is how a control silently diverges from its copy.

### 7.2 The authority layer — `middleware.py`

This is where every backend decision about *who may do what* is made:

- `extract_token()` / `_authenticate()` — pull the Bearer token, resolve the session, populate
  `g.user`, `g.grants`, `g.permissions`. Authority has two sources: the role in the permission
  matrix, and any capability released by a live authorisation.
- `@login_required` — 401 unless a valid session.
- `@requires_permission(permission)` — 401/403 unless the role (or a released grant) holds it.
- `can(permission)` — role permission or a capability grant.
- `case_access()` / `load_case()` / `visible_case_ids()` — scope enforcement: analysts see only
  their assigned cases; `cases:view_all` (compliance/admin) sees all; every case fetch is scoped.

Handlers **never** read authority from the request body — they read `g.user`/`g.permissions`.

### 7.3 Privacy — `services/privacy.py` + `security/classification.py`

- `services/privacy.py` — per-caller masking decisions: `mask_name`, `mask_account`, `mask_email`,
  `mask_device`, `redaction_level(user, settings)`, `_released(user, permission)`. Answers
  *"should this value be masked for this caller?"* for one response.
- `security/classification.py` — the registry that answers *"is this field personal data, and how
  long may you keep it?"* Used by tests and by the audit layer to describe a record without
  reproducing it.

Masking happens **before serialisation** — an analyst's payload is asserted to contain no raw
identifier from the underlying data.

### 7.4 Accountability — `services/audit.py`

Every consequential action is recorded with the acting identity, target, result, timestamp, case_id,
resource_type, and resource_id. Two things make it defensible:

1. **Append-only over the API** — routes can write and read it, never edit or delete it.
2. **Tamper-evident hash chain** — each entry carries `seq`, `prev_hash`, and its own
   `entry_hash` over its full meaning; appends use compare-and-swap on the chain head, so two
   concurrent writers cannot claim the same link; `verify()` recomputes the chain and reports the
   first entry that does not reproduce (edited, removed, or inserted after the fact).

`GET /api/admin/audit-integrity` is the live verification surface. This closes **G-05** in
SECURITY.md — it was already implemented (the register had listed it as blocking).


## 8. The data flows that matter

### 8.1 A case from anomaly to decision

1. A case exists (seeded, or created by the pipeline ingest scenario).
2. An analyst opens it; the backend scopes the read to assigned cases and masks PII.
3. The analyst runs the pipeline — `pipeline_bp` advances the case through the 12 stages,
   calling `bank_gateway` for bank requests, `graph_engine` for network expansion, `services.reports`
   for drafting.
4. Bank requests leave the platform — `bank_gateway.submit` → `mock_banks` → held with a response
   deadline → settled/awaiting/failed → lapses when the window closes.
5. The analyst drafts a report (`reports:create`), submits it (`reports:submit`) — it enters the
   compliance review queue.
6. Compliance reviews, amends, requests clarification; the report moves toward a determination.
7. A decision is recorded at the decision stage (`cases_bp.decision`), with rationale.

### 8.2 Restricted information — the access-governance flow

1. An analyst (or compliance) requests restricted subject information for a case, naming categories
   (`POST /api/access-requests`).
2. The request is approved/rejected/clarified by someone with `access:approve`.
3. An approval creates a time-limited `access_authorizations` grant, case-scoped, expiring.
4. A read at `GET /api/restricted/<case_id>` checks that grant; if valid, releases the data
   (masked for analysts, unmasked for compliance within scope); if not, returns the lock.
5. **Admin is not exempt** — the gate is the authorisation, not the role.

### 8.3 The audit trail — the accountability backbone

Every workflow above calls `services.audit.record()` at consequential points: logins, denials,
case opens, transaction views, graph views, evidence adds/accesses, report creates/submits/amends/
reviews, access requests approved/rejected, restricted reads/denials, decisions, permission changes.
Each entry is hashed into the chain. The trail is the one thing a supervisor or regulator reads;
if it can be edited, nothing else can be trusted — which is exactly why it is hashed and
append-only.


## 9. Graph and visualisation subsystems

Two distinct visualisation concerns, with two distinct libraries:

- **Charts (recharts):** `Dashboard.jsx` uses `AreaChart`/`Area` for the dual-series KPI chart
  (solid = transactions, dashed = volume/value), with a 24h/7d/30d segmented control and legend;
  `BarChart`/`Bar` for the bank-volume chart; tabular KPI numbers with delta + movement chips.
- **Network graph (vis-network + vis-data):** `NetworkGraph.jsx` (inside `CaseDetail`) and
  `GraphView.jsx` (standalone screen) both dynamically import `vis-network/standalone` and render
  an interactive entity graph — nodes (entities/devices/counterparties), edges (relationships with
  weight), physics, hover. `graph_engine.build_entity_graph()` builds the node/edge structure from
  transactions in the lookback window; `expand_network()` widens scope up to `MAX_HOPS_CAP`.


## 10. Test matrix

### 10.1 Backend suites

Run by `node scripts/test.mjs` (or `npm test`). All Python suites need
`PYTHONIOENCODING=utf-8` so the ₹ and box-drawing characters survive the Windows console.

| Suite | File | What it covers | Static `check(` sites | Reported count |
|---|---|---|---|---|
| Pipeline | `backend/test_pipeline.py` | 12-stage investigation pipeline | 96 (loop-generated) | "All pipeline checks passed." |
| RBAC / privacy | `backend/test_rbac.py` | authentication, roles, masking, session, authorisation boundaries | 78 (loop-generated → 81) | 81 passed, 0 failed |
| Workflow | `backend/test_workflow.py` | reports, evidence, access, audit, bank gateway | 199 (loop-generated → 209) | 209 passed, 0 failed |
| Security invariants | `backend/test_security.py` | credential storage, session handling, mandatory auth, authorisation boundaries, permission-matrix invariants, masking, audit integrity + hash chain, account lifecycle, demo kill switch | 62 | 62 passed, 0 failed |
| Security controls | `backend/test_security_controls.py` | response hardening, origin trust, throttling semantics, input validation + its false-positive check, boot posture, classification/retention, log scrubbing | 52 | 52 passed, 0 failed |
| **Documentation drift** | `backend/test_documentation.py` | the gap register, roadmap marks, README counts, runner list, local links against the code | 24 | 46 passed, 0 failed |

Two notes on the counts:

- For `test_rbac`, `test_workflow`, and `test_pipeline`, **the real count comes from running the
  suite and parsing its own `N passed, M failed` line** — the static `check(` site count is lower
  because those suites generate checks inside loops. Any check that counts call sites would silently
  miss drift in exactly those suites.
- `test_documentation.py` deliberately does **not** add its own checks to the documented total — a
  number that includes its own verifier cannot be computed honestly. It verifies the other counts.

### 10.2 Frontend suite

`frontend/src/lib/format.test.js` — 7 tests, run by `node --test frontend/src/lib/*.test.js`
inside the runner when a full `npm test` fires. No framework dependency to install; Node's built-in
runner is enough.

### 10.3 What "all green" actually means right now

As of the last verified gate (captured in `gate_20261006T230640.out` and
`build_20261006T230640.out`):

- `npm test` → **7 suites, all passed** (pipeline, rbac 81, workflow 209, security 62, controls 52,
  **docs 46**, frontend 7), exit 0.
- `npm run build` → exit 0; CSS ~80.65 kB, JS chunks ~621 kB + ~720 kB (chunk-size warning only,
  pre-existing).
- Coverage proof: no product source file (`.py`/`.jsx`/`.mjs`/`.html`/`.css`/`.json`) is newer than
  that gate log — so the green run reflects the shipped code. (The drift suite itself and the dist/
  artifacts are excluded from that check by construction.)

### 10.4 What the test matrix does **not** cover

- No dedicated component 렌더링 / integration tests for the React tree (the frontend suite is the
  formatting helpers only).
- No contract tests against a real bank (the bank channel is simulated — G-14).
- No penetration test, no independent review (G-16).
- No load/DoS test beyond the unit assertions on the rate-limiter semantics (the limiter's
  per-process limit is stated, not load-tested — G-18).


## 11. What is used for what — module map

### 11.1 Backend — by responsibility

| Responsibility | Where it lives | What it is for | What it is NOT for |
|---|---|---|---|
| App boot, blueprint registration | `app.py` | Create the app, register 12 blueprints, call `security.install`, seed if empty, assert posture | Business logic — that lives in services |
| Config, MongoDB, indexes, org/channel/threshold defaults | `config.py` | One place for every environment default; lazy DB singleton; indexes created on first call | Runtime authority — that's middleware |
| Session + authority + scope | `middleware.py` | Extract token, resolve session, populate `g.user`/`g.permissions`, `@login_required`, `@requires_permission`, `can()`, case scope | Business logic or response formatting |
| Permission matrix + user lifecycle | `services/users.py` | `ROLE_PERMISSIONS`, `has_permission`, `permissions_for`, hash token, public_user, ensure_users, password policy, lockout, session revocation | Privacy masking or audit |
| Privacy masking (per-caller) | `services/privacy.py` | `mask_*`, `redaction_level`, `_released` — should this value be masked for this caller? | Field registry or retention (that's classification) |
| Data classification + retention registry | `security/classification.py` | `PII_FIELDS`, `RETENTION_DAYS`, `classify`, `assert_registry_intact` — is this field personal, and how long may you keep it? | Per-response masking (that's privacy.py) or log scrubbing |
| PII scrubbing in logs | `security/logguard.py` | `ScrubFilter` on app/werkzeug loggers; value + field-name passes; preserves shape | Guarantee (it's a safety net; classification is primary) |
| Input validation (central) | `security/validation.py` | Reject `$` keys, prototype keys, depth/size bombs on every `/api` request | Per-route schema enforcement (that's residual G-10) |
| Throttling | `security/ratelimit.py` | Sliding-window budgets per IP/auth/account/write; 429 + Retry-After | Shared counters across workers (not yet — G-18) |
| Response hardening | `security/headers.py` | After-request headers on every API response | Document CSP (that's the static host config) |
| CORS / origin trust | `security/cors.py` | Explicit allowlist, never `*`; denied origins get no headers | Credentials from untrusted origins (never allowed) |
| Boot posture guard | `security/posture.py` | Refuse production boot with debug/demo/unauthenticated-DB/unset-origins | Runtime request handling (it's boot-time) |
| Case status workflow | `services/workflow.py` | 12 stages, transitions, role-gated next-states, progress fraction | Pipeline execution (that's pipeline routes + services) |
| Pipeline stages + run | `routes/pipeline.py`, `services/` | Flow definition, run a case, record a decision | Graph or reports |
| Graph engine | `services/graph_engine.py` | `build_entity_graph`, `expand_network` (up to `MAX_HOPS_CAP=5`), `build_behavioral_profile`, `resolve_depth` | Rendering (that's vis-network in the frontend) |
| Bank channel (carriage) | `services/bank_gateway.py` | Submit, hold, retry, lapse on deadline; record every step | The decision (that's bank_review) |
| Bank decision (simulated) | `services/bank_review.py` | Reviewer-for, consent evidence, review/release | Real bank integration (not built — G-14) |
| Bank responses (simulated) | `services/mock_banks.py` | Fake bank responses for the demo flows | Real bank integration |
| Reports lifecycle | `services/reports.py`, `routes/reports.py` | Draft, submit, amend, review, clarification; versioning | Compliance workflow state (that's workflow) |
| Evidence vault | `services/evidence.py`, `routes/evidence.py` | Add, baseline, get, provenance, update, supersede, timeline; access-level gating | Restricted subject information (that's access) |
| Access governance | `services/access.py`, `routes/access.py` | Requests, authorisations, restricted reads, subject-information submission, locked resources, statements | Bank-held records (those go through the gateway) |
| Investigation notes/relevance/updates | `services/notes.py`, `services/updates.py`, `routes/investigation.py` | Notes, resolve, relevance flags, updates, acknowledge, notifications | Report lifecycle (separate) |
| Audit trail + chain | `services/audit.py` | `record`, hash chain, CAS appends, `verify`, query, security_events | Privacy masking (separate) |
| Seeding / demo data | `services/seed.py`, `services/seed_access.py`, `services/reset.py` | Generate cases/transactions/entities/evidence/restricted info; reset demo state | Production data (never; G-04) |
| Models (CRUD) | `models/__init__.py` | Collection CRUD for transactions, entities, cases, bank_reports, decisions, graph_edges | Domain workflow (that's services) |
| Jobs / sweep | `jobs.py` | Lazy sweep for bank-response-deadline expiry | A real job runner (not built — Phase 8) |

### 11.2 Frontend — by responsibility

| Responsibility | Where it lives | What it is for |
|---|---|---|
| App shell + view state + permission gate | `App.jsx` | `view` string, session restore side-effect, case/graph handlers, `VIEW_PERMISSIONS` gate → `<NotPermitted>` |
| Session + role context | `context/RoleContext.jsx` | `RoleProvider`: user, booting, notice, `can()`, signIn/signOut, role presentation metadata |
| API client | `api.js` | One `fetch`-based client, central 401 handling, one function per workflow |
| Dashboard | `Dashboard.jsx` | KPI cards with deltas, dual-series area chart, alerts rail, case cards |
| Case workbench | `CaseDetail.jsx` + its tab components | Tabbed case view: pipeline, transactions, bank reports, graph, report, evidence, updates, timeline, restricted info |
| Graph | `GraphView.jsx`, `NetworkGraph.jsx` | vis-network entity graph; standalone + inline |
| Reports / access / admin / settings / status | `ReportsQueue.jsx`, `AccessRequests.jsx`, `UsersAdmin.jsx`, `SettingsPanel.jsx`, `SystemStatus.jsx` | Each privileged surface, gated by `VIEW_PERMISSIONS` |
| Audit / updates / timeline / locked / restricted / evidence / pipeline / transactions / bank request / analyst report | the remaining components | Each a focused view on one workflow |
| Formatting helpers | `lib/format.js` + `format.test.js` | Shared formatting; the only frontend unit tests |
| Theme | `styles/global.css` | The entire dark visual theme |

### 11.3 Infrastructure / tooling

| Thing | What it is for |
|---|---|
| `package.json` (root) | Task runner only: `dev`, `dev:api`, `dev:web`, `seed`, `build`, `test`, and the per-suite `test:xxx` shorthands |
| `scripts/test.mjs` | The test runner: spawns each Python suite with the right env, runs the frontend suite, exits non-zero on any failure |
| `scripts/dev.mjs` | Starts the dev servers (Flask + Vite) |
| `frontend/vite.config.js` | Vite config (HMR, proxy to Flask for `/api` in dev) |
| `frontend/index.html` | Vite entry; no-referrer meta so case URLs don't leak via Referer |
| `backend/security/web/security-headers.conf` | Reference static-host config (nginx/Caddy) for the document CSP — not deployed yet (G-19) |


## 12. What is not built yet (and is named there)

These are real gaps, stated in the register rather than hidden:

- **G-02 (Partly):** TLS + a real WSGI server behind it (the app refuses debug-in-production but
  does not terminate TLS itself).
- **G-03:** database authentication, network isolation, a least-privilege app DB role (any process
  reaching 27017 can still write — the chain would detect it, but it has already permitted it).
- **G-04 (Partly):** managed secret store; demo mode still defaults on for the demonstration.
- **G-05 (Partly):** the app DB user is not yet refused on `update`/`delete` against `audit_log`;
  the chain head is not anchored outside the database.
- **G-06:** encryption at rest.
- **G-08 (Partly):** token still in localStorage; full fix is httpOnly/SameSite cookies + CSRF (or
  short-lived access + refresh).
- **G-10 (Partly):** per-route rejection of unknown fields; response schemas asserting which fields
  are personal data.
- **G-11 (Partly):** a sweeper that acts on the retention windows; backup classification; the
  data-principal access/erasure path.
- **G-18:** rate-limit counters are per-process (multi-worker deployments need a shared store).
- **G-19:** the static-host document CSP is a reference config, not deployed.
- **G-09 (Open):** no dual control / break-glass for the most sensitive reads — an administrator can
  still read unmasked identifiers and restricted subject information alone. This is the one the
  roadmap specifically flags for closure.

Infrastructure gaps that code cannot close from inside this repo: database auth, encryption at rest,
SIEM export, supply-chain controls, a real bank contract, penetration testing.


## 13. One-line answer to "where does the project stand?"

A working, gated, security-hardened dark-console risk-intelligence platform — Flask API + React/Vite
UI + MongoDB — with 12 route blueprints, a 12-stage pipeline, per-role access scoping, masked PII on
release, a hash-chained append-only audit trail with a live integrity endpoint, a full application
security layer (headers, CORS, throttling, validation, posture, classification, log scrubbing), and
6 backend suites + 1 frontend suite + a documentation-drift suite that fails the build when the gap
register disagrees with the code. The UI is a Sentinel-grade dark dashboard with KPI deltas, a
dual-series area chart, a Recent Alerts rail, and a role-scoped navigation model. What remains is the
infrastructure and regulatory halves of the roadmap — TLS/WSGI, DB auth, encryption at rest, the
retention sweeper, the document CSP deployment, shared rate-limit counters, and dual control for the
most sensitive reads (G-09).
