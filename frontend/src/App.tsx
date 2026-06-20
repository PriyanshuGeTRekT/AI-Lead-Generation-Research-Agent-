import { useEffect, useState } from 'react'
import Landing from './components/Landing'
import CrmApp from './components/crm/CrmApp'
import StartupIndia from './components/startups/StartupIndia'
import Sidebar from './components/sidebar/Sidebar'
import MetricsStrip from './components/MetricsStrip'
import FlywheelPanel from './components/flywheel/FlywheelPanel'
import SignalsRow from './components/SignalsRow'
import FilterBar from './components/FilterBar'
import LeadsGrid from './components/leads/LeadsGrid'
import AgentTheater from './components/theater/AgentTheater'
import Settings from './components/Settings'
import ChatWidget from './components/ChatWidget'
import Toasts from './components/Toasts'
import { useApp } from './store/AppContext'

export type Portal = 'home' | 'crm' | 'leadgen' | 'startups'

const VALID: Portal[] = ['home', 'crm', 'leadgen', 'startups']
function portalFromHash(): Portal {
  const h = window.location.hash.replace(/^#\/?/, '') as Portal
  return VALID.includes(h) ? h : 'home'
}

export default function App() {
  const { setTheaterOpen, pipeline } = useApp()
  const [portal, setPortalState] = useState<Portal>(portalFromHash)
  const [settingsOpen, setSettingsOpen] = useState(false)

  // Keep the URL hash in sync so a reload reopens the same page.
  const setPortal = (p: Portal) => {
    window.location.hash = p === 'home' ? '' : `/${p}`
    setPortalState(p)
  }
  useEffect(() => {
    const onHash = () => setPortalState(portalFromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  if (portal === 'home') return (<><Landing onPick={setPortal} /><Toasts /></>)

  return (
    <div className="shell">
      {/* Slim top bar with portal switch */}
      <div className="portal-bar">
        <button className="portal-home" onClick={() => setPortal('home')}>⌂</button>
        <img src="/logo.svg" className="pb-logo" alt="" />
        <span className="pb-title">HRMS Leads <span className="accent">AI</span></span>
        <div className="pb-switch">
          <button className={portal === 'crm' ? 'on' : ''} onClick={() => setPortal('crm')}>CRM · Sales</button>
          <button className={portal === 'startups' ? 'on' : ''} onClick={() => setPortal('startups')}>Startup India</button>
          <button className={portal === 'leadgen' ? 'on' : ''} onClick={() => setPortal('leadgen')}>Lead Gen &amp; Training</button>
        </div>
        <button className="pb-gear" onClick={() => setSettingsOpen(true)}>⚙</button>
      </div>

      {portal === 'crm' && (
        <main className="content crm-content" key="crm">
          <div className="page-head">
            <div>
              <div className="page-title">CRM <span className="accent">Pipeline</span></div>
              <div className="page-sub">Work every lead — filter, sort and update across the full database</div>
            </div>
          </div>
          <CrmApp />
        </main>
      )}

      {portal === 'startups' && (
        <main className="content crm-content" key="startups">
          <div className="page-head">
            <div>
              <div className="page-title">Startup India <span className="accent">Source</span></div>
              <div className="page-sub">Harvest the government startup registry — the ICP feedstock, contact enrichment is step two</div>
            </div>
          </div>
          <StartupIndia />
        </main>
      )}

      {portal === 'leadgen' && (
        <div className="layout" key="leadgen">
          <Sidebar />
          <main className="content">
            <div className="page-head reveal">
              <div>
                <div className="page-title">Lead Generation <span className="accent">&amp; Training</span></div>
                <div className="page-sub">Generate, enrich and score leads · A/B testing · self-learning ICP</div>
              </div>
              <button className="theater-btn" onClick={() => setTheaterOpen(true)}>
                <span className="tb-dot" /> {pipeline.running ? 'Watch live' : 'Agent Theater'}
              </button>
            </div>
            <MetricsStrip />
            <FlywheelPanel />
            <SignalsRow />
            <FilterBar />
            <LeadsGrid />
          </main>
        </div>
      )}

      <AgentTheater />
      <Settings open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      <ChatWidget />
      <Toasts />
    </div>
  )
}
