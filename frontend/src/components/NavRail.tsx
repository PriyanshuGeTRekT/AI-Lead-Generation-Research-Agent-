import { useApp } from '../store/AppContext'

export type View = 'dashboard' | 'leads' | 'crm' | 'sequences' | 'insights'

const NAV: { id: View; label: string; icon: string }[] = [
  { id: 'dashboard', label: 'Dashboard', icon: 'M3 13h8V3H3v10zm0 8h8v-6H3v6zm10 0h8V11h-8v10zm0-18v6h8V3h-8z' },
  { id: 'leads', label: 'Leads', icon: 'M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z' },
  { id: 'crm', label: 'CRM Pipeline', icon: 'M4 4h4v16H4zM10 4h4v10h-4zM16 4h4v7h-4z' },
  { id: 'sequences', label: 'Sequences', icon: 'M4 4h16v12H5.17L4 17.17V4z' },
  { id: 'insights', label: 'Insights', icon: 'M3 3v18h18M7 14l4-4 3 3 5-6' },
]

function Icon({ d }: { d: string }) {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d={d} />
    </svg>
  )
}

export default function NavRail({
  view,
  onNavigate,
  onOpenSettings,
}: {
  view: View
  onNavigate: (v: View) => void
  onOpenSettings: () => void
}) {
  const { health } = useApp()
  return (
    <nav className="rail">
      <img className="rail-logo" src="/logo.svg" alt="RazorInfotech" title="RazorInfotech HRMS Leads AI" />
      <div className="rail-nav">
        {NAV.map((n) => (
          <button
            key={n.id}
            className={'rail-item' + (view === n.id ? ' active' : '')}
            title={n.label}
            aria-label={n.label}
            onClick={() => onNavigate(n.id)}
          >
            <Icon d={n.icon} />
            <span className="rail-tip">{n.label}</span>
          </button>
        ))}
      </div>
      <div className="rail-foot">
        <button className="rail-item" title="Settings · API keys" aria-label="Settings" onClick={onOpenSettings}>
          <Icon d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
          <span className="rail-tip">Settings</span>
        </button>
        <div className={'rail-status ' + (health.online ? 'on' : 'off')} title={health.online ? 'API online' : 'API offline'} />
      </div>
    </nav>
  )
}
