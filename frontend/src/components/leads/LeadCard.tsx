import { useState } from 'react'
import type { Lead } from '../../types'
import { useApp } from '../../store/AppContext'
import { initials, isHttp, scoreClass, scoreColor, stripProtocol } from '../../lib/format'
import EmailSequence from './EmailSequence'
import DebatePanel from './DebatePanel'
import EmailArena from './EmailArena'

const STATUS_BADGE: Record<string, { cls: string; label: string }> = {
  outreach_ready: { cls: 'outreach', label: '✉ Outreach Ready' },
  pending_review: { cls: 'pending', label: '⏳ Pending Review' },
  qualified: { cls: 'qualified', label: '✓ Qualified' },
  disqualified: { cls: 'disqualified', label: '✗ Disqualified' },
  researched: { cls: 'researched', label: '○ Researched' },
}

type Tab = 'debate' | 'arena' | 'sequence' | null

const TIMING: Record<string, { label: string; cls: string }> = {
  now: { label: '⚡ Buy-ready now', cls: 'now' },
  quarter: { label: '◷ This quarter', cls: 'quarter' },
  watch: { label: '👁 Watch', cls: 'watch' },
}

export default function LeadCard({
  lead,
  num,
  total,
  index = 0,
}: {
  lead: Lead
  num: number
  total: number
  index?: number
}) {
  const { approve, reject, generateEmail, genEmail } = useApp()
  const [tab, setTab] = useState<Tab>(null)
  const generating = genEmail.has(lead.id || '')

  const score = lead.qualification_score
  const badge = STATUS_BADGE[lead.status] || null
  const verified = new Set(
    (lead.verified_emails || []).map((v) => (typeof v === 'string' ? v : v.email)),
  )
  const emails = (lead.contact_emails || []).filter(Boolean)
  const dmName = lead.decision_maker_full_name || lead.decision_maker_name || ''
  const dmLinkedin = isHttp(lead.decision_maker_linkedin) ? lead.decision_maker_linkedin : ''
  const tech = lead.tech_stack
  const tools = tech?.current_tools || []
  const pains = (lead.pain_points || []).slice(0, 5)

  const hasDraft = !!lead.outreach_draft?.email_body
  const hasScore = score != null && lead.status !== 'researched'

  const hrms = lead.hrms
  const sc = lead.lead_score
  const tc = lead.target_contact
  const noHrms = hrms?.no_hrms_confidence ?? sc?.no_hrms_confidence ?? null
  const hasTargeting = !!(hrms || sc || tc)
  const timing = sc?.timing ? TIMING[sc.timing] : null

  const toggle = (t: Tab) => setTab((cur) => (cur === t ? null : t))

  return (
    <div className="lead-card" style={{ animationDelay: `${Math.min(index * 0.05, 0.4)}s` }}>
      <div className="lead-head">
        <div className="lead-head-main">
          <div className="lead-num-row">
            <span className="lead-num">
              #{num}
              <span className="of"> / {total}</span>
            </span>
            <div className="lead-company">{lead.company_name || 'Unknown'}</div>
            {lead.icp_tier && (
              <span className={'icp-badge ' + lead.icp_tier.toLowerCase()}>
                {lead.icp_tier === 'Hot' ? '🔥 ' : lead.icp_tier === 'Warm' ? '🌤 ' : '❄ '}
                {lead.icp_tier}
              </span>
            )}
            {lead.verified && (
              <span
                className="icp-badge"
                style={{ background: '#dceee0', color: '#2f6b4a' }}
                title={`Reasoned & verified · confidence ${Math.round((lead.verify?.confidence || 0) * 100)}%`}
              >
                ✓ Verified {Math.round((lead.verify?.confidence || 0) * 100)}%
              </span>
            )}
          </div>
          <div className="lead-meta">
            {lead.industry && <span>📊 {lead.industry}</span>}
            {lead.size && <span>👥 {lead.size}</span>}
            {lead.location && <span>📍 {lead.location}</span>}
          </div>
          <div className="lead-meta-row">
            {isHttp(lead.website) && (
              <a className="lead-web" href={lead.website} target="_blank" rel="noopener noreferrer">
                {stripProtocol(lead.website)}
              </a>
            )}
            {tech?.maturity && (
              <span className={'tech-badge ' + (tech.maturity || 'unknown')}>
                {tools.length ? tools.slice(0, 2).join(', ') : tech.maturity}
              </span>
            )}
          </div>
        </div>
        <div className="lead-badges">{badge && <span className={'badge ' + badge.cls}>{badge.label}</span>}</div>
      </div>

      <div className="lead-body">
        {hasScore && (
          <div className="score-bar">
            <span className="sb-label">Score</span>
            <div className="sb-track">
              <div
                className={'sb-fill ' + scoreClass(score)}
                style={{ width: `${Math.round((score || 0) * 10)}%`, background: scoreColor(score) }}
              />
            </div>
            <span className="sb-val" style={{ color: scoreColor(score) }}>
              {score}/10
            </span>
          </div>
        )}

        {hasTargeting && (
          <div className="targeting">
            <div className="tg-row">
              <span className="tg-k">No-HRMS fit</span>
              <div className="tg-meter">
                <div className="tg-fill" style={{ width: `${Math.round((noHrms ?? 0) * 100)}%` }} />
              </div>
              <span className="tg-v">{noHrms != null ? `${Math.round(noHrms * 100)}%` : '—'}</span>
            </div>
            <div className="tg-tags">
              {hrms?.has_hrms ? (
                <span className="tg-tag bad">Runs {hrms.detected_vendors?.[0] || 'HRMS'}</span>
              ) : (
                <span className="tg-tag good">No HRMS detected</span>
              )}
              {!hrms?.has_hrms && hrms?.application_method && hrms.application_method !== 'unknown' && (
                <span className="tg-tag">apply via {String(hrms.application_method).replace('_', ' ')}</span>
              )}
              {timing && <span className={'tg-tag timing ' + timing.cls}>{timing.label}</span>}
              {sc?.predicted_score != null && <span className="tg-tag">fit {sc.predicted_score}/10</span>}
              {lead.employee_band && <span className="tg-tag">👥 {lead.employee_band}</span>}
              {sc?.segment === 'gcc' && <span className="tg-tag">GCC</span>}
              {lead.verification && (
                <span
                  className={'tg-tag verify ' + (lead.verification.verified ? 'ok' : 'weak')}
                  title={
                    `Confidence ${lead.verification.confidence}% · ${lead.verification.sources_checked} sources\n` +
                    `Phone: ${lead.verification.phone.status} (${lead.verification.phone.sources.join(', ') || '—'})\n` +
                    `Employees: ${lead.verification.employees.corroborated ? 'corroborated' : 'single source'}\n` +
                    `No-HRMS 2nd source: ${lead.verification.hrms_absence.second_source}` +
                    (lead.verification.notes.length ? `\n• ${lead.verification.notes.join('\n• ')}` : '')
                  }
                >
                  {lead.verification.verified ? '✓✓' : '⚠'} {lead.verification.sources_checked}-source · {lead.verification.confidence}%
                </span>
              )}
            </div>
            {tc && (
              <div className="tg-contact">
                <span className="tg-k">Reach out to</span> <b>{tc.target_title}</b>
                <span className="tg-rat">{tc.rationale}</span>
              </div>
            )}
          </div>
        )}

        {lead.summary ? (
          <pre className="lead-summary">{lead.summary}</pre>
        ) : (
          <>
            {lead.description && <div className="lead-desc">{lead.description}</div>}
            {lead.qualification_reason && <div className="qual-reason">{lead.qualification_reason}</div>}
          </>
        )}

        {/* Decision maker */}
        <div className="section">
          <div className="section-h">Decision Maker</div>
          <div className="dm-row">
            <div className="dm-avatar">{dmName ? initials(dmName) : '?'}</div>
            <div className="dm-info">
              <div className="dm-name">
                {dmName || <span className="muted-i">Not identified</span>}
              </div>
              {lead.decision_maker_title && <div className="dm-title">{lead.decision_maker_title}</div>}
            </div>
            {dmLinkedin && (
              <a className="dm-linkedin" href={dmLinkedin} target="_blank" rel="noopener noreferrer">
                LinkedIn ↗
              </a>
            )}
          </div>
        </div>

        {/* Contact */}
        <div className="section">
          <div className="section-h">
            Contact Info {verified.size > 0 && <span className="muted-i">(✓ = verified MX)</span>}
          </div>
          <div className="contact-emails">
            {emails.length ? (
              emails.map((e) => (
                <span className="email-chip" key={e}>
                  <a href={`mailto:${e}`}>{e}</a>
                  <span className={verified.has(e) ? 'q-high' : 'q-med'}>
                    {verified.has(e) ? '✓' : '✉'}
                  </span>
                </span>
              ))
            ) : (
              <span className="muted-i">No email found</span>
            )}
          </div>
          {(() => {
            const mobile = lead.mobile || (lead.phone_type === 'mobile' ? lead.phone : '')
            const office = lead.office_phone || ''
            return (
              <>
                {mobile && mobile.trim() && (
                  <div className="contact-line">
                    📱 <a href={`tel:${mobile}`}>{mobile}</a>
                    <span className="ph-tag verified">mobile</span>
                  </div>
                )}
                {office && office.trim() && (
                  <div className="contact-line muted">
                    ☎ <a href={`tel:${office}`}>{office}</a>
                    <span className="ph-tag">office line</span>
                  </div>
                )}
              </>
            )
          })()}
          {lead.address && lead.address.trim().toLowerCase() !== 'unknown' && (
            <div className="contact-line muted">🏢 {lead.address}</div>
          )}
          {lead.dm_name && (
            <div className="contact-line">
              👤 <b>{lead.dm_name}</b>
              {lead.dm_role && <span className="ph-tag">{lead.dm_role}</span>}
            </div>
          )}
        </div>

        {/* Deep-verify reasoning output */}
        {lead.verify && (lead.verify.pitch_angle || lead.verify.needs_manual) && (
          <div className="section">
            <div className="section-h">AI Verdict</div>
            {lead.verify.pitch_angle && <div className="pitch">💡 {lead.verify.pitch_angle}</div>}
            <div className="lead-meta" style={{ marginTop: 6 }}>
              {lead.verify.fit && <span>{lead.verify.fit === 'yes' ? '✓ Good fit' : '✗ Weak fit'}</span>}
              {lead.verify.confidence != null && (
                <span>🎯 {Math.round((lead.verify.confidence || 0) * 100)}% confidence</span>
              )}
              {lead.verify.needs_manual && <span style={{ color: '#9a6a14' }}>⚠ needs manual contact lookup</span>}
            </div>
          </div>
        )}

        {/* Tech stack */}
        {tech?.maturity && (
          <div className="section">
            <div className="section-h">Current HR Stack</div>
            <div className="tech-row">
              <span className={'tech-badge ' + tech.maturity}>{String(tech.maturity).toUpperCase()}</span>
              {tools.length > 0 && <span className="tech-tools">{tools.join(' · ')}</span>}
            </div>
            {tech.pitch_angle && <div className="pitch">💡 {tech.pitch_angle}</div>}
          </div>
        )}

        {/* Pain points */}
        {pains.length > 0 && (
          <div className="section">
            <div className="section-h">Pain Points</div>
            <div className="pain-tags">
              {pains.map((p) => (
                <span className="pain-tag" key={p}>
                  {p}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Intelligence tabs */}
      {(hasScore || hasDraft || !!lead.id) && (
        <div className="lead-tabs">
          {hasScore && (
            <button className={'lead-tab' + (tab === 'debate' ? ' on' : '')} onClick={() => toggle('debate')}>
              ⚖ Debate
            </button>
          )}
          {hasDraft && (
            <button className={'lead-tab' + (tab === 'arena' ? ' on' : '')} onClick={() => toggle('arena')}>
              🥊 Buyer Arena
            </button>
          )}
          {hasDraft ? (
            <button className={'lead-tab' + (tab === 'sequence' ? ' on' : '')} onClick={() => toggle('sequence')}>
              ✉ Sequence
            </button>
          ) : (
            lead.id && (
              <button
                className="lead-tab gen"
                disabled={generating}
                onClick={() => generateEmail(lead.id || '')}
                title="Draft the 4-touch outreach for this lead"
              >
                {generating ? '✶ Generating…' : '✉ Generate outreach'}
              </button>
            )
          )}
        </div>
      )}
      {tab && (
        <div className="lead-tab-panel">
          {tab === 'debate' && <DebatePanel lead={lead} />}
          {tab === 'arena' && <EmailArena lead={lead} />}
          {tab === 'sequence' && <EmailSequence lead={lead} />}
        </div>
      )}

      {/* Review actions */}
      {lead.status === 'pending_review' && lead.id && (
        <div className="review-actions">
          <button className="btn-approve" onClick={() => approve(lead.id!)}>
            ✓ Approve → CRM
          </button>
          <button className="btn-reject" onClick={() => reject(lead.id!)}>
            ✗ Reject
          </button>
        </div>
      )}
    </div>
  )
}
