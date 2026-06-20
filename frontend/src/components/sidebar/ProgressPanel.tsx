import { useApp } from '../../store/AppContext'
import { fmtMs } from '../../lib/format'

const STAGES: { key: 'research' | 'qualify' | 'sales'; label: string; sub: string }[] = [
  { key: 'research', label: 'Research Agent', sub: 'Serper · LinkedIn · Tech stack' },
  { key: 'qualify', label: 'Qualification', sub: 'Debate scoring · RAG' },
  { key: 'sales', label: 'Sales Agent', sub: 'Buyer sim · 4-touch sequence' },
]

export default function ProgressPanel() {
  const { pipeline, setTheaterOpen } = useApp()
  if (pipeline.status === 'idle') return null

  const { stages, elapsedMs, progressPct, counts, status, runId } = pipeline
  const pulseClass = status === 'done' ? 'done' : status === 'error' ? 'error' : ''

  return (
    <div className="progress card">
      <div className="progress-head">
        <div className="progress-title">
          <span className={'pulse ' + pulseClass} />
          {status === 'done'
            ? 'Pipeline Complete ✓'
            : status === 'error'
              ? 'Pipeline Failed ✗'
              : 'Pipeline Running'}
        </div>
        <span className="elapsed">{fmtMs(elapsedMs)}</span>
      </div>

      <div className="pbar">
        <div
          className="pbar-fill"
          style={{
            width: `${progressPct}%`,
            background: status === 'done' ? 'var(--green)' : undefined,
          }}
        />
      </div>

      <div className="stage-steps">
        {STAGES.map((s) => {
          const st = stages[s.key]
          return (
            <div key={s.key} className={'stage-step ' + st}>
              <span className="step-icon">
                {st === 'active' ? '⟳' : st === 'done' ? '✓' : '○'}
              </span>
              <span className="step-label">
                {s.label}
                <span className="step-sub">{s.sub}</span>
              </span>
            </div>
          )
        })}
      </div>

      <div className="pcounts">
        <Count val={counts.found} label="Found" color="var(--ink)" />
        <Count val={counts.qualified} label="Qualified" color="var(--green)" />
        <Count val={counts.review} label="In Review" color="var(--amber)" />
      </div>

      <button className="theater-link" onClick={() => setTheaterOpen(true)}>
        ▶ Open Agent Theater
      </button>
      {runId && <div className="run-id">run_id: {runId}</div>}
    </div>
  )
}

function Count({ val, label, color }: { val: number; label: string; color: string }) {
  return (
    <div className="pcount">
      <div className="pcount-val" style={{ color }}>
        {val}
      </div>
      <div className="pcount-label">{label}</div>
    </div>
  )
}
