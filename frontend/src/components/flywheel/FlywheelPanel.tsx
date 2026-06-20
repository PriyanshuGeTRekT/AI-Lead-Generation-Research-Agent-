import { useApp } from '../../store/AppContext'
import { pct } from '../../lib/format'

export default function FlywheelPanel() {
  const { flywheel } = useApp()
  if (!flywheel) return null
  const { precision, drift, approved, rejected, history, signals } = flywheel

  // sparkline path
  const w = 220
  const h = 46
  const pts = history.length ? history : [{ run: 1, precision }]
  const max = Math.max(...pts.map((p) => p.precision), 0.6)
  const min = Math.min(...pts.map((p) => p.precision), 0.4)
  const span = max - min || 1
  const path = pts
    .map((p, i) => {
      const x = pts.length > 1 ? (i / (pts.length - 1)) * w : w
      const y = h - ((p.precision - min) / span) * (h - 8) - 4
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')

  return (
    <div className="flywheel card">
      <div className="fw-left">
        <div className="fw-eyebrow">SELF-LEARNING ICP FLYWHEEL</div>
        <div className="fw-headline">
          <span className="fw-precision">{pct(precision)}</span>
          <span className="fw-label">qualification precision</span>
          {drift > 0 && <span className="fw-drift up">▲ +{Math.round(drift * 100)}pp</span>}
        </div>
        <svg className="fw-spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
          <path d={path} fill="none" stroke="var(--gold-deep)" strokeWidth={2.5} strokeLinejoin="round" />
          {pts.map((p, i) => {
            const x = pts.length > 1 ? (i / (pts.length - 1)) * w : w
            const y = h - ((p.precision - min) / span) * (h - 8) - 4
            return <circle key={i} cx={x} cy={y} r={2.5} fill="var(--ink)" />
          })}
        </svg>
        <div className="fw-counts">
          <span>
            <b className="green">{approved}</b> approved
          </span>
          <span>
            <b className="red">{rejected}</b> rejected
          </span>
          <span className="muted">each label retrains the ICP profile</span>
        </div>
      </div>
      <div className="fw-right">
        <div className="fw-eyebrow">LEARNED ICP SIGNALS (re-weighted from your approvals)</div>
        <div className="fw-signals">
          {signals.map((s) => (
            <div className="fw-sig" key={s.label}>
              <span className="sig-label">{s.label}</span>
              <div className="sig-track">
                <div
                  className={'sig-fill ' + (s.weight >= 0 ? 'pos' : 'neg')}
                  style={{ width: `${Math.abs(s.weight) * 100}%` }}
                />
              </div>
              <span className={'sig-w ' + (s.weight >= 0 ? 'pos' : 'neg')}>
                {s.weight >= 0 ? '+' : ''}
                {s.weight.toFixed(2)}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
