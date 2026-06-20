import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Visitor, AbStats } from '../types'

export default function SignalsRow() {
  const [visitors, setVisitors] = useState<Visitor[] | null>(null)
  const [ab, setAb] = useState<AbStats | null>(null)

  const load = useCallback(() => {
    api.getVisitors().then((d) => setVisitors(d.visitors)).catch(() => setVisitors([]))
    api.getAbStats().then(setAb).catch(() => setAb({ variants: [], winner: null }))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  return (
    <div className="signals-row">
      {/* Website visitors */}
      <div className="card signal-card">
        <div className="signal-head">
          <div className="signal-title">
            <span className="signal-ico">🌐</span> Website Visitors
          </div>
          <button className="signal-refresh" onClick={load} title="Refresh">
            ↻
          </button>
        </div>
        {visitors === null ? (
          <div className="signal-empty">Loading…</div>
        ) : visitors.length === 0 ? (
          <div className="signal-empty">
            No identified visitors yet. Embed the tracking pixel
            <code>{' '}/track/pixel.gif{' '}</code>
            on your site to surface anonymous companies.
          </div>
        ) : (
          <div className="visitor-list">
            {visitors.slice(0, 8).map((v, i) => (
              <div className="visitor-item" key={i}>
                <span className="v-org">{v.org}</span>
                <span className="v-meta">
                  {[v.city, v.country].filter(Boolean).join(', ')}
                  {v.page ? ` · ${v.page}` : ''}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Email A/B */}
      <div className="card signal-card">
        <div className="signal-head">
          <div className="signal-title">
            <span className="signal-ico">✉️</span> Email A/B — live engagement
          </div>
          <button className="signal-refresh" onClick={load} title="Refresh">
            ↻
          </button>
        </div>
        {ab === null ? (
          <div className="signal-empty">Loading…</div>
        ) : ab.variants.length === 0 ? (
          <div className="signal-empty">
            No email engagement tracked yet. Route outreach through the tracking links to see
            real open/click rates and the winning variant.
          </div>
        ) : (
          <div className="ab-table">
            <div className="ab-row ab-head">
              <span>Variant</span>
              <span>Sent</span>
              <span>Opens</span>
              <span>Clicks</span>
            </div>
            {ab.variants.map((v) => (
              <div className={'ab-row' + (ab.winner === v.variant ? ' win' : '')} key={v.variant}>
                <span>
                  {v.variant}
                  {ab.winner === v.variant && <span className="ab-win-tag">winner</span>}
                </span>
                <span>{v.sent}</span>
                <span>{v.opens}</span>
                <span>{v.clicks}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
