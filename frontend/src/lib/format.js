/**
 * Formatting and statement helpers shared across the interface.
 *
 * These live here rather than in each component because they decide what the user
 * *sees* of a rule the backend enforces: `meetsStatementMinimum` must agree with the
 * server's 25-word gate, and `shortTime` renders every timestamp in the product. Both
 * are covered by `format.test.js`, which runs with Node's built-in test runner — no
 * test dependency to install and keep current.
 */

/**
 * Render a timestamp as UTC minutes: `2026-10-03 11:08Z`.
 * An absent timestamp is an em dash, never "null" or "undefined" leaking into a table.
 */
export function shortTime(iso) {
  if (!iso) return '—'
  return `${String(iso).slice(0, 16).replace('T', ' ')}Z`
}

/** How many words the statement contains. Empty and whitespace-only are zero. */
export function countWords(text) {
  return (text || '').trim().split(/\s+/).filter(Boolean).length
}

/**
 * Whether a statement clears the gate before it is allowed to reach a decider.
 * The threshold is supplied by the backend (`min_statement_words`) and defaults to
 * the same 25 the server enforces, so a caller that forgets to pass it behaves the
 * way the server behaves rather than permissively.
 */
export function meetsStatementMinimum(text, minimum = 25) {
  return countWords(text) >= Number(minimum)
}

/** Chip labels for the locked-access states, shared with the API's vocabulary. */
export const LOCKED_STATE_LABEL = {
  locked: 'Locked',
  pending: 'Requested',
  awaiting_bank: 'Awaiting the bank',
  granted: 'Released',
  rejected: 'Refused',
  expired: 'Lapsed',
}
