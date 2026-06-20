// Local "intelligence simulator". When the backend is offline or hasn't yet
// produced a payload for a feature, these deterministic generators keep every
// feature fully functional for a demo — grounded in each lead's real fields.
import type {
  BuyerSimulation,
  DebateResult,
  DebateTurn,
  FlywheelStats,
  Lead,
  TheaterEvent,
} from '../types'

function hash(s: string): number {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return Math.abs(h)
}
function rng(seed: number) {
  let s = seed || 1
  return () => {
    s = (s * 1103515245 + 12345) & 0x7fffffff
    return s / 0x7fffffff
  }
}

// ── Demo leads (used by "Load demo data" when backend is empty/offline) ───────
const DEMO: Lead[] = [
  {
    id: 'demo-1',
    company_name: 'Rajesh Textiles Pvt Ltd',
    website: 'https://rajeshtextiles.in',
    industry: 'Textile Manufacturing',
    size: '240 employees',
    location: 'Surat, Gujarat',
    phone: '0261 2345678',
    phone_type: 'landline',
    phone_source: 'google_places',
    contact_confidence: 'high',
    employee_band: '201-500 employees',
    employee_min: 201,
    employee_max: 500,
    verification: {
      verified: true,
      confidence: 100,
      sources_checked: 4,
      phone: { value: '0261 2345678', sources: ['google_places', 'company_website'], agree: 2, status: 'high' },
      employees: { band: '201-500 employees', corroborated: true, sources: ['linkedin', 'company_website'] },
      hrms_absence: { confirmed: true, second_source: 'clear', vendor: null },
      domain: { official: true },
      notes: [],
    },
    status: 'outreach_ready',
    qualification_score: 8.4,
    qualification_reason:
      'Mid-size manufacturer running HR on spreadsheets; strong fit for attendance + payroll automation with an accessible HR head.',
    key_signals: ['manual Excel HR', '240 staff', 'expanding to 2nd unit'],
    decision_maker_full_name: 'Anita Sharma',
    decision_maker_title: 'Head of HR',
    decision_maker_linkedin: 'https://linkedin.com/in/anita-sharma',
    contact_emails: ['hr@rajeshtextiles.in', 'anita@rajeshtextiles.in'],
    verified_emails: [{ email: 'hr@rajeshtextiles.in', valid: true, quality: 'high' }],
    pain_points: ['Manual attendance', 'Payroll errors', 'High shop-floor attrition'],
    tech_stack: {
      maturity: 'manual',
      current_tools: ['Excel', 'Paper registers'],
      pitch_angle: 'Replace spreadsheets with automated attendance + payroll.',
    },
    outreach_draft: {
      subject: 'Cutting payroll errors at Rajesh Textiles',
      email_body:
        'Hi Anita,\n\nRunning a 240-person floor on spreadsheets usually means payroll corrections eat a full day each cycle. HumanMaximizer automates attendance-to-payroll so that day disappears.\n\nWorth a 15-min look next week?\n\nBest regards,\nPriyanshu\nHumanMaximizer | humanmaximizer.com',
      hallucination_confidence: 0.92,
    },
    follow_up_sequence: [
      { day: 3, subject: 'Re: payroll', email_body: 'Quick follow-up, Anita — one number...' },
      { day: 7, subject: 'How Surat mills cut attrition', email_body: 'Sharing a quick insight...' },
      { day: 14, subject: 'Closing the loop — Rajesh Textiles', email_body: 'Last note from me...' },
    ],
  },
  {
    id: 'demo-2',
    company_name: 'Nimbus Logistics',
    website: 'https://nimbuslogistics.co',
    industry: 'Logistics & Supply Chain',
    size: '520 employees',
    location: 'Pune, Maharashtra',
    phone: '020 28765432',
    phone_type: 'landline',
    phone_source: 'company_website',
    contact_confidence: 'medium',
    employee_band: '501-1,000 employees',
    employee_min: 501,
    employee_max: 1000,
    status: 'pending_review',
    qualification_score: 6.3,
    qualification_reason:
      'Growing multi-city logistics firm on legacy SAP; moderate fit, but shift-scheduling pain is acute and the DM is identified.',
    key_signals: ['hiring drivers', 'multi-city ops', 'legacy SAP'],
    decision_maker_full_name: 'Vikram Rao',
    decision_maker_title: 'People Operations Lead',
    contact_emails: ['vikram@nimbuslogistics.co'],
    pain_points: ['Shift scheduling chaos', 'Compliance across states'],
    tech_stack: {
      maturity: 'legacy',
      current_tools: ['SAP SuccessFactors'],
      pitch_angle: 'Modernize shift scheduling on top of existing SAP.',
    },
    outreach_draft: {
      subject: 'Shift scheduling across Nimbus’ 6 hubs',
      email_body:
        'Hi Vikram,\n\nMulti-state driver rosters on SAP tend to break at the depot level. HumanMaximizer layers smart shift-scheduling on top of SAP — no rip-and-replace.\n\nOpen to a quick walkthrough?\n\nBest regards,\nPriyanshu\nHumanMaximizer | humanmaximizer.com',
      hallucination_confidence: 0.86,
    },
    follow_up_sequence: [
      { day: 3, subject: 'Re: scheduling', email_body: 'One more thought, Vikram...' },
    ],
  },
  {
    id: 'demo-3',
    company_name: 'Meridian Hospitals',
    website: 'https://meridianhospitals.in',
    industry: 'Healthcare',
    size: '900 employees',
    location: 'Hyderabad, Telangana',
    status: 'outreach_ready',
    qualification_score: 7.6,
    qualification_reason:
      '24/7 hospital network with complex nurse rostering and statutory compliance — high need, strong budget signals.',
    key_signals: ['24/7 rostering', 'NABH compliance', '3 new branches'],
    decision_maker_full_name: 'Dr. Kavya Reddy',
    decision_maker_title: 'VP People & Culture',
    contact_emails: ['careers@meridianhospitals.in'],
    pain_points: ['Nurse rostering', 'Statutory compliance', 'Credential tracking'],
    tech_stack: {
      maturity: 'modern',
      current_tools: ['Darwinbox'],
      pitch_angle: 'Specialized healthcare rostering Darwinbox lacks.',
    },
    outreach_draft: {
      subject: 'Nurse rostering across Meridian’s branches',
      email_body:
        'Hi Kavya,\n\nDarwinbox is solid for core HR, but 24/7 nurse rostering with NABH credential tracking is where most hospitals still bleed hours. That gap is exactly what we close.\n\nWorth comparing notes?\n\nBest regards,\nPriyanshu\nHumanMaximizer | humanmaximizer.com',
      hallucination_confidence: 0.9,
    },
  },
  {
    id: 'demo-4',
    company_name: 'PayrollPro Solutions',
    website: 'https://payrollpro.io',
    industry: 'HRMS software',
    size: '80 employees',
    location: 'Bengaluru, Karnataka',
    status: 'disqualified',
    qualification_score: 1.0,
    qualification_reason: 'Competitor — sells HRMS/payroll software. Not a prospect.',
    key_signals: ['sells HR software', 'competitor'],
    pain_points: [],
    summary:
      'PayrollPro Solutions  |  HRMS software  |  Bengaluru  |  80 employees\nScore: 1.0/10  █░░░░░░░░░\nCOMPETITOR — sells HRMS software, not a prospect.',
  },
  {
    id: 'demo-5',
    company_name: 'Aanya Foods & Beverages',
    website: 'https://aanyafoods.com',
    industry: 'FMCG Manufacturing',
    size: '160 employees',
    location: 'Indore, Madhya Pradesh',
    status: 'qualified',
    qualification_score: 6.8,
    qualification_reason:
      'Signal score 6.8/10 — growing FMCG plant with seasonal contract labor and manual shift compliance; no HRMS detected.',
    key_signals: ['no HRMS detected', 'seasonal contract labor', '160 staff'],
    pain_points: ['Seasonal contract labor', 'Shift compliance'],
    tech_stack: { maturity: 'manual', current_tools: ['Excel'] },
  },
]

