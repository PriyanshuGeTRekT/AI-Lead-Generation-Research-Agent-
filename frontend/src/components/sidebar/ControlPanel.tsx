import { useState } from 'react'
import { useApp } from '../../store/AppContext'

// India-only ICP (foreign markets have different HR compliance). Region presets
// cover the Hindi + English speaking belt; specific states also selectable.
const REGIONS = [
  'Any', 'Hindi Belt', 'Metros', 'Maharashtra', 'Karnataka', 'Tamil Nadu',
  'Telangana', 'Delhi', 'Haryana', 'Uttar Pradesh', 'Gujarat', 'West Bengal',
  'Rajasthan', 'Punjab', 'Kerala', 'Madhya Pradesh', 'Andhra Pradesh',
]

// Cities indexed by JustDial + IndiaMART — incl. Delhi/Maharashtra which the MCA
// mirror lacks. Directory harvest pulls real, contact-bearing businesses per city.
const DIR_CITIES = [
  'Delhi', 'Mumbai', 'Pune', 'Bengaluru', 'Chennai', 'Hyderabad', 'Ahmedabad',
  'Surat', 'Noida', 'Gurugram', 'Faridabad', 'Thane', 'Nagpur', 'Kolkata',
  'Jaipur', 'Indore', 'Coimbatore', 'Ludhiana',
]

