import { useEffect, useState } from 'react'
import type { BuyerSimulation, Lead } from '../../types'
import { buildSimulation } from '../../api/mock'
import { api } from '../../api/client'
import { pct } from '../../lib/format'

export default function EmailArena({ lead }: { lead: Lead }) {
  const [sim, setSim] = useState<BuyerSimulation | null>(lead.simulation || null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (sim || !lead.id) {
      if (!sim) setSim(buildSimulation(lead))
      return
    }
    let cancelled = false
    setLoading(true)
    api
      .simulate(lead.id)
      .then((s) => !cancelled && setSim(s))
      .catch(() => !cancelled && setSim(buildSimulation(lead)))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lead.id])

  if (loading || !sim) return <div className="arena-loading">Simulating buyer…</div>

  return (
    <div className="arena">
      <div className="persona">
        <span className="persona-badge">SIMULATED BUYER</span>
        {sim.persona_summary}
      </div>
      <div className="arena-grid">
        {sim.variants.map((v) => {
          const win = v.variant === sim.winner
          return (
            <div key={v.variant} className={'variant' + (win ? ' winner' : '')}>
              <div className="variant-head">
                <span className="variant-tag">Variant {v.variant}</span>
                {win && <span className="win-badge">WINNER</span>}
                <span className="reply">{pct(v.reply_likelihood)} reply</span>
              </div>
              <div className="variant-subject">{v.subject}</div>
              <div className="reply-bar">
                <div
                  className="reply-fill"
                  style={{
                    width: pct(v.reply_likelihood),
                    background: win ? 'var(--gold-deep)' : 'var(--border)',
                  }}
                />
              </div>
              <div className={'reaction ' + v.sentiment}>“{v.predicted_reaction}”</div>
              <div className="objection">Top objection: {v.top_objection}</div>
            </div>
          )
        })}
      </div>
      <div className="arena-foot">
        Self-play pick: <b>Variant {sim.winner}</b> — +{sim.uplift}pp predicted reply uplift over
        the loser. The sales agent ships the winner.
      </div>
    </div>
  )
}
