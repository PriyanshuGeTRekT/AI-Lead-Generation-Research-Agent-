import { useMemo, useState } from 'react'
import { useApp } from '../../store/AppContext'
import type { Lead } from '../../types'

// Our own lightweight CRM pipeline (until a real CRM is integrated).
const STAGES = [
  { id: 'new', label: 'New', hue: '#7a8794' },
  { id: 'contacted', label: 'Contacted', hue: '#3f78c2' },
  { id: 'demo', label: 'Demo Booked', hue: '#b07d2a' },
  { id: 'won', label: 'Won', hue: '#4f8a6b' },
  { id: 'lost', label: 'Lost', hue: '#bf5b3c' },
] as const
type StageId = (typeof STAGES)[number]['id']

const LS_KEY = 'leadiq_crm_stages'

function loadStages(): Record<string, StageId> {
  try {
    return JSON.parse(localStorage.getItem(LS_KEY) || '{}')
  } catch {
    return {}
  }
}

function defaultStage(l: Lead): StageId {
  if (l.status === 'outreach_ready') return 'contacted'
  if (l.status === 'disqualified') return 'lost'
  return 'new'
}

const leadKey = (l: Lead) => l.id || l.company_name || ''

export default function CrmBoard() {
  const { leads } = useApp()
  const [stages, setStages] = useState<Record<string, StageId>>(loadStages)
  const [dragId, setDragId] = useState<string | null>(null)
  const [over, setOver] = useState<StageId | null>(null)

  const stageOf = (l: Lead): StageId => stages[leadKey(l)] || defaultStage(l)

  const columns = useMemo(() => {
    const map: Record<StageId, Lead[]> = { new: [], contacted: [], demo: [], won: [], lost: [] }
    for (const l of leads) map[stageOf(l)].push(l)
    return map
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [leads, stages])

  const move = (id: string, stage: StageId) => {
    setStages((s) => {
      const next = { ...s, [id]: stage }
      try {
        localStorage.setItem(LS_KEY, JSON.stringify(next))
      } catch {
        /* ignore */
      }
      return next
    })
  }

  const onDrop = (stage: StageId) => {
    if (dragId) move(dragId, stage)
    setDragId(null)
    setOver(null)
  }

  if (!leads.length) {
    return (
      <div className="crm-empty">
        No leads in the pipeline yet. Run a search (or load demo data) and they’ll appear here as draggable cards.
      </div>
    )
  }

  return (
    <div className="crm-board">
      {STAGES.map((col) => (
        <div
          key={col.id}
          className={'crm-col' + (over === col.id ? ' over' : '')}
          onDragOver={(e) => {
            e.preventDefault()
            setOver(col.id)
          }}
          onDragLeave={() => setOver((o) => (o === col.id ? null : o))}
          onDrop={() => onDrop(col.id)}
        >
          <div className="crm-col-head" style={{ ['--hue' as string]: col.hue }}>
            <span className="crm-dot" />
            <span className="crm-col-label">{col.label}</span>
            <span className="crm-count">{columns[col.id].length}</span>
          </div>
          <div className="crm-col-body">
            {columns[col.id].map((l) => {
              const score = l.lead_score?.predicted_score ?? l.qualification_score
              const dm = l.decision_maker_full_name || l.decision_maker_name
              const email = (l.contact_emails || [])[0]
              return (
                <div
                  key={leadKey(l)}
                  className="crm-card"
                  draggable
                  onDragStart={() => setDragId(leadKey(l))}
                  onDragEnd={() => {
                    setDragId(null)
                    setOver(null)
                  }}
                >
                  <div className="crm-card-top">
                    <span className="crm-company">{l.company_name}</span>
                    {score != null && <span className="crm-score">{Number(score).toFixed(1)}</span>}
                  </div>
                  <div className="crm-meta">
                    {[l.industry, l.location].filter(Boolean).join(' · ') || '—'}
                  </div>
                  {dm && (
                    <div className="crm-dm">
                      <span className="crm-dm-name">{dm}</span>
                      {l.decision_maker_title && <span className="crm-dm-title"> · {l.decision_maker_title}</span>}
                    </div>
                  )}
                  <div className="crm-contact">
                    {l.phone && <span title="phone">📞 {l.phone}</span>}
                    {email && (
                      <a href={`mailto:${email}`} title="email" onClick={(e) => e.stopPropagation()}>
                        ✉ {email}
                      </a>
                    )}
                  </div>
                  <select
                    className="crm-move"
                    value={stageOf(l)}
                    onChange={(e) => move(leadKey(l), e.target.value as StageId)}
                    title="Move stage"
                  >
                    {STAGES.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.label}
                      </option>
                    ))}
                  </select>
                </div>
              )
            })}
            {columns[col.id].length === 0 && <div className="crm-col-empty">Drop here</div>}
          </div>
        </div>
      ))}
    </div>
  )
}
