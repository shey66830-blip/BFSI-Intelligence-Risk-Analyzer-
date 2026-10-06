/**
 * Renders a field that may have been redacted by the privacy policy.
 *
 * Redaction is applied by the backend (see backend/services/privacy.py) *before*
 * the response is serialised, so the browser never holds a value the session is
 * not entitled to. This component therefore does not mask anything itself — it
 * shows exactly what it was sent, and marks fields the server declared as
 * redacted so the viewer knows the value was withheld rather than missing.
 */
export function MaskedField({ value, type = 'text', currency = '₹', className = '', redacted = false }) {
  if (value === null || value === undefined || value === '') {
    return <span className="mono-muted">—</span>
  }

  const display = type === 'amount'
    ? `${currency}${Number(value).toLocaleString('en-IN')}`
    : String(value)

  return (
    <span
      className={`${className} ${redacted ? 'redacted-by-policy' : ''}`.trim()}
      title={redacted ? 'Redacted by the privacy policy for your role' : undefined}
    >
      {display}
    </span>
  )
}

export default MaskedField
