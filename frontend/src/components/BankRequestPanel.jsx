import { useState, useEffect } from 'react'
import { fetchMockBankEndpoints } from '../api.js'

function JsonBlock({ data, label }) {
  const [expanded, setExpanded] = useState(false)
  return (
    <div style={{ marginTop: 8 }}>
      {label && (
        <div
          style={{
            fontSize: 11,
            fontWeight: 600,
            color: 'var(--text-muted)',
            cursor: 'pointer',
            textTransform: 'uppercase',
            letterSpacing: '0.06em',
          }}
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? '▾' : '▸'} {label}
        </div>
      )}
      {expanded && (
        <pre style={{
          background: 'var(--bg-primary)',
          padding: 12,
          borderRadius: 'var(--radius)',
          fontSize: 11,
          fontFamily: 'var(--font-mono)',
          color: 'var(--text-secondary)',
          overflow: 'auto',
          maxHeight: 300,
          marginTop: 8,
          lineHeight: 1.5,
        }}>
          {JSON.stringify(data, null, 2)}
        </pre>
      )}
    </div>
  )
}

export default function BankRequestPanel({ bankResponses, investigationResult, caseData }) {
  const [endpoints, setEndpoints] = useState(null)

  useEffect(() => {
    fetchMockBankEndpoints().then(setEndpoints)
  }, [])

  return (
    <>
      {/* Mock bank endpoints overview */}
      <div className="bank-request-panel">
        <div className="bank-request-title">
          🔌 Mock Bank API Endpoints
        </div>
        <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 16 }}>
          These are simulated bank endpoints for demo purposes. In production, swap for real APIs.
        </div>
        {endpoints && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 12 }}>
            {Object.entries(endpoints).map(([bankId, info]) => (
              <div key={bankId} className="request-box">
                <div className="request-box-label">{info.name}</div>
                <div className="request-box-content">
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, marginBottom: 8, color: 'var(--accent-green)' }}>
                    {info.api_base}
                  </div>
                  <div style={{ fontSize: 12 }}>
                    Status: <span style={{ color: 'var(--accent-green)' }}>{info.status}</span>
                  </div>
                  <div style={{ fontSize: 12, marginTop: 4 }}>
                    Capabilities: {info.capabilities.join(', ')}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Context verification responses */}
      {bankResponses.length > 0 && (
        <div className="bank-request-panel">
          <div className="bank-request-title">
            📨 Context Verification Responses
          </div>
          {bankResponses.map((resp, i) => (
            <div key={i} style={{
              padding: 16,
              background: 'var(--bg-card)',
              borderRadius: 'var(--radius)',
              border: '1px solid var(--border)',
              marginBottom: 12,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                <div>
                  <span style={{ fontWeight: 600, fontSize: 13 }}>
                    Request to {resp.response.responding_bank}
                  </span>
                  <span style={{
                    marginLeft: 8,
                    padding: '2px 8px',
                    borderRadius: 4,
                    fontSize: 11,
                    background: 'rgba(34, 197, 94, 0.1)',
                    color: 'var(--accent-green)',
                  }}>
                    {resp.response.status}
                  </span>
                </div>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)' }}>
                  {resp.request.request_id}
                </span>
              </div>
              <div className="request-flow">
                <div className="request-box" style={{ flex: 1 }}>
                  <div className="request-box-label">Request Sent</div>
                  <div className="request-box-content">
                    <div>Type: <code>{resp.request.type}</code></div>
                    <div>Entity: <code>{resp.request.entity_id}</code></div>
                    <div>Reason: {resp.request.reason}</div>
                    <div>Fields: {resp.request.requested_fields.join(', ')}</div>
                  </div>
                </div>
                <div className="flow-arrow">→</div>
                <div className="request-box" style={{ flex: 1 }}>
                  <div className="request-box-label">Bank Response</div>
                  <div className="request-box-content">
                    {Object.entries(resp.response.data).filter(([k]) => !k.includes('additional')).map(([key, val]) => (
                      <div key={key} style={{ marginBottom: 4 }}>
                        <span style={{ color: 'var(--text-muted)' }}>{key}: </span>
                        <span style={{ color: 'var(--text-primary)' }}>{String(val)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
              {resp.response.data.additional_context && (
                <div style={{
                  padding: 12,
                  background: 'var(--bg-primary)',
                  borderRadius: 'var(--radius)',
                  borderLeft: '3px solid var(--accent-blue)',
                  marginTop: 8,
                }}>
                  <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--accent-blue)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                    Additional Context from {resp.response.responding_bank}
                  </div>
                  <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 4 }}>
                    {resp.response.data.additional_context}
                  </div>
                </div>
              )}
              <JsonBlock data={resp} label="Full Request/Response" />
            </div>
          ))}
        </div>
      )}

      {/* Investigation result */}
      {investigationResult && (
        <div className="bank-request-panel">
          <div className="bank-request-title">
            🔍 Investigation Results
          </div>
          <div style={{
            padding: 16,
            background: 'var(--bg-card)',
            borderRadius: 'var(--radius)',
            border: '1px solid var(--border)',
            marginBottom: 12,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
              <span style={{ fontWeight: 600, fontSize: 14 }}>
                Investigation Request
              </span>
              <span className="risk-badge risk-critical">
                {investigationResult.request.priority} priority
              </span>
            </div>
            <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 12 }}>
              {investigationResult.request.reason}
            </div>

            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>
              Entities under review: {investigationResult.request.entities_under_review.join(', ')}
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 16 }}>
              Legal basis: {investigationResult.request.legal_basis}
            </div>

            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 12 }}>
              Bank Responses:
            </div>
            {Object.entries(investigationResult.responses).map(([bankId, resp]) => (
              <div key={bankId} style={{
                padding: 16,
                background: 'var(--bg-primary)',
                borderRadius: 'var(--radius)',
                marginBottom: 12,
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                  <span style={{ fontWeight: 600, fontSize: 13 }}>{bankId}</span>
                  <span style={{
                    padding: '2px 8px',
                    borderRadius: 4,
                    fontSize: 11,
                    background: 'rgba(34, 197, 94, 0.1)',
                    color: 'var(--accent-green)',
                  }}>
                    {resp.status}
                  </span>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, fontSize: 12 }}>
                  <div>
                    <div style={{ color: 'var(--text-muted)' }}>Linked entities</div>
                    <div style={{ color: 'var(--text-primary)' }}>
                      {resp.data.entities_linked?.join(', ') || 'N/A'}
                    </div>
                  </div>
                  <div>
                    <div style={{ color: 'var(--text-muted)' }}>90-day transactions</div>
                    <div style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
                      {resp.data.transaction_count_90d || 'N/A'}
                    </div>
                  </div>
                  <div>
                    <div style={{ color: 'var(--text-muted)' }}>Cross-border txns</div>
                    <div style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
                      {resp.data.cross_border_transactions || 0}
                    </div>
                  </div>
                  <div>
                    <div style={{ color: 'var(--text-muted)' }}>Crypto-related</div>
                    <div style={{ color: 'var(--accent-red)', fontFamily: 'var(--font-mono)' }}>
                      {resp.data.crypto_related_transactions || 0}
                    </div>
                  </div>
                </div>
                {resp.data.device_profiles && (
                  <div style={{ marginTop: 12 }}>
                    <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 4 }}>
                      Device Profiles
                    </div>
                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                      {resp.data.device_profiles.map((d, i) => (
                        <div key={i} style={{
                          padding: '4px 8px',
                          background: 'var(--bg-card)',
                          borderRadius: 4,
                          fontSize: 11,
                          border: `1px solid ${d.trusted ? 'rgba(34, 197, 94, 0.3)' : 'rgba(239, 68, 68, 0.3)'}`,
                        }}>
                          <span style={{ fontFamily: 'var(--font-mono)' }}>{d.device_id}</span>
                          <span style={{ color: 'var(--text-muted)', margin: '0 4px' }}>•</span>
                          <span style={{ color: d.trusted ? 'var(--accent-green)' : 'var(--accent-red)' }}>
                            {d.trusted ? 'Trusted' : 'New'}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
          <JsonBlock data={investigationResult} label="Full Investigation Response" />
        </div>
      )}

      {bankResponses.length === 0 && !investigationResult && (
        <div className="bank-request-panel">
          <div className="bank-request-title">📬 No Bank Requests Yet</div>
          <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
            Use the action buttons in the case header to send context verification or investigation requests to the mock bank APIs.
          </div>
        </div>
      )}
    </>
  )
}
