// ── Core lead shape — mirrors graph/state.py Lead (all fields optional-safe) ──
export type LeadStatus =
  | 'researched'
  | 'qualified'
  | 'disqualified'
  | 'outreach_ready'
  | 'pending_review'

export interface TechStack {
  current_tools?: string[]
  maturity?: 'legacy' | 'modern' | 'manual' | 'unknown' | string
  signals?: string[]
  pitch_angle?: string
}

export interface VerifiedEmail {
  email: string
  valid?: boolean
  quality?: 'high' | 'medium' | 'low' | string
}

export interface OutreachDraft {
  subject?: string
  email_body?: string
  follow_up_note?: string
  hallucination_confidence?: number
  hallucination_action?: 'pass' | 'warn' | 'reject' | string
  hallucination_warnings?: string[]
}

export interface FollowUp {
  day: number
  subject?: string
  email_body?: string
}

// ── Adversarial Qualification Debate ─────────────────────────────────────────
export interface DebateTurn {
  persona: 'skeptic' | 'champion' | 'analyst' | string
  round: number
  argument: string
  score: number
}
export interface DebateResult {
  consensus_score: number
  confidence: number
  rounds: number
  transcript: DebateTurn[]
  verdict: string
}

// ── Buyer Simulation & Email Arena ───────────────────────────────────────────
export interface SimVariant {
  variant: string // 'A' | 'B'
  subject: string
  email_body: string
  reply_likelihood: number // 0..1
  predicted_reaction: string
  top_objection: string
  sentiment: 'positive' | 'neutral' | 'negative' | string
}
export interface BuyerSimulation {
  persona_summary: string
  winner: string // 'A' | 'B'
  variants: SimVariant[]
  uplift: number // winner - loser reply likelihood (pp)
}

// ── No-HRMS detection + predictive scoring (the targeting core) ───────────────
export interface HrmsVerdict {
  has_hrms: boolean
  no_hrms_confidence: number // 0..1, higher = more confident they have NO HRMS
  detected_vendors: string[]
  maturity: 'manual' | 'legacy' | 'modern' | 'none' | 'unknown' | string
  application_method?: 'ats_portal' | 'email' | 'google_form' | 'static' | 'unknown' | string
  signals?: string[]
  pitch_angle?: string
}
export interface LeadScore {
  predicted_score: number // 0..10
  propensity: number // 0..1
  timing: 'now' | 'quarter' | 'watch' | string
  fit: number
  need: number
  reach: number
  no_hrms_confidence: number
  segment?: string // 'sme' | 'gcc'
  reasons: string[]
}
export interface TargetContact {
  target_title: string
  rationale: string
}

export interface GeoOpts {
  country?: string
  region?: string
  exclude_with_hrms?: boolean
  mode?: string // 'discover' | 'company'
  fast?: boolean // fast mode: deterministic, no per-company AI
}

// ── Cross-source verification ────────────────────────────────────────────────
export interface Verification {
  verified: boolean
  confidence: number
  sources_checked: number
  phone: { value: string | null; sources: string[]; agree: number; status: string }
  employees: { band: string | null; corroborated: boolean; sources: string[] }
  hrms_absence: { confirmed: boolean; second_source: string; vendor: string | null }
  domain: { official: boolean }
  notes: string[]
}

// ── Signals: website visitors + email A/B ────────────────────────────────────
export interface Visitor {
  ip: string
  org: string
  domain?: string
  city?: string
  country?: string
  page?: string
  ref?: string
  ts?: string
}
export interface AbVariant {
  variant: string
  sent: number
  opens: number
  clicks: number
  open_rate?: number | null
  click_rate?: number | null
}
export interface AbStats {
  variants: AbVariant[]
  winner: string | null
}

