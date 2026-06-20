import { useEffect, useRef } from 'react'
import type { TheaterEvent } from '../../types'

const TYPE_META: Record<string, { icon: string; cls: string }> = {
  stage_start: { icon: '▸', cls: 'start' },
  stage_end: { icon: '◼', cls: 'end' },
  reasoning: { icon: '…', cls: 'reason' },
  lead_found: { icon: '＋', cls: 'found' },
  score: { icon: '⚖', cls: 'score' },
  tool: { icon: '⚙', cls: 'tool' },
  email: { icon: '✉', cls: 'email' },
  done: { icon: '✓', cls: 'done' },
}

export default function ReasoningStream({ events }: { events: TheaterEvent[] }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight
  }, [events])

  return (
    <div className="stream" ref={ref}>
      {events.length === 0 && (
        <div className="stream-idle">Waiting for the agents to start reasoning…</div>
      )}
      {events.map((e, i) => {
        const m = TYPE_META[e.type] || { icon: '•', cls: 'reason' }
        return (
          <div key={i} className={'stream-row ' + m.cls}>
            <span className="sr-icon">{m.icon}</span>
            <span className="sr-agent">{e.agent.replace('_agent', '')}</span>
            <span className="sr-msg">{e.message}</span>
          </div>
        )
      })}
    </div>
  )
}