// ── Client-side targeting enrichment (mirrors backend tools/lead_scoring.py) ──
// Fills hrms / lead_score / target_contact when the backend hasn't (offline demo,
// simulated runs, or older payloads), so the targeting UI always has data.
const _WORKFORCE = [
  'manufact', 'logistic', 'supply', 'retail', 'hospitalit', 'hotel', 'restaurant',
  'healthcare', 'hospital', 'construction', 'bpo', 'staffing', 'security', 'textile',
  'fmcg', 'pharma', 'education', 'ecommerce', 'e-commerce', 'warehous', 'transport', 'food',
]
function _sizeN(s?: string | null): number | null {
  const m = String(s || '').replace(/,/g, '').match(/(\d+)/)
  return m ? parseInt(m[1], 10) : null
}
function _sizeFit(n: number | null): number {
  if (n == null) return 0.5
  if (n < 15) return 0.2
  if (n < 30) return 0.55
  if (n <= 200) return 1
  if (n <= 500) return 0.9
  if (n <= 1000) return 0.65
  if (n <= 2000) return 0.4
  return 0.2
}
function _contact(n: number | null) {
  if (n == null) return { target_title: 'HR Head / Founder', rationale: 'size unknown — start with the HR head' }
  if (n < 50) return { target_title: 'Founder / Director', rationale: '<50 staff: HR reports to the founder/owner' }
  if (n <= 200) return { target_title: 'HR Manager / HR Head', rationale: '50–200 staff: an HR manager owns tooling decisions' }
  if (n <= 500) return { target_title: 'Head of People / VP HR', rationale: '200–500 staff: a people-ops leader drives HRMS purchases' }
  return { target_title: 'CHRO / VP HR', rationale: '500+ staff: the CHRO owns the HRMS budget' }
}