// ── Runtime settings (API keys / LLM provider, set from the UI) ──────────────
export interface SecretField {
  set: boolean
  preview: string
}
export interface RuntimeConfig {
  llm_provider: string
  active_provider: string
  // model ids (non-secret)
  aws_region: string
  bedrock_model: string
  anthropic_model: string
  openai_model: string
  deepseek_model: string
  gemini_model: string
  groq_model: string
  openrouter_model: string
  // secrets (masked)
  bedrock_api_key: SecretField
  aws_access_key_id: SecretField
  aws_secret_access_key: SecretField
  anthropic_api_key: SecretField
  openai_api_key: SecretField
  deepseek_api_key: SecretField
  gemini_api_key: SecretField
  groq_api_key: SecretField
  openrouter_api_key: SecretField
  serper_api_key: SecretField
  apollo_api_key: SecretField
  instantly_api_key: SecretField
  explorium_api_key: SecretField
  ipinfo_token: SecretField
  slack_webhook_url: SecretField
  crm_webhook_url: SecretField
}

export interface Lead {
  id?: string
  company_name?: string
  website?: string
  industry?: string
  size?: string | null
  location?: string | null
  address?: string | null
  phone?: string | null
  phone_type?: string | null // 'mobile' | 'landline'
  phone_source?: string | null // 'google_places' | 'company_website'
  mobile?: string | null // decision-maker mobile (primary contact)
  office_phone?: string | null // landline / toll-free (secondary)
  state?: string | null // Indian state (for filtering)
  lead_grade?: string | null // 'A' | 'B' | 'C' (contactability)
  icp_tier?: string | null // 'Hot' | 'Warm' | 'Cold' (likelihood to buy)
  icp_fit?: number | null // 0..1 industry HR-intensity
  dm_name?: string | null // decision-maker name
  dm_role?: string | null // decision-maker role (Founder/Director/HR…)
  verified?: boolean | null // passed the deep-verify reasoning pass
  verify?: {
    fit?: string
    confidence?: number
    needs_manual?: boolean
    pitch_angle?: string
    site_scraped?: boolean
    people_found?: { name: string; role: string }[]
  } | null
  contact_confidence?: string | null
  employee_band?: string | null
  employee_min?: number | null
  employee_max?: number | null
  verification?: Verification | null
  description?: string | null
  decision_makers?: string[] | null
  contact_emails?: string[] | null
  pain_points?: string[] | null
  status: LeadStatus | string

  decision_maker_name?: string | null
  decision_maker_full_name?: string | null
  decision_maker_title?: string | null
  decision_maker_linkedin?: string | null
  email_guesses?: string[] | null

  tech_stack?: TechStack | null

  qualification_score?: number | null
  qualification_reason?: string | null
  key_signals?: string[] | null
  recommended_action?: string | null
  summary?: string | null

  outreach_draft?: OutreachDraft | null
  follow_up_sequence?: FollowUp[] | null
  verified_emails?: VerifiedEmail[] | null

  // new-feature payloads (optional, populated when backend/sim available)
  debate?: DebateResult | null
  simulation?: BuyerSimulation | null
  hrms?: HrmsVerdict | null
  lead_score?: LeadScore | null
  target_contact?: TargetContact | null

  // client-only geo hint for the map
  _lat?: number
  _lng?: number
}

// ── API responses ────────────────────────────────────────────────────────────
export interface GenerateResponse {
  status: 'queued' | 'success' | string
  run_id?: string
  leads?: Lead[]
  pipeline_log?: string[]
}

export interface PipelineStatus {
  run_id: string
  status: 'PENDING' | 'STARTED' | 'SUCCESS' | 'FAILURE' | string
  result?: GenerateResponse
  error?: string
}

export interface HealthResponse {
  status?: string
  dependencies?: {
    redis?: string
    groq_model?: string
    [k: string]: unknown
  }
}

export interface FlywheelStats {
  approved: number
  rejected: number
  precision: number // 0..1
  history: { run: number; precision: number }[]
  signals: { label: string; weight: number }[]
  drift: number // positive = improving
}

// ── Live Agent Theater event stream ──────────────────────────────────────────
export type TheaterStage = 'research' | 'qualify' | 'sales' | 'done'
export interface TheaterEvent {
  ts: number
  stage: TheaterStage | string
  agent: string
  type:
    | 'stage_start'
    | 'stage_end'
    | 'reasoning'
    | 'lead_found'
    | 'score'
    | 'tool'
    | 'email'
    | 'done'
    | string
  message: string
  lead?: Partial<Lead>
  meta?: Record<string, unknown>
}
