# Context Guard — Security Plan

**Audience:** engineering and the sponsoring bank's information-security function.
**Purpose:** take this platform from a demonstration build to a deployment that can hold real
customer data, mapped to the Indian regulatory frame (DPDP Act 2023, RBI cyber/KYC directions,
PMLA and FIU-IND reporting).
**Companions:**
[`docs/security-architecture.md`](docs/security-architecture.md) — the layered design each control
fits into, and the corrected current-state audit. This file is the *register*; that one is the
*architecture*. Read them together.
[`backend/security/`](backend/security/__init__.py) — the application-layer controls, installed
with one call.
[`backend/test_security.py`](backend/test_security.py) and
[`backend/test_security_controls.py`](backend/test_security_controls.py) — the invariants that stop
a regression, so a control cannot be quietly weakened.

Run both security suites:

```bash
npm test                     # everything, incl. both security suites
npm run test:security        # the original invariants only
```

---

## 0. Reconciliation note (2026-10-06)

This register was reconciled against the code, not against its own earlier claims. It had drifted in
the way these documents always drift — in the safe direction (*"planned"* read as *"done"*) and in
the expensive direction (*"unbuilt"* read as *"fine"*). Three corrections:

1. **G-05 was listed as a blocking gap. It was already implemented.** `services/audit.py` carries a
   SHA-256 hash chain (`seq`, `prev_hash`, `entry_hash`) with compare-and-swap appends, a full
   `verify()` recomputation, and a live verification endpoint at `GET /api/admin/audit-integrity`.
   `test_security.py` already asserts it. Six weeks of "blocking" work was already on disk.
2. **The invariant count was wrong.** The document claimed 48 checks; the suite reports **62**.
3. **G-01 and G-07 are now closed, and G-02/G-04/G-10/G-11 are partly closed**, by
   `backend/security/`. Those closures are asserted by a second suite (**52 checks**).

The lesson worth keeping: a register that is not re-derived from the code will eventually describe a
different system than the one being defended.

### Status legend

| Mark | Meaning |
|---|---|
| ✅ **Closed** | True in the code today, and asserted by a test. |
| ◐ **Partially closed** | The application-layer half is done; a named residual remains. |
| ⬜ **Open** | Not true today. |

---

## 1. What we are protecting

| Asset | Where it lives | Why it matters |
|---|---|---|
| Restricted subject information | `restricted_subject_information` | Identity, contact, documents about an investigation subject. No determination of wrongdoing attaches to it. |
| Unmasked identifiers | transaction fields, entity names, account numbers | Personal data under DPDP; a leak is a notifiable breach. |
| Bank-held records | released through the gateway, never stored | The bank remains the custodian; we hold a copy only for the life of the authorisation. |
| Evidence vault | `case_evidence` | The material a decision rests on; integrity matters as much as confidentiality. |
| Access statements & capability grants | `access_requests`, `access_authorizations` | The record of *why* someone was entitled to act. Defence against insider over-reach. |
| Audit trail | `audit_log`, `audit_chain` | The single source of truth a supervisor or regulator reads. If it can be edited, nothing else can be trusted. The chain head is the anchor the trail proves against. |
| Credentials & sessions | `users`, `sessions` | The root of every other control. |

## 2. Trust boundaries

```
 ┌──────────────┐        HTTPS (bearer token)        ┌─────────────────────┐
 │ Browser      │ ─────────────────────────────────▶ │ Flask API           │
 │ (untrusted)  │   1. identity + capability grants  │ authority from      │
 └──────────────┘                                    │ g.user / g.permissions
        ▲                                            └──────────┬──────────┘
        │ no raw identifier is ever sent to a                   │ 3. queries
        │ session that is not entitled to it                    ▼
        │                                            ┌─────────────────────┐
        │                                            │ MongoDB             │
        │                                            │ users · sessions ·  │
        │                                            │ restricted · audit  │
        │                                            └─────────────────────┘
        │                                                     ▲
        │ 4. released records only                            │ 2. consent request
 ┌──────────────┐   (simulated today — see G-14)   ┌──────────┴──────────┐
 │ Admin console│ ────────────────────────────────▶│ Bank consent desk   │
 │ (privileged) │                                  │ (services/          │
 └──────────────┘                                  │  bank_gateway.py)   │
                                                   └─────────────────────┘
```

