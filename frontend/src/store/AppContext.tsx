import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { api } from '../api/client'
import { buildFlywheel, demoLeads, enrichTargeting, simulateTheater } from '../api/mock'
import { fmtMs, leadKey, QUALIFIED_STATUSES } from '../lib/format'
import type {
  FlywheelStats,
  GeoOpts,
  Lead,
  TheaterEvent,
} from '../types'

type StageName = 'research' | 'qualify' | 'sales'
type StageState = 'wait' | 'active' | 'done'
export interface Toast {
  id: number
  msg: string
  type: 'success' | 'error' | 'info'
}
export interface LogLine {
  text: string
  type: '' | 'err' | 'warn'
}

interface PipelineState {
  running: boolean
  mode: 'sync' | 'async' | null
  runId: string | null
  elapsedMs: number
  progressPct: number
  lastDurationMs: number | null
  stages: Record<StageName, StageState>
  stageTimes: Partial<Record<StageName, number>>
  status: 'idle' | 'running' | 'done' | 'error'
  counts: { found: number; qualified: number; review: number }
}

interface Health {
  online: boolean
  redis: 'connected' | 'degraded' | 'unknown'
  model: string
}

interface PoolStats {
  total: number
  leads: number
  raw: number
  enriched: number
  qualified: number
  outreach_ready: number
  pending_review: number
  excluded: number
  with_email: number
  with_phone: number
}

interface AppValue {
  // data
  leads: Lead[]
  health: Health
  flywheel: FlywheelStats | null
  // view
  filter: string
  setFilter: (f: string) => void
  sortByScore: boolean
  toggleSort: () => void
  search: string
  setSearch: (s: string) => void
  visibleLeads: Lead[]
  stateFilter: string
  setStateFilter: (s: string) => void
  industryFilter: string
  setIndustryFilter: (s: string) => void
  mobileOnly: boolean
  setMobileOnly: (b: boolean) => void
  tierFilter: string
  setTierFilter: (s: string) => void
  stateOptions: string[]
  industryOptions: string[]
  // pipeline
  pipeline: PipelineState
  logs: LogLine[]
  runPipeline: (keyword: string, maxLeads: number, geo?: GeoOpts) => Promise<void>
  ingest: () => Promise<void>
  flush: () => Promise<void>
  approve: (id: string) => Promise<void>
  reject: (id: string) => Promise<void>
  generateEmail: (id: string) => Promise<void>
  genEmail: Set<string>
  loadDemo: () => void
  // warehouse (pre-harvested pool)
  poolStats: PoolStats
  harvest: (keyword: string, geo?: GeoOpts) => Promise<void>
  buildPool: (maxQueries?: number) => Promise<void>
  enrichPool: (batch?: number, geo?: GeoOpts) => Promise<void>
  harvestDirectory: (city: string) => Promise<void>
  ingestMca: (states?: string) => Promise<void>
  enrichPeople: (state?: string) => Promise<void>
  deepEnrich: (state?: string, batch?: number) => Promise<void>
  refreshPool: () => Promise<void>
  // theater
  theaterOpen: boolean
  setTheaterOpen: (o: boolean) => void
  theaterEvents: TheaterEvent[]
  theaterLive: boolean
  // toasts
  toasts: Toast[]
  toast: (msg: string, type?: Toast['type']) => void
  dismissToast: (id: number) => void
}

const Ctx = createContext<AppValue | null>(null)
export function useApp(): AppValue {
  const v = useContext(Ctx)
  if (!v) throw new Error('useApp must be used within AppProvider')
  return v
}

const STAGE_RESEARCH_END = 60_000
const STAGE_QUAL_END = 140_000
const TOTAL_ESTIMATE = 210_000

