import type { Lead } from '../types'

export function fmtMs(ms: number): string {
  const s = Math.floor(ms / 1000)
  const m = Math.floor(s / 60)
  return m > 0 ? `${m}m ${s % 60}s` : `${s}s`
}

export function initials(name?: string | null): string {
  if (!name) return '?'
  return name
    .trim()
    .split(/\s+/)
    .map((w) => w[0])
    .slice(0, 2)
    .join('')
    .toUpperCase()
}

export function scoreColor(score?: number | null): string {
  if (score == null) return 'var(--muted)'
  if (score >= 7) return 'var(--green)'
  if (score >= 4) return 'var(--amber)'
  return 'var(--red)'
}

export function scoreClass(score?: number | null): 'high' | 'mid' | 'low' | 'none' {
  if (score == null) return 'none'
  if (score >= 7) return 'high'
  if (score >= 4) return 'mid'
  return 'low'
}

export function stripProtocol(url?: string | null): string {
  return (url || '').replace(/^https?:\/\//, '')
}

export function isHttp(url?: string | null): url is string {
  // Hide synthetic dedup URLs for phone-only leads (*.osm.lead).
  return !!url && /^https?:\/\//.test(url) && !url.includes('.osm.lead')
}

export const QUALIFIED_STATUSES = ['outreach_ready', 'pending_review', 'qualified']

export function leadKey(l: Lead): string {
  return l.id || l.company_name || JSON.stringify(l)
}

export function pct(n: number): string {
  return `${Math.round(n * 100)}%`
}
