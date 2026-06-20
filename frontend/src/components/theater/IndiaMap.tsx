import { useMemo } from 'react'
import type { TheaterEvent, Lead } from '../../types'
import { geocode, project, indiaPath } from '../../lib/geo'

// Accurate India outline, generated from real border coordinates projected with
// the SAME project() as the pins — so every pin lands on its true location.
const INDIA_PATH = indiaPath()

interface Pin {
  id: string
  name: string
  x: number
  y: number
  score?: number
}

export default function IndiaMap({ events, leads = [] }: { events: TheaterEvent[]; leads?: Lead[] }) {
  const pins = useMemo<Pin[]>(() => {
    const map = new Map<string, Pin>()
    const add = (l: Partial<Lead> | undefined, i: number) => {
      if (!l) return
      const name = l.company_name || ''
      if (!name) return
      const { lat, lng } = geocode(l.location || l.address || name, i)
      const { x, y } = project(lat, lng)
      const prev = map.get(name)
      map.set(name, {
        id: name,
        name,
        x,
        y,
        score: l.lead_score?.predicted_score ?? l.qualification_score ?? prev?.score,
      })
    }
    // Live-run events drive the map; otherwise show the current leads.
    events.forEach((e, i) => {
      if (e.type === 'lead_found' || e.type === 'score') add(e.lead, i)
    })
    if (map.size === 0) leads.forEach((l, i) => add(l, i))
    return [...map.values()]
  }, [events, leads])

  return (
    <div className="map-wrap">
      <svg viewBox="0 0 100 100" className="india-map" preserveAspectRatio="xMidYMid meet">
        <defs>
          <radialGradient id="pinGlow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="var(--gold)" stopOpacity="0.7" />
            <stop offset="100%" stopColor="var(--gold)" stopOpacity="0" />
          </radialGradient>
        </defs>
        <path d={INDIA_PATH} className="india-shape" />
        {pins.map((p) => {
          const color =
            p.score == null
              ? 'var(--slate)'
              : p.score >= 7
                ? 'var(--green)'
                : p.score >= 4
                  ? 'var(--gold-deep)'
                  : 'var(--red)'
          return (
            <g key={p.id} className="pin" transform={`translate(${p.x} ${p.y})`}>
              <circle r={6} fill="url(#pinGlow)" className="pin-glow" />
              <circle r={1.8} fill={color} stroke="#fff" strokeWidth={0.5} />
              <title>
                {p.name}
                {p.score != null ? ` — ${p.score}/10` : ''}
              </title>
            </g>
          )
        })}
      </svg>
      <div className="map-legend">
        <span className="lg-title">Live discovery</span>
        <span className="lg">
          <i style={{ background: 'var(--green)' }} /> hot ≥7
        </span>
        <span className="lg">
          <i style={{ background: 'var(--gold-deep)' }} /> warm
        </span>
        <span className="lg">
          <i style={{ background: 'var(--red)' }} /> cold
        </span>
        <span className="lg-count">{pins.length} pins</span>
      </div>
    </div>
  )
}
