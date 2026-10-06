import { useEffect, useRef, useMemo } from 'react'

const BANK_COLORS = {
  bank_a: '#5b93f8',
  bank_b: '#a78bfa',
  bank_c: '#d4a843',
  bank_d: '#22c58a',
  bank_e: '#e8a33d',
}

const BANK_NAMES = {
  bank_a: 'HDFC Bank',
  bank_b: 'ICICI Bank',
  bank_c: 'Axis Bank',
  bank_d: 'Kotak Bank',
  bank_e: 'SBI',
}

export default function NetworkGraph({ network }) {
  const containerRef = useRef(null)
  const networkRef = useRef(null)

  const nodes = useMemo(() => {
    if (!network?.nodes) return []
    const seen = new Set()
    return network.nodes.filter((n) => {
      if (seen.has(n.id)) return false
      seen.add(n.id)
      return true
    }).map((n) => ({
      id: n.id,
      label: n.label || n.id,
      // Restricted subjects keep their place in the network but lose their identity and
      // quantities: the relationship matters, the person's details do not appear until an
      // authorisation covers them.
      color: n.restricted
        ? (n.authorized ? { background: '#14342a', border: '#22c58a' }
                        : { background: '#20242c', border: '#6d7688' })
        : (BANK_COLORS[n.bank_id] || '#5b93f8'),
      size: n.restricted
        ? 20
        : Math.max(15, Math.min(30, 15 + (n.transaction_count || 0) * 2)),
      font: { color: n.restricted ? '#aeb7c8' : '#d9dee8', size: 11 },
      shape: n.type === 'business' && !n.restricted ? 'diamond' : 'dot',
      borderWidth: 2,
      borderWidthSelected: 3,
      shapeProperties: { borderDashes: n.restricted && !n.authorized },
      title: n.restricted && !n.authorized
        ? 'Restricted subject information — an approved authorisation is required'
        : (n.authorized ? `Authorised under ${n.authorized_under || 'an approval'}` : undefined),
    }))
  }, [network?.nodes])

  const edges = useMemo(() => {
    if (!network?.edges) return []
    return network.edges.map((e, i) => ({
      id: `e${i}`,
      from: e.source,
      to: e.target,
      label: e.total_amount ? `₹${(e.total_amount / 1000).toFixed(0)}K` : '',
      color: { color: '#3a4150', highlight: '#e9edf5' },
      font: { size: 9, color: '#8d97ac', strokeWidth: 0 },
      arrows: { to: { enabled: true, scaleFactor: 0.5 } },
      smooth: { type: 'cubicBezier', roundness: 0.4 },
      width: Math.max(1, Math.min(4, (e.weight || 1) * 1.5)),
    }))
  }, [network?.edges])

  useEffect(() => {
    if (!containerRef.current || !nodes.length) return

    import('vis-network/standalone').then(({ Network, DataSet }) => {
      const nodeDataSet = new DataSet(nodes)
      const edgeDataSet = new DataSet(edges)

      if (networkRef.current) {
        networkRef.current.setData({ nodes: nodeDataSet, edges: edgeDataSet })
        return
      }

      networkRef.current = new Network(containerRef.current, {
        nodes: nodeDataSet,
        edges: edgeDataSet,
      }, {
        physics: {
          enabled: true,
          barnesHut: { gravitationalConstant: -3000, centralGravity: 0.3, springLength: 150, springConstant: 0.02 },
          stabilization: { iterations: 100 },
        },
        interaction: { hover: true, tooltipDelay: 200, zoomView: true, dragView: true },
        edges: { smooth: { type: 'cubicBezier', roundness: 0.4 } },
      })
    }).catch(() => {})

    return () => {
      if (networkRef.current) {
        networkRef.current.destroy()
        networkRef.current = null
      }
    }
  }, [nodes, edges])

  const uniqueBanks = [...new Set((network?.nodes || [])
    .filter((n) => n.bank_id && !n.restricted)
    .map((n) => n.bank_id))]
  const restrictedCount = network?.restricted?.masked || 0
  const authorizedCount = network?.restricted?.authorized || 0

  return (
    <div className="graph-container">
      <div className="graph-header">
        <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--gray-700)' }}>Network Graph</div>
        <div style={{ fontSize: 12, color: 'var(--gray-500)' }}>
          {nodes.length} nodes · {edges.length} edges
        </div>
      </div>
      <div ref={containerRef} className="graph-canvas" />
      <div className="graph-legend">
        {uniqueBanks.map((bid) => (
          <div key={bid} className="legend-item">
            <div className="legend-dot" style={{ background: BANK_COLORS[bid] || '#999' }} />
            <span>{BANK_NAMES[bid] || bid}</span>
          </div>
        ))}
        <div className="legend-item">
          <div className="legend-dot" style={{ background: 'var(--gray-300)', border: '2px dashed var(--gray-400)', width: 14, height: 14 }} />
          <span>Suspicion Link</span>
        </div>
        {restrictedCount > 0 && (
          <div className="legend-item">
            <div className="legend-dot" style={{ background: '#20242c', border: '2px dashed #6d7688', width: 14, height: 14 }} />
            <span>🔒 Restricted information ({restrictedCount})</span>
          </div>
        )}
        {authorizedCount > 0 && (
          <div className="legend-item">
            <div className="legend-dot" style={{ background: '#14342a', border: '2px solid #22c58a', width: 14, height: 14 }} />
            <span>🔓 Authorised information ({authorizedCount})</span>
          </div>
        )}
      </div>
      {network?.notice && <div className="graph-notice">{network.notice}</div>}
    </div>
  )
}