export function enrichTargeting(lead: Lead): Lead {
  if (lead.lead_score && lead.hrms && lead.target_contact) return lead
  const maturity = (lead.hrms?.maturity || lead.tech_stack?.maturity || 'unknown') as string
  const tools = lead.hrms?.detected_vendors || lead.tech_stack?.current_tools || []
  const hasHrms = lead.hrms?.has_hrms ?? (maturity === 'legacy' || maturity === 'modern')
  const noHrms =
    lead.hrms?.no_hrms_confidence ??
    ({ manual: 0.9, none: 0.75, unknown: 0.5, legacy: 0.1, modern: 0.05 } as Record<string, number>)[
      maturity
    ] ??
    0.5
  const n = _sizeN(lead.size)
  const blob = `${lead.industry || ''} ${lead.description || ''} ${(lead.pain_points || []).join(' ')}`.toLowerCase()
  const fit = Number((0.6 * _sizeFit(n) + 0.4 * (_WORKFORCE.some((k) => blob.includes(k)) ? 1 : 0.55)).toFixed(2))
  const hiring = /hiring|vacanc|recruit|career/.test(blob)
  let need = 0.4
  if (maturity === 'manual') need = 0.9
  else if ((lead.pain_points || []).length) need = 0.6
  if (hiring) need = Math.max(need, 0.75)
  let reach = 0.2
  if (lead.decision_maker_full_name || lead.decision_maker_name) reach += 0.4
  if ((lead.contact_emails || []).length) reach += 0.4
  reach = Math.min(1, reach)
  const predicted = Number((10 * (0.35 * noHrms + 0.3 * need + 0.2 * fit + 0.15 * reach)).toFixed(1))
  const near = n != null && ((n >= 40 && n <= 120) || (n >= 90 && n <= 220))
  const timing = noHrms >= 0.7 && (hiring || near) ? 'now' : noHrms >= 0.6 && fit >= 0.7 ? 'quarter' : 'watch'
  const reasons: string[] = []
  if (noHrms >= 0.7) reasons.push('no HRMS detected (greenfield)')
  if (hasHrms) reasons.push('already runs an HRMS — weak fit')
  if (_sizeFit(n) >= 0.9 && n != null) reasons.push(`${n} employees — prime adoption band`)
  if (maturity === 'manual') reasons.push('manual HR processes')

  return {
    ...lead,
    hrms:
      lead.hrms ||
      {
        has_hrms: hasHrms,
        no_hrms_confidence: noHrms,
        detected_vendors: tools,
        maturity,
        application_method: hasHrms ? 'ats_portal' : maturity === 'manual' ? 'email' : 'static',
        signals: lead.tech_stack?.signals || [],
        pitch_angle: lead.tech_stack?.pitch_angle || '',
      },
    lead_score: lead.lead_score || {
      predicted_score: predicted,
      propensity: Number((predicted / 10).toFixed(2)),
      timing,
      fit,
      need: Number(need.toFixed(2)),
      reach: Number(reach.toFixed(2)),
      no_hrms_confidence: Number(noHrms.toFixed(2)),
      reasons: reasons.slice(0, 5),
    },
    target_contact: lead.target_contact || _contact(n),
  }
}

export function demoLeads(): Lead[] {
  return DEMO.map((l) => enrichTargeting({ ...l }))
}