export function AppProvider({ children }: { children: ReactNode }) {
  const [leads, setLeads] = useState<Lead[]>([])
  const leadsRef = useRef<Lead[]>([])
  leadsRef.current = leads
  const knownIds = useRef<Set<string>>(new Set())
  const runIndex = useRef(0)

  const [health, setHealth] = useState<Health>({ online: false, redis: 'unknown', model: '' })
  const [flywheel, setFlywheel] = useState<FlywheelStats | null>(null)

  const [filter, setFilter] = useState('all')
  const [sortByScore, setSortByScore] = useState(true)
  const [search, setSearch] = useState('')
  const [stateFilter, setStateFilter] = useState('all')
  const [industryFilter, setIndustryFilter] = useState('all')
  const [mobileOnly, setMobileOnly] = useState(false)
  const [tierFilter, setTierFilter] = useState('all')

  const [logs, setLogs] = useState<LogLine[]>([])
  const [toasts, setToasts] = useState<Toast[]>([])
  const toastId = useRef(0)

  const [theaterOpen, setTheaterOpen] = useState(false)
  const [theaterEvents, setTheaterEvents] = useState<TheaterEvent[]>([])
  const [theaterLive, setTheaterLive] = useState(false)

  const [pipeline, setPipeline] = useState<PipelineState>({
    running: false,
    mode: null,
    runId: null,
    elapsedMs: 0,
    progressPct: 0,
    lastDurationMs: null,
    stages: { research: 'wait', qualify: 'wait', sales: 'wait' },
    stageTimes: {},
    status: 'idle',
    counts: { found: 0, qualified: 0, review: 0 },
  })

  // timers / stream refs
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const elapsedRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const startRef = useRef(0)
  const esRef = useRef<EventSource | null>(null)
  const simRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const sawLiveRef = useRef(false)

  // ── toasts / logs ──────────────────────────────────────────────────────────
  const toast = useCallback((msg: string, type: Toast['type'] = 'success') => {
    const id = ++toastId.current
    setToasts((t) => [...t, { id, msg, type }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4500)
  }, [])
  const dismissToast = useCallback((id: number) => setToasts((t) => t.filter((x) => x.id !== id)), [])
  const log = useCallback((text: string, type: LogLine['type'] = '') => {
    setLogs((l) => [...l, { text, type }].slice(-200))
  }, [])

  // ── health ───────────────────────────────────────────────────────────────
  const checkHealth = useCallback(async () => {
    try {
      const d = await api.health()
      const redis = (d.dependencies?.redis as string) || ''
      setHealth({
        online: true,
        redis: redis.includes('connected') ? 'connected' : 'degraded',
        model: (d.dependencies?.groq_model as string) || '',
      })
    } catch {
      setHealth({ online: false, redis: 'unknown', model: '' })
    }
  }, [])

  // ── flywheel ───────────────────────────────────────────────────────────────
  const refreshFlywheel = useCallback(async (currentLeads: Lead[]) => {
    const approved = currentLeads.filter((l) => l.status === 'outreach_ready').length
    const rejected = currentLeads.filter((l) => l.status === 'disqualified').length
    try {
      setFlywheel(await api.flywheel())
    } catch {
      setFlywheel(buildFlywheel(approved, rejected, Math.max(1, runIndex.current)))
    }
  }, [])

  // ── stage helpers ──────────────────────────────────────────────────────────
  const setStages = useCallback(
    (research: StageState, qualify: StageState, sales: StageState) => {
      setPipeline((p) => ({ ...p, stages: { research, qualify, sales } }))
    },
    [],
  )

  const updateStageFromElapsed = useCallback(() => {
    const e = Date.now() - startRef.current
    if (e < STAGE_RESEARCH_END) setStages('active', 'wait', 'wait')
    else if (e < STAGE_QUAL_END) setStages('done', 'active', 'wait')
    else setStages('done', 'done', 'active')
  }, [setStages])

  // ── theater stream ─────────────────────────────────────────────────────────
  const stopStream = useCallback(() => {
    esRef.current?.close()
    esRef.current = null
    if (simRef.current) {
      clearInterval(simRef.current)
      simRef.current = null
    }
  }, [])

  const openLiveStream = useCallback((runId: string) => {
    esRef.current?.close() // never leak a previous subscription
    sawLiveRef.current = false
    try {
      const es = new EventSource(api.streamUrl(runId))
      esRef.current = es
      es.onmessage = (m) => {
        try {
          const data = JSON.parse(m.data) as TheaterEvent
          sawLiveRef.current = true
          setTheaterLive(true)
          setTheaterEvents((evs) => [...evs, data])
          if (data.type === 'done') stopStream()
        } catch {
          /* ignore malformed frame */
        }
      }
      es.onerror = () => {
        // Backend may not implement /stream — fall back silently.
        es.close()
        esRef.current = null
      }
    } catch {
      /* EventSource unsupported / blocked */
    }
  }, [stopStream])

  // Drive a simulated theater stream from resolved leads (offline / no-SSE).
  const playSimulatedTheater = useCallback((keyword: string, resultLeads: Lead[]) => {
    if (sawLiveRef.current) return // real stream already covered it
    const gen = simulateTheater(keyword, resultLeads)
    if (simRef.current) clearInterval(simRef.current)
    simRef.current = setInterval(() => {
      const next = gen.next()
      if (next.done) {
        if (simRef.current) clearInterval(simRef.current)
        simRef.current = null
        return
      }
      setTheaterEvents((evs) => [...evs, { ...next.value, ts: Date.now() }])
    }, 280)
  }, [])

  // ── results ────────────────────────────────────────────────────────────────
  const handleResults = useCallback(
    (data: { leads?: Lead[]; pipeline_log?: string[] }, elapsed: number, keyword: string) => {
      const incoming = data.leads || []
      const fresh: Lead[] = []
      for (const l of incoming) {
        const key = leadKey(l)
        if (!key || knownIds.current.has(key)) continue
        knownIds.current.add(key)
        fresh.push(enrichTargeting(l))
      }
      const dup = incoming.length - fresh.length

      setLeads((prev) => {
        const merged = [...fresh, ...prev]
        void refreshFlywheel(merged)
        return merged
      })

      const lines = data.pipeline_log || [`Pipeline complete — ${fresh.length} new leads`]
      if (dup > 0) lines.push(`${dup} duplicate(s) skipped (already shown this session)`)
      lines.forEach((l) => log(l))

      setPipeline((p) => ({ ...p, lastDurationMs: elapsed }))

      // theater fallback if no live stream happened
      playSimulatedTheater(keyword, incoming)

      if (dup > 0 && fresh.length === 0)
        toast(`All ${dup} results already shown — try a different keyword`, 'error')
      else if (dup > 0) toast(`+${fresh.length} new leads (${dup} duplicates skipped)`, 'success')
      else toast(`✓ ${fresh.length} leads in ${fmtMs(elapsed)}`, 'success')
    },
    [log, playSimulatedTheater, refreshFlywheel, toast],
  )

  // ── timers ─────────────────────────────────────────────────────────────────
  const stopTimers = useCallback(() => {
    if (pollRef.current) clearInterval(pollRef.current)
    if (elapsedRef.current) clearInterval(elapsedRef.current)
    pollRef.current = null
    elapsedRef.current = null
  }, [])

  const finishRun = useCallback(
    (status: 'done' | 'error') => {
      stopTimers()
      setPipeline((p) => ({
        ...p,
        running: false,
        status,
        progressPct: status === 'done' ? 100 : p.progressPct,
        stages:
          status === 'done'
            ? { research: 'done', qualify: 'done', sales: 'done' }
            : p.stages,
      }))
    },
    [stopTimers],
  )

  const startElapsedTimer = useCallback(() => {
    if (elapsedRef.current) clearInterval(elapsedRef.current)
    elapsedRef.current = setInterval(() => {
      const e = Date.now() - startRef.current
      updateStageFromElapsed()
      setPipeline((p) => ({
        ...p,
        elapsedMs: e,
        progressPct: Math.min(94, (e / TOTAL_ESTIMATE) * 100),
      }))
    }, 500)
  }, [updateStageFromElapsed])

  const startPolling = useCallback(
    (runId: string, keyword: string) => {
      if (pollRef.current) clearInterval(pollRef.current)
      pollRef.current = setInterval(async () => {
        try {
          const s = await api.status(runId)
          if (s.status === 'SUCCESS') {
            const elapsed = Date.now() - startRef.current
            finishRun('done')
            stopStream()
            handleResults(s.result || {}, elapsed, keyword)
          } else if (s.status === 'FAILURE') {
            finishRun('error')
            stopStream()
            log('Pipeline failed: ' + (s.error || 'Unknown'), 'err')
            toast('Pipeline failed', 'error')
          }
        } catch (e) {
          log('Poll error: ' + (e as Error).message, 'warn')
        }
      }, 3000)
    },
    [finishRun, handleResults, log, stopStream, toast],
  )

  // ── offline simulated run (backend unreachable) ─────────────────────────────
  // Drives the Theater + stage progression entirely client-side so the headline
  // experience demos with zero infrastructure.
  const runOfflineSimulation = useCallback(
    (keyword: string) => {
      let base = leadsRef.current
      if (!base.length) {
        base = demoLeads()
        base.forEach((l) => knownIds.current.add(leadKey(l)))
        setLeads(base)
        void refreshFlywheel(base)
      }
      setPipeline((p) => ({ ...p, mode: 'sync' }))
      startRef.current = Date.now()
      const gen = simulateTheater(keyword, base)
      if (simRef.current) clearInterval(simRef.current)
      simRef.current = setInterval(() => {
        const next = gen.next()
        if (next.done) {
          if (simRef.current) clearInterval(simRef.current)
          simRef.current = null
          finishRun('done')
          const elapsed = Date.now() - startRef.current
          setPipeline((p) => ({ ...p, lastDurationMs: elapsed, progressPct: 100 }))
          toast(`✓ Simulated run complete (${base.length} leads)`, 'success')
          return
        }
        const e = next.value
        setTheaterEvents((evs) => [...evs, { ...e, ts: Date.now() }])
        setPipeline((p) => {
          const stages = { ...p.stages }
          if (e.stage === 'research') stages.research = 'active'
          else if (e.stage === 'qualify') {
            stages.research = 'done'
            stages.qualify = 'active'
          } else if (e.stage === 'sales') {
            stages.research = 'done'
            stages.qualify = 'done'
            stages.sales = 'active'
          } else if (e.stage === 'done') {
            stages.research = stages.qualify = stages.sales = 'done'
          }
          return {
            ...p,
            stages,
            elapsedMs: Date.now() - startRef.current,
            progressPct: Math.min(96, p.progressPct + 6),
          }
        })
      }, 260)
    },
    [finishRun, refreshFlywheel, toast],
  )

  // ── run pipeline ─────────────────────────────────────────────────────────────
  const runPipeline = useCallback(
    async (keyword: string, maxLeads: number, geo: GeoOpts = {}) => {
      if (!keyword.trim()) {
        toast('Enter a keyword first', 'error')
        return
      }
      runIndex.current += 1
      startRef.current = Date.now()
      setTheaterEvents([])
      setTheaterLive(false)
      sawLiveRef.current = false
      setTheaterOpen(true)
      // Mint the stream id CLIENT-side and subscribe before the request, so the
      // Agent Theater is live from second 0 — even in blocking sync mode.
      const runId = 'r' + Math.random().toString(36).slice(2, 10)
      setPipeline((p) => ({
        ...p,
        running: true,
        status: 'running',
        mode: null,
        runId,
        elapsedMs: 0,
        progressPct: 0,
        stages: { research: 'wait', qualify: 'wait', sales: 'wait' },
        counts: { found: 0, qualified: 0, review: 0 },
      }))
      log(`▶ Run #${runIndex.current} — "${keyword}" (max ${maxLeads})`)
      startElapsedTimer()
      openLiveStream(runId)

      try {
        const data = await api.generate(keyword, maxLeads, geo, runId)
        if (data.status === 'queued' && data.run_id) {
          setPipeline((p) => ({ ...p, mode: 'async', runId: data.run_id! }))
          log(`Queued — run_id ${data.run_id}; polling every 3s`)
          startPolling(data.run_id, keyword)
          if (data.run_id !== runId) openLiveStream(data.run_id)
        } else {
          setPipeline((p) => ({ ...p, mode: 'sync' }))
          const elapsed = Date.now() - startRef.current
          finishRun('done')
          handleResults(data, elapsed, keyword)
        }
      } catch {
        // Backend unreachable → fall back to a fully simulated run so the
        // Theater and all four features still demonstrate end-to-end.
        log('Backend unreachable — running simulated pipeline', 'warn')
        runOfflineSimulation(keyword)
      }
    },
    [
      finishRun,
      handleResults,
      log,
      openLiveStream,
      runOfflineSimulation,
      startElapsedTimer,
      startPolling,
      toast,
    ],
  )

  // ── other actions ────────────────────────────────────────────────────────────
  const ingest = useCallback(async () => {
    try {
      const d = await api.ingest()
      toast(
        d.status === 'skipped'
          ? '✓ Knowledge base already built'
          : `✓ Ingested ${d.pages_scraped ?? '?'} pages, ${d.chunks_stored ?? '?'} chunks`,
        'success',
      )
      log('› ' + (d.message || `Ingested ${d.chunks_stored ?? ''} chunks`))
    } catch (e) {
      toast('Ingest failed: ' + (e as Error).message, 'error')
      log('Ingest failed: ' + (e as Error).message, 'err')
    }
  }, [log, toast])

  const flush = useCallback(async () => {
    try {
      const d = await api.flush()
      toast('✓ ' + (d.message || 'Cache flushed'), 'success')
      log('› Redis flushed — next run starts fresh')
    } catch (e) {
      toast('Flush failed: ' + (e as Error).message, 'error')
    }
  }, [log, toast])

  const approve = useCallback(
    async (id: string) => {
      try {
        await api.approve(id)
      } catch {
        /* keep optimistic update even if backend offline in demo */
      }
      setLeads((prev) => {
        const next = prev.map((l) => (l.id === id ? { ...l, status: 'outreach_ready' } : l))
        void refreshFlywheel(next)
        return next
      })
      toast('✓ Lead approved → CRM', 'success')
      log(`› Lead ${id} approved → outreach_ready`)
    },
    [log, refreshFlywheel, toast],
  )

  const reject = useCallback(
    async (id: string) => {
      try {
        await api.reject(id)
      } catch {
        /* optimistic */
      }
      setLeads((prev) => {
        const next = prev.map((l) => (l.id === id ? { ...l, status: 'disqualified' } : l))
        void refreshFlywheel(next)
        return next
      })
      toast('Lead rejected', 'info')
    },
    [refreshFlywheel, toast],
  )

  const [genEmail, setGenEmail] = useState<Set<string>>(new Set())

  // ── Lead Warehouse (pre-harvested pool) ──────────────────────────────────────
  const [poolStats, setPoolStats] = useState<PoolStats>({ total: 0, leads: 0, raw: 0, enriched: 0, qualified: 0, outreach_ready: 0, pending_review: 0, excluded: 0, with_email: 0, with_phone: 0 })

  const refreshPool = useCallback(async () => {
    try {
      setPoolStats(await api.warehouseStats())
    } catch {
      /* warehouse offline — leave zeros */
    }
  }, [])

  const harvest = useCallback(
    async (keyword: string, geo?: GeoOpts) => {
      try {
        const d = await api.harvest(keyword, geo || {})
        toast('🌾 ' + (d.message || 'Harvest started'), 'info')
        log(`› Harvesting raw candidates for "${keyword}" into the pool…`)
        // Pool grows in the background — poll a few times to reflect growth.
        for (let i = 0; i < 6; i++) {
          await new Promise((r) => setTimeout(r, 2500))
          await refreshPool()
        }
      } catch (e) {
        toast('Harvest failed: ' + (e as Error).message, 'error')
        log('Harvest failed: ' + (e as Error).message, 'err')
      }
    },
    [log, toast, refreshPool],
  )

  const buildPool = useCallback(
    async (maxQueries = 60) => {
      try {
        const d = await api.harvestMatrix(maxQueries, 50)
        if (d.status === 'busy') {
          toast('Pool sweep already running…', 'info')
          return
        }
        toast('🏭 Building pool — sweeping industries × cities…', 'info')
        log(`› Matrix harvest started (${maxQueries} industry×city queries)…`)
        // Poll status until the sweep finishes (background on the server).
        for (let i = 0; i < 60; i++) {
          await new Promise((r) => setTimeout(r, 5000))
          const st = await api.harvestMatrixStatus().catch(() => null)
          await refreshPool()
          if (st && !st.running) {
            log(`› Pool sweep done: +${st.added} raw companies across ${st.done} queries.`)
            toast(`✓ Pool sweep added ${st.added} companies`, 'success')
            break
          }
        }
      } catch (e) {
        toast('Pool build failed: ' + (e as Error).message, 'error')
      }
    },
    [log, toast, refreshPool],
  )

  const enrichPool = useCallback(
    async (batch = 25, geo?: GeoOpts) => {
      try {
        const d = await api.enrichPool(batch, geo || {})
        if (d.status === 'busy') {
          toast('Enrichment already running…', 'info')
          return
        }
        toast('⚙ ' + (d.message || 'Enriching pool'), 'info')
        log(`› Enriching up to ${batch} pooled candidates in the background…`)
        // Enrichment is slower than harvest — poll longer to reflect growth.
        for (let i = 0; i < 10; i++) {
          await new Promise((r) => setTimeout(r, 4000))
          await refreshPool()
        }
        // Pull the freshly-enriched leads into the list.
        try {
          const got = (await api.leads()).leads || []
          got.forEach((l) => knownIds.current.add(leadKey(l)))
          setLeads(got.map(enrichTargeting))
        } catch {
          /* ignore */
        }
      } catch (e) {
        toast('Enrich failed: ' + (e as Error).message, 'error')
        log('Enrich failed: ' + (e as Error).message, 'err')
      }
    },
    [log, toast, refreshPool],
  )
  // Harvest a single city from EVERY working source at once: OSM (reliable, free,
  // phone+website), Google Places (if a key is set — verified phone), and the
  // JustDial/IndiaMART directories (best-effort, needs the headless engine). All
  // land as enriched leads; we poll until they settle and report the combined total.
  const harvestDirectory = useCallback(
    async (city: string) => {
      const c = city.trim()
      if (!c) {
        toast('Enter a city first', 'error')
        return
      }
      try {
        // Fire all sources. Each is independent + fail-safe; ignore individual errors.
        // OSM + Places are the reliable engines; the directory sweep (IndiaMART,
        // JustDial, TradeIndia, Sulekha, ExportersIndia via headless) is best-effort.
        await Promise.all([
          api.harvestOsm(c).catch(() => null),
          api.harvestPlaces(c).catch(() => null),
          api.harvestDirectories(c).catch(() => null),
        ])
        toast(`🏙 Harvesting ${c} from OSM + Places + 5 directories…`, 'info')
        log(`› Multi-source harvest started for ${c} (OSM · Google Places · IndiaMART · JustDial · TradeIndia · Sulekha · ExportersIndia)…`)
        for (let i = 0; i < 45; i++) {
          await new Promise((r) => setTimeout(r, 4000))
          const [osm, pl, dir] = await Promise.all([
            api.harvestOsmStatus().catch(() => null),
            api.harvestPlacesStatus().catch(() => null),
            api.harvestDirectoriesStatus().catch(() => null),
          ])
          await refreshPool()
          const allDone = [osm, pl, dir].every((s) => !s || !s.running)
          if (allDone) {
            const added = (osm?.added || 0) + (pl?.added || 0) + (dir?.added || 0)
            const bySite = dir?.by_site ? ' · ' + Object.entries(dir.by_site).map(([s, n]) => `${s} ${n}`).join(' ') : ''
            log(`› ${c}: harvest done — +${added} leads (OSM ${osm?.added || 0} · Places ${pl?.added || 0}${bySite}).`)
            toast(`✓ ${c}: +${added} leads from all sources`, 'success')
            break
          }
        }
      } catch (e) {
        toast('Harvest failed: ' + (e as Error).message, 'error')
        log('Harvest failed: ' + (e as Error).message, 'err')
      }
    },
    [log, toast, refreshPool],
  )

  // Ingest MCA company master data from data.gov.in for the states the free mirror
  // lacks (Delhi, Maharashtra) — tens of thousands of leads, same quality as the rest.
  const ingestMca = useCallback(
    async (states = 'Delhi,Maharashtra') => {
      try {
        const d = await api.harvestMcaLive(states)
        if (d.status === 'error') {
          toast(d.message || 'data.gov.in key required', 'error')
          log('› MCA ingest needs a free data.gov.in API key (Settings → Data sources).', 'warn')
          return
        }
        if (d.status === 'busy') { toast('MCA ingest already running…', 'info'); return }
        toast(`🏛 Ingesting ${states} from MCA (data.gov.in)…`, 'info')
        log(`› MCA (data.gov.in) ingest started for ${states} — tens of thousands of companies…`)
        for (let i = 0; i < 60; i++) {
          await new Promise((r) => setTimeout(r, 5000))
          const st = await api.harvestMcaLiveStatus().catch(() => null)
          await refreshPool()
          if (st && !st.running) {
            const by = st.by_state ? ' (' + Object.entries(st.by_state).map(([s, n]) => `${s} ${n}`).join(' · ') + ')' : ''
            log(`› MCA ingest done — +${st.added} leads${by}.`)
            toast(`✓ MCA: +${st.added} leads${by}`, 'success')
            break
          }
        }
      } catch (e) {
        toast('MCA ingest failed: ' + (e as Error).message, 'error')
      }
    },
    [log, toast, refreshPool],
  )

  // Attach the decision-maker (HR head/founder + email) to pooled leads via
  // Crustdata/PDL — the "right person to contact" fix.
  const enrichPeople = useCallback(
    async (state = '') => {
      try {
        const d = await api.enrichPeople(state)
        if (d.status === 'error') { toast(d.message || 'Crustdata/PDL key required', 'error'); return }
        if (d.status === 'busy') { toast('Decision-maker enrichment already running…', 'info'); return }
        toast(`👤 Finding decision-makers${state ? ` (${state})` : ''}…`, 'info')
        log(`› Decision-maker enrichment started (Crustdata/PDL)${state ? ` for ${state}` : ''}…`)
        for (let i = 0; i < 60; i++) {
          await new Promise((r) => setTimeout(r, 5000))
          const st = await api.enrichPeopleStatus().catch(() => null)
          await refreshPool()
          if (st && !st.running) {
            log(`› Decision-makers found for ${st.enriched}/${st.total} leads (${st.provider || '?'}).`)
            toast(`✓ Found decision-makers for ${st.enriched} leads`, 'success')
            break
          }
        }
      } catch (e) {
        toast('Enrichment failed: ' + (e as Error).message, 'error')
      }
    },
    [log, toast, refreshPool],
  )

  // Deep-enrich prime leads (optionally for one state): scrape the site for the
  // decision-maker + contact, then the LLM picks the right person + pitch angle.
  const deepEnrich = useCallback(
    async (state = '', batch = 50) => {
      try {
        const d = await api.deepVerify(batch, state)
        if (d.status === 'busy') {
          toast('Enrichment already running…', 'info')
          return
        }
        const where = state ? ` (${state})` : ''
        toast(`🔎 Deep-enriching ${batch} prime leads${where}…`, 'info')
        log(`› Deep-verify started — ${batch} prime leads${where} (decision-maker + contact + pitch).`)
        for (let i = 0; i < 30; i++) {
          await new Promise((r) => setTimeout(r, 4000))
          const st = await api.deepVerifyStatus().catch(() => null)
          await refreshPool()
          if (st && !st.running) {
            log(`› Deep-verify done — ${st.enriched ?? '?'} leads enriched.`)
            toast(`✓ Deep-enriched ${st.enriched ?? batch} leads`, 'success')
            break
          }
        }
      } catch (e) {
        toast('Deep-enrich failed: ' + (e as Error).message, 'error')
        log('Deep-enrich failed: ' + (e as Error).message, 'err')
      }
    },
    [log, toast, refreshPool],
  )

  const generateEmail = useCallback(
    async (id: string) => {
      setGenEmail((s) => new Set(s).add(id))
      try {
        const r = await api.generateEmail(id)
        if (r && (r as { outreach_draft?: unknown }).outreach_draft) {
          setLeads((prev) =>
            prev.map((l) =>
              l.id === id
                ? { ...l, outreach_draft: r.outreach_draft, follow_up_sequence: r.follow_up_sequence, status: r.status || l.status }
                : l,
            ),
          )
          toast('✓ Outreach sequence generated', 'success')
        } else {
          toast('Generation failed: ' + ((r as { error?: string })?.error || 'unknown'), 'error')
        }
      } catch (e) {
        toast('Generation failed: ' + (e as Error).message, 'error')
      } finally {
        setGenEmail((s) => {
          const n = new Set(s)
          n.delete(id)
          return n
        })
      }
    },
    [toast],
  )

  const loadDemo = useCallback(() => {
    const d = demoLeads()
    d.forEach((l) => knownIds.current.add(leadKey(l)))
    setLeads(d)
    void refreshFlywheel(d)
    log('› Loaded demo dataset (5 sample leads)')
    toast('Demo data loaded', 'info')
  }, [log, refreshFlywheel, toast])

  // ── derived: counts on pipeline panel ──────────────────────────────────────
  useEffect(() => {
    const found = leads.length
    const qualified = leads.filter((l) => QUALIFIED_STATUSES.includes(l.status)).length
    const review = leads.filter((l) => l.status === 'pending_review').length
    setPipeline((p) => ({ ...p, counts: { found, qualified, review } }))
  }, [leads])

  // ── boot ───────────────────────────────────────────────────────────────────
  useEffect(() => {
    checkHealth()
    void refreshPool()
    ;(async () => {
      try {
        const d = await api.leads()
        const got = (d.leads || []).map(enrichTargeting)
        if (got.length) {
          got.forEach((l) => knownIds.current.add(leadKey(l)))
          setLeads(got)
          void refreshFlywheel(got)
          log(`› Loaded ${d.total ?? got.length} leads from previous runs`)
        }
      } catch {
        log('⚠ Backend offline — use "Load demo data" to explore', 'warn')
      }
    })()
    return () => {
      stopTimers()
      stopStream()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── derived: visible (filtered/searched/sorted) leads ──────────────────────
  const visibleLeads = useMemo(() => {
    let v = [...leads]
    if (filter !== 'all') v = v.filter((l) => l.status === filter)
    if (stateFilter !== 'all') v = v.filter((l) => l.state === stateFilter)
    if (industryFilter !== 'all') v = v.filter((l) => l.industry === industryFilter)
    if (tierFilter !== 'all') v = v.filter((l) => l.icp_tier === tierFilter)
    if (mobileOnly) v = v.filter((l) => l.mobile || (l.phone_type === 'mobile' && l.phone))
    const q = search.toLowerCase().trim()
    if (q)
      v = v.filter(
        (l) =>
          (l.company_name || '').toLowerCase().includes(q) ||
          (l.industry || '').toLowerCase().includes(q),
      )
    if (sortByScore)
      v.sort((a, b) => (b.qualification_score || 0) - (a.qualification_score || 0))
    return v
  }, [leads, filter, search, sortByScore, stateFilter, industryFilter, mobileOnly, tierFilter])

  // Distinct states / industries present in the current leads, for filter dropdowns.
  const stateOptions = useMemo(
    () => Array.from(new Set(leads.map((l) => l.state || '').filter(Boolean))).sort() as string[],
    [leads],
  )
  const industryOptions = useMemo(
    () => Array.from(new Set(leads.map((l) => l.industry || '').filter(Boolean))).sort() as string[],
    [leads],
  )

  const value: AppValue = {
    leads,
    health,
    flywheel,
    filter,
    setFilter,
    sortByScore,
    toggleSort: () => setSortByScore((s) => !s),
    search,
    setSearch,
    visibleLeads,
    stateFilter,
    setStateFilter,
    industryFilter,
    setIndustryFilter,
    mobileOnly,
    setMobileOnly,
    tierFilter,
    setTierFilter,
    stateOptions,
    industryOptions,
    pipeline,
    logs,
    runPipeline,
    ingest,
    flush,
    approve,
    reject,
    generateEmail,
    genEmail,
    loadDemo,
    poolStats,
    harvest,
    buildPool,
    enrichPool,
    harvestDirectory,
    ingestMca,
    enrichPeople,
    deepEnrich,
    refreshPool,
    theaterOpen,
    setTheaterOpen,
    theaterEvents,
    theaterLive,
    toasts,
    toast,
    dismissToast,
  }

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}
