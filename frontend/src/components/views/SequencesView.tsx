import { useApp } from '../../store/AppContext'
import type { Lead } from '../../types'

const SUBLABEL: Record<number, string> = { 1: 'Cold intro', 3: 'Follow-up', 7: 'Value', 14: 'Break-up' }

function touches(l: Lead) {
  const d = l.outreach_draft
  if (!d?.email_body) return []
  const seq = l.follow_up_sequence || []
  return [
    { day: 1, subject: d.subject || '', body: d.email_body },
    ...seq.map((s) => ({ day: s.day, subject: s.subject || '', body: s.email_body || '' })),
  ]
}

export default function SequencesView() {
  const { leads } = useApp()
  const withSeq = leads.filter((l) => l.outreach_draft?.email_body)

  if (!withSeq.length) {
    return (
      <div className="crm-empty">
        No outreach sequences yet. Qualified leads get a 4-touch email cadence (Day 1 / 3 / 7 / 14) from the Sales agent — run a search to generate them.
      </div>
    )
  }

  return (
    <div className="seq-list">
      {withSeq.map((l) => (
        <div className="seq-card card" key={l.id || l.company_name}>
          <div className="seq-card-head">
            <div>
              <div className="seq-company">{l.company_name}</div>
              <div className="seq-to">
                To: {l.decision_maker_full_name || l.decision_maker_name || 'decision maker'}
                {(l.contact_emails || [])[0] ? ` · ${(l.contact_emails || [])[0]}` : ''}
              </div>
            </div>
            <span className="seq-badge">{touches(l).length}-touch</span>
          </div>
          <div className="seq-touches">
            {touches(l).map((t, i) => (
              <details className="seq-touch" key={i} open={i === 0}>
                <summary>
                  <span className="seq-day">Day {t.day}</span>
                  <span className="seq-sublabel">{SUBLABEL[t.day] || 'Touch'}</span>
                  <span className="seq-subject">{t.subject}</span>
                  <button
                    className="seq-copy"
                    onClick={(e) => {
                      e.preventDefault()
                      navigator.clipboard?.writeText(`Subject: ${t.subject}\n\n${t.body}`)
                    }}
                  >
                    Copy
                  </button>
                </summary>
                <pre className="seq-body">{t.body}</pre>
              </details>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}