1. **Browser → API.** Untrusted. Authority is never read from the request body — handlers read
   `g.user` and `g.permissions`, which the middleware populates from the session and the live
   authorisations. This is what stops a client from claiming a role. **✅ Guarded.**
2. **API → Bank.** The platform holds no bank record; it asks, and the bank decides in writing
   (`services/bank_review.py`, carried by `services/bank_gateway.py`). **⬜ Simulated — G-14.**
3. **API → MongoDB.** The trail is append-only *over the API*, and the hash chain now makes a direct
   database edit **detectable** rather than silent (**✅ G-05**). What remains is that any process
   reaching port 27017 can still *write* — it just cannot do so unnoticed. **⬜ G-03.**
4. **Admin console.** Highest privilege. Configuration authority is deliberately *not* financial-data
   authority: the administrator cannot raise an access request and cannot bypass `restricted:view`.
   **✅ Guarded.**

## 3. Regulatory mapping

### DPDP Act 2023

| Obligation | How this platform addresses it | Status |
|---|---|---|
| Lawful purpose & consent before processing | A bank report is only requested for entities with an active consent record; the bank re-checks its own consent before releasing | ✅ In place |
| Purpose limitation & data minimisation | Locked items are released per request, scoped to a case, with the stated purpose recorded; nothing is pre-fetched | ✅ In place |
| Storage limitation | Every data class now has a declared retention window (`security/policy.py`), and the audit trail is configured to outlive what it describes. **Nothing acts on the window yet** | ◐ Policy declared, no sweeper — G-11 |
| Security safeguards | Server-side masking, role-based authority, hashed credentials, hashed sessions, audit of access and denial, **plus** throttling, strict origin trust, response hardening, input validation and log scrubbing | ✅ In place |
| Transparency to the data principal | Not built — there is no data-principal-facing notice or access/erasure request path | ⬜ G-11 |
| Breach notification to the Board & principals | Not built — no runbook, no detection-to-notification clock | ⬜ G-12 |
| Grievance redressal / DPO | Not built | ⬜ G-12 |

### RBI (cyber-security framework, KYC Master Direction, storage of payment system data)

| Expectation | Status |
|---|---|
| Identity & access management with least privilege and periodic review | Least privilege ✅; **no scheduled access review** — G-13 |
| Inventory of assets and data flows | ✅ §1–2 here, plus the classification registry in `security/classification.py`; no machine-readable export yet — G-16 |
| Encryption of sensitive data in transit and at rest | TLS only in a real deployment (G-02); **at rest still absent** — G-06 |
| Logging, monitoring and audit with tamper protection | ✅ Logging and **tamper protection** (G-05); SIEM export still absent — G-17 |
| Incident response, BCP and DR | Not built — G-12, G-16 |
| Cyber-incident reporting within the regulator's window (hours, not days) | Not built — G-12 |
| Data localisation | Deployment decision; not encoded in the code — G-15 |

### PMLA / FIU-IND

| Expectation | Status |
|---|---|
| Record retention (5 years) for transactions and KYC | Retention windows now declared at the 5-year horizon for C3/C4; **enforcement absent** — G-11 |
| Strictly confidential filing, no tipping-off | The decision path is audited and statements are `recorded_only`; there is no customer-facing channel — ✅ |
| Principal officer / designated director oversight | Not modelled — no role for it — G-13 |

## 4. Threat model

Ranked by the harm a realistic attacker achieves. Controls changed since the last revision are
marked **†**.

