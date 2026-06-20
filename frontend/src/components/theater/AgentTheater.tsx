import { useApp } from '../../store/AppContext'
import { fmtMs } from '../../lib/format'
import GraphFlow from './GraphFlow'
import IndiaMap from './IndiaMap'
import ReasoningStream from './ReasoningStream'

export default function AgentTheater() {
  const { theaterOpen, setTheaterOpen, theaterEvents, theaterLive, pipeline, leads } = useApp()
  if (!theaterOpen) return null

  const found = theaterEvents.filter((e) => e.type === 'lead_found').length

  return (
    <div className="theater-overlay" onClick={() => setTheaterOpen(false)}>
      <div className="theater" onClick={(e) => e.stopPropagation()}>
        <div className="theater-head">
          <div className="theater-title">
            <span className="theater-dot" />
            Agent Theater
            <span className={'live-pill ' + (theaterLive ? 'live' : pipeline.running ? 'sim' : 'idle')}>
              {theaterLive ? '● LIVE STREAM' : pipeline.running ? '● SIMULATED' : '○ READY'}
            </span>
          </div>
          <div className="theater-stat">
            <span>{fmtMs(pipeline.elapsedMs)}</span>
            <span>{found} discovered</span>
            <span className="status">{pipeline.status}</span>
          </div>
          <button className="theater-close" onClick={() => setTheaterOpen(false)}>
            ✕
          </button>
        </div>

        <GraphFlow events={theaterEvents} />

        <div className="theater-body">
          <div className="theater-map">
            <IndiaMap events={theaterEvents} leads={leads} />
          </div>
          <div className="theater-stream">
            <div className="stream-head">REASONING STREAM</div>
            <ReasoningStream events={theaterEvents} />
          </div>
        </div>
      </div>
    </div>
  )
}
