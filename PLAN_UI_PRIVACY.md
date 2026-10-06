# Context Guard — UI & Privacy Improvement Plan

## Based on your answers:

| Area | Your Choice |
|------|-------------|
| UI feel | Basic → Enterprise, less overwhelming, easier navigation |
| Privacy | Masked fields, role-based visibility, audit trail (filtered by role), consent indicators |
| Demo vs Production | Prominent "DEMO DATA" banner |
| Layout | Collapsible sidebar + split pane (list left, detail right) |
| Theme | Classic Banking — Navy (#1a2744) + White + Gold/amber alerts |
| Charts | Transaction timeline, case risk breakdown, bank volume, pipeline timeline |
| Audit trail | Visible to all, filtered by role (admin sees all, analysts see own) |

---

## PHASE 1: Theme & Layout Overhaul

### 1.1 New CSS Theme — Classic Banking
- Replace the dark theme with **white backgrounds, navy (#1a2744) sidebar/header, subtle gray (#f5f7fa) content areas**
- Gold/amber (#d4a843) for warning alerts, deep red (#c0392b) for critical risk
- Clean typography: Inter for body, JetBrains Mono for data/IDs
- Proper card shadows, subtle borders, professional spacing

### 1.2 Collapsible Sidebar Navigation
- Left sidebar with: Dashboard, Cases, Network Graph, Audit Log (admin only)
- Sidebar collapses to icons on hover/click
- Active state indicator, user role badge at bottom
- Sidebar width: 260px expanded, 64px collapsed

### 1.3 Split Pane Layout (Case Detail)
- Left panel (40%): Transaction list / case summary
- Right panel (60%): Detail view (pipeline, reports, graph)
- Resizable divider
- Breadcrumb navigation at top

### 1.4 Prominent Demo Banner
- Top banner: "⚠ DEMO MODE — Using simulated data. Not real transactions or institutions."
- Gold/amber background, dismissable but returns on refresh
- Visible on every page

---

## PHASE 2: Data Masking & Privacy

### 2.1 Sensitive Field Masking (Default On)
- **Account numbers**: Show last 4 only → `XXXX-XXXX-1234`
- **Entity names**: Show initials for non-admin → `P. Sharma` (full name on hover/click)
- **Amounts**: Blur/obscure with `***` for non-admin, click to reveal
- **Emails/phone**: Partially masked → `p****@gmail.com`
- Toggle: "Show sensitive data" button for analysts who need it

### 2.2 Role-Based Visibility
- **Login/role selector** at startup: Analyst, Compliance Officer, Admin
- **Analyst**: Sees masked data, own audit entries, no system config
- **Compliance Officer**: Sees unmasked data, all case details, own + team audit entries
- **Admin**: Sees everything, audit trail (all users), system config, user management
- Role persisted in localStorage, switchable from sidebar

### 2.3 Consent Indicators
- Every transaction row shows a consent badge:
  - ✅ Green: Consent given and valid
  - ⚠ Amber: Consent expiring soon
  - ❌ Red: No consent / expired
- Consent details expandable on click
- Pipeline stages that use consent show which consent was used

### 2.4 Audit Trail (Role-Filtered)
- New collection: `audit_logs` in MongoDB
- Logs: who viewed a case, who ran pipeline, who made decision, who viewed raw data
- **Admin page**: Full audit trail with filters (user, action, date, case)
- **Analyst view**: Only their own actions
- **Compliance view**: Their own + team's actions
- Entry format: `{ user, role, action, target, timestamp, details }`

---

## PHASE 3: Charts & Visualizations

### 3.1 Transaction Timeline Chart (Case Detail)
- Bar chart showing transaction amounts over time for the case
- Color-coded by bank
- Hover shows details

### 3.2 Case Risk Breakdown (Dashboard)
- Donut/pie chart showing cases by risk level (Low, Medium, High, Critical)
- Center shows total case count

### 3.3 Bank Volume Comparison (Dashboard)
- Horizontal bar chart: total transaction volume per bank
- Color matches bank identity

### 3.4 Pipeline Timeline (Case Detail)
- Visual timeline of investigation stages with timestamps
- Shows time between stages (how long each took)
- Milestones highlighted

---

## PHASE 4: UI Polish & Enterprise Feel

### 4.1 Card & Component Redesign
- Proper card components with shadows, rounded corners, padding
- Status badges: colored dots + labels
- Table styling: alternating rows, hover states, sortable columns
- Form inputs: proper labels, validation states, focus styles

### 4.2 Navigation Improvements
- Breadcrumbs: Dashboard > Case_3 > Pipeline
- Quick actions: "Run Pipeline" floating action button
- Search/filter bar on case list
- Pagination or infinite scroll for large datasets

### 4.3 Empty States & Loading
- Proper empty state illustrations (not just text)
- Skeleton loading screens
- Progress indicators for pipeline stages

### 4.4 Responsive Considerations
- Sidebar collapses on smaller screens
- Split pane stacks vertically on narrow viewports
- Charts resize appropriately

---

## Backend Changes Needed

1. **Audit log collection + routes**: `GET /api/audit-logs`, `POST /api/audit-logs`
2. **Role middleware**: Check role from header/localStorage on sensitive endpoints
3. **Masking endpoint** (optional): `GET /api/entities/:id/masked` — returns masked version based on caller role
4. **Consent tracking on transactions**: Already has `consent_given` field, may need expiry dates

---

## Implementation Order

1. **Theme + Sidebar + Demo Banner** (most visual impact)
2. **Split Pane Layout** (case detail)
3. **Data Masking + Role Selector** (privacy)
4. **Charts** (all 4)
5. **Audit Trail** (backend + frontend)
6. **Polish** (empty states, loading, responsive)

## Estimated Scope
- ~15 files modified
- ~5 new files (audit routes, chart components, role context)
- No breaking changes to existing API (additive only)
