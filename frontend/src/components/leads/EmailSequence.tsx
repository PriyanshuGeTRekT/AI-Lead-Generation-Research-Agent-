import { useMemo, useState } from 'react'
import type { Lead } from '../../types'

interface Touch {
  label: string
  sub: string
  subject?: string
  body?: string
}

export default function EmailSequence({ lead }: { lead: Lead }) {
  const draft = lead.outreach_draft
  const touches = useMemo<Touch[]>(() => {
    if (!draft?.email_body) return []
    const seq = lead.follow_up_sequence || []
    return [
      { label: 'Day 1', sub: 'Cold Intro', subject: draft.subject, body: draft.email_body },
      ...seq.map((s) => ({
        label: `Day ${s.day}`,
        sub: s.day === 3 ? 'Follow-up' : s.day === 7 ? 'Value Email' : 'Break-up',
        subject: s.subject,
        body: s.email_body,
      })),
    ]
  }, [draft, lead.follow_up_sequence])

  const [active, setActive] = useState(0)
  const [copied, setCopied] = useState(false)
  if (!touches.length) return null

  const cur = touches[active]
  const action = draft?.hallucination_action
  const warn = action === 'warn' || action === 'reject'

  const copy = () => {
    navigator.clipboard.writeText(cur.body || '')
    setCopied(true)
    setTimeout(() => setCopied(false), 1800)
  }

  return (
    <div className="seq">
      {warn && (
        <div className={'halluc ' + action}>
          {action === 'reject' ? '❌' : '⚠️'} Hallucination guard: {action?.toUpperCase()}
          {(draft?.hallucination_warnings || []).length > 0 && (
            <ul>
              {draft!.hallucination_warnings!.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      <div className="seq-tabs">
        {touches.map((t, i) => (
          <button
            key={i}
            className={'seq-tab' + (i === active ? ' active' : '')}
            onClick={() => setActive(i)}
          >
            {t.label}
            <span className="seq-sub">{t.sub}</span>
          </button>
        ))}
      </div>
      <div className="email-subject">
        <span>Subject: </span>
        {cur.subject || '(no subject)'}
      </div>
      <pre className="email-text">{cur.body}</pre>
      <button className={'copy-btn' + (copied ? ' copied' : '')} onClick={copy}>
        {copied ? '✓ Copied!' : 'Copy'}
      </button>
    </div>
  )
}
