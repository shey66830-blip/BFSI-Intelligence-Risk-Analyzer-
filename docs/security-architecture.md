# Context Guard — Security Architecture

**Audience:** engineering, the sponsoring bank's information-security function, and anyone who has
to answer "is this thing safe to put real customer data in?".
**Status:** target architecture with a live current-state audit (verified against the code on
2026-10-06, not against the plan).
**Companion docs:** [`SECURITY.md`](../SECURITY.md) (gap register + staged roadmap),
[`backend/test_security.py`](../backend/test_security.py) (enforceable invariants).

---

## 0. Why this document exists

`SECURITY.md` is a **gap register** — it lists what is missing and when to fix it. This document is
the **architecture**: the layered design a control has to fit into, so that a future change knows
where it belongs and what it must not weaken.

It is written after a code-level audit, because the plan and the code had drifted apart. Two
corrections carry through everything below:

- **G-05 (tamper-evident audit trail) is closed.** `backend/services/audit.py` implements a
  SHA-256 hash chain (`seq`, `prev_hash`, `entry_hash`) with compare-and-swap appends, a full
  `verify()` recomputation, and a live endpoint at `GET /api/admin/audit-integrity`
  (`backend/routes/admin.py:306`). `SECURITY.md` still lists it as a gap.
- **The enforceable-invariant count is 62, not 48.** `npm run test:security` reports
  `62 passed`.

A stale plan is a real risk: it causes teams to re-implement controls that exist and to trust
"planned" controls that were never built. §6 below is the corrected state.

---

## 1. Security objectives

| # | Objective | Failure mode it prevents |
|---|---|---|
| O1 | **Confidentiality** — no session receives an identifier its role is not entitled to | Analyst session scrapes unmasked PII |
| O2 | **Integrity** — the audit trail and case evidence cannot be altered undetectably | Insider edits the log after a bad decision |
| O3 | **Availability** — the service resists being taken down by cheap traffic | Brute-force locks out every analyst |
| O4 | **Accountability** — every consequential act is attributable to a real identity and a reason | "Nobody knows who approved it" |
| O5 | **Privacy by design** — personal data is minimised, purpose-bound, retention-limited and erasable | Data held forever because nobody owned deletion |
| O6 | **Least privilege** — authority comes from the server, never from the client | Client claims `role: admin` |
| O7 | **Regulatory defensibility** — DPDP 2023, RBI cyber/KYC, PMLA/FIU-IND obligations are traceable to controls | A regulator asks and the answer is "we assumed" |

---

## 2. Asset classification

Protection level drives which layer enforces the control. This is the taxonomy the code should
reference rather than inventing per-route rules.

| Class | Examples | Collections | Required protection |
|---|---|---|---|
| **C4 — Restricted** | Identity documents, contact details, investigation-subject records | `restricted_subject_information` | Field-level encryption, capability-gated read (`restricted:view`), dual control, every read audited |
| **C3 — Sensitive personal** | Account numbers, entity names, counterparties, device ids, emails, phones | `transactions`, `entities`, `users` | Masking before serialisation, unmasked read needs `txn:view_unmasked`, audited |
| **C2 — Confidential business** | Case narratives, analyst reports, evidence, bank correspondence | `cases`, `analyst_reports`, `case_evidence` | Case-scoped authorisation, in-transit + at-rest encryption |
| **C1 — Internal** | Graph edges, work queue, settings, notifications | `graph_edges`, `settings` | Authenticated access, no masking requirement |
| **A0 — Accountability** | Audit entries, access statements, capability grants | `audit_log`, `audit_chain`, `access_authorizations` | Append-only, hash-chained, never deletable by the app's DB role |

