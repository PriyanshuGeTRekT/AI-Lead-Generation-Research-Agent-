import type { TheaterEvent } from '../../types'

const NODES = [
  { key: 'research', label: 'Research', x: 18, sub: 'discover + extract' },
  { key: 'qualify', label: 'Qualify', x: 50, sub: 'debate scoring' },
  { key: 'sales', label: 'Sales', x: 82, sub: 'sim + sequence' },
] as const

type NodeState = 'wait' | 'active' | 'done'

export default function GraphFlow({ events }: { events: TheaterEvent[] }) {
  // Derive each node's state from the latest stage events.
  const state: Record<string, NodeState> = { research: 'wait', qualify: 'wait', sales: 'wait' }
  const order = ['research', 'qualify', 'sales']
  let activeIdx = -1
  for (const e of events) {
    const i = order.indexOf(e.stage)
    if (e.type === 'stage_start' && i >= 0) {
      activeIdx = i
      for (let k = 0; k < i; k++) state[order[k]] = 'done'
      state[order[i]] = 'active'
    }
    if (e.type === 'stage_end' && i >= 0) state[order[i]] = 'done'
    if (e.type === 'done') {
      order.forEach((o) => (state[o] = 'done'))
      activeIdx = order.length
    }
  }
  void activeIdx

  return (
    <svg viewBox="0 0 100 26" className="graph-flow" preserveAspectRatio="xMidYMid meet">
      <line x1="18" y1="13" x2="50" y2="13" className={'edge ' + (state.qualify !== 'wait' ? 'lit' : '')} />
      <line x1="50" y1="13" x2="82" y2="13" className={'edge ' + (state.sales !== 'wait' ? 'lit' : '')} />
      {NODES.map((n) => {
        const st = state[n.key]
        return (
          <g key={n.key} transform={`translate(${n.x} 13)`} className={'gnode ' + st}>
            <circle r={7} className="gnode-c" />
            {st === 'active' && <circle r={7} className="gnode-ring" />}
            <text y={-10} className="gnode-label">
              {n.label}
            </text>
            <text y={13} className="gnode-sub">
              {n.sub}
            </text>
            <text y={1.4} className="gnode-icon">
              {st === 'done' ? '✓' : st === 'active' ? '⟳' : '○'}
            </text>
          </g>
        )
      })}
    </svg>
  )
}
