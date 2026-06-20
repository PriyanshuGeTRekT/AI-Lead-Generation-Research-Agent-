import { api } from '../api/client'
import { useApp } from '../store/AppContext'

const FILTERS: [string, string][] = [
  ['all', 'All'],
  ['qualified', '✓ Qualified'],
  ['outreach_ready', '✉ Outreach Ready'],
  ['pending_review', '⏳ Pending'],
  ['disqualified', '✗ Disqualified'],
  ['researched', '○ Researched'],
]

export default function FilterBar() {
  const {
    filter, setFilter, leads,
    stateFilter, setStateFilter, industryFilter, setIndustryFilter,
    mobileOnly, setMobileOnly, tierFilter, setTierFilter, stateOptions, industryOptions,
  } = useApp()
  const count = (f: string) =>
    f === 'all' ? leads.length : leads.filter((l) => l.status === f).length
  const mobileCount = leads.filter(
    (l) => l.mobile || (l.phone_type === 'mobile' && l.phone),
  ).length
  const tierCount = (t: string) => leads.filter((l) => l.icp_tier === t).length

  return (
    <div className="filter-bar">
      {/* ICP quality tier — who's most likely to buy HRMS */}
      <span className="filter-label">Quality:</span>
      {[['all', 'All'], ['Hot', '🔥 Hot'], ['Warm', '🌤 Warm'], ['Cold', '❄ Cold']].map(([key, label]) => (
        <button
          key={key}
          className={'chip tier-' + key.toLowerCase() + (tierFilter === key ? ' active' : '')}
          onClick={() => setTierFilter(key)}
        >
          {label} {key !== 'all' && <span className="count">{tierCount(key)}</span>}
        </button>
      ))}
      <span className="filter-label" style={{ marginLeft: 8 }}>Status:</span>
      {FILTERS.map(([key, label]) => {
        const c = count(key)
        return (
          <button
            key={key}
            className={'chip' + (filter === key ? ' active' : '')}
            onClick={() => setFilter(key)}
          >
            {label} {c > 0 && <span className="count">{c}</span>}
          </button>
        )
      })}

      {/* Mobile-only — the numbers that actually reach a decision-maker */}
      <button
        className={'chip' + (mobileOnly ? ' active' : '')}
        onClick={() => setMobileOnly(!mobileOnly)}
        title="Show only leads with a mobile number"
      >
        📱 Mobile only <span className="count">{mobileCount}</span>
      </button>

      <select className="filter-select" value={stateFilter} onChange={(e) => setStateFilter(e.target.value)}>
        <option value="all">All states</option>
        {stateOptions.map((s) => (
          <option key={s} value={s}>{s}</option>
        ))}
      </select>

      <select className="filter-select" value={industryFilter} onChange={(e) => setIndustryFilter(e.target.value)}>
        <option value="all">All industries</option>
        {industryOptions.map((s) => (
          <option key={s} value={s}>{s}</option>
        ))}
      </select>

      <a className="export-btn" href={api.csvUrl} download="leads.csv">
        ⬇ Export CSV
      </a>
    </div>
  )
}