// ── Adversarial Qualification Debate ─────────────────────────────────────────
export function buildDebate(lead: Lead): DebateResult {
  const base = lead.qualification_score ?? 5
  const r = rng(hash(lead.company_name || lead.id || 'x'))
  const pains = lead.pain_points || []
  const tools = lead.tech_stack?.current_tools || []
  const dm = lead.decision_maker_full_name || lead.decision_maker_name
  const rounds = 2
  const transcript: DebateTurn[] = []

  const champLines = [
    `${lead.company_name} shows ${pains[0] || 'clear workforce pain'} — textbook trigger for HRMS adoption.`,
    dm
      ? `We even have the decision maker: ${dm}${lead.decision_maker_title ? `, ${lead.decision_maker_title}` : ''}. Warm path in.`
      : `${lead.industry || 'This sector'} with ${lead.size || 'this headcount'} almost always buys within two quarters.`,
  ]
  const skepticLines = [
    tools.length
      ? `They already run ${tools.join(', ')} — switching cost is real. I'd discount enthusiasm.`
      : `No visible HR tooling means no budget line yet — this could be a long nurture, not a close.`,
    `${lead.location || 'Region'} mid-market deals stall on procurement. Consensus score should stay grounded.`,
  ]
  const analystLines = [
    `ICP match on size (${lead.size || 'unknown'}) and industry (${lead.industry || 'n/a'}) is ${
      base >= 6 ? 'strong' : 'partial'
    }.`,
    `Weighing both: pain is genuine, but ${tools.length ? 'incumbent tooling' : 'budget ambiguity'} caps confidence.`,
  ]

  for (let round = 1; round <= rounds; round++) {
    transcript.push({
      persona: 'champion',
      round,
      argument: champLines[round - 1] || champLines[0],
      score: clamp(base + 1.2 + r() * 0.6),
    })
    transcript.push({
      persona: 'skeptic',
      round,
      argument: skepticLines[round - 1] || skepticLines[0],
      score: clamp(base - 1.4 - r() * 0.7),
    })
    transcript.push({
      persona: 'analyst',
      round,
      argument: analystLines[round - 1] || analystLines[0],
      score: clamp(base + (r() - 0.5) * 0.8),
    })
  }

  const consensus = clamp(
    transcript.filter((t) => t.round === rounds).reduce((a, t) => a + t.score, 0) / 3,
  )
  const spread = Math.max(...transcript.map((t) => t.score)) - Math.min(...transcript.map((t) => t.score))
  const confidence = clamp01(1 - spread / 10)

  return {
    consensus_score: round1(consensus),
    confidence: round2(confidence),
    rounds,
    transcript,
    verdict:
      consensus >= 5
        ? `Consensus: pursue. Champion and Analyst outweigh the Skeptic's switching-cost concern.`
        : `Consensus: nurture, don't pursue yet. Skeptic's budget/timing concerns dominate.`,
  }
}

// ── Buyer Simulation & Email Arena ───────────────────────────────────────────
export function buildSimulation(lead: Lead): BuyerSimulation {
  const r = rng(hash((lead.company_name || '') + 'sim'))
  const dm = lead.decision_maker_full_name || lead.decision_maker_name || 'the HR lead'
  const title = lead.decision_maker_title || 'HR decision maker'
  const pain = (lead.pain_points || ['HR efficiency'])[0]
  const tools = lead.tech_stack?.current_tools || []
  const a = lead.outreach_draft?.email_body || `Hi, quick note about ${pain}...`
  const subjectA = lead.outreach_draft?.subject || `Solving ${pain}`

  // Variant B = a sharper, shorter, more specific rewrite.
  const subjectB = `${dm.split(' ')[0]}, one fix for ${pain.toLowerCase()}`
  const b = `Hi ${dm.split(' ')[0]},\n\nNoticed ${lead.company_name} likely wrestles with ${pain.toLowerCase()}. We fixed exactly this for a ${
    lead.industry || 'similar'
  } firm in ${lead.location || 'India'} in 3 weeks. Want the 2-line summary of how?\n\n— Priyanshu`

  const likeA = clamp01(0.28 + (lead.qualification_score ?? 5) / 25 + r() * 0.1)
  const likeB = clamp01(likeA + 0.06 + r() * 0.12) // sharper variant usually wins
  const winner = likeB >= likeA ? 'B' : 'A'

  const objection = tools.length
    ? `"We already use ${tools[0]} — why switch?"`
    : `"Is this really a budget priority this quarter?"`

  return {
    persona_summary: `${dm}, ${title} at ${lead.company_name}. Pragmatic, time-poor, skeptical of cold email. Cares about ${pain.toLowerCase()} and avoiding rip-and-replace. Responds to specificity and proof, ignores generic pitches.`,
    winner,
    uplift: round1(Math.abs(likeB - likeA) * 100),
    variants: [
      {
        variant: 'A',
        subject: subjectA,
        email_body: a,
        reply_likelihood: round2(likeA),
        predicted_reaction:
          likeA > 0.4
            ? `${dm.split(' ')[0]} skims it, sees the relevance, flags for later.`
            : `Reads the first line, finds it slightly generic, likely archives.`,
        top_objection: objection,
        sentiment: likeA > 0.4 ? 'neutral' : 'negative',
      },
      {
        variant: 'B',
        subject: subjectB,
        email_body: b,
        reply_likelihood: round2(likeB),
        predicted_reaction: `Opens on the named pain, the "2-line summary" ask is low-friction — ${dm.split(' ')[0]} is likely to reply "sure".`,
        top_objection: objection,
        sentiment: likeB > 0.45 ? 'positive' : 'neutral',
      },
    ],
  }
}

