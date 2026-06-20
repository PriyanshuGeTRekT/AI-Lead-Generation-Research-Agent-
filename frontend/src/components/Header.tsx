import { useApp } from '../store/AppContext'

export default function Header() {
  const { health, search, setSearch, sortByScore, toggleSort, pipeline } = useApp()
  return (
    <header className="topbar">
      <div className="tb-left">
        <span className="tb-crumb">RazorInfotech</span>
        <span className="tb-sep">/</span>
        <span className="tb-here">HRMS Leads AI</span>
      </div>
      <div className="tb-right">
        <div className="tb-search">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
            <circle cx="11" cy="11" r="7" />
            <path d="m21 21-4.3-4.3" />
          </svg>
          <input
            placeholder="Search companies…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <button className={'sort-btn' + (sortByScore ? ' active' : '')} onClick={toggleSort} title="Sort by score">
          {sortByScore ? '↓' : '↑'} Score
        </button>
        <span className={'mode-badge ' + (pipeline.mode === 'async' ? 'async' : 'sync')}>
          {pipeline.mode === 'async' ? 'ASYNC' : 'SYNC'}
        </span>
        <div className="tb-status">
          <span className={'dot ' + (health.online ? 'green' : 'red')} />
          {health.online ? 'Online' : 'Offline'}
          {health.model && <span className="model">{health.model}</span>}
        </div>
      </div>
    </header>
  )
}
