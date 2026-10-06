/**
 * Consent badge showing the consent status of a transaction.
 * ✅ Valid — consent given and active
 * ⚠ Expiring — consent given but approaching expiry
 * ❌ Expired — no consent or consent has expired
 */

export default function ConsentBadge({ consentGiven, consentExpiry }) {
  // Determine status
  let status = 'valid'
  let label = 'Consent active'
  let icon = '✓'

  if (!consentGiven) {
    status = 'expired'
    label = 'No consent'
    icon = '✗'
  } else if (consentExpiry) {
    const expiryDate = new Date(consentExpiry)
    const now = new Date()
    const daysLeft = (expiryDate - now) / (1000 * 60 * 60 * 24)

    if (daysLeft < 0) {
      status = 'expired'
      label = 'Consent expired'
      icon = '✗'
    } else if (daysLeft < 30) {
      status = 'expiring'
      label = `Consent expires in ${Math.ceil(daysLeft)}d`
      icon = '⚠'
    }
  }

  return (
    <span className={`consent-badge ${status}`} title={label}>
      <span>{icon}</span>
      <span>{label}</span>
    </span>
  )
}
