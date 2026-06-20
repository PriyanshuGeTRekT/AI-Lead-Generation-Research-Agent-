export default function Gauge({
  value,
  max = 10,
  label,
  caption,
}: {
  value: number | null
  max?: number
  label: string
  caption?: React.ReactNode
}) {
  const deg = value != null ? Math.max(0, Math.min(360, (value / max) * 360)) : 0
  return (
    <div className="gauge-card">
      <div
        className="gauge-ring"
        style={{ background: `conic-gradient(var(--gold) ${deg}deg, var(--gold-soft) ${deg}deg)` }}
      >
        <div className="gauge-inner">
          <b>{value != null ? value.toFixed(1) : '—'}</b>
          <span>avg</span>
        </div>
      </div>
      <div className="gauge-meta">
        <div className="gm-label">{label}</div>
        {caption && <div className="gm-sub">{caption}</div>}
      </div>
    </div>
  )
}
