import { useEffect, useRef, useState, useCallback } from 'react'
import { api, type StartupRow } from '../../api/client'

const PAGE = 50

export default function StartupIndia() {
  const [counts, setCounts] = useState<{ total: number; with_phone: number; by_state: { state: string; n: number }[]; by_industry: { industry: string; n: number }[] } | null>(null)
  const [opts, setOpts] = useState<{ states: string[]; industries: string[] }>({ states: [], industries: [] })
  const [rows, setRows] = useState<StartupRow[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(0)
  const [state, setState] = useState('')
  const [industry, setIndustry] = useState('')
  const [q, setQ] = useState('')
  const [ncr, setNcr] = useState(false)
  const [dpiitOnly, setDpiitOnly] = useState(false)
  const [stage, setStage] = useState('')
  const [loading, setLoading] = useState(false)

  // harvest control
  const [dpiit, setDpiit] = useState(false)
  const [status, setStatus] = useState<Awaited<ReturnType<typeof api.startupsHarvestStatus>> | null>(null)
  const poll = useRef<number | null>(null)

  const loadCounts = useCallback(() => {
    api.startupsCounts().then(setCounts).catch(() => {})
    api.startupsOptions().then(setOpts).catch(() => {})
  }, [])

  const loadRows = useCallback(() => {
    setLoading(true)
    api.startups({ state, industry, q, ncr, dpiit: dpiitOnly, stage, limit: PAGE, offset: page * PAGE })
      .then(r => { setRows(r.rows); setTotal(r.total) })
      .catch(() => { setRows([]); setTotal(0) })
      .finally(() => setLoading(false))
  }, [state, industry, q, ncr, dpiitOnly, stage, page])

  useEffect(() => { loadCounts() }, [loadCounts])
  useEffect(() => { loadRows() }, [loadRows])

  // poll harvest status
  const refreshStatus = useCallback(() => {
    api.startupsHarvestStatus().then(s => {
      setStatus(s)
      if (s.running && poll.current == null) {
        poll.current = window.setInterval(() => {
          api.startupsHarvestStatus().then(st => {
            setStatus(st)
            if (!st.running && poll.current != null) { window.clearInterval(poll.current); poll.current = null; loadCounts(); loadRows() }
          }).catch(() => {})
        }, 3000)
      }
    }).catch(() => {})
  }, [loadCounts, loadRows])

  useEffect(() => { refreshStatus(); return () => { if (poll.current != null) window.clearInterval(poll.current) } }, [refreshStatus])

  const startHarvest = async () => {
    await api.startupsHarvest({ dpiit }).catch(() => {})
    setTimeout(refreshStatus, 800)
  }

  const stopHarvest = async () => {
    await api.startupsHarvestStop().catch(() => {})
    setTimeout(refreshStatus, 800)
  }

  // ── Apify contact enrichment (runs on the current filter) ──
  const [enrich, setEnrich] = useState<Awaited<ReturnType<typeof api.startupsEnrichStatus>> | null>(null)
  const epoll = useRef<number | null>(null)
  const refreshEnrich = useCallback(() => {
    api.startupsEnrichStatus().then(s => {
      setEnrich(s)
      if (s.running && epoll.current == null) {
        epoll.current = window.setInterval(() => {
          api.startupsEnrichStatus().then(st => {
            setEnrich(st)
            if (!st.running && epoll.current != null) { window.clearInterval(epoll.current); epoll.current = null; loadRows(); loadCounts() }
          }).catch(() => {})
        }, 4000)
      }
    }).catch(() => {})
  }, [loadRows, loadCounts])
  useEffect(() => { refreshEnrich(); return () => { if (epoll.current != null) window.clearInterval(epoll.current) } }, [refreshEnrich])

  const startEnrich = async () => {
    await api.startupsEnrich({ ncr, dpiit: dpiitOnly, stage, limit: 1000 }).catch(() => {})
    setTimeout(refreshEnrich, 800)
  }

  const pages = Math.ceil(total / PAGE)

  return (
    <div className="si-wrap">
      <style>{SI_CSS}</style>

      <div className="si-head">
        <div>
          <div className="si-title">Startup India <span className="si-accent">Registry</span></div>
          <div className="si-sub">Government registry of recognized startups — name, location, industry, sector & stage. Step 1: harvest the universe. Step 2: enrich the ICP slice with contact details.</div>
        </div>
        <div className="si-stat-row">
          <div className="si-stat"><div className="si-stat-n">{(counts?.total ?? 0).toLocaleString('en-IN')}</div><div className="si-stat-l">in database</div></div>
          <div className="si-stat"><div className="si-stat-n">{(counts?.with_phone ?? 0).toLocaleString('en-IN')}</div><div className="si-stat-l">with phone</div></div>
        </div>
      </div>

      {/* Harvest control */}
      <div className="si-card si-harvest">
        <div className="si-harvest-left">
          <div className="si-card-h">Harvest from startupindia.gov.in</div>
          <label className="si-toggle">
            <input type="checkbox" checked={dpiit} onChange={e => setDpiit(e.target.checked)} />
            <span>Only DPIIT-recognized (~146k) — higher quality. Off = all ~454k.</span>
          </label>
          <div className="si-note">Resumable: re-running continues where it left off. Scrapes 9/page, so the full set takes a while — it runs in the background and the table fills as it goes.</div>
        </div>
        <div className="si-harvest-right">
          <div className="si-btn-row">
            <button className="si-btn si-btn-gold" disabled={status?.running} onClick={startHarvest}>
              {status?.running ? 'Harvesting…' : '▶ Start / Resume harvest'}
            </button>
            {status?.running && (
              <button className="si-btn si-btn-stop" onClick={stopHarvest}>■ Stop</button>
            )}
          </div>
          {status && (status.running || status.scraped_in_db > 0) && (
            <div className="si-prog">
              <div className="si-prog-bar"><div className="si-prog-fill" style={{ width: `${status.pct ?? 0}%` }} /></div>
              <div className="si-prog-txt">
                {status.running ? '● live · ' : ''}
                page {status.last_page?.toLocaleString('en-IN')} / {status.pages?.toLocaleString('en-IN')} · {(status.pct ?? 0).toFixed(1)}% of {status.total?.toLocaleString('en-IN')}
              </div>
              {status.error && <div className="si-err">{status.error}</div>}
            </div>
          )}
        </div>
      </div>

      {/* Campaign preset */}
      <div className="si-presets">
        <button className="si-preset"
          onClick={() => { setPage(0); setNcr(true); setDpiitOnly(true); setStage('Scaling'); setState('') }}>
          🎯 Delhi-NCR · DPIIT · Scaling
        </button>
        {(ncr || dpiitOnly || stage || state || industry || q) && (
          <button className="si-clear"
            onClick={() => { setPage(0); setNcr(false); setDpiitOnly(false); setStage(''); setState(''); setIndustry(''); setQ('') }}>
            ✕ Clear filters
          </button>
        )}
      </div>

      {/* Filters */}
      <div className="si-filters">
        <label className={`si-chip ${ncr ? 'on' : ''}`}>
          <input type="checkbox" checked={ncr} onChange={e => { setPage(0); setNcr(e.target.checked) }} /> Delhi-NCR
        </label>
        <label className={`si-chip ${dpiitOnly ? 'on' : ''}`}>
          <input type="checkbox" checked={dpiitOnly} onChange={e => { setPage(0); setDpiitOnly(e.target.checked) }} /> DPIIT recognized
        </label>
        <select value={stage} onChange={e => { setPage(0); setStage(e.target.value) }}>
          <option value="">All stages</option>
          <option value="Scaling">Scaling</option>
          <option value="EarlyTraction">Early Traction</option>
          <option value="Validation">Validation</option>
          <option value="Prototype">Prototype</option>
        </select>
        <select value={state} disabled={ncr} title={ncr ? 'Cleared while Delhi-NCR is on' : ''}
          onChange={e => { setPage(0); setState(e.target.value) }}>
          <option value="">{ncr ? 'Delhi-NCR' : 'All states'}</option>
          {opts.states.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <select value={industry} onChange={e => { setPage(0); setIndustry(e.target.value) }}>
          <option value="">All industries</option>
          {opts.industries.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <input placeholder="Search company name…" value={q}
          onChange={e => { setPage(0); setQ(e.target.value) }} />
        <div className="si-spacer" />
        <button className="si-btn si-btn-gold" disabled={enrich?.running} onClick={startEnrich}
          title="Find phone, decision-maker, LinkedIn & email for this filtered slice via Apify">
          {enrich?.running ? 'Enriching…' : '✨ Enrich contacts'}
        </button>
        <a className="si-btn si-btn-ghost" href={api.startupsExportUrl({ state, industry, q, ncr, dpiit: dpiitOnly, stage })}>⤓ Export CSV</a>
      </div>

      {enrich && (enrich.running || enrich.done > 0) && (
        <div className="si-enrich">
          {enrich.running ? '● ' : '✓ '}
          enriched {enrich.done}/{enrich.total} · 📞 {enrich.with_phone} phones · 👤 {enrich.with_person} decision-makers
          {' '}· stage: {enrich.stage || '—'} · cost ${Number(enrich.cost_usd || 0).toFixed(2)}
          {enrich.error && <span className="si-err"> · {enrich.error}</span>}
        </div>
      )}

      {/* Table */}
      <div className="si-card si-tablewrap">
        <div className="si-tablebar">
          <span>{total.toLocaleString('en-IN')} companies{state || industry || q ? ' (filtered)' : ''}</span>
          {loading && <span className="si-loading">loading…</span>}
        </div>
        <table className="si-table">
          <thead><tr>
            <th>Company</th><th>City</th><th>Industry</th><th>Stage</th><th>DPIIT</th><th>Phone</th><th>Decision-maker</th><th>LinkedIn</th>
          </tr></thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.sid}>
                <td className="si-name">{r.website ? <a href={r.website} target="_blank" rel="noreferrer">{r.name}</a> : r.name}</td>
                <td>{r.city || '—'}</td>
                <td>{r.industry || '—'}</td>
                <td><span className="si-stage">{r.stage || '—'}</span></td>
                <td>{r.dpiit_certified ? <span className="si-badge">✓</span> : '—'}</td>
                <td>{r.phone ? <span className="si-have">{r.phone}</span> : <span className="si-pending">—</span>}</td>
                <td>{r.dm_name ? <span><b>{r.dm_name}</b>{r.dm_role ? <span className="si-muted"> · {r.dm_role}</span> : ''}</span> : <span className="si-pending">—</span>}</td>
                <td>{r.linkedin ? <a href={r.linkedin} target="_blank" rel="noreferrer" className="si-li">in ↗</a> : '—'}</td>
              </tr>
            ))}
            {!rows.length && !loading && <tr><td colSpan={8} className="si-empty">No companies match — adjust filters or start a harvest above.</td></tr>}
          </tbody>
        </table>
        {pages > 1 && (
          <div className="si-pager">
            <button disabled={page <= 0} onClick={() => setPage(p => p - 1)}>‹ Prev</button>
            <span>Page {page + 1} of {pages.toLocaleString('en-IN')}</span>
            <button disabled={page >= pages - 1} onClick={() => setPage(p => p + 1)}>Next ›</button>
          </div>
        )}
      </div>

      {/* Breakdown */}
      {counts && (counts.by_state.length > 0) && (
        <div className="si-grid2">
          <div className="si-card">
            <div className="si-card-h">By state</div>
            {counts.by_state.slice(0, 12).map(s => (
              <div key={s.state} className="si-bar-row" onClick={() => { setPage(0); setState(s.state) }}>
                <span className="si-bar-l">{s.state || '—'}</span>
                <span className="si-bar-track"><span className="si-bar-fill" style={{ width: `${Math.min(100, s.n * 100 / (counts.by_state[0]?.n || 1))}%` }} /></span>
                <span className="si-bar-n">{s.n.toLocaleString('en-IN')}</span>
              </div>
            ))}
          </div>
          <div className="si-card">
            <div className="si-card-h">By industry</div>
            {counts.by_industry.slice(0, 12).map(s => (
              <div key={s.industry} className="si-bar-row" onClick={() => { setPage(0); setIndustry(s.industry) }}>
                <span className="si-bar-l">{s.industry || '—'}</span>
                <span className="si-bar-track"><span className="si-bar-fill" style={{ width: `${Math.min(100, s.n * 100 / (counts.by_industry[0]?.n || 1))}%` }} /></span>
                <span className="si-bar-n">{s.n.toLocaleString('en-IN')}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

const SI_CSS = `
.si-wrap { display:flex; flex-direction:column; gap:16px; }
.si-head { display:flex; justify-content:space-between; align-items:flex-start; gap:20px; flex-wrap:wrap; }
.si-title { font-size:26px; font-weight:700; color:var(--ink); letter-spacing:-.02em; }
.si-accent { color:var(--gold-deep); }
.si-sub { color:var(--muted); font-size:13px; max-width:620px; margin-top:4px; line-height:1.5; }
.si-stat-row { display:flex; gap:12px; }
.si-stat { background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); padding:10px 18px; text-align:center; box-shadow:var(--shadow-xs); }
.si-stat-n { font-size:22px; font-weight:700; color:var(--gold-deep); font-variant-numeric:tabular-nums; }
.si-stat-l { font-size:11px; color:var(--muted); text-transform:uppercase; letter-spacing:.05em; }
.si-card { background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); padding:16px; box-shadow:var(--shadow-xs); }
.si-card-h { font-size:13px; font-weight:700; color:var(--ink); text-transform:uppercase; letter-spacing:.05em; margin-bottom:12px; }
.si-harvest { display:flex; justify-content:space-between; gap:24px; flex-wrap:wrap; align-items:center; background:linear-gradient(180deg,var(--paper-2),var(--surface)); }
.si-harvest-left { flex:1; min-width:280px; }
.si-toggle { display:flex; gap:8px; align-items:center; font-size:13px; color:var(--ink); cursor:pointer; margin:4px 0; }
.si-note { font-size:12px; color:var(--muted); margin-top:6px; line-height:1.5; }
.si-harvest-right { display:flex; flex-direction:column; gap:8px; min-width:240px; }
.si-btn { border:1px solid var(--border-strong); background:var(--surface); color:var(--ink); padding:9px 16px; border-radius:var(--radius-sm); font-size:13px; font-weight:600; cursor:pointer; text-decoration:none; display:inline-block; text-align:center; transition:all var(--dur-1) var(--ease); }
.si-btn:hover { border-color:var(--gold); }
.si-btn-gold { background:var(--gold-grad); color:#3a2e08; border-color:var(--gold-deep); box-shadow:var(--shadow-gold); }
.si-btn-gold:disabled { opacity:.6; cursor:default; }
.si-btn-row { display:flex; gap:8px; }
.si-btn-stop { background:var(--red-soft); border-color:var(--red); color:var(--red); }
.si-btn-stop:hover { background:var(--red); color:#fff; }
.si-btn-ghost { padding:7px 14px; }
.si-prog { display:flex; flex-direction:column; gap:4px; }
.si-prog-bar { height:8px; background:var(--border-soft); border-radius:99px; overflow:hidden; }
.si-prog-fill { height:100%; background:var(--gold-grad); transition:width .5s var(--ease); }
.si-prog-txt { font-size:11px; color:var(--muted); font-variant-numeric:tabular-nums; }
.si-err { font-size:11px; color:var(--red); }
.si-presets { display:flex; gap:10px; align-items:center; }
.si-preset { background:var(--gold-grad); color:#3a2e08; border:1px solid var(--gold-deep); border-radius:99px; padding:8px 18px; font-size:13px; font-weight:700; cursor:pointer; box-shadow:var(--shadow-gold); }
.si-preset:hover { filter:brightness(1.05); }
.si-clear { background:transparent; border:1px solid var(--border); border-radius:99px; padding:7px 14px; font-size:12px; color:var(--muted); cursor:pointer; }
.si-clear:hover { border-color:var(--red); color:var(--red); }
.si-chip { display:inline-flex; gap:6px; align-items:center; padding:7px 13px; border:1px solid var(--border); border-radius:99px; font-size:13px; color:var(--ink); cursor:pointer; background:var(--surface); user-select:none; }
.si-chip.on { border-color:var(--gold-deep); background:var(--gold-soft); color:var(--gold-deep); font-weight:600; }
.si-filters { display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
.si-filters select, .si-filters input { padding:8px 12px; border:1px solid var(--border); border-radius:var(--radius-sm); background:var(--surface); color:var(--ink); font-size:13px; }
.si-filters input { min-width:220px; }
.si-spacer { flex:1; }
.si-tablewrap { padding:0; overflow:hidden; }
.si-tablebar { display:flex; justify-content:space-between; padding:12px 16px; font-size:12px; color:var(--muted); border-bottom:1px solid var(--border-soft); }
.si-loading { color:var(--gold-deep); }
.si-table { width:100%; border-collapse:collapse; font-size:13px; }
.si-table th { text-align:left; padding:10px 14px; font-size:11px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); border-bottom:1px solid var(--border); background:var(--paper-2); position:sticky; top:0; }
.si-table td { padding:10px 14px; border-bottom:1px solid var(--border-soft); color:var(--ink); }
.si-table tr:hover td { background:var(--paper-2); }
.si-name { font-weight:600; }
.si-muted { color:var(--muted); }
.si-stage { font-size:11px; padding:2px 8px; border-radius:99px; background:var(--gold-soft); color:var(--gold-deep); }
.si-badge { color:var(--green); font-weight:700; }
.si-have { color:var(--green); font-variant-numeric:tabular-nums; }
.si-pending { font-size:11px; color:var(--muted); font-style:italic; }
.si-li { color:var(--gold-deep); font-weight:600; text-decoration:none; font-size:12px; }
.si-li:hover { text-decoration:underline; }
.si-enrich { font-size:12px; color:var(--ink); background:var(--gold-soft); border:1px solid var(--gold); border-radius:var(--radius-sm); padding:8px 14px; font-variant-numeric:tabular-nums; }
.si-empty { text-align:center; color:var(--muted); padding:32px; }
.si-pager { display:flex; justify-content:center; align-items:center; gap:16px; padding:12px; font-size:13px; color:var(--muted); }
.si-pager button { padding:6px 14px; border:1px solid var(--border); border-radius:var(--radius-sm); background:var(--surface); cursor:pointer; color:var(--ink); }
.si-pager button:disabled { opacity:.4; cursor:default; }
.si-grid2 { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
@media (max-width:820px){ .si-grid2 { grid-template-columns:1fr; } }
.si-bar-row { display:flex; align-items:center; gap:10px; padding:5px 0; cursor:pointer; }
.si-bar-row:hover .si-bar-l { color:var(--gold-deep); }
.si-bar-l { width:140px; font-size:12px; color:var(--ink); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.si-bar-track { flex:1; height:8px; background:var(--border-soft); border-radius:99px; overflow:hidden; }
.si-bar-fill { display:block; height:100%; background:var(--gold-grad); }
.si-bar-n { width:64px; text-align:right; font-size:12px; color:var(--muted); font-variant-numeric:tabular-nums; }
`