export default function ControlPanel() {
  const {
    runPipeline, ingest, pipeline, loadDemo, harvest, buildPool, enrichPool,
    harvestDirectory, ingestMca, enrichPeople, deepEnrich, poolStats,
  } = useApp()
  const [harvesting, setHarvesting] = useState(false)
  const [enriching, setEnriching] = useState(false)
  const [building, setBuilding] = useState(false)
  const [dirHarvesting, setDirHarvesting] = useState(false)
  const [mcaIngesting, setMcaIngesting] = useState(false)
  const [peopleEnriching, setPeopleEnriching] = useState(false)
  const [deepEnriching, setDeepEnriching] = useState(false)
  const [dirCity, setDirCity] = useState('Delhi')
  const [keyword, setKeyword] = useState('SME companies 200 employees')
  const [maxLeads, setMaxLeads] = useState(10)
  const [region, setRegion] = useState('Any')
  const [excludeHrms, setExcludeHrms] = useState(true)
  const [mode, setMode] = useState<'discover' | 'company'>('discover')
  const [fast, setFast] = useState(true)
  const [ingesting, setIngesting] = useState(false)

  const running = pipeline.running
  const company = mode === 'company'

  const run = () =>
    runPipeline(keyword, maxLeads, {
      country: 'India',
      region: region === 'Any' ? undefined : region,
      exclude_with_hrms: excludeHrms,
      mode,
      fast,
    })

  return (
    <div className="card panel">
      <div className="mode-switch">
        <button className={'mode-tab' + (!company ? ' on' : '')} onClick={() => setMode('discover')}>
          Discover ICP
        </button>
        <button className={'mode-tab' + (company ? ' on' : '')} onClick={() => setMode('company')}>
          Find a company
        </button>
      </div>
      <div className="section-label">{company ? 'Company name' : 'Target Market Keyword'}</div>
      <textarea
        className="keyword"
        value={keyword}
        onChange={(e) => setKeyword(e.target.value)}
        placeholder={company ? 'e.g. Razor Infotech Pvt Ltd' : 'e.g. logistics company India 500 employees'}
      />

      <div className="slider-head">
        <span className="section-label" style={{ marginBottom: 0 }}>
          Max Leads to Find
        </span>
        <span className="slider-val">{maxLeads}</span>
      </div>
      <input
        type="range"
        min={1}
        max={100}
        step={1}
        value={maxLeads}
        onChange={(e) => setMaxLeads(Number(e.target.value))}
        className="slider"
      />
      <div className="slider-scale">
        <span>1 · demo</span>
        <span>50 · default</span>
        <span>100 · max</span>
      </div>

      {/* Geo filter — India only (Hindi + English belt) */}
      <div className="geo-grid">
        <div className="geo-field">
          <label className="mini-label">Market</label>
          <div className="geo-fixed">🇮🇳 India</div>
        </div>
        <div className="geo-field">
          <label className="mini-label">Region</label>
          <select className="geo-select" value={region} onChange={(e) => setRegion(e.target.value)}>
            {REGIONS.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </div>
      </div>

      <label className="toggle-row">
        <input type="checkbox" checked={excludeHrms} onChange={(e) => setExcludeHrms(e.target.checked)} />
        <span>
          Only companies <b>without</b> an HRMS
        </span>
      </label>
      <div className="icp-note">ICP: SMEs across all industries · 50–1000 staff · GCCs flagged</div>

      <div className="mode-switch" style={{ marginTop: 12, marginBottom: 6 }}>
        <button className={'mode-tab' + (fast ? ' on' : '')} onClick={() => setFast(true)}>
          ⚡ Fast
        </button>
        <button className={'mode-tab' + (!fast ? ' on' : '')} onClick={() => setFast(false)}>
          🎯 Deep AI
        </button>
      </div>
      <div className="icp-note">
        {fast
          ? 'Fast: deterministic (Places + LinkedIn), no per-company AI — best for volume & speed.'
          : 'Deep AI: the model reads each site — slower, richer extraction.'}
      </div>

      <button className="btn btn-primary" disabled={running} onClick={run}>
        {running ? '⟳ Running…' : '▶ Generate Leads'}
      </button>

      {/* Lead Warehouse — pre-harvest the pool, then search = instant filter */}
      <div className="pool-meter">
        <div className="pool-head">
          <span className="section-label" style={{ marginBottom: 0 }}>Lead pool</span>
          <span className="pool-total">{poolStats.total.toLocaleString()} companies</span>
        </div>
        <div className="pool-bars">
          <span className="pool-chip raw">{poolStats.raw} raw</span>
          <span className="pool-chip enr">{poolStats.enriched + poolStats.qualified} enriched</span>
        </div>
        <div className="icp-note" style={{ marginTop: 4 }}>
          Harvest builds the pool once · searches then filter it instantly (no re-crawl, no tokens).
        </div>
      </div>
      <button
        className="btn btn-secondary"
        disabled={running || building}
        title="Sweep every industry × city to fill the pool with real companies (free sources)"
        onClick={async () => {
          setBuilding(true)
          await buildPool(60)
          setBuilding(false)
        }}
      >
        {building ? '⟳ Building pool…' : '🏭 Build pool (all industries)'}
      </button>
      <button
        className="btn btn-secondary"
        disabled={running || harvesting}
        onClick={async () => {
          setHarvesting(true)
          await harvest(keyword, {
            country: 'India',
            region: region === 'Any' ? undefined : region,
            mode,
          })
          setHarvesting(false)
        }}
      >
        {harvesting ? '⟳ Harvesting pool…' : '🌾 Harvest leads into pool'}
      </button>
      <button
        className="btn btn-secondary"
        disabled={running || enriching || poolStats.raw === 0}
        title={poolStats.raw === 0 ? 'Harvest some raw leads first' : `Enrich ${Math.min(poolStats.raw, 25)} raw leads`}
        onClick={async () => {
          setEnriching(true)
          await enrichPool(25, { region: region === 'Any' ? undefined : region, fast })
          setEnriching(false)
        }}
      >
        {enriching ? '⟳ Enriching pool…' : `⚙ Enrich pool (${poolStats.raw} raw)`}
      </button>
      {/* Directory harvest — JustDial + IndiaMART, contact-bearing leads per city.
          The fix for thin metros (Delhi/Maharashtra) the MCA mirror lacks. */}
      <div className="pool-meter" style={{ marginTop: 14 }}>
        <div className="pool-head">
          <span className="section-label" style={{ marginBottom: 0 }}>Harvest a city</span>
          <span className="pool-chip enr">OSM · Places · 5 directories</span>
        </div>
        <div className="icp-note" style={{ marginTop: 4 }}>
          Pulls businesses for one city from OSM + Google Places + IndiaMART/JustDial/TradeIndia/Sulekha/ExportersIndia (name · phone · website).
        </div>
      </div>
      <div className="geo-grid" style={{ marginBottom: 8 }}>
        <div className="geo-field" style={{ gridColumn: '1 / -1' }}>
          <label className="mini-label">City</label>
          <select className="geo-select" value={dirCity} onChange={(e) => setDirCity(e.target.value)}>
            {DIR_CITIES.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </div>
      </div>
      <button
        className="btn btn-secondary"
        disabled={running || dirHarvesting}
        title={`Harvest ${dirCity} from OSM + Google Places + JustDial/IndiaMART into the pool`}
        onClick={async () => {
          setDirHarvesting(true)
          await harvestDirectory(dirCity)
          setDirHarvesting(false)
        }}
      >
        {dirHarvesting ? `⟳ Harvesting ${dirCity}…` : `🏙 Harvest ${dirCity} (all sources)`}
      </button>
      <button
        className="btn btn-secondary"
        disabled={running || mcaIngesting}
        title="Bulk-ingest MCA company registry for Delhi + Maharashtra (the states the free mirror lacks) — tens of thousands of leads. Needs a free data.gov.in key in Settings."
        onClick={async () => {
          setMcaIngesting(true)
          await ingestMca('Delhi,Maharashtra')
          setMcaIngesting(false)
        }}
      >
        {mcaIngesting ? '⟳ Ingesting MCA (Delhi + MH)…' : '🏛 Ingest Delhi + Maharashtra (MCA registry)'}
      </button>
      <button
        className="btn btn-secondary"
        disabled={running || peopleEnriching}
        title="Find the decision-maker (HR head / founder) + email for pooled leads via Crustdata or PDL. Needs a Crustdata/PDL key in Settings."
        onClick={async () => {
          setPeopleEnriching(true)
          await enrichPeople(region === 'Any' ? '' : region)
          setPeopleEnriching(false)
        }}
      >
        {peopleEnriching
          ? '⟳ Finding decision-makers…'
          : `👤 Find decision-makers + direct dial (Apollo)${region === 'Any' ? '' : ` · ${region}`}`}
      </button>
      <button
        className="btn btn-secondary"
        disabled={running || deepEnriching}
        title="Scrape prime leads' sites for the decision-maker + contact, then AI picks the right person & pitch"
        onClick={async () => {
          setDeepEnriching(true)
          await deepEnrich(region === 'Any' ? '' : region)
          setDeepEnriching(false)
        }}
      >
        {deepEnriching
          ? '⟳ Deep-enriching…'
          : `🔎 Deep-enrich prime leads${region === 'Any' ? '' : ` (${region})`}`}
      </button>

      <button
        className="btn btn-secondary"
        disabled={running || ingesting}
        onClick={async () => {
          setIngesting(true)
          await ingest()
          setIngesting(false)
        }}
      >
        {ingesting ? '⟳ Ingesting…' : '⟳ Rebuild RAG Knowledge Base'}
      </button>
      <button className="btn btn-secondary" disabled={running} onClick={loadDemo}>
        ✦ Load demo data
      </button>
    </div>
  )
}
