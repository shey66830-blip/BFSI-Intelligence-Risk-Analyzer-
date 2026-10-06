import { useRef, useEffect, useState } from 'react'

const BANK_COLORS = {
  bank_a: '#5b93f8',
  bank_b: '#a78bfa',
  bank_c: '#d4a843',
}

const TYPE_SHAPES = {
  individual: 'dot',
  business: 'diamond',
  counterparty: 'triangle',
  device: 'square',
}

export default function GraphView({ graphData, onBack }) {
  const containerRef = useRef(null)
  const networkRef = useRef(null)
  const [hoveredNode, setHoveredNode] = useState(null)

  useEffect(() => {
    if (!containerRef.current || !graphData?.nodes?.length) return

    import('vis-network/standalone').then(({ Network, DataSet }) => {
      const seen = new Set()
      const uniqueNodes = graphData.nodes.filter((n) => {
        if (seen.has(n.id)) return false
        seen.add(n.id)
        return true
      })

      const nodes = new DataSet(
        uniqueNodes.map((n) => ({
          id: n.id,
          label: n.label,
          color: {
            background: BANK_COLORS[n.bank_id] || '#6b7280',
            border: BANK_COLORS[n.bank_id] || '#6b7280',
            highlight: { background: '#e9edf5', border: BANK_COLORS[n.bank_id] || '#8d97ac' },
          },
          shape: TYPE_SHAPES[n.type] || 'dot',
          size: n.type === 'counterparty' ? 18 : n.type === 'device' ? 14 : 28,
          font: { color: '#e9edf5', size: 12, face: 'Inter' },
          borderWidth: 2,
          shadow: true,
          title: `${n.label}\nType: ${n.type}\nTransactions: ${n.transaction_count || 0}\nVolume: ₹${(n.total_volume || 0).toLocaleString()}`,
        }))
      )

      const seenEdges = new Set()
      const uniqueEdges = graphData.edges.filter((e) => {
        const key = `${e.source}|${e.target}|${e.edge_type}`
        if (seenEdges.has(key)) return false
        seenEdges.add(key)
        return true
      })

      const edgeColors = {
        transaction: '#3a4150',
        shared_device: '#a78bfa',
        shared_counterparty: '#e8a33d',
        cross_bank_flow: '#f0665a',
      }

      const edges = new DataSet(
        uniqueEdges.map((e, i) => ({
          id: i,
          from: e.source,
          to: e.target,
          label: e.edge_type === 'transaction' ? `₹${(e.total_amount || 0).toLocaleString()}` : '',
          color: { color: edgeColors[e.edge_type] || '#3a4150', highlight: '#e9edf5' },
          width: e.weight > 1 ? Math.min(e.weight, 4) : 1.5,
          dashes: e.edge_type !== 'transaction',
          arrows: { to: { enabled: true, scaleFactor: 0.5 } },
          font: {
            color: '#8d97ac',
            size: 10,
            face: 'JetBrains Mono',
            strokeWidth: 3,
            strokeColor: '#0a0b0f',
            align: 'middle',
          },
          smooth: { type: 'curvedCW', roundness: 0.2 },
          title: `${e.edge_type}\nWeight: ${e.weight}\nAmount: ₹${(e.total_amount || 0).toLocaleString()}`,
        }))
      )

      const options = {
        physics: {
          barnesHut: {
            gravitationalConstant: -3000,
            centralGravity: 0.3,
            springLength: 200,
            springConstant: 0.04,
            damping: 0.09,
          },
          stabilization: { iterations: 200 },
        },
        interaction: {
          hover: true,
          tooltipDelay: 200,
          zoomView: true,
          dragView: true,
        },
      }

      if (networkRef.current) networkRef.current.destroy()
      networkRef.current = new Network(containerRef.current, { nodes, edges }, options)

      networkRef.current.on('hoverNode', (params) => {
        const node = graphData.nodes.find((n) => n.id === params.node)
        setHoveredNode(node)
      })
      networkRef.current.on('blurNode', () => setHoveredNode(null))
    })

    return () => {
      if (networkRef.current) {
        networkRef.current.destroy()
        networkRef.current = null
      }
    }
  }, [graphData])

  if (!graphData?.nodes?.length) {
    return (
      <div>
        <button className="btn btn-ghost" onClick={onBack} style={{ marginBottom: 16 }}>
          ← Back to Dashboard
        </button>
        <div className="pipeline-empty">No graph data available.</div>
      </div>
    )
  }

  const meta = graphData.metadata || {}
  const clusters = graphData.clusters || []
  const cycles = graphData.circular_flows || []

  return (
    <div>
      <div style={{ marginBottom: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, fontSize: 12, color: 'var(--gray-500)' }}>
          <button className="btn btn-ghost btn-sm" onClick={onBack}>Dashboard</button>
          <span>/</span>
          <span style={{ color: 'var(--ink)', fontWeight: 600 }}>Network Graph</span>
        </div>
        <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--ink)' }}>Network Intelligence Graph</div>
        <div style={{ fontSize: 13, color: 'var(--gray-500)', marginTop: 4 }}>
          Behavioral relationships across banks, entities, devices, and counterparties
        </div>
      </div>

      {/* Metadata cards */}
      <div className="stats-grid" style={{ marginBottom: 20 }}>
        <div className="stat-card">
          <div className="stat-label">Nodes</div>
          <div className="stat-value">{meta.total_nodes || graphData.nodes.length}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Edges</div>
          <div className="stat-value gold">{meta.total_edges || graphData.edges.length}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Clusters</div>
          <div className="stat-value green">{clusters.length}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Circular Flows</div>
          <div className="stat-value" style={{ color: 'var(--red)' }}>{cycles.length}</div>
        </div>
      </div>

      {/* Graph */}
      <div className="graph-container">
        <div className="graph-header">
          <div>
            <div style={{ fontWeight: 600, fontSize: 14, color: 'var(--gray-700)' }}>Entity Relationship Graph</div>
            <div style={{ fontSize: 12, color: 'var(--gray-500)', marginTop: 2 }}>
              Drag nodes, scroll to zoom, hover for details
            </div>
          </div>
        </div>
        <div ref={containerRef} className="graph-canvas" style={{ height: 500 }} />
        <div className="graph-legend">
          <div className="legend-item">
            <div className="legend-dot" style={{ background: BANK_COLORS.bank_a }} />
            <span>HDFC Bank</span>
          </div>
          <div className="legend-item">
            <div className="legend-dot" style={{ background: BANK_COLORS.bank_b }} />
            <span>ICICI Bank</span>
          </div>
          <div className="legend-item">
            <div className="legend-dot" style={{ background: BANK_COLORS.bank_c }} />
            <span>Axis Bank</span>
          </div>
          <div className="legend-item">
            <div className="legend-dot" style={{ background: '#6b7280' }} />
            <span>External</span>
          </div>
          <div className="legend-item">
            <div style={{ width: 20, height: 2, background: '#f0665a' }} />
            <span>Cross-Bank Flow</span>
          </div>
          <div className="legend-item">
            <div style={{ width: 20, height: 0, borderTop: '2px dashed #e8a33d' }} />
            <span>Shared Counterparty</span>
          </div>
        </div>
      </div>

      {/* Node details on hover */}
      {hoveredNode && (
        <div className="card" style={{ marginTop: 12 }}>
          <div style={{ fontWeight: 700, fontSize: 15, color: 'var(--ink)' }}>{hoveredNode.label}</div>
          <div style={{ display: 'flex', gap: 16, marginTop: 6, color: 'var(--gray-500)', fontSize: 13 }}>
            <span>Type: {hoveredNode.type}</span>
            <span>Bank: {hoveredNode.bank_id || 'N/A'}</span>
            <span>Transactions: {hoveredNode.transaction_count}</span>
            <span>Volume: ₹{(hoveredNode.total_volume || 0).toLocaleString()}</span>
          </div>
          {hoveredNode.first_seen && (
            <div style={{ marginTop: 4, fontSize: 12, color: 'var(--gray-400)' }}>
              First seen: {hoveredNode.first_seen?.slice(0, 10)} · Last seen: {hoveredNode.last_seen?.slice(0, 10)}
            </div>
          )}
        </div>
      )}

      {/* Clusters */}
      {clusters.length > 0 && (
        <div className="card" style={{ marginTop: 16 }}>
          <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 12, color: 'var(--ink)' }}>Network Clusters</div>
          {clusters.map((cluster) => (
            <div key={cluster.cluster_id} style={{
              padding: '10px 14px',
              background: 'var(--gray-50)',
              borderRadius: 'var(--radius-md)',
              marginBottom: 8,
              fontSize: 13,
              border: '1px solid var(--gray-200)',
            }}>
              <span style={{ fontWeight: 600 }}>{cluster.cluster_id}</span>
              <span style={{ color: 'var(--gray-400)', margin: '0 8px' }}>·</span>
              <span style={{ color: 'var(--gray-600)' }}>
                {cluster.size} entities: {cluster.entities.join(', ')}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Circular flows */}
      {cycles.length > 0 && (
        <div className="card" style={{ marginTop: 16, borderColor: 'var(--red)' }}>
          <div style={{ fontWeight: 600, fontSize: 14, color: 'var(--red)', marginBottom: 12 }}>
            ⚠ Circular Fund Flows Detected
          </div>
          {cycles.map((cycle, i) => (
            <div key={i} style={{
              padding: '10px 14px',
              background: 'var(--red-light)',
              borderRadius: 'var(--radius-md)',
              marginBottom: 8,
              fontSize: 13,
              fontFamily: 'var(--font-mono)',
              color: 'var(--red)',
            }}>
              Cycle {i + 1}: {cycle.join(' → ')} → {cycle[0]}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
