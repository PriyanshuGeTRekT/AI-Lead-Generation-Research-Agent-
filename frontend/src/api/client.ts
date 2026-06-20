import type {
  GenerateResponse,
  HealthResponse,
  Lead,
  PipelineStatus,
  FlywheelStats,
  BuyerSimulation,
  GeoOpts,
  RuntimeConfig,
  Visitor,
  AbStats,
} from '../types'

// Root-relative base; Vite proxies these to FastAPI in dev (see vite.config.ts).
const BASE = ''

async function j<T>(res: Response): Promise<T> {
  const text = await res.text()
  const data = text ? JSON.parse(text) : {}
  if (!res.ok) {
    const detail = (data && (data.detail || data.error)) || res.statusText
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return data as T
}

export const api = {
  async health(): Promise<HealthResponse> {
    return j<HealthResponse>(await fetch(`${BASE}/health`))
  },

  async leads(status?: string): Promise<{ leads: Lead[]; total?: number }> {
    const q = status ? `?status=${encodeURIComponent(status)}` : ''
    return j(await fetch(`${BASE}/leads${q}`))
  },

  async generate(
    keyword: string,
    max_leads: number,
    geo: GeoOpts = {},
    runId?: string,
  ): Promise<GenerateResponse> {
    return j<GenerateResponse>(
      await fetch(`${BASE}/generate-leads`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          keyword,
          max_leads,
          country: geo.country || null,
          region: geo.region || null,
          exclude_with_hrms: geo.exclude_with_hrms ?? true,
          mode: geo.mode || 'discover',
          fast: geo.fast ?? true,
          run_id: runId || null,
        }),
      }),
    )
  },

  async status(runId: string): Promise<PipelineStatus> {
    return j<PipelineStatus>(await fetch(`${BASE}/pipeline-status/${runId}`))
  },

  async ingest(): Promise<{ status?: string; message?: string; pages_scraped?: number; chunks_stored?: number }> {
    return j(await fetch(`${BASE}/ingest-knowledge`, { method: 'POST' }))
  },

  async flush(): Promise<{ message?: string }> {
    return j(await fetch(`${BASE}/flush-cache`, { method: 'POST' }))
  },

  async approve(id: string): Promise<unknown> {
    return j(await fetch(`${BASE}/leads/${id}/approve`, { method: 'POST' }))
  },

  async reject(id: string): Promise<unknown> {
    return j(await fetch(`${BASE}/leads/${id}/reject`, { method: 'POST' }))
  },

  // ── New-feature endpoints (backend may or may not implement; callers fall
  //    back to the local simulator in api/mock.ts on failure) ────────────────
  async flywheel(): Promise<FlywheelStats> {
    return j<FlywheelStats>(await fetch(`${BASE}/flywheel/stats`))
  },

  async simulate(id: string): Promise<BuyerSimulation> {
    return j<BuyerSimulation>(await fetch(`${BASE}/leads/${id}/simulate`, { method: 'POST' }))
  },

  async getConfig(): Promise<RuntimeConfig> {
    return j<RuntimeConfig>(await fetch(`${BASE}/config`))
  },

  async generateEmail(
    id: string,
  ): Promise<{ outreach_draft?: Lead['outreach_draft']; follow_up_sequence?: Lead['follow_up_sequence']; status?: string; error?: string }> {
    return j(await fetch(`${BASE}/leads/${id}/generate-email`, { method: 'POST' }))
  },

  async getVisitors(): Promise<{ total: number; visitors: Visitor[] }> {
    return j<{ total: number; visitors: Visitor[] }>(await fetch(`${BASE}/visitors`))
  },

  async getAbStats(): Promise<AbStats> {
    return j<AbStats>(await fetch(`${BASE}/track/ab-stats`))
  },

  async chat(messages: { role: string; content: string }[]): Promise<{ reply: string }> {
    return j<{ reply: string }>(
      await fetch(`${BASE}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages }),
      }),
    )
  },

  async saveConfig(patch: Record<string, string>): Promise<RuntimeConfig> {
    return j<RuntimeConfig>(
      await fetch(`${BASE}/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      }),
    )
  },

  // ── Lead Warehouse (pre-harvested pool; search = instant filter) ───────────
  async warehouseStats(): Promise<{
    total: number; leads: number; raw: number; enriched: number; qualified: number
    outreach_ready: number; pending_review: number; excluded: number
    with_email: number; with_phone: number
  }> {
    return j(await fetch(`${BASE}/warehouse/stats`))
  },

  async llmPool(): Promise<{
    endpoints: number
    fast: number
    strong: number
    available: number
    providers: { name: string; model: string; tier: string; cooling_down: boolean }[]
  }> {
    return j(await fetch(`${BASE}/llm/pool`))
  },

  async enrichPool(
    batch: number,
    geo: GeoOpts = {},
  ): Promise<{ status?: string; batch?: number; message?: string }> {
    return j(
      await fetch(`${BASE}/warehouse/enrich`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          keyword: 'enrich',
          max_leads: batch,
          region: geo.region || null,
          fast: geo.fast ?? true,
        }),
      }),
    )
  },

  async harvestMatrix(
    maxQueries = 60,
    perQuery = 50,
  ): Promise<{ status?: string; message?: string }> {
    return j(
      await fetch(`${BASE}/harvest/matrix?max_queries=${maxQueries}&per_query=${perQuery}`, {
        method: 'POST',
      }),
    )
  },

  async harvestMatrixStatus(): Promise<{
    running: boolean
    done: number
    total: number
    added: number
  }> {
    return j(await fetch(`${BASE}/harvest/matrix/status`))
  },

  async harvest(
    keyword: string,
    geo: GeoOpts = {},
  ): Promise<{ status?: string; keyword?: string; message?: string }> {
    return j(
      await fetch(`${BASE}/harvest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          keyword,
          max_leads: 200,
          country: geo.country || null,
          region: geo.region || null,
          mode: geo.mode || 'discover',
        }),
      }),
    )
  },

  // ── Directory harvest (JustDial / IndiaMART) — contact-bearing leads ───────
  async harvestDirectory(
    source: 'indiamart' | 'justdial',
    cities = '',
    categories = '',
  ): Promise<{ status?: string; message?: string; cities?: unknown; categories?: unknown }> {
    const qs = new URLSearchParams()
    if (cities) qs.set('cities', cities)
    if (categories) qs.set('categories', categories)
    return j(await fetch(`${BASE}/harvest/${source}?${qs.toString()}`, { method: 'POST' }))
  },

  async harvestDirectoryStatus(
    source: 'indiamart' | 'justdial',
  ): Promise<{ running: boolean; queries_done: number; queries_total: number; added: number }> {
    return j(await fetch(`${BASE}/harvest/${source}/status`))
  },

  async harvestOsm(cities = ''): Promise<{ status?: string; message?: string }> {
    const qs = cities ? `?cities=${encodeURIComponent(cities)}` : ''
    return j(await fetch(`${BASE}/harvest/osm${qs}`, { method: 'POST' }))
  },

  async harvestOsmStatus(): Promise<{ running: boolean; added: number }> {
    return j(await fetch(`${BASE}/harvest/osm/status`))
  },

  async harvestPlaces(cities = ''): Promise<{ status?: string; message?: string }> {
    const qs = cities ? `?cities=${encodeURIComponent(cities)}` : ''
    return j(await fetch(`${BASE}/harvest/places${qs}`, { method: 'POST' }))
  },

  async harvestPlacesStatus(): Promise<{ running: boolean; added: number; error?: string }> {
    return j(await fetch(`${BASE}/harvest/places/status`))
  },

  // Live single-company verification — look up any company by name on demand.
  async verifyCompany(name: string, city = ''): Promise<{
    query: string; in_warehouse: boolean
    warehouse_row?: { company: string; state: string; industry: string; phone: string }
    places?: { title?: string; phone?: string; website?: string; address?: string; rating?: number; ratingCount?: number; category?: string }
    decision_maker?: { name?: string; role?: string; phone?: string; email?: string }
    error?: string
  }> {
    const qs = new URLSearchParams({ name }); if (city) qs.set('city', city)
    return j(await fetch(`${BASE}/verify/company?${qs.toString()}`))
  },

  async directoryEngine(): Promise<{ headless_available: boolean; engine: string | null; hint: string | null }> {
    return j(await fetch(`${BASE}/harvest/directory/engine`))
  },

  // Unified directory sweep (IndiaMART + JustDial + TradeIndia + Sulekha + ExportersIndia via headless)
  async harvestDirectories(cities = ''): Promise<{ status?: string; message?: string }> {
    const qs = cities ? `?cities=${encodeURIComponent(cities)}` : ''
    return j(await fetch(`${BASE}/harvest/directories${qs}`, { method: 'POST' }))
  },

  async harvestDirectoriesStatus(): Promise<{ running: boolean; added: number; by_site?: Record<string, number> }> {
    return j(await fetch(`${BASE}/harvest/directories/status`))
  },

  // MCA company-master-data via data.gov.in (Delhi/Maharashtra — tens of thousands)
  async harvestMcaLive(states = 'Delhi,Maharashtra'): Promise<{ status?: string; message?: string; states?: unknown }> {
    return j(await fetch(`${BASE}/harvest/mca-live?states=${encodeURIComponent(states)}`, { method: 'POST' }))
  },

  async harvestMcaLiveStatus(): Promise<{ running: boolean; added: number; by_state?: Record<string, number>; error?: string }> {
    return j(await fetch(`${BASE}/harvest/mca-live/status`))
  },

  // Decision-maker enrichment via Crustdata/PDL (the right person + email)
  async enrichPeople(state = '', limit = 200): Promise<{ status?: string; message?: string }> {
    const qs = new URLSearchParams({ limit: String(limit) })
    if (state) qs.set('state', state)
    return j(await fetch(`${BASE}/enrich/people?${qs.toString()}`, { method: 'POST' }))
  },

  async enrichPeopleStatus(): Promise<{ running: boolean; done: number; total: number; enriched: number; provider?: string }> {
    return j(await fetch(`${BASE}/enrich/people/status`))
  },

  // ── Deep enrichment (fill decision-maker + contact + pitch angle) ──────────
  async deepVerify(
    batch = 50,
    state = '',
    industry = '',
  ): Promise<{ status?: string; message?: string }> {
    const qs = new URLSearchParams({ batch: String(batch) })
    if (state) qs.set('state', state)
    if (industry) qs.set('industry', industry)
    return j(await fetch(`${BASE}/warehouse/deep-verify?${qs.toString()}`, { method: 'POST' }))
  },

  async deepVerifyStatus(): Promise<{ running: boolean; done?: number; total?: number; enriched?: number }> {
    return j(await fetch(`${BASE}/warehouse/deep-verify/status`))
  },

  // ── CRM (server-side paginated/filtered/sorted — scales to lakhs) ──────────
  async crmLeads(params: {
    stage?: string; tier?: string; state?: string; industry?: string; q?: string
    sort?: string; dir?: string; page?: number; page_size?: number; min_signal?: number
    has_phone?: boolean; has_contact?: boolean; enriched_recently?: boolean; industries?: string
  }): Promise<{ total: number; page: number; page_size: number; leads: Lead[] }> {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') qs.set(k, String(v))
    })
    return j(await fetch(`${BASE}/crm/leads?${qs.toString()}`))
  },

  async crmCounts(filters: { tier?: string; state?: string; industry?: string; industries?: string; has_phone?: boolean } = {}): Promise<Record<string, number>> {
    const qs = new URLSearchParams()
    Object.entries(filters).forEach(([k, v]) => { if (v) qs.set(k, String(v)) })
    return j(await fetch(`${BASE}/crm/counts?${qs.toString()}`))
  },

  async crmOptions(): Promise<{ states: string[]; industries: string[] }> {
    return j(await fetch(`${BASE}/crm/options`))
  },

  async crmDashboard(): Promise<{
    total: number
    stages: Record<string, number>
    tiers: Record<string, number>
    top_industries: { name: string; count: number }[]
    top_states: { name: string; count: number }[]
    with_email: number
    with_phone: number
    win_rate: number
  }> {
    return j(await fetch(`${BASE}/crm/dashboard`))
  },

  crmExportUrl(params: { stage?: string; tier?: string; state?: string; industry?: string; q?: string; sort?: string; min_signal?: number }): string {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => { if (v) qs.set(k, String(v)) })
    return `${BASE}/crm/export?${qs.toString()}`
  },

  async crmUpdateStage(
    id: string, stage: string, method?: string, note?: string,
  ): Promise<{ ok: boolean; stage?: string; error?: string }> {
    return j(
      await fetch(`${BASE}/crm/leads/${encodeURIComponent(id)}/stage`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stage, method, note }),
      }),
    )
  },

  // ── Startup India registry (government source — 454k startups) ─────────────
  async startupsHarvest(opts: { dpiit?: boolean; states?: string; industries?: string; max_pages?: number; restart?: boolean } = {}): Promise<{ status?: string; scope?: string; message?: string }> {
    const qs = new URLSearchParams()
    if (opts.dpiit) qs.set('dpiit', 'true')
    if (opts.states) qs.set('states', opts.states)
    if (opts.industries) qs.set('industries', opts.industries)
    if (opts.max_pages) qs.set('max_pages', String(opts.max_pages))
    if (opts.restart) qs.set('restart', 'true')
    return j(await fetch(`${BASE}/startups/harvest?${qs.toString()}`, { method: 'POST' }))
  },

  async startupsHarvestStop(): Promise<{ status?: string; message?: string }> {
    return j(await fetch(`${BASE}/startups/harvest/stop`, { method: 'POST' }))
  },

  async startupsHarvestStatus(): Promise<{
    running: boolean; filter: string; scraped: number; total: number
    last_page: number; pages: number; scraped_in_db: number; pct?: number; error?: string
  }> {
    return j(await fetch(`${BASE}/startups/harvest/status`))
  },

  async startups(params: {
    state?: string; industry?: string; q?: string; limit?: number; offset?: number
    has_contact?: boolean; sort?: string; direction?: string
    ncr?: boolean; dpiit?: boolean; stage?: string
  } = {}): Promise<{ rows: StartupRow[]; total: number; limit: number; offset: number }> {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') qs.set(k, String(v))
    })
    return j(await fetch(`${BASE}/startups?${qs.toString()}`))
  },

  async startupsCounts(): Promise<{
    total: number; with_phone: number
    by_state: { state: string; n: number }[]; by_industry: { industry: string; n: number }[]
  }> {
    return j(await fetch(`${BASE}/startups/counts`))
  },

  async startupsOptions(): Promise<{ states: string[]; industries: string[] }> {
    return j(await fetch(`${BASE}/startups/options`))
  },

  async startupsEnrich(params: { ncr?: boolean; dpiit?: boolean; stage?: string; limit?: number } = {}): Promise<{ status?: string; message?: string }> {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== '') qs.set(k, String(v)) })
    return j(await fetch(`${BASE}/startups/enrich?${qs.toString()}`, { method: 'POST' }))
  },

  async startupsEnrichStatus(): Promise<{
    running: boolean; done: number; total: number; with_phone: number
    with_person: number; cost_usd: number; stage: string; error?: string
  }> {
    return j(await fetch(`${BASE}/startups/enrich/status`))
  },

  startupsExportUrl(params: { state?: string; industry?: string; q?: string; ncr?: boolean; dpiit?: boolean; stage?: string } = {}): string {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => { if (v) qs.set(k, String(v)) })
    return `${BASE}/startups/export?${qs.toString()}`
  },

  csvUrl: `${BASE}/warehouse/export/csv`,
  streamUrl: (runId: string) => `${BASE}/stream/${runId}`,
}

export interface StartupRow {
  sid: string; name: string; state: string; city: string; industry: string
  sector: string; stage: string; dpiit_certified: number; registered_on: number
  website: string; phone: string; dm_name: string; dm_role: string; linkedin: string
  email: string; contact_status: string
}