| # | Threat | Path | Current control | Residual |
|---|---|---|---|---|
| T1 | Credential stuffing / brute force | `/api/auth/login` | Hashed passwords, per-account lockout, generic errors, **† per-IP and per-account throttling with 429 + `Retry-After`** | Distributed, low-and-slow attacks still reach the lockout — G-13 |
| T2 | Session theft via XSS | token in `localStorage` | **† Strict CSP on every API response; site policy supplied for the static host**; masking limits what a stolen analyst token sees | Token still exfiltratable; no httpOnly cookie — G-08 |
| T3 | Privilege escalation by request manipulation | any route | Authority from `g.user`/`g.permissions` only | ✅ None found |
| T4 | Insider over-reach by an administrator | admin console | Separation of duties; `restricted:view` in no role | Admin still reads all unmasked data; no dual control — G-09 |
| T5 | Audit-trail tampering | direct DB access | **† Hash-chained with CAS appends and a verification endpoint** | Detectable, not prevented; no off-DB anchor — G-03 |
| T6 | Masking bypass / data exfiltration | case & transaction reads | Redaction before serialisation; **† a declared personal-data registry, so a new field is a reviewed act** | Free-text fields in future features could still leak — G-10 |
| T7 | NoSQL operator injection | JSON payloads | **† Central rejection of `$`-prefixed and prototype keys, plus depth and size caps** | Not per-route schema enforcement — G-10 |
| T8 | Bank channel spoofing / replay | gateway | Decision attributed to the bank identity | No mTLS, signing or nonce — G-14 |
| T9 | Cross-origin API use | CORS | **† Explicit origin allowlist; an unlisted origin receives no CORS headers** | ✅ Closed — G-01 |
| T10 | PII in logs, backups or analytics | audit `detail`, logs, DB backups | Audit visible only to `audit:view_all`; **† log filter scrubs personal data by value and by field name** | No backup classification policy — G-11 |
| T11 | Orphaned access after staff exit | sessions, grants | Role/status/password change revokes sessions | No joiner-mover-leaver review — G-13 |
| T12 | Supply-chain compromise | dependencies, images | None | No SCA, no pinned images, no image signing — G-16 |
| T13 | **† Denial of service via the lockout** | `/api/auth/login` | **† Per-account budget answers 429 before an attacker can spend a known analyst's five lockout attempts** | Per-process counters — G-18 |
| T14 | **† Flood / resource exhaustion** | any route | **† General, write and auth budgets; oversized bodies refused at 413** | Counters not shared across workers — G-18 |

## 5. Controls in place today

Each is enforced server-side and has a regression guard in one of the two security suites.

**Identity and authority** — enforced in `middleware.py` / `services/`

- **Credentials** — PBKDF2 via Werkzeug; no plaintext password field exists; hashes never leave the
  backend (`public_user()` strips them); the client is never sent a failure counter.
- **Sessions** — 32-byte opaque tokens, stored only as a SHA-256 digest; expiry recorded and
  enforced; forged, expired and signed-out tokens are refused; logout deletes the session.
- **Authentication** — every protected route answers 401 to an anonymous caller.
- **Authorisation** — the permission matrix is the only place authority is decided; no role reaches
  a route outside its set; `restricted:view` appears in no role and is released only by a live,
  case-scoped, expiring authorisation.
- **Separation of duties** — the approver of access requests cannot raise one; self-approval is
  refused; admin cannot bypass it.
- **Account lifecycle** — provisioning requires `users:manage`; weak passwords and unknown roles are
  refused; repeated failures lock an account; reinstatement is an admin action; a role change
  revokes existing sessions.
- **Enumeration** — a wrong password and an unknown user are indistinguishable.
- **Demo kill switch** — the synthetic accounts disappear when `demo_mode` is off.

**Privacy** — enforced in `services/privacy.py` and `security/`

- **Masking** — redaction happens before serialisation; an analyst's payload is asserted to contain
  no raw identifier from the underlying data.
- **Free-text redaction** — entity names embedded in case prose are masked, longest name first.
- **Classification** — a declared registry maps every personal field to a data class, so adding
  personal data is a reviewed edit rather than an oversight.
- **Retention policy** — a window per class, with the audit trail deliberately outliving what it
  describes.
- **Log scrubbing** — a filter on the application, request and root loggers removes personal values
  by shape (email, account number, PAN, phone, non-loopback IP) and by declared field name. It works
  on deferred `%s` messages, which is where the value actually hides.

**Accountability** — enforced in `services/audit.py`

