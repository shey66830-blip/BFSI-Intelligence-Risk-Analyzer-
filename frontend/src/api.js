const API_BASE = '/api';
const TOKEN_KEY = 'cg_token';

// ── Session token ─────────────────────────────────────────────────────────

export function getToken() {
  try { return localStorage.getItem(TOKEN_KEY) } catch { return null }
}

export function setToken(token) {
  try { localStorage.setItem(TOKEN_KEY, token) } catch {}
}

export function clearToken() {
  try { localStorage.removeItem(TOKEN_KEY) } catch {}
}

let unauthorizedHandler = null;

/** Registered by the auth provider so a 401 anywhere drops the session. */
export function setUnauthorizedHandler(fn) {
  unauthorizedHandler = fn;
}

async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (options.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (res.status === 401 && !path.startsWith('/auth/login')) {
    clearToken();
    if (unauthorizedHandler) unauthorizedHandler();
  }
  return res;
}

async function get(path) {
  const res = await request(path);
  return res.ok ? res.json() : null;
}

async function send(method, path, body) {
  const res = await request(path, {
    method,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await res.json().catch(() => ({}));
  return { ok: res.ok, status: res.status, body: payload };
}

// ── Authentication ────────────────────────────────────────────────────────

export async function login(username, password) {
  const res = await request('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) return { ok: false, error: body.error || 'Sign-in failed' };
  setToken(body.token);
  return { ok: true, user: body.user };
}

export async function logout() {
  await send('POST', '/auth/logout');
  clearToken();
}

export async function fetchMe() {
  return get('/auth/me');
}

export async function fetchDemoAccounts() {
  return (await get('/auth/demo-accounts')) || [];
}

// ── Cases & transactions ──────────────────────────────────────────────────

export async function fetchDashboardStats() {
  return get('/dashboard-stats');
}

export async function fetchCases() {
  return (await get('/cases')) || [];
}

export async function fetchCase(caseId) {
  const res = await request(`/cases/${caseId}`);
  if (res.status === 403) return { error: (await res.json()).error, forbidden: true };
  return res.json();
}

export async function fetchTransactions(caseId) {
  const url = caseId ? `/transactions?case_id=${caseId}` : '/transactions';
  return (await get(url)) || [];
}

export async function fetchEntities() {
  return (await get('/entities')) || [];
}

export async function fetchBanks() {
  return (await get('/banks')) || [];
}

// ── Pipeline ──────────────────────────────────────────────────────────────

export async function fetchPipelineFlow() {
  return get('/pipeline/flow');
}

export async function runPipeline(caseId) {
  return send('POST', `/pipeline/run/${caseId}`);
}

export async function submitDecision(caseId, { decision, rationale }) {
  return send('POST', `/cases/${caseId}/decision`, { decision, rationale });
}

export async function ingestTransaction(scenario) {
  const res = await send('POST', '/pipeline/ingest', { scenario });
  return res.body;
}

// ── Graph ─────────────────────────────────────────────────────────────────

export async function fetchGraph(entityIds, lookbackDays) {
  const params = new URLSearchParams();
  if (entityIds) params.set('entity_ids', entityIds.join(','));
  if (lookbackDays) params.set('lookback_days', lookbackDays);
  const qs = params.toString();
  return get(`/graph/entity${qs ? `?${qs}` : ''}`);
}

// ── Administration ────────────────────────────────────────────────────────

export async function fetchUsers() {
  return get('/users');
}

export async function fetchAnalysts() {
  return get('/users/analysts');
}

export async function createUser(payload) {
  return send('POST', '/users', payload);
}

export async function updateUser(userId, payload) {
  return send('PATCH', `/users/${userId}`, payload);
}

export async function assignCase(caseId, userId) {
  return send('POST', `/cases/${caseId}/assign`, { user_id: userId });
}

export async function fetchSettings() {
  return get('/settings');
}

export async function updateSettings(payload) {
  return send('PUT', '/settings', payload);
}

export async function fetchThresholdBacktest(params = {}) {
  const query = new URLSearchParams(params).toString();
  return get(`/admin/threshold-backtest${query ? `?${query}` : ''}`);
}

export async function applyThresholds(payload) {
  return send('POST', '/admin/threshold-backtest/apply', payload);
}

export async function fetchAuditLogs(scope = 'own', action = 'all') {
  const params = new URLSearchParams({ scope });
  if (action && action !== 'all') params.set('action', action);
  return get(`/audit-logs?${params.toString()}`);
}

// ── Notifications ─────────────────────────────────────────────────────────

export async function fetchNotifications(unreadOnly = false) {
  return (await get(`/notifications${unreadOnly ? '?unread=1' : ''}`)) || { notifications: [], unread: 0 };
}

export async function markNotificationRead(notificationId) {
  return send('POST', `/notifications/${notificationId}/read`);
}

export async function markAllNotificationsRead() {
  return send('POST', '/notifications/read-all');
}

// ── Investigation updates ─────────────────────────────────────────────────

export async function fetchCaseUpdates(caseId) {
  return get(`/cases/${caseId}/updates`);
}

export async function fetchComplianceUpdates({ acknowledged = 'all', caseId } = {}) {
  const params = new URLSearchParams({ acknowledged });
  if (caseId) params.set('case_id', caseId);
  return get(`/compliance/updates?${params.toString()}`);
}

export async function postCaseUpdate(caseId, payload) {
  return send('POST', `/cases/${caseId}/updates`, payload);
}

export async function acknowledgeUpdate(updateId, note) {
  return send('POST', `/updates/${updateId}/acknowledge`, { note });
}

// ── Analyst reports ───────────────────────────────────────────────────────

export async function fetchMyReports() {
  return (await get('/analyst/reports')) || { reports: [] };
}

export async function fetchComplianceReports(statuses) {
  const qs = statuses ? `?status=${statuses}` : '';
  return (await get(`/compliance/reports${qs}`)) || { reports: [] };
}

export async function fetchCaseReports(caseId) {
  return (await get(`/cases/${caseId}/analyst-reports`)) || { versions: [] };
}

export async function createAnalystReport(caseId, payload = { build_from_case: true }) {
  return send('POST', `/cases/${caseId}/analyst-report`, payload);
}

export async function fetchReport(reportId) {
  return get(`/reports/${reportId}`);
}

export async function updateReport(reportId, payload) {
  return send('PATCH', `/reports/${reportId}`, payload);
}

export async function submitReport(reportId) {
  return send('POST', `/analyst/reports/${reportId}/submit`);
}

export async function amendReport(reportId, reason) {
  return send('POST', `/analyst/reports/${reportId}/amend`, { reason });
}

export async function reviewReport(reportId, outcome, note) {
  return send('POST', `/analyst/reports/${reportId}/review`, { outcome, note });
}

export async function requestReportClarification(reportId, note) {
  return send('POST', `/analyst/reports/${reportId}/clarification`, { note });
}

// ── Evidence vault ────────────────────────────────────────────────────────

export async function fetchEvidenceVault(caseId) {
  return get(`/cases/${caseId}/evidence`);
}

export async function addEvidence(caseId, payload) {
  return send('POST', `/cases/${caseId}/evidence`, payload);
}

export async function updateEvidence(evidenceId, payload) {
  return send('PATCH', `/evidence/${evidenceId}`, payload);
}

export async function supersedeEvidence(evidenceId, payload) {
  return send('POST', `/evidence/${evidenceId}/supersede`, payload);
}

export async function fetchEvidenceProvenance(evidenceId) {
  return get(`/evidence/${evidenceId}/provenance`);
}

export async function fetchCaseTimeline(caseId) {
  return get(`/cases/${caseId}/timeline`);
}

// ── Investigation working record ──────────────────────────────────────────

export async function fetchCaseNotes(caseId, kind) {
  const qs = kind && kind !== 'all' ? `?kind=${kind}` : '';
  return (await get(`/cases/${caseId}/notes${qs}`)) || { notes: [], counts: {} };
}

export async function addCaseNote(caseId, payload) {
  return send('POST', `/cases/${caseId}/notes`, payload);
}

export async function resolveCaseNote(noteId, resolution) {
  return send('POST', `/notes/${noteId}/resolve`, { resolution });
}

export async function fetchRelevance(caseId) {
  return (await get(`/cases/${caseId}/relevant-transactions`)) || { relevant_transactions: [] };
}

export async function setTransactionRelevance(caseId, transactionId, relevant, reason) {
  return send('POST', `/cases/${caseId}/relevance`, {
    transaction_id: transactionId, relevant, reason,
  });
}

// ── Restricted subject information & authorisations ───────────────────────

export async function fetchRestrictedInformation(caseId) {
  const res = await request(`/restricted/${caseId}`);
  const payload = await res.json().catch(() => ({}));
  return { ok: res.ok, status: res.status, ...payload };
}

export async function fetchRestrictedMatrix(caseId) {
  return get(`/restricted/${caseId}/matrix`);
}

export async function createAccessRequest(payload) {
  return send('POST', '/access-requests', payload);
}

export async function fetchLockedResources(caseId) {
  const res = await request(`/locked-resources?case_id=${encodeURIComponent(caseId)}`);
  const payload = await res.json().catch(() => ({}));
  return { ok: res.ok, status: res.status, ...payload };
}

export async function fetchRequestStatements(requestId) {
  const res = await request(`/access-requests/${requestId}/statements`);
  const payload = await res.json().catch(() => ({}));
  return { ok: res.ok, status: res.status, ...payload };
}

export async function fetchAccessRequests(status) {
  const qs = status && status !== 'all' ? `?status=${status}` : '';
  return (await get(`/access-requests${qs}`)) || { requests: [] };
}

export async function fetchAccessRequest(requestId) {
  return get(`/access-requests/${requestId}`);
}

export async function approveAccessRequest(requestId, payload) {
  return send('POST', `/access-requests/${requestId}/approve`, payload);
}

export async function rejectAccessRequest(requestId, reason) {
  return send('POST', `/access-requests/${requestId}/reject`, { reason });
}

export async function clarifyAccessRequest(requestId, note) {
  return send('POST', `/access-requests/${requestId}/clarification`, { note });
}

export async function fetchAuthorizations(caseId) {
  const qs = caseId ? `?case_id=${caseId}` : '';
  return (await get(`/access-authorizations${qs}`)) || { authorizations: [] };
}

export async function revokeAuthorization(authorizationId, reason) {
  return send('POST', `/access-authorizations/${authorizationId}/revoke`, { reason });
}

// ── System status ─────────────────────────────────────────────────────────

export async function fetchSystemStatus() {
  return get('/admin/system-status');
}

/** Public liveness probe — used by the sidebar's system-status pill. */
export async function fetchHealth() {
  return get('/health');
}
