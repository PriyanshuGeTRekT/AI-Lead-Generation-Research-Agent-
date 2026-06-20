import { api } from '../../api/client'

type Dash = Awaited<ReturnType<typeof api.crmDashboard>>

const FUNNEL: [string, string, string][] = [
  ['new', 'Not Contacted', '#b9a36b'],
  ['contacted', 'Contacted', '#d9a826'],
  ['in_loop', 'In the Loop', '#5b8def'],
  ['won', 'Won', '#2f9e5a'],
]

export default function CrmDashboard({ data, onJump }: { data: Dash | null; onJump: (stage: string) => void }) {
  const d = data
  if (!d) return <div className="dash-loading">Loading overview…</div>

  const maxFunnel = Math.max(d.stages.new, d.stages.contacted, d.stages.in_loop, d.stages.won, 1)
  const tierTotal = Object.values(d.tiers).reduce((a, b) => a + b, 0) || 1
  const kpis: { label: string; value: number | string; accent?: string; sub?: string }[] = [
    { label: 'Total Prospects', value: d.total.toLocaleString() },
    { label: '🔥 Hot', value: (d.tiers.Hot || 0).toLocaleString(), accent: 'hot' },
    { label: 'Contacted', value: d.stages.contacted.toLocaleString(), accent: 'gold' },
    { label: 'In the Loop', value: d.stages.in_loop.toLocaleString(), accent: 'blue' },
    { label: 'Won', value: d.stages.won.toLocaleString(), accent: 'green' },
    { label: 'Win Rate', value: `${d.win_rate}%`, accent: 'green', sub: 'of worked leads' },
  ]
  const maxInd = Math.max(...d.top_industries.map((x) => x.count), 1)
  const maxState = Math.max(...d.top_states.map((x) => x.count), 1)

  return (
    <div className="dash">
      {/* KPI cards */}
      <div className="dash-kpis">
        {kpis.map((k) => (
          <div className={'dash-kpi' + (k.accent ? ' k-' + k.accent : '')} key={k.label}>
            <div className="dk-val">{k.value}</div>
            <div className="dk-label">{k.label}</div>
            {k.sub && <div className="dk-sub">{k.sub}</div>}
          </div>
        ))}
      </div>

      <div className="dash-grid">
        {/* Pipeline funnel */}
        <div className="dash-card">
          <div className="dash-h">Sales Pipeline</div>
          <div className="funnel">
            {FUNNEL.map(([key, label, color]) => {
              const v = d.stages[key] || 0
              return (
                <button className="funnel-row" key={key} onClick={() => onJump(key)} title="View these leads">
                  <span className="funnel-label">{label}</span>
                  <span className="funnel-bar-wrap">
                    <span className="funnel-bar" style={{ width: `${Math.max((v / maxFunnel) * 100, 2)}%`, background: color }} />
                  </span>
                  <span className="funnel-val">{v.toLocaleString()}</span>
                </button>
              )
            })}
          </div>
          <div className="dash-foot">
            {d.with_email.toLocaleString()} reachable by email · {d.with_phone.toLocaleString()} by phone
          </div>
        </div>

        {/* Tier mix */}
        <div className="dash-card">
          <div className="dash-h">Lead Quality Mix</div>
          <div className="tier-bar">
            {(['Hot', 'Warm', 'Cold'] as const).map((t) => {
              const v = d.tiers[t] || 0
              const pct = (v / tierTotal) * 100
              return pct > 0 ? (
                <span key={t} className={'tier-seg ' + t.toLowerCase()} style={{ width: `${pct}%` }} title={`${t}: ${v.toLocaleString()}`} />
              ) : null
            })}
          </div>
          <div className="tier-legend">
            <span><i className="dot hot" /> Hot {(d.tiers.Hot || 0).toLocaleString()}</span>
            <span><i className="dot warm" /> Warm {(d.tiers.Warm || 0).toLocaleString()}</span>
            <span><i className="dot cold" /> Cold {(d.tiers.Cold || 0).toLocaleString()}</span>
          </div>
        </div>

        {/* Top industries */}
        <div className="dash-card">
          <div className="dash-h">Top Industries</div>
          <div className="minibars">
            {d.top_industries.map((x) => (
              <div className="minibar" key={x.name}>
                <span className="mb-label">{x.name}</span>
                <span className="mb-track"><span className="mb-fill" style={{ width: `${(x.count / maxInd) * 100}%` }} /></span>
                <span className="mb-val">{x.count.toLocaleString()}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Top states */}
        <div className="dash-card">
          <div className="dash-h">Top States</div>
          <div className="minibars">
            {d.top_states.map((x) => (
              <div className="minibar" key={x.name}>
                <span className="mb-label">{x.name}</span>
                <span className="mb-track"><span className="mb-fill alt" style={{ width: `${(x.count / maxState) * 100}%` }} /></span>
                <span className="mb-val">{x.count.toLocaleString()}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
