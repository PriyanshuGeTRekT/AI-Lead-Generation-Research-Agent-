import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { useApp } from '../store/AppContext'
import type { RuntimeConfig, SecretField } from '../types'

interface FieldDef {
  k: string
  label: string
  secret?: boolean
  ph?: string
}

// LLM providers — each with its key(s) + model id. Add a key, flip the pill, go.
const PROVIDERS: { id: string; label: string; note?: string; fields: FieldDef[] }[] = [
  {
    id: 'bedrock',
    label: 'AWS Bedrock',
    note: 'Use a Bedrock API key (ABSK… bearer) OR a classic access-key/secret pair.',
    fields: [
      { k: 'bedrock_api_key', label: 'Bedrock API Key (bearer · ABSK…)', secret: true },
      { k: 'aws_access_key_id', label: 'Access Key ID (alt)', secret: true },
      { k: 'aws_secret_access_key', label: 'Secret Access Key (alt)', secret: true },
      { k: 'aws_region', label: 'Region', ph: 'us-east-1' },
      { k: 'bedrock_model', label: 'Model ID', ph: 'us.anthropic.claude-sonnet-4-20250514-v1:0' },
    ],
  },
  {
    id: 'anthropic',
    label: 'Claude (Anthropic)',
    fields: [
      { k: 'anthropic_api_key', label: 'API Key', secret: true },
      { k: 'anthropic_model', label: 'Model', ph: 'claude-3-5-sonnet-latest' },
    ],
  },
  {
    id: 'openai',
    label: 'OpenAI',
    fields: [
      { k: 'openai_api_key', label: 'API Key', secret: true },
      { k: 'openai_model', label: 'Model', ph: 'gpt-4o' },
    ],
  },
  {
    id: 'deepseek',
    label: 'DeepSeek',
    fields: [
      { k: 'deepseek_api_key', label: 'API Key', secret: true },
      { k: 'deepseek_model', label: 'Model', ph: 'deepseek-v4-flash' },
    ],
  },
  {
    id: 'gemini',
    label: 'Gemini (Google)',
    fields: [
      { k: 'gemini_api_key', label: 'API Key', secret: true },
      { k: 'gemini_model', label: 'Model', ph: 'gemini-2.5-flash' },
    ],
  },
  {
    id: 'groq',
    label: 'Groq',
    fields: [
      { k: 'groq_api_key', label: 'API Key', secret: true },
      { k: 'groq_model', label: 'Model', ph: 'llama-3.1-8b-instant' },
    ],
  },
  {
    id: 'openrouter',
    label: 'OpenRouter',
    note: 'OpenAI-compatible gateway to 100+ models (free + paid).',
    fields: [
      { k: 'openrouter_api_key', label: 'API Key (sk-or-…)', secret: true },
      { k: 'openrouter_model', label: 'Model', ph: 'google/gemma-4-31b-it:free' },
    ],
  },
  {
    id: 'nvidia',
    label: 'NVIDIA NIM',
    note: 'build.nvidia.com — free frontier open models (Llama 3.3 70B, DeepSeek-R1…). Add both a fast (bulk) + strong (reasoning) model.',
    fields: [
      { k: 'nvidia_api_key', label: 'API Key (nvapi-…)', secret: true },
      { k: 'nvidia_model_fast', label: 'Fast model (bulk classify)', ph: 'meta/llama-3.1-8b-instruct' },
      { k: 'nvidia_model_strong', label: 'Strong model (reasoning/email)', ph: 'meta/llama-3.3-70b-instruct' },
    ],
  },
  {
    id: 'pool',
    label: '⚡ Multi-model Pool',
    note: 'Round-robins across EVERY key you’ve added (NVIDIA + DeepSeek + Groq + OpenRouter) with automatic failover. Fastest + most resilient — recommended once you have 2+ keys.',
    fields: [],
  },
]

const SOURCES: FieldDef[] = [
  { k: 'datagovin_api_key', label: 'data.gov.in — MCA company data for Delhi/Maharashtra (FREE key)', secret: true },
  { k: 'crustdata_api_key', label: 'Crustdata — company + decision-maker (HR/founder) data + email', secret: true },
  { k: 'pdl_api_key', label: 'People Data Labs — company discovery + decision-maker enrichment', secret: true },
  { k: 'google_places_api_key', label: 'Google Places — city×category businesses + verified phone ($200/mo free)', secret: true },
  { k: 'serper_api_key', label: 'Serper.dev — search + verified phone', secret: true },
  { k: 'apollo_api_key', label: 'Apollo.io — decision-maker + DIRECT-DIAL phone (free tier)', secret: true },
  { k: 'explorium_api_key', label: 'Explorium — B2B firmographics', secret: true },
  { k: 'instantly_api_key', label: 'Instantly.ai — B2B contacts', secret: true },
  { k: 'ipinfo_token', label: 'IPinfo — website-visitor → company', secret: true },
  { k: 'slack_webhook_url', label: 'Slack webhook — human review', secret: true },
  { k: 'crm_webhook_url', label: 'CRM webhook — HubSpot / Zapier', secret: true },
]