**Rule:** a value's class is a property of the *field*, declared once. A route never decides its own
masking rule; it asks the classification layer. This is what stops a new endpoint leaking an
identifier by forgetting to redact (today's G-10).

---

## 3. Trust boundaries

```
                          UNTRUSTED                          │            TRUSTED
                                                             │
 ┌────────────┐  HTTPS  ┌──────────────┐  network  ┌─────────┴──────┐  TCP  ┌──────────┐
 │  Browser   │────────▶│  Edge /      │──────────▶│  Flask API     │──────▶│ MongoDB  │
 │ (untrusted)│         │  reverse     │           │  (authority    │       │ users ·  │
 │            │◀────────│  proxy       │           │   lives here)  │       │ audit ·  │
 └────────────┘         │ TLS · HSTS   │           └────────────────┘       │ restrict.│
   L1 · L2              │ CSP · CORS   │             L3–L7                  └──────────┘
                        └──────────────┘                                       L7–L8
        ▲                                                                          ▲
        │ no raw identifier reaches a session not entitled to it                   │
        │                                                                app DB user
 ┌──────┴───────┐   ▲ privileged, and deliberately *not* financially      cannot update
 │ Bank consent │     authoritative — admin holds no `restricted:view`    or delete the
 │ desk (sim.)  │                                            audit_log
 └──────────────┘
```

Crossing rules that must hold for every request:

1. **Browser → API.** The client is untrusted. Identity is read from the session, authority from
   the permission matrix and live grants (`middleware.py` → `g.user`, `g.permissions`). The request
   body can never set a role. *Implemented.*
2. **API → MongoDB.** Today effectively trusted (no DB auth — G-03). The app must hold a DB user
   that **cannot** `update`/`delete` `audit_log`, so even a full app compromise cannot rewrite
   history. *Not yet true — this is the single highest-value infrastructure change.*
3. **API → Bank.** Simulated. The production contract (mTLS, signed payloads, nonce, idempotency,
   dead-letter) does not exist (G-14).
4. **Admin console.** Highest privilege, but configuration authority is separated from financial-data
   authority. Admin holds `users:manage` and `settings:manage` yet holds neither `restricted:view`
   nor the ability to raise an access request. *Implemented.*

---

## 4. Defense in depth — the layers

Each layer assumes the one outside it has already failed. This is what makes a single bypass
survivable.

### L1 — Browser / client hardening
**Threat:** XSS, clickjacking, token theft, malicious third-party script.
**Controls:** strict Content-Security-Policy; `X-Content-Type-Options: nosniff`;
`X-Frame-Options: DENY` + `frame-ancestors 'none'`; `Referrer-Policy: no-referrer`;
`Permissions-Policy` denying camera/mic/geolocation; no inline script.
**Current state:** **implemented** in `backend/security/headers.py` — the full set on every API
response, including refusals and errors, with `default-src 'none'` and `Cache-Control: no-store` on
personal data. HSTS is asserted only where TLS is guaranteed.
**Still missing:** the *document* policy, which cannot come from a JSON API —
`security/web/security-headers.conf` is written but remains a reference config until it is deployed
at the static host (G-19).
**Note:** the session token currently lives in `localStorage` (G-08), so a CSP is the *main* thing
standing between an XSS and full session takeover. Until G-08 is closed, L1 is load-bearing.

### L2 — Transport & origin
**Threat:** downgrade, MITM, cross-origin API abuse, cookie theft.
**Controls:** TLS 1.2+ with HSTS (`max-age=31536000; includeSubDomains; preload`); strict origin
allowlist; `Secure`/`HttpOnly`/`SameSite=Lax` on any cookie; no wildcard CORS with credentials.
**Current state:** **implemented** in `backend/security/cors.py` — an explicit allowlist, never a
wildcard, and production refuses to boot without one named. An unlisted origin receives no CORS
headers at all. **G-01 closed.** TLS termination remains a deployment requirement (G-02).

### L3 — API entry
**Threat:** brute force, credential stuffing, DoS, NoSQL operator injection, oversized payloads.
**Controls:** per-IP and per-account token buckets with progressive backoff; global payload size
cap; central request validation that rejects `$`-prefixed keys, prototype-pollution keys
(`__proto__`, `constructor`), and fields not in a declared shape.
**Current state:** **implemented** — `backend/security/ratelimit.py` (per-IP, per-account and
per-write budgets, sliding window, 429 + `Retry-After`) and `backend/security/validation.py`
(operator keys, prototype keys, depth and size caps). The per-account budget answers 429 *before* an
attacker can spend a known analyst's five lockout attempts, which is what closes the lockout-as-DoS
vector. **Residual:** counters are per-process (G-18), and unknown fields are not yet rejected
per-route (G-10).

### L4 — Identity & session
**Threat:** credential theft, session hijack, replay, orphaned sessions.
**Controls:** PBKDF2 password hashing (Werkzeug); sessions are 32-byte opaque tokens stored only as
a SHA-256 digest; server-side expiry; role/status/password change revokes sessions; identical
response for wrong-password and unknown-user.
**Current state:** **implemented and guarded** by tests. Add MFA for `access:approve`,
`users:manage`, `settings:manage`.

### L5 — Authorisation
**Threat:** privilege escalation, insider over-reach.
**Controls:** one permission matrix (`ROLE_PERMISSIONS`) is the only place authority is decided;
capability grants are resolved **per request**, so an expired grant stops working with no restart;
`restricted:view` is in **no** role — it is released only by a live, case-scoped, expiring
authorisation; separation of duties prevents an approver from raising a request and prevents
self-approval.
**Current state:** **implemented and guarded.** Analyst holds `cases:view_assigned` (not
`view_all`), which is the boundary that keeps one analyst out of another's caseload.

### L6 — Privacy
**Threat:** over-collection, secondary use, indefinite retention, unmaskable re-identification.
**Controls:** masking **before serialisation** (so the raw value never leaves the server, not just
the screen); free-text redaction for names embedded in prose; purpose recorded on every release;
data-subject rights (access/correction/erasure) with legal-hold handling; retention windows per
class.
**Current state:** masking and free-text redaction **implemented** (`services/privacy.py`);
classification and retention are **now declared** in `backend/security/classification.py`, and
PII-in-logs is **closed** by `backend/security/logguard.py`.
**Still absent:** a sweeper that acts on the retention windows, backup classification, and the
data-principal access/erasure path (G-11).

### L7 — Data at rest
**Threat:** disk/backup theft, over-broad DB access.
**Controls:** volume encryption floor; field-level encryption for C4/C3; SCRAM auth; bind to
loopback or cluster network; per-service DB credentials; app DB role denied
`update`/`delete` on `audit_log`.
**Current state:** **absent** (G-03, G-06) and explicitly out of scope for application code — it is
a deployment control, but it must be recorded as an unmet dependency.

### L8 — Audit & accountability
**Threat:** log tampering, deletion of evidence of wrongdoing, repudiation.
**Controls:** append-only over the API; SHA-256 hash chain with CAS append; `verify()` recomputes
every entry and reports the first break; anchoring the chain head **outside** the database so a
full-DB rewrite is still detectable; SIEM export with detections for denial spikes, capability
grants, and `login_failed` bursts.
**Current state:** chain + verification endpoint **implemented**. Off-DB anchoring and SIEM export
are **absent**.

### L9 — Supply chain & operations
**Threat:** compromised dependency or image, lost region.
**Controls:** lockfile audit + SCA in CI, pinned/signed images, dependency review, backup integrity
tests, rehearsed restore, residency asserted in CI.
**Current state:** **absent** (G-15, G-16, G-17).

---

## 5. Privacy architecture (data + users)

Privacy is not a filter applied at the end; it is a property of the data model.

```
  declare field class  ──▶  enforce at the boundary  ──▶  prove it
  ┌─────────────────┐       ┌─────────────────────┐      ┌──────────────────┐
  │ classification  │       │ mask before         │      │ test asserts an  │
  │ registry:       │──────▶│ serialisation;      │─────▶│ analyst payload  │
  │ field → class + │       │ reject undeclared   │      │ contains no raw  │
  │ purpose +       │       │ field in a response │      │ identifier       │
  │ retention       │       └─────────────────────┘      └──────────────────┘
  └─────────────────┘                 │
          │                           ▼
          │                 ┌─────────────────────┐
          └────────────────▶│ retention sweeper + │
                            │ subject-rights path │
                            │ (erasure vs hold)   │
                            └─────────────────────┘
```

Principles applied:

1. **Minimisation** — nothing is pre-fetched. Locked items are released per request, scoped to a
   case, with the stated purpose recorded. *(implemented)*
2. **Purpose limitation** — every capability release carries a purpose and an expiry; the grant
   lapses on its own. *(implemented)*
3. **Storage limitation** — each class gets a retention window; a sweeper enforces it. *(absent)*
4. **Accuracy & subject rights** — a data principal can ask what is held and request correction or
   erasure. *(absent)*
5. **Accountability** — reads of C4 are individually audited with actor + reason. *(implemented)*

### The DPDP erasure vs PMLA retention conflict

This is the sharp edge and it must be designed, not discovered:

| Obligation | Source | Demands |
|---|---|---|
| Erasure on request | DPDP Act 2023 | Delete personal data when purpose is spent |
| 5-year retention of transactions/KYC | PMLA | Keep it, and keep it confidential |

**Resolution:** erasure is **scoped by class, not by table**. C1/C2 personal data with no statutory
basis is erasable; C3/C4 records under a legal hold are *retained but restricted* — access is
narrowed to the statutory purpose, and the erasure request is recorded as **partially satisfied
with a documented legal basis**. The platform must be able to answer "why is this still held?"
with a citation, not a shrug.

---

## 6. Current state vs. target (corrected audit, 2026-10-06)

Verified by reading the code, not the plan.

| Control | Layer | State | Evidence |
|---|---|---|---|
| Password hashing, no plaintext | L4 | ✅ Guarded | `services/users.py` Werkzeug PBKDF2 |
| Opaque hashed sessions + expiry | L4 | ✅ Guarded | `services/users.py` `resolve_session` |
| Mandatory auth on protected routes | L4 | ✅ Guarded | `middleware.py` `login_required` |
| Single permission matrix | L5 | ✅ Guarded | `services/users.py` `ROLE_PERMISSIONS` |
| Capability grants resolved per request | L5 | ✅ Guarded | `middleware.py` `_authenticate` |
| `restricted:view` in no role | L5 | ✅ Guarded | permission matrix |
| Separation of duties / no self-approval | L5 | ✅ Guarded | `services/access.py` |
| Masking before serialisation | L6 | ✅ Guarded | `services/privacy.py` |
| Free-text name redaction in prose | L6 | ✅ Guarded | `services/privacy.py` `redact_text` |
| Account lockout after repeated failures | L4 | ✅ Guarded | `services/users.py` |
| Enumeration-resistant login errors | L4 | ✅ Guarded | `routes/auth.py` |
| Hash-chained audit + verification | L8 | ✅ Guarded | `services/audit.py`, `admin.py:306` |
| Demo kill switch (`demo_mode` off) | L4 | ✅ Guarded | `routes/auth.py:83` |
| **Security response headers / CSP** | L1 | ✅ Delivered | `security/headers.py`; document policy undeployed (G-19) |
| **CORS allowlist** | L2 | ✅ Delivered | `security/cors.py` — **G-01 closed** |
| **Request throttling / 429** | L3 | ✅ Delivered | `security/ratelimit.py` — per-process (G-18) |
| **Central input validation** | L3 | ◐ Partial | `security/validation.py`; per-route unknown-field rejection open (G-10) |
| **Boot-time posture guard** | L3 | ✅ Delivered | `security/posture.py` — G-02/G-04 application half |
| **Data classification + retention** | L6 | ◐ Partial | `security/classification.py` declares both; no sweeper (G-11) |
| **PII in logs/scrubbing policy** | L6 | ✅ Delivered | `security/logguard.py` — G-11 log half closed |
| DB auth & least-privilege DB role | L7 | ❌ Absent | G-03 |
| At-rest encryption | L7 | ❌ Absent | G-06 |
| Off-DB chain anchor + SIEM export | L8 | ❌ Absent | G-17 |
| Supply chain / DR / residency | L9 | ❌ Absent | G-15, G-16 |

**The three that mattered most — all now closed, all application-layer:**

1. **L3 throttling** — delivered. A script can no longer hammer `/api/auth/login`, and the
   per-account budget answers 429 *before* an attacker can spend a known analyst's five lockout
   attempts.
2. **L1 headers** — delivered for the API. The document policy remains undeployed (G-19), so an XSS
   is only partly blunted until it ships.
3. **L2 CORS** — closed. An unlisted origin receives no CORS headers.

Each was closable inside this codebase without infrastructure, which is why they were first. What
remains in this table is **infrastructure and process** — database authentication, encryption at
rest, an off-database chain anchor, supply chain. No amount of application code closes those, and
claiming otherwise would be security theatre.

---

## 7. Control verification

A control with no test is a claim, not a control.

| Control | Proof |
|---|---|
| Header set present on every response | assert all headers on `/api/health` and a 401 |
| CSP blocks inline script | assert `script-src` has no `unsafe-inline` |
| CORS allowlist | listed origin gets `ACAO`; unlisted does not |
| Throttling | N+1th login attempt returns 429 with `Retry-After` |
| Throttle is per-account *and* per-IP | one IP cannot lock a known account; one account cannot be flooded from many IPs |
| Validation rejects `$`-keys | `{"$where": ...}` → 400, not a DB error |
| Validation rejects `__proto__` | 400 |
| Payload size cap | oversized body → 413 |
| Posture guard | production + `debug` → refuses to boot |
| Classification registry | every C3/C4 collection field is declared, or the test fails |
| Log scrubbing | a log line containing an account number is masked |

---

## 8. Deployment topology (target)

```
        Internet
           │  HTTPS 443
   ┌───────▼────────┐
   │ Reverse proxy  │  TLS termination · HSTS · rate limit (edge, coarse)
   │ (nginx/Caddy)  │  static assets · CSP
   └───────┬────────┘
           │ loopback only
   ┌───────▼────────┐        ┌──────────────────┐
   │ gunicorn       │───────▶│ MongoDB (SCRAM,  │
   │ (no debug,     │        │ private network) │
   │  no reload)    │        │ app role: no     │
   └────────────────┘        │ update/delete on │
                             │ audit_log        │
                             └──────────────────┘
```

Non-negotiables: Flask's dev server never faces the network; `debug=False` outside development;
the app refuses to start without a real `MONGO_URI` credential once `APP_ENVIRONMENT` is production.

---

## 9. Residual risk and honest limitations

- Bank connectivity is **simulated**; every "release" derives from seeded data. No live payment,
  aggregator or government integration exists.
- Demo credentials are public **by design** and must never exist in a production database.
- Timestamps are UTC-naive strings; there is no trusted time source, which weakens chain anchoring
  until fixed.
- Application-layer controls do **not** substitute for L7/L9 (DB auth, encryption at rest, supply
  chain). A determined attacker with host access still wins; the goal is that they are *detected*
  (L8) rather than silent.
- This document covers the application and its data. It does not cover the bank's systems, the
  hosting provider's physical controls, or personnel security.