- **Append-only over the API** — no delete/update/amend route exists.
- **Tamper-evident chain** — every entry carries its sequence number, its predecessor's hash and its
  own hash; appends use compare-and-swap so concurrent writers cannot claim the same link.
  `GET /api/admin/audit-integrity` recomputes the chain and names the first entry that fails to
  reproduce, distinguishing an edited entry from a removed one.
- **Denials and restricted reads** carry the acting identity and a `result`; an analyst's audit view
  is scoped to their own activity; statements are recorded in full with `recorded_only`.

**Perimeter** — enforced in `backend/security/`, installed by one call in `app.py`

- **Response hardening** — nosniff, frame-deny, `default-src 'none'` CSP, no-referrer,
  cross-origin isolation, a device-permission deny list, `no-store` on personal data, and no stack
  advertisement. Applied to refusals and errors, not only successes.
- **Origin trust** — an explicit allowlist, never a wildcard, via `security/cors.py`.
- **Throttling** — general, write and auth budgets, with a per-account budget that closes the
  lockout-as-DoS path, and a sliding window so a burst cannot be split across a boundary.
- **Input validation** — central rejection of MongoDB operator keys, prototype-pollution keys,
  deeply nested payloads and oversized bodies.
- **Boot posture** — the application **refuses to start** in a production environment with debug
  enabled, an unauthenticated local database, or a development origin allowlist.

## 6. Gap register

### Blocking — do not process live personal data until closed

| ID | Status | Gap | Why it matters | Fix |
|---|---|---|---|---|
| **G-01** | ✅ **Closed** | CORS allowed `origins: "*"` | Any web origin could call the API with a token it had obtained | Done: `security/cors.py` allowlist, asserted by `test_security_controls.py` |
| **G-02** | ◐ **Partly** | TLS, WSGI server and debug mode | The Werkzeug debugger is remote code execution if reachable | **Done:** the app now refuses to boot as production with debug on (`security/posture.py`). **Remaining:** serve behind gunicorn/waitress with TLS termination |
| **G-03** | ⬜ Open | Database has no authentication or network isolation | Any process reaching 27017 can write every collection — including rewriting the trail, which the chain would then *detect* but has already permitted | SCRAM auth, loopback/cluster binding, per-service credentials, **and an app DB role denied `update`/`delete` on `audit_log`** |
| **G-04** | ◐ **Partly** | Secrets in the environment; demo passwords served | `MONGO_URI` in plain env; `/api/auth/demo-accounts` returns working credentials | **Done:** boot is refused as production with `demo_mode` on or synthetic accounts present (`security/posture.py`). **Remaining:** secrets from a managed store; `demo_mode` still defaults on for the demonstration |
| **G-05** | ◐ **Partly** | Audit trail was append-only by convention, not construction | An edit made directly in MongoDB — the insider's move — was undetectable | **Done:** hash chain, CAS appends, `verify()`, `/api/admin/audit-integrity`, and test coverage. **Remaining:** the app's DB user is not yet refused on `update`/`delete`, and the chain head is not anchored outside the database (G-03, G-17) |
| **G-06** | ⬜ Open | No encryption at rest | Restricted subject information and unmasked identifiers sit in plaintext on disk and in backups | Volume/disk encryption as the floor; field-level encryption for the restricted store and identifiers |

### Before a bank pilot