export default function Settings({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { toast } = useApp()
  const [cfg, setCfg] = useState<RuntimeConfig | null>(null)
  const [provider, setProvider] = useState('bedrock')
  const [fields, setFields] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!open) return
    setFields({})
    api
      .getConfig()
      .then((c) => {
        setCfg(c)
        setProvider(c.llm_provider || c.active_provider || 'bedrock')
      })
      .catch(() => toast('Backend offline — settings will apply when it’s running', 'info'))
  }, [open, toast])

  if (!open) return null

  const set = (k: string, v: string) => setFields((f) => ({ ...f, [k]: v }))
  const cfgVal = (k: string): unknown => (cfg ? (cfg as unknown as Record<string, unknown>)[k] : undefined)

  const placeholder = (f: FieldDef): string => {
    if (f.secret) {
      const s = cfgVal(f.k) as SecretField | undefined
      return s?.set ? `•••• ${s.preview.slice(-4)} (set)` : 'not set'
    }
    return (cfgVal(f.k) as string) || f.ph || ''
  }

  const save = async () => {
    setSaving(true)
    const patch: Record<string, string> = { llm_provider: provider }
    for (const [k, v] of Object.entries(fields)) if (v !== '') patch[k] = v
    try {
      const updated = await api.saveConfig(patch)
      setCfg(updated)
      toast(`✓ Saved · active LLM: ${updated.active_provider}`, 'success')
      onClose()
    } catch (e) {
      toast('Save failed: ' + (e as Error).message, 'error')
    } finally {
      setSaving(false)
    }
  }

  const cur = PROVIDERS.find((p) => p.id === provider) || PROVIDERS[0]

  return (
    <div className="settings-overlay" onClick={onClose}>
      <div className="settings" onClick={(e) => e.stopPropagation()}>
        <div className="settings-head">
          <div className="settings-title">⚙ Settings · Providers &amp; API Keys</div>
          <button className="settings-close" onClick={onClose}>
            ✕
          </button>
        </div>

        <div className="settings-body">
          <div className="set-group">
            <div className="set-glabel">LLM Provider — switch anytime</div>
            <div className="provider-row">
              {PROVIDERS.map((p) => {
                const hasKey = p.fields[0] && (cfgVal(p.fields[0].k) as SecretField | undefined)?.set
                return (
                  <button
                    key={p.id}
                    className={'provider-pill' + (provider === p.id ? ' on' : '')}
                    onClick={() => setProvider(p.id)}
                  >
                    {p.label}
                    {hasKey && <span className="key-dot" title="key set" />}
                  </button>
                )
              })}
            </div>
            {cfg && (
              <div className="set-note">
                Active: <b>{cfg.active_provider}</b> · keys stored server-side, never echoed back.
              </div>
            )}
          </div>

          <div className="set-group">
            <div className="set-glabel">{cur.label} {cur.fields.length ? 'credentials' : 'status'}</div>
            {cur.note && <div className="set-note">{cur.note}</div>}
            {cur.fields.map((f) => (
              <Field
                key={f.k}
                label={f.label}
                type={f.secret ? 'password' : 'text'}
                ph={placeholder(f)}
                onChange={(v) => set(f.k, v)}
              />
            ))}
            {cur.id === 'pool' && <PoolStatus open={open} />}
          </div>

          <div className="set-group">
            <div className="set-glabel">Data sources &amp; integrations</div>
            {SOURCES.map((f) => (
              <Field key={f.k} label={f.label} type="password" ph={placeholder(f)} onChange={(v) => set(f.k, v)} />
            ))}
          </div>
        </div>

        <div className="settings-foot">
          <button className="btn btn-secondary" onClick={onClose} style={{ width: 'auto' }}>
            Cancel
          </button>
          <button className="btn btn-primary" onClick={save} disabled={saving} style={{ width: 'auto' }}>
            {saving ? 'Saving…' : 'Save settings'}
          </button>
        </div>
      </div>
    </div>
  )
}

function PoolStatus({ open }: { open: boolean }) {
  const [pool, setPool] = useState<Awaited<ReturnType<typeof api.llmPool>> | null>(null)
  useEffect(() => {
    if (!open) return
    api.llmPool().then(setPool).catch(() => setPool(null))
  }, [open])
  if (!pool) return <div className="set-note">No endpoints yet — add an NVIDIA / DeepSeek / Groq key above.</div>
  if (!pool.endpoints)
    return <div className="set-note">Pool empty — add at least one OpenAI-compatible key (NVIDIA, DeepSeek, Groq, OpenRouter).</div>
  return (
    <div className="pool-status">
      <div className="set-note">
        <b>{pool.endpoints}</b> endpoints · {pool.fast} fast · {pool.strong} strong · {pool.available} ready now
      </div>
      <div className="pool-eps">
        {pool.providers.map((p) => (
          <div key={p.name} className={'pool-ep' + (p.cooling_down ? ' cooling' : '')}>
            <span className={'pool-ep-tier ' + p.tier}>{p.tier}</span>
            <span className="pool-ep-name">{p.name}</span>
            <span className="pool-ep-model">{p.model}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function Field({
  label,
  ph,
  type = 'text',
  onChange,
}: {
  label: string
  ph?: string
  type?: string
  onChange: (v: string) => void
}) {
  return (
    <label className="set-field">
      <span className="set-flabel">{label}</span>
      <input className="set-input" type={type} placeholder={ph} onChange={(e) => onChange(e.target.value)} autoComplete="off" />
    </label>
  )
}
