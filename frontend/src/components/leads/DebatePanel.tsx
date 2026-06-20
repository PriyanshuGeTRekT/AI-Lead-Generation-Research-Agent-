import { useMemo } from 'react'
import type { Lead } from '../../types'
import { buildDebate } from '../../api/mock'
import { pct } from '../../lib/format'

const PERSONA_META: Record<string, { name: string; icon: string; cls: string }> = {
  champion: { name: 'The Champion', icon: '▲', cls: 'champion' },
  skeptic: { name: 'The Skeptic', icon: '▼', cls: 'skeptic' },
  analyst: { name: 'The ICP Analyst', icon: '◆', cls: 'analyst' },
}

export default function DebatePanel({ lead }: { lead: Lead }) {
  // Use backend debate if present, else synthesize locally from the lead.
  const debate = useMemo(() => lead.debate || buildDebate(lead), [lead])

  return (
    <div className="debate">
      <div className="debate-head">
        <div>
          <div className="debate-title">Adversarial Debate</div>
          <div className="debate-verdict">{debate.verdict}</div>
        </div>
        <div className="debate-consensus">
          <b>{debate.consensus_score.toFixed(1)}</b>
          <span>consensus · {pct(debate.confidence)} conf.</span>
        </div>
      </div>
      <div className="debate-feed">
        {debate.transcript.map((t, i) => {
          const m = PERSONA_META[t.persona] || { name: t.persona, icon: '•', cls: 'analyst' }
          return (
            <div key={i} className={'debate-turn ' + m.cls}>
              <div className="dt-avatar">{m.icon}</div>
              <div className="dt-body">
                <div className="dt-head">
                  <span className="dt-name">{m.name}</span>
                  <span className="dt-round">R{t.round}</span>
                  <span className="dt-score">{t.score.toFixed(1)}</span>
                </div>
                <div className="dt-arg">{t.argument}</div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
