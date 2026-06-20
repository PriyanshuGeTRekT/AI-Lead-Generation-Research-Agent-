import { useState } from 'react'
import { api } from '../../api/client'

type Res = Awaited<ReturnType<typeof api.verifyCompany>>

// Live "look up any company" — type a name, fetch its Google-Maps + decision-maker
// data on demand. Lets the user verify the pipeline against companies they know.
export default function VerifyCompany() {
  const [name, setName] = useState('')
  const [city, setCity] = useState('')
  const [res, setRes] = useState<Res | null>(null)
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)

  const run = async () => {
    if (!name.trim()) return
    setLoading(true); setRes(null)
    try { setRes(await api.verifyCompany(name.trim(), city.trim())) }
    catch { setRes({ query: name, in_warehouse: false, error: 'lookup failed' }) }
    finally { setLoading(false) }
  }

  const p = res?.places || {}
  const dm = res?.decision_maker || {}

  return (
    <div className="verify-box">
      <button className="verify-toggle" onClick={() => setOpen((o) => !o)}>
        🔎 Verify any company {open ? '▲' : '▼'}
      </button>
      {open && (
        <div className="verify-body">
          <div className="verify-row">
            <input className="crm-search" placeholder="Company name (e.g. your own company)" value={name}
                   onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && run()} />
            <input className="crm-search" style={{ maxWidth: 160 }} placeholder="City (optional)" value={city}
                   onChange={(e) => setCity(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && run()} />
            <button className="btn btn-primary" style={{ width: 'auto', padding: '0 18px' }} disabled={loading} onClick={run}>
              {loading ? '⟳ Looking up…' : 'Look up'}
            </button>
          </div>
          {res && !loading && (
            <div className="verify-result">
              {res.error && <div className="vr-err">{res.error}</div>}
              <div className="vr-line">
                <b>{p.title || res.query}</b>
                {p.category && <span className="vr-chip">{p.category}</span>}
                {typeof p.rating === 'number' && <span className="vr-chip">★ {p.rating} ({p.ratingCount || 0})</span>}
                <span className={'vr-chip ' + (res.in_warehouse ? 'in' : 'out')}>
                  {res.in_warehouse ? '✓ already in your pool' : 'not yet in pool'}
                </span>
              </div>
              <div className="vr-grid">
                <div><span className="vr-k">📞 Phone</span> {p.phone || dm.phone || <i className="muted-i">not found</i>}</div>
                <div><span className="vr-k">🌐 Website</span> {p.website ? <a href={p.website} target="_blank" rel="noreferrer">{p.website}</a> : <i className="muted-i">—</i>}</div>
                <div><span className="vr-k">📍 Address</span> {p.address || <i className="muted-i">—</i>}</div>
                <div><span className="vr-k">👤 Decision-maker</span> {dm.name ? `${dm.name}${dm.role ? ' (' + dm.role + ')' : ''}` : <i className="muted-i">ask for the owner</i>}</div>
                <div><span className="vr-k">✉ Email</span> {dm.email || <i className="muted-i">—</i>}</div>
              </div>
              {!p.title && !p.phone && !dm.name && !dm.phone && (
                <div className="vr-err">No live match found for this name — try adding the city, or a more exact name.</div>
              )}
            </div>
          )}
          <div className="verify-hint">Live lookup via Google Maps + web — proves the pipeline on any company you know. Not added to the pool.</div>
        </div>
      )}
    </div>
  )
}
