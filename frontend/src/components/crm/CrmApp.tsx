import { useEffect, useState, useCallback } from 'react'
import { api } from '../../api/client'
import type { Lead } from '../../types'
import { useApp } from '../../store/AppContext'
import LeadDetail from './LeadDetail'
import CrmDashboard from './CrmDashboard'
import VerifyCompany from './VerifyCompany'

const STAGES: [string, string][] = [
  ['all', 'All Leads'],
  ['new', 'Not Contacted'],
  ['contacted', 'Contacted'],
  ['in_loop', 'In the Loop'],
  ['won', 'Won'],
  ['rejected', 'Rejected'],
]

type Col = { key: string; label: string; sortable?: boolean }
const COLS: Col[] = [
  { key: 'company_name', label: 'Company', sortable: true },
  { key: 'dm_name', label: 'Contact Person' },
  { key: 'dm_email', label: 'Email', sortable: true },
  { key: 'phone', label: 'Phone', sortable: true },
  { key: 'industry', label: 'Industry', sortable: true },
  { key: 'state', label: 'State', sortable: true },
  { key: 'icp_tier', label: 'Tier', sortable: true },
  { key: 'signal_score', label: '🔥 Signal', sortable: true },
  { key: 'score', label: 'HRMS Fit', sortable: true },
  { key: 'crm_stage', label: 'Status', sortable: true },
]

const STAGE_LABEL: Record<string, string> = {
  new: 'Not Contacted', contacted: 'Contacted', in_loop: 'In the Loop', won: 'Won', rejected: 'Rejected',
}

// The active campaign we're primarily working: Delhi-NCR × IT/BPO/consulting, phone-first.
const CAMPAIGN = { state: 'Delhi NCR', industries: 'IT services,BPO,consulting', has_phone: true }

