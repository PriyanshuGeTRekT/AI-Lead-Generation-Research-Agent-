import { useApp } from '../../store/AppContext'

export default function StatsPanel() {
  const { leads, health } = useApp()
  const total = leads.length
  const ready = leads.filter((l) => l.status === 'outreach_ready').length
  const pending = leads.filter((l) => l.status === 'pending_review').length
  const disq = leads.filter((l) => l.status === 'disqualified').length
  const contact = leads.filter(
    (l) => (l.contact_emails || []).length > 0 || (l.phone && l.phone.trim()),
  ).length
  const dm = leads.filter((l) => l.decision_maker_full_name || l.decision_maker_name).length
  const seq = leads.filter(
    (l) => l.outreach_draft?.email_body || (l.follow_up_sequence?.length || 0) > 0,
  ).length
  const scores = leads.map((l) => l.qualification_score).filter((s): s is number => s != null)
  const avg = scores.length ? (scores.reduce((a, b) => a + b, 0) / scores.length).toFixed(1) : '—'

  const rows: [string, string | number, string][] = [
    ['Total leads', total, 'ink'],
    ['Outreach ready', ready, 'green'],
    ['Pending review', pending, 'amber'],
    ['Disqualified', disq, 'red'],
    ['With contact info', contact, 'ink'],
    ['DM found (LinkedIn)', dm, 'purple'],
    ['Sequences generated', seq, 'green'],
    ['Avg score', avg !== '—' ? `${avg}/10` : '—', 'amber'],
    ['Redis', health.redis, health.redis === 'connected' ? 'green' : 'amber'],
  ]

  return (
    <div className="card panel">
      <div className="section-label">Last Run Stats</div>
      <div className="pill-rows">
        {rows.map(([label, val, color]) => (
          <div className="stat-pill" key={label}>
            <span className="pill-label">{label}</span>
            <span className={'pill-val ' + color}>{val}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