| ID | Status | Gap | Why it matters | Fix |
|---|---|---|---|---|
| **G-07** | ◐ **Partly** | No request throttling; account lockout was abusable | A script could lock every known analyst out of the platform | **Done:** per-IP, per-account and per-write budgets with 429 + `Retry-After`. **Remaining:** counters are per-process (G-18), and a distributed low-and-slow attack still reaches the account lockout |
| **G-08** | ◐ **Partly** | Token in `localStorage` | Any XSS becomes full session takeover | **Done:** a strict CSP on API responses, and a document policy for the static host (`security/web/security-headers.conf`). **Remaining:** move the session to an httpOnly, SameSite cookie plus CSRF — or short-lived access + refresh; and the document policy must actually be deployed (G-19) |
| **G-09** | ⬜ Open | No dual control on the most sensitive reads | An administrator can read unmasked identifiers and restricted subject information alone | Require a second approver for `restricted:view` outside a case's own team, or a just-in-time break-glass flow with post-hoc review |
| **G-10** | ◐ **Partly** | No central input validation / output classification | A future field could leak an identifier or pass a `$` operator into a query | **Done:** central rejection of operator, prototype, oversized and over-nested payloads (`security/validation.py`), plus a declared field-classification registry (`security/classification.py`). **Remaining:** per-route rejection of unknown fields, and response schemas that assert which fields are personal data |
| **G-11** | ◐ **Partly** | No retention, erasure or classification policy | DPDP storage limitation and PMLA's 5-year retention both fail as written; erasure requests cannot be answered | **Done:** a data-class registry with a retention window each, and PII-in-logs closed by `security/logguard.py`. **Remaining:** a sweeper that acts on the windows, backup classification, and the data-principal access/erasure path that respects legal holds |
| **G-12** | ⬜ Open | No incident response, breach runbook, DPO or grievance path | RBI and DPDP both require notification on a clock; today there is no clock, no owner and no template | Write the runbook, name the principal officer and DPO, define the detection-to-notification timeline, and rehearse it |
| **G-13** | ⬜ Open | No access review, no MFA for privileged roles, and no FIU principal-officer role | Staff keep access after moving roles; a stolen password is sufficient for `access:approve` or `users:manage`; nobody owns regulatory oversight | Quarterly access review with attestation; MFA on every privileged permission; add a principal-officer role with the reporting duties it implies |
| **G-14** | ⬜ Open | The bank channel is simulated | The production contract — mutual authentication, message signing, replay protection, idempotency, retry/dead-letter — does not exist | Specify mTLS + signed payloads + nonce/timestamp + idempotency keys; run the gateway over a durable queue with a dead-letter path instead of the lazy sweep |
| **G-18** | ⬜ Open | **Rate-limit counters live in one process** | Behind multiple workers each holds its own budget, so effective limits multiply by worker count | Move the counters to a shared store (Redis) implementing the same interface; the in-process path stays as the single-worker fallback |
| **G-19** | ⬜ Open | **The browser document policy is a reference config, not applied** | `security/web/security-headers.conf` hardens the console only once it is deployed at the static host; until then the console document has no CSP, and development cannot have one (the Vite HMR preamble needs inline script) | Deploy the static-host config with the production console, and assert the headers on the deployed origin in a smoke test |

### Before wide rollout

| ID | Status | Gap | Why it matters | Fix |
|---|---|---|---|---|
| **G-15** | ⬜ Open | Data localisation is a deployment hope, not a constraint | RBI requires payment/KYC data to stay in-country | Encode residency in the deployment targets and in backup/DR location; assert it in CI |
| **G-16** | ⬜ Open | No supply-chain or DR controls | One compromised dependency or a lost region ends the service | Lockfile audit + SCA in CI, pinned and signed images, dependency review; backup integrity tests and a rehearsed restore |
| **G-17** | ⬜ Open | No monitoring/SIEM export, and no off-database chain anchor | Entries exist but nobody is watching them; a full-database rewrite is undetectable without an external anchor | Ship the trail to a SIEM with detections for denial spikes, capability grants and `login_failed` bursts; periodically anchor the chain head outside the database |

### Closed or improved since the last revision

| ID | Was | Now |
|---|---|---|
| G-01 | Any origin could call the API | Explicit allowlist; unlisted origins receive no CORS headers |
| G-02 | Debug on by default, bound to `0.0.0.0` | Production boot with debug is refused |
| G-04 | Demo credentials served, `demo_mode` defaulting on | Production boot with demo mode or synthetic accounts is refused |
| G-05 | Described as a blocking gap | Chain, CAS appends, verification endpoint and tests — were already on disk |
| G-07 | No throttling anywhere | Per-IP, per-account and per-write budgets |
| G-10 | Payloads read ad hoc | Operator, prototype, size and depth rejection, centrally |
| G-11 | Audit `detail` could carry PII to logs | Log filter scrubs by value and by field name |

## 7. Roadmap

Sequenced so each stage is independently useful. Where it overlaps the product roadmap, the phase is
named. **S0's application half and S1's audit half are complete; the infrastructure halves are not.**