export default function CrmApp() {
  const { toast } = useApp()
  const [tab, setTab] = useState<'overview' | 'leads' | 'campaign'>('campaign')
  const [stage, setStage] = useState('all')
  const [tier, setTier] = useState('')
  const [stateF, setStateF] = useState('')
  const [industry, setIndustry] = useState('')
  const [q, setQ] = useState('')
  const [sort, setSort] = useState('score')
  const [dir, setDir] = useState('desc')
  const [hotOnly, setHotOnly] = useState(false)  // 🔥 signal-qualified Hot List
  const [hasContact, setHasContact] = useState(false)  // 📞 only leads with a phone
  const [justEnriched, setJustEnriched] = useState(false)  // ✨ only just-enriched
  const [page, setPage] = useState(1)
  const pageSize = 50

  const [rows, setRows] = useState<Lead[]>([])
  const [total, setTotal] = useState(0)
  const [counts, setCounts] = useState<Record<string, number>>({})
  const [opts, setOpts] = useState<{ states: string[]; industries: string[] }>({ states: [], industries: [] })
  const [loading, setLoading] = useState(false)
  const [detail, setDetail] = useState<Lead | null>(null)
  const [contacting, setContacting] = useState<Lead | null>(null)

  // Dashboard data fetched ONCE here (not on every tab toggle) → instant switching.
  const [dash, setDash] = useState<Awaited<ReturnType<typeof api.crmDashboard>> | null>(null)

  useEffect(() => {
    api.crmOptions().then(setOpts).catch(() => {})
    api.crmDashboard().then(setDash).catch(() => {})
  }, [])

  const inCampaign = tab === 'campaign'

  const loadCounts = useCallback(() => {
    const f = inCampaign
      ? { state: CAMPAIGN.state, industries: CAMPAIGN.industries, has_phone: true }
      : { tier, state: stateF, industry }
    api.crmCounts(f).then(setCounts).catch(() => {})
  }, [inCampaign, tier, stateF, industry])

  const load = useCallback(() => {
    setLoading(true)
    const params = inCampaign
      ? { stage, state: CAMPAIGN.state, industries: CAMPAIGN.industries, has_phone: true,
          q, sort, dir, page, page_size: pageSize }
      : { stage, tier, state: stateF, industry, q, sort, dir, page, page_size: pageSize,
          min_signal: hotOnly ? 60 : 0, has_phone: hasContact || undefined,
          enriched_recently: justEnriched || undefined }
    api
      .crmLeads(params)
      .then((d) => {
        setRows(d.leads || [])
        setTotal(d.total || 0)
      })
      .catch(() => toast('Failed to load leads', 'error'))
      .finally(() => setLoading(false))
  }, [inCampaign, stage, tier, stateF, industry, q, sort, dir, page, hotOnly, hasContact, justEnriched, toast])

  // Debounce search; reload on any filter/sort/page change.
  useEffect(() => {
    const t = setTimeout(load, q ? 350 : 0)
    return () => clearTimeout(t)
  }, [load, q])
  useEffect(loadCounts, [loadCounts])
  // Reset to page 1 when filters/stage/search change.
  useEffect(() => { setPage(1) }, [stage, tier, stateF, industry, q, hotOnly, hasContact, justEnriched, tab])

  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  const onSort = (key: string) => {
    if (!COLS.find((c) => c.key === key)?.sortable) return
    if (sort === key) setDir(dir === 'asc' ? 'desc' : 'asc')
    else { setSort(key); setDir('desc') }
  }

  const updateStage = async (lead: Lead, newStage: string, method?: string) => {
    const id = ((lead as unknown as Record<string, string>).id) || (lead.website || '')
    const res = await api.crmUpdateStage(id, newStage, method).catch(() => ({ ok: false }))
    if (res.ok) {
      toast(`→ ${STAGE_LABEL[newStage] || newStage}`, 'success')
      load(); loadCounts()
    } else {
      toast('Update failed', 'error')
    }
  }

  const onStageChange = (lead: Lead, newStage: string) => {
    if (newStage === 'contacted') setContacting(lead)  // ask method first
    else updateStage(lead, newStage)
  }

  const jumpToStage = (s: string) => { setTab('leads'); setStage(s) }

  return (
    <div className="crm">
      {/* Campaign / Dashboard / Leads sub-nav */}
      <div className="crm-subnav">
        <button className={tab === 'campaign' ? 'on' : ''} onClick={() => { setSort('signal_score'); setDir('desc'); setStage('all'); setTab('campaign') }}>🎯 Active Campaign</button>
        <button className={tab === 'overview' ? 'on' : ''} onClick={() => setTab('overview')}>📊 Dashboard</button>
        <button className={tab === 'leads' ? 'on' : ''} onClick={() => setTab('leads')}>🗂️ All Leads</button>
      </div>

      {tab === 'overview' && <CrmDashboard data={dash} onJump={jumpToStage} />}

      {(tab === 'leads' || tab === 'campaign') && (
      <>
      {inCampaign && (
        <div className="campaign-banner">
          <div className="cb-title">🎯 Active Campaign — Delhi-NCR · IT / BPO / Consulting · phone-first</div>
          <div className="cb-sub">
            Your primary list: signal-ranked, every lead has a phone. {total.toLocaleString()} leads ·
            call top-down (highest signal first). Switch to <b>All Leads</b> for the full pool.
          </div>
        </div>
      )}
      {inCampaign && <VerifyCompany />}
      {/* Stage panels */}
      <div className="crm-stages">
        {STAGES.map(([key, label]) => (
          <button
            key={key}
            className={'crm-stage-tab' + (stage === key ? ' on' : '') + ' st-' + key}
            onClick={() => setStage(key)}
          >
            <span className="cst-label">{label}</span>
            <span className="cst-count">{(counts[key] ?? 0).toLocaleString()}</span>
          </button>
        ))}
      </div>

      {/* Filters */}
      <div className="crm-toolbar">
        <input
          className="crm-search"
          placeholder="Search company / email / phone…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        {!inCampaign && (<>
        <select value={tier} onChange={(e) => setTier(e.target.value)} className="filter-select">
          <option value="">All tiers</option>
          <option value="Hot">🔥 Hot</option>
          <option value="Warm">🌤 Warm</option>
          <option value="Cold">❄ Cold</option>
        </select>
        <select value={stateF} onChange={(e) => setStateF(e.target.value)} className="filter-select">
          <option value="">All states</option>
          {opts.states.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select value={industry} onChange={(e) => setIndustry(e.target.value)} className="filter-select">
          <option value="">All industries</option>
          {opts.industries.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <button
          className={'filter-select' + (hotOnly ? ' on' : '')}
          title="Show only signal-qualified leads (buy-likelihood ≥ 60), ranked by signal"
          style={hotOnly ? { background: '#d9a826', color: '#1a1a1a', fontWeight: 700, border: 'none' } : { cursor: 'pointer' }}
          onClick={() => {
            const next = !hotOnly
            setHotOnly(next)
            if (next) { setSort('signal_score'); setDir('desc') }
          }}
        >
          🔥 Hot List
        </button>
        <button
          className="filter-select"
          title="Show only leads that have a contact phone number"
          style={hasContact ? { background: '#2f9e5a', color: '#fff', fontWeight: 700, border: 'none' } : { cursor: 'pointer' }}
          onClick={() => setHasContact((v) => !v)}
        >
          📞 Has phone
        </button>
        <button
          className="filter-select"
          title="Show only leads we just enriched (decision-maker + phone added)"
          style={justEnriched ? { background: '#5b8def', color: '#fff', fontWeight: 700, border: 'none' } : { cursor: 'pointer' }}
          onClick={() => setJustEnriched((v) => !v)}
        >
          ✨ Just enriched
        </button>
        </>)}
        <a
          className="crm-export"
          href={inCampaign
            ? api.crmExportUrl({ state: CAMPAIGN.state, q, sort: 'signal_score' }) + '&industries=' + encodeURIComponent(CAMPAIGN.industries) + '&has_phone=true'
            : api.crmExportUrl({ stage, tier, state: stateF, industry, q,
                sort: hotOnly ? 'signal_score' : sort, min_signal: hotOnly ? 60 : 0 })}
          download="campaign_leads.csv"
        >
          ⬇ Export CSV
        </a>
        <div className="crm-total">{total.toLocaleString()} leads</div>
      </div>

      {/* Table */}
      <div className="crm-table-wrap">
        <table className="crm-table">
          <thead>
            <tr>
              {COLS.map((c) => (
                <th
                  key={c.key}
                  className={(c.sortable ? 'sortable' : '') + (sort === c.key ? ' sorted' : '')}
                  onClick={() => onSort(c.key)}
                >
                  {c.label}
                  {c.sortable && <span className="sort-ind">{sort === c.key ? (dir === 'asc' ? ' ▲' : ' ▼') : ' ⇅'}</span>}
                </th>
              ))}
              <th>Action</th>
            </tr>
          </thead>
          <tbody className={loading ? 'loading' : ''}>
            {rows.map((l, i) => {
              const x = l as unknown as Record<string, unknown>
              return (
                <tr key={(x.id as string) || i} onClick={() => setDetail(l)}>
                  <td className="c-company">{l.company_name || '—'}</td>
                  <td>{(x.dm_name as string) || <span className="muted-i">—</span>}</td>
                  <td className="c-email">{(l.contact_emails || [])[0] || (x.dm_email as string) || '—'}</td>
                  <td>{l.mobile || l.phone || '—'}</td>
                  <td>{l.industry || '—'}</td>
                  <td>{(x.state as string) || '—'}</td>
                  <td>
                    {l.icp_tier && (
                      <span className={'tierdot ' + l.icp_tier.toLowerCase()}>
                        {l.icp_tier === 'Hot' ? '🔥' : l.icp_tier === 'Warm' ? '🌤' : '❄'} {l.icp_tier}
                      </span>
                    )}
                  </td>
                  <td title={((x.signal_reasons as string[]) || []).join(' · ')}>
                    {x.signal_score != null ? (
                      <span className="sigbar" style={{
                        fontWeight: 700,
                        color: (x.signal_score as number) >= 70 ? '#2f9e5a' : (x.signal_score as number) >= 60 ? '#d9a826' : '#8a7f63',
                      }}>{Math.round(x.signal_score as number)}</span>
                    ) : '—'}
                  </td>
                  <td><b>{(l.qualification_score ?? '—')}</b></td>
                  <td>
                    <select
                      className={'stage-select ss-' + ((x.crm_stage as string) || 'new')}
                      value={(x.crm_stage as string) || 'new'}
                      onClick={(e) => e.stopPropagation()}
                      onChange={(e) => onStageChange(l, e.target.value)}
                    >
                      <option value="new">Not Contacted</option>
                      <option value="contacted">Contacted</option>
                      <option value="in_loop">In the Loop</option>
                      <option value="won">Won</option>
                      <option value="rejected">Rejected</option>
                    </select>
                  </td>
                  <td><button className="row-view" onClick={(e) => { e.stopPropagation(); setDetail(l) }}>View</button></td>
                </tr>
              )
            })}
            {!rows.length && !loading && (
              <tr><td colSpan={COLS.length + 1} className="crm-empty">No leads match these filters.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className="crm-pager">
        <button disabled={page <= 1} onClick={() => setPage(1)}>« First</button>
        <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>‹ Prev</button>
        <span className="pager-info">Page {page.toLocaleString()} of {totalPages.toLocaleString()}</span>
        <button disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>Next ›</button>
        <button disabled={page >= totalPages} onClick={() => setPage(totalPages)}>Last »</button>
      </div>
      </>
      )}

      {detail && <LeadDetail lead={detail} onClose={() => setDetail(null)} onStage={onStageChange} />}

      {contacting && (
        <ContactMethodModal
          lead={contacting}
          onClose={() => setContacting(null)}
          onPick={(method) => { updateStage(contacting, 'contacted', method); setContacting(null) }}
        />
      )}
    </div>
  )
}

function ContactMethodModal({ lead, onClose, onPick }: { lead: Lead; onClose: () => void; onPick: (m: string) => void }) {
  return (
    <div className="settings-overlay" onClick={onClose}>
      <div className="contact-modal" onClick={(e) => e.stopPropagation()}>
        <div className="cm-title">How did you contact <b>{lead.company_name}</b>?</div>
        <div className="cm-options">
          <button className="cm-opt" onClick={() => onPick('email')}>✉️ Email</button>
          <button className="cm-opt" onClick={() => onPick('call')}>📞 Call</button>
        </div>
        <button className="cm-cancel" onClick={onClose}>Cancel</button>
      </div>
    </div>
  )
}
