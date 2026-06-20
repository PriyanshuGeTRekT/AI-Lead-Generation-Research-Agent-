import type { Portal } from '../App'

export default function Landing({ onPick }: { onPick: (p: Portal) => void }) {
  return (
    <div className="landing">
      <div className="landing-inner">
        <div className="landing-brand">
          <img src="/logo.svg" alt="" className="landing-logo" />
          <div>
            <div className="landing-title">
              RazorInfotech · HRMS Leads <span className="accent">AI</span>
            </div>
            <div className="landing-sub">Find companies that don’t have HRMS yet — and close them.</div>
          </div>
        </div>

        <div className="landing-cards">
          <button className="portal-card" onClick={() => onPick('crm')}>
            <div className="portal-ico">🗂️</div>
            <div className="portal-name">CRM <span className="accent">· Sales</span></div>
            <p className="portal-desc">
              Work your pipeline — every lead with full contact details, HRMS-fit score and
              Hot/Warm/Cold tier. Move leads through Not&nbsp;Contacted → Contacted → In&nbsp;the&nbsp;Loop →
              Won, filter and sort across lakhs of records instantly.
            </p>
            <div className="portal-go">Open CRM →</div>
          </button>

          <button className="portal-card" onClick={() => onPick('leadgen')}>
            <div className="portal-ico">⚙️</div>
            <div className="portal-name">Lead Generation <span className="accent">· & Training</span></div>
            <p className="portal-desc">
              Generate and refine leads with the harvest → enrich → score pipeline, watch the
              live agent theater, run A/B email tests, and let the self-learning flywheel sharpen
              the ICP from every deal you win.
            </p>
            <div className="portal-go">Open Studio →</div>
          </button>
        </div>
      </div>
    </div>
  )
}
