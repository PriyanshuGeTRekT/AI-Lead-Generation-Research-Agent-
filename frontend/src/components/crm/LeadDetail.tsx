import type { Lead } from '../../types'

const STAGES: [string, string][] = [
  ['new', 'Not Contacted'], ['contacted', 'Contacted'], ['in_loop', 'In the Loop'],
  ['won', 'Won'], ['rejected', 'Rejected'],
]

export default function LeadDetail({
  lead, onClose, onStage,
}: {
  lead: Lead
  onClose: () => void
  onStage: (lead: Lead, stage: string) => void
}) {
  const x = lead as unknown as Record<string, unknown>
  const verify = (x.verify || {}) as Record<string, unknown>
  const hrms = (x.hrms || {}) as Record<string, unknown>
  const emails = lead.contact_emails || (x.dm_email ? [x.dm_email as string] : [])
  const stage = (x.crm_stage as string) || 'new'

  const Row = ({ label, value }: { label: string; value: React.ReactNode }) =>
    value ? (
      <div className="ld-row">
        <span className="ld-k">{label}</span>
        <span className="ld-v">{value}</span>
      </div>
    ) : null

  return (
    <div className="ld-overlay" onClick={onClose}>
      <aside className="ld-drawer" onClick={(e) => e.stopPropagation()}>
        <div className="ld-head">
          <div>
            <div className="ld-name">{lead.company_name || 'Unknown'}</div>
            <div className="ld-tags">
              {lead.icp_tier && (
                <span className={'icp-badge ' + lead.icp_tier.toLowerCase()}>
                  {lead.icp_tier === 'Hot' ? '🔥' : lead.icp_tier === 'Warm' ? '🌤' : '❄'} {lead.icp_tier}
                </span>
              )}
              {lead.industry && <span className="ld-chip">{lead.industry}</span>}
              {(x.state as string) && <span className="ld-chip">📍 {x.state as string}</span>}
            </div>
          </div>
          <button className="ld-close" onClick={onClose}>✕</button>
        </div>

        {/* Buying signal — why this lead is ranked where it is */}
        {x.signal_score != null && (
          <div className="ld-section">
            <div className="ld-sh">🔥 Buying signal — {Math.round(x.signal_score as number)}/100</div>
            {Array.isArray(x.signal_reasons) && (x.signal_reasons as string[]).length > 0 && (
              <ul className="ld-pains">
                {(x.signal_reasons as string[]).map((r) => <li key={r}>{r}</li>)}
              </ul>
            )}
          </div>
        )}

        {/* Quick stage control */}
        <div className="ld-stage-row">
          {STAGES.map(([k, l]) => (
            <button
              key={k}
              className={'ld-stage-btn' + (stage === k ? ' on' : '')}
              onClick={() => onStage(lead, k)}
            >
              {l}
            </button>
          ))}
        </div>

        {/* Contact block */}
        <div className="ld-section">
          <div className="ld-sh">Contact</div>
          <Row label="Lead ID" value={(x.id as string) || (lead.website || '').replace(/^https?:\/\//, '')} />
          <Row label="Decision-maker" value={(x.dm_name as string) || ''} />
          <Row label="Role" value={(x.dm_role as string) || ''} />
          <Row
            label="Email"
            value={emails.length ? emails.map((e) => <a key={e} href={`mailto:${e}`}>{e}</a>).reduce((a, b) => <>{a}, {b}</>) : ''}
          />
          <Row label="Mobile" value={lead.mobile ? <a href={`tel:${lead.mobile}`}>{lead.mobile}</a> : ''} />
          <Row label="Office line" value={(x.office_phone as string) ? <a href={`tel:${x.office_phone as string}`}>{x.office_phone as string}</a> : ''} />
          <Row label="Website" value={lead.website && !String(lead.website).includes('.lead') ? <a href={lead.website} target="_blank" rel="noreferrer">{lead.website}</a> : ''} />
          <Row label="Address" value={(x.address as string) || ''} />
        </div>

        {/* Qualification block */}
        <div className="ld-section">
          <div className="ld-sh">Qualification</div>
          <Row label="HRMS-fit score" value={lead.qualification_score != null ? <b>{lead.qualification_score} / 10</b> : ''} />
          <Row label="ICP tier" value={lead.icp_tier} />
          <Row label="Industry" value={lead.industry} />
          <Row label="State / location" value={(x.state as string) || lead.location} />
          <Row label="Company status" value={(x.company_status as string) || ''} />
          <Row label="CIN" value={(x.cin as string) || ''} />
          <Row label="Source" value={(x.source as string) || ''} />
          <Row label="Has existing HRMS?" value={hrms.vendors && (hrms.vendors as string[]).length ? `Yes — ${(hrms.vendors as string[]).join(', ')}` : 'No (prospect)'} />
        </div>

        {/* AI verdict */}
        {(verify.pitch_angle || verify.confidence != null) && (
          <div className="ld-section">
            <div className="ld-sh">AI Verdict</div>
            {verify.pitch_angle ? <div className="pitch">💡 {verify.pitch_angle as string}</div> : null}
            <Row label="Fit" value={verify.fit as string} />
            <Row label="Confidence" value={verify.confidence != null ? `${Math.round((verify.confidence as number) * 100)}%` : ''} />
            <Row label="Needs manual lookup" value={verify.needs_manual ? 'Yes' : ''} />
          </div>
        )}

        {/* Pain points */}
        {Array.isArray(x.pain_points) && (x.pain_points as string[]).length > 0 && (
          <div className="ld-section">
            <div className="ld-sh">Pitch — likely HR pain</div>
            <ul className="ld-pains">
              {(x.pain_points as string[]).map((p) => <li key={p}>{p}</li>)}
            </ul>
          </div>
        )}
      </aside>
    </div>
  )
}
