import { useState } from 'react'
import { MaskedField } from './MaskedField.jsx'
import ConsentBadge from './ConsentBadge.jsx'

export default function TransactionTable({ transactions }) {
  const [sortField, setSortField] = useState('timestamp')
  const [sortDir, setSortDir] = useState('desc')

  const sorted = [...transactions].sort((a, b) => {
    let va = a[sortField], vb = b[sortField]
    if (sortField === 'amount') { va = Number(va) || 0; vb = Number(vb) || 0 }
    if (va < vb) return sortDir === 'asc' ? -1 : 1
    if (va > vb) return sortDir === 'asc' ? 1 : -1
    return 0
  })

  const toggleSort = (field) => {
    if (sortField === field) setSortDir(sortDir === 'asc' ? 'desc' : 'asc')
    else { setSortField(field); setSortDir('desc') }
  }

  const sortIcon = (field) => {
    if (sortField !== field) return ''
    return sortDir === 'asc' ? ' ↑' : ' ↓'
  }

  if (!transactions.length) {
    return <div className="pipeline-empty">No transactions.</div>
  }

  return (
    <div className="table-container">
      <table>
        <thead>
          <tr>
            <th onClick={() => toggleSort('timestamp')} style={{ cursor: 'pointer' }}>Time{sortIcon('timestamp')}</th>
            <th onClick={() => toggleSort('amount')} style={{ cursor: 'pointer' }}>Amount{sortIcon('amount')}</th>
            <th>Type</th>
            <th>Description</th>
            <th>Entity</th>
            <th>Bank</th>
            <th>Counterparty</th>
            <th>Consent</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((t) => (
            <tr key={t.id}>
              <td className="mono" style={{ fontSize: 11, whiteSpace: 'nowrap' }}>
                {t.timestamp ? new Date(t.timestamp).toLocaleString('en-IN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—'}
              </td>
              <td style={{ fontWeight: 600, fontFamily: 'var(--font-mono)' }}>
                <MaskedField value={t.amount} type="amount" currency="₹" />
              </td>
              <td>
                <span style={{
                  padding: '2px 6px',
                  borderRadius: 4,
                  fontSize: 10,
                  fontWeight: 600,
                  textTransform: 'uppercase',
                  background: t.type === 'credit' ? 'var(--green-bg)' : 'var(--red-bg)',
                  color: t.type === 'credit' ? 'var(--green)' : 'var(--red)',
                }}>
                  {t.type}
                </span>
              </td>
              <td style={{ maxWidth: 200 }}>{t.description}</td>
              <td>
                <MaskedField
                  value={t.entity_name || t.entity_id}
                  type="name"
                  redacted={(t.redacted_fields || []).includes('entity_name')}
                />
              </td>
              <td>{t.bank_name || t.bank_id}</td>
              <td>
                <MaskedField
                  value={t.counterparty}
                  type="name"
                  redacted={(t.redacted_fields || []).includes('counterparty')}
                />
              </td>
              <td>
                <ConsentBadge consentGiven={t.consent_given} consentExpiry={t.consent_expiry} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
