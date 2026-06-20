import { useApp } from '../store/AppContext'
import { fmtMs } from '../lib/format'
import Gauge from './Gauge'
import CountUp from './CountUp'

export default function MetricsStrip() {
  const { leads, pipeline, poolStats } = useApp()
  // Show the TRUE warehouse-wide totals (905k+), not just the browser slice. Fall
  // back to the loaded slice only before the warehouse stats have loaded.
  const total = poolStats.total || leads.length
  const qualified = poolStats.qualified || leads.filter((l) => l.status === 'qualified').length
  const ready = poolStats.outreach_ready || leads.filter((l) => l.status === 'outreach_ready').length
  const withEmail = poolStats.with_email || leads.filter((l) => (l.contact_emails || []).length > 0).length
  const withPhone = poolStats.with_phone || leads.filter((l) => l.phone && l.phone.trim()).length
  const scores = leads.map((l) => l.qualification_score).filter((s): s is number => s != null)
  const avg = scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : null

  const cards: [number, string][] = [
    [total, 'Total Leads'],
    [qualified, 'Qualified'],
    [ready, 'Outreach Ready'],
    [withEmail, 'With Email'],
    [withPhone, 'With Phone'],
  ]

  return (
    <div className="metrics-strip">
      {cards.map(([val, label], i) => (
        <div className="metric-card" key={label} style={{ animationDelay: `${i * 0.05}s` }}>
          <div className="mc-val">
            <CountUp value={val} />
          </div>
          <div className="mc-label">{label}</div>
        </div>
      ))}
      <Gauge
        value={avg}
        label="Lead Quality"
        caption={
          <>
            Avg score across all leads
            <br />
            Last run ·{' '}
            <b style={{ color: 'var(--ink)' }}>
              {pipeline.lastDurationMs ? fmtMs(pipeline.lastDurationMs) : '—'}
            </b>
          </>
        }
      />
    </div>
  )
}
