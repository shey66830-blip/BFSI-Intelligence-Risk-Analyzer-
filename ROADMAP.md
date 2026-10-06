# Context Guard — Roadmap & Task Split

**What this phase is for:** a demonstration build — a reviewer spends ten minutes in it and comes
away convinced the engineering is real. Synthetic data only, no real bank access.

**Constraints:** no live customer data, no bank sandbox, integration work is specified rather than
built. Everything here runs on a local machine.

**Companion documents:** [`SECURITY.md`](SECURITY.md) (threat model, gap register, security
roadmap) and [`README.md`](README.md) (what exists today).

---

## 1. What it can do today

| Capability | Detail |
|---|---|
| Score & route | Each transaction scored against its **own** baseline, then gated: no action / context verification / investigation |
| Investigate | 12-stage pipeline — identify banks, request context in scope, correlate returns, expand the network, draft a report, assess risk, stop for a named decision with a rationale |
| Explain | Report separates *what happened* from *why*, and states what it does **not** establish |
| Consent | A bank report is only requested where an active consent record exists |
| Scope | Analyst = assigned cases, masked; compliance = all cases, unmasked; admin = identity + policy |
| Gate information | Restricted subject information behind time-limited authorisations |
| Gate capability | Locked features/information behind a 25-word written statement, decided by the bank or an administrator, recordable even when never displayed |
| Bank realism | Response latency, transport failure + retry, **partial** releases, 48-hour response deadline that lapses |
| Evidence | Per-case vault with folders, versions, access levels, timelines |
| Account | Append-only trail of logins, denials, reads, decisions and statements |
| Verify | 6 suites, 411 checks + pipeline, and a documented security plan |

## 2. What more it can do

### Direction A — deeper investigation product
New typologies beyond the current three scenarios: **mule-account networks**, **structuring /
smurfing** just under reporting thresholds, **trade-based laundering**, **round-tripping**, and
**sanctions / PEP screening** on counterparties. Plus stronger explainability (per-finding evidence
trails, a "why this score" panel that shows the arithmetic), and an STR/FIU filing workflow with a
principal-officer review step.

### Direction B — production & engineering foundation
A job runner instead of lazy sweeps, pagination on every list, CI on every push, docker-compose for
one-command startup, frontend tests, and a graph-depth control so large networks stay readable.

### Direction C — real-world integration readiness
OIDC/SAML instead of local passwords, a bank API contract (mTLS, signed payloads, idempotency,
dead-letter), and SIEM export. *Specified and stubbed here — cannot be built without a bank.* 

### Direction D — regulatory product features
Retention and erasure workflows, data classification, tamper-evident audit (verification UI), and
incident/breach tooling.

---

## 3. The plan

### Track 1 — Promised roadmap phases *(I execute now)*

Status: ✅ delivered and verified · ◐ partially delivered · ⏳ not started

| # | Phase | Outcome | Status |
|---|---|---|---|
| 3 | **Evidence provenance** | Every vault item and released bank record carries a chain: which request, which authorisation, which actor, from which source — visible where the record is read | ✅ |
| 4 | **Pagination** | Every list endpoint returns `{items, total, limit, offset, has_more}` and accepts `limit`/`offset`, so a large case does not ship everything at once | ✅ |
| 5 | **Threshold backtest** | An endpoint replays the demo scenarios at candidate thresholds and reports the routing confusion matrix, so a threshold change is argued with evidence rather than by feel | ✅ |
| 6 | **Audit hash-chain** | Each entry carries `prev_hash` + `entry_hash`; a verification endpoint recomputes the chain and reports the first break. Closed security gap **G-05** | ✅ |
| 7 | **Graph depth** | Depth/limit controls on the network expansion so a big graph is explorable instead of overwhelming | ✅ |
| 8 | **Production shape** | CI workflow, docker-compose, frontend test harness, and a job runner for the gateway sweep | ◐ — frontend harness done; CI workflow and docker-compose absent |

### Track 2 — Security *(from SECURITY.md)*
S0's application half is delivered — CORS allowlist (**G-01**), no debug in production (**G-02**),
demo mode refused at boot (**G-04**) — by [`backend/security/`](backend/security/__init__.py). Its
infrastructure half, database authentication (**G-03**) and encryption at rest (**G-06**), remains
open and is not buildable inside this codebase. S1 audit integrity (**G-05**) is delivered by Track 1
Phase 6, and the S2 throttling control (**G-07**) is delivered by the same package. SECURITY.md §6
carries the current status of every gap.

### Track 3 — New capability *(needs your input — see §4)*
Typologies, explainability, STR filing.

### Track 4 — Integration *(parked by constraint)*
OIDC, real bank contract, SIEM. Written as specifications; not buildable without a bank and a cloud
account.

---

## 4. Who does what

### Yours — I cannot do these

These need an account, a relationship, a decision, or domain knowledge I do not have.

| # | Task | Why only you | Blocks |
|---|---|---|---|
| Y1 | **Pick the demo story** — which three cases a reviewer sees, in what order | Only you know the audience | Track 1 Phase 8 polish |
| Y2 | **Sign off on the security priorities** — are G-01…G-06 the right blockers? | Risk appetite is an owner's call | Track 2 |
| Y3 | **Choose typologies** — mule networks? structuring? sanctions screening? | Domain judgement about what matters in Indian retail banking | Track 3 |
| Y4 | **Supply any real domain rules** you know (thresholds, reporting triggers, red flags) — sanitised | I can invent plausible ones, not *correct* ones | Track 3 |
| Y5 | **Confirm the regulatory framing** — is DPDP + RBI + FIU-IND the right story for your audience? | Determines how the compliance narrative reads | Track 3/4 docs |
| Y6 | **Bank/hosting/legal accounts** — if you ever want real integration | I have none and must not create them | Track 4 |
| Y7 | **Approve what is published** — organisation name, branding, claims | You own what the demo asserts about itself | All |

**Nothing on Track 1 is blocked by these.** I can deliver all six phases without any of the above; the
Y-tasks shape what comes *after*.

### Mine — executing now

- Phases 3–8, each with tests, docs and a verified build.
- Frontend surfaces for provenance, pagination and the backtest.
- Security Track 2 items that are pure code/configuration.

### You only need to do one thing to unblock Track 3
Answer **Y3 and Y4** — which typologies, and any real red-flag rules you already know. Everything on
Track 1 proceeds regardless.

---

## 5. Execution order

1. Phase 3 → Phase 4 → Phase 5 → Phase 6 → Phase 7 → Phase 8, each verified (`npm test`, `vite build`,
   and a live check) before the next.
2. Track 2 S0 once Track 1 lands, because Phase 6 closes the largest gap.
3. Track 3 starts when Y3/Y4 are answered.

Every phase adds its regression guard in the same change — a phase without a test is a claim, not a
feature.