### S0 — Foundation (blocking)

- ✅ **G-01** CORS allowlist
- ✅ **G-02** (application half) refuse to boot production with debug on
- ◐ **G-04** refuse to boot production with demo mode or synthetic accounts; secrets still in env
- ⬜ **G-02** (infrastructure half) gunicorn/waitress behind TLS
- ⬜ **G-03** database authentication, isolation, and a least-privilege app role
- ⬜ **G-06** encryption at rest

**Done when:** an unauthenticated request from an unlisted origin is refused ✅; the app refuses to
start with `debug` on outside dev ✅; the database rejects an unauthenticated connection ⬜; a fresh
production deploy contains no synthetic account ✅.

### S1 — Evidence you can defend (audit integrity) — *product Phase 6*

- ✅ **G-05** hash-chained audit trail, CAS appends, verification endpoint, test coverage
- ⬜ **G-05** (residual) DB role denied `update`/`delete` on `audit_log`; off-database chain anchor
- ✅ **G-10** (application half) input validation and field classification
- ⬜ **G-17** SIEM export for the fail-closed paths

**Done when:** `GET /api/admin/audit-integrity` reports a verified chain ✅ and a tampered entry is
detected by recomputation ✅; the app's DB user is refused on `delete`/`update` against `audit_log`
⬜.

### S2 — Identity hardening

- ✅ **G-07** throttling (per-process)
- ⬜ **G-18** shared counters for multi-worker deployments
- ⬜ **G-08** cookie sessions + CSRF, and deploy the document CSP (**G-19**)
- ⬜ **G-13** access review, the principal-officer role, and MFA for any role holding
  `access:approve`, `users:manage` or `settings:manage`
- ⬜ **G-09** dual control / break-glass for the most sensitive reads

**Done when:** privileged sign-in without a second factor is refused; a locked-out account cannot be
locked out by a third party ✅ (the per-account budget answers 429 first); a quarterly review
produces an attestation artefact.

### S3 — Regulatory and operational readiness

- ⬜ **G-11** retention sweeper, backup classification, and the erasure path against a legal hold
- ⬜ **G-12** incident response, breach runbook, DPO and grievance paths
- ⬜ **G-14** the real bank channel (mTLS, signing, idempotency, dead-letter)
- ⬜ **G-15** residency encoded in deployment
- ⬜ **G-16** supply chain and DR
- ⬜ Independent penetration test and remediation

**Done when:** a breach tabletop executes the runbook inside the regulatory window; an erasure request
is answered end to end against a legal hold; a restore from backup is verified.

## 8. Enforceable invariants

Two suites are the floor that may not drop. **114 checks total.**

| Suite | Checks | Covers |
|---|---|---|
| `backend/test_security.py` | **62** | Credential storage, session handling, mandatory authentication, authorisation boundaries, the permission-matrix invariants, server-side masking, audit integrity and the hash chain, account lifecycle, the demo kill switch |
| `backend/test_security_controls.py` | **52** | Response hardening, origin trust, throttling (account, address and window semantics), input validation and its own false-positive check, boot posture, classification and retention, log scrubbing |

When you close a gap above, add the assertion here in the same pull request. A control with no test is
a claim; these files are where claims become checks. The reconciliation in §0 is what happens when
they are not kept in step.

## 9. Assumptions and limitations

- Bank connectivity is simulated on localhost; no live payment, account-aggregator or government
  integration exists. Every "release" is derived from seeded data.
- Demo accounts are synthetic and their passwords are public by design. **They must not exist in a
  production database** — boot is now refused if they do, but the demonstration environment still
  encourages keeping them.
- Timestamps are UTC-naive strings; there is no trusted time source yet, which matters once the audit
  chain is anchored (S1).
- The rate limiter's counters are in-process, so limits are exact only for a single-worker
  deployment (G-18).
- The log scrubber is a safety net, not a guarantee: it catches the formats this platform handles and
  the fields it declares. The classification registry is the primary control; scrubbing is what stops
  the unexpected case becoming a breach.
- This plan covers the application and its data. It does not cover the bank's own systems, the
  hosting provider's physical controls, or personnel security.