// ── Self-Learning ICP Flywheel ───────────────────────────────────────────────
export function buildFlywheel(approved: number, rejected: number, runIndex: number): FlywheelStats {
  const total = approved + rejected
  const base = total ? approved / total : 0.5
  const history: { run: number; precision: number }[] = []
  // Simulate precision climbing as more labels accumulate.
  for (let i = 1; i <= Math.max(1, runIndex); i++) {
    const p = clamp01(0.42 + i * 0.05 + Math.sin(i) * 0.02)
    history.push({ run: i, precision: round2(Math.min(p, 0.94)) })
  }
  const precision = history.length ? history[history.length - 1].precision : round2(base)
  const drift = history.length > 1 ? round2(precision - history[0].precision) : 0
  return {
    approved,
    rejected,
    precision,
    history,
    drift,
    signals: [
      { label: 'manual / spreadsheet HR', weight: 0.92 },
      { label: '100–500 employees', weight: 0.81 },
      { label: 'manufacturing / logistics', weight: 0.74 },
      { label: 'identified HR decision maker', weight: 0.69 },
      { label: 'multi-location ops', weight: 0.55 },
      { label: 'already on modern HRMS', weight: -0.63 },
      { label: 'sells HR software', weight: -0.98 },
    ],
  }
}

// ── Simulated Theater event stream (offline fallback for Live Agent Theater) ──
export function* simulateTheater(keyword: string, leads: Lead[]): Generator<TheaterEvent> {
  const now = 0
  yield ev('research', 'research_agent', 'stage_start', `Searching multi-source for "${keyword}"`)
  yield ev('research', 'research_agent', 'tool', 'Querying Instantly.ai (160M contacts) + Serper.dev')
  const found = leads.filter((l) => l.status !== 'disqualified' || (l.qualification_score ?? 0) <= 2)
  for (const l of leads) {
    yield ev('research', 'research_agent', 'reasoning', `Scraping ${l.website || l.company_name}…`)
    yield ev('research', 'research_agent', 'lead_found', `Extracted ${l.company_name}`, l)
  }
  yield ev('research', 'research_agent', 'stage_end', `${found.length} leads extracted`)

  yield ev('qualify', 'qualification_agent', 'stage_start', 'Adversarial debate scoring')
  for (const l of leads) {
    const s = l.qualification_score ?? 5
    yield ev('qualify', 'qualification_agent', 'reasoning', `Debating ${l.company_name} (3 personas)…`, l)
    yield ev('qualify', 'qualification_agent', 'score', `${l.company_name} → ${s}/10`, l, { score: s })
  }
  yield ev('qualify', 'qualification_agent', 'stage_end', 'Consensus scores assigned')

  yield ev('sales', 'sales_agent', 'stage_start', 'Drafting + buyer-simulating sequences')
  for (const l of leads.filter((l) => (l.qualification_score ?? 0) >= 5)) {
    yield ev('sales', 'sales_agent', 'reasoning', `Simulating ${l.decision_maker_full_name || 'buyer'} reading the email…`, l)
    yield ev('sales', 'sales_agent', 'email', `Variant B won for ${l.company_name}`, l)
  }
  yield ev('sales', 'sales_agent', 'stage_end', 'Sequences ready')
  yield ev('done', 'supervisor', 'done', 'Pipeline complete')
  void now
}

function ev(
  stage: string,
  agent: string,
  type: TheaterEvent['type'],
  message: string,
  lead?: Lead,
  meta?: Record<string, unknown>,
): TheaterEvent {
  return { ts: Date.now(), stage, agent, type, message, lead, meta }
}

// ── number helpers ───────────────────────────────────────────────────────────
function clamp(n: number) {
  return Math.max(0, Math.min(10, n))
}
function clamp01(n: number) {
  return Math.max(0, Math.min(1, n))
}
function round1(n: number) {
  return Math.round(n * 10) / 10
}
function round2(n: number) {
  return Math.round(n * 100) / 100
}
