import { useApp } from '../../store/AppContext'
import ControlPanel from './ControlPanel'
import ProgressPanel from './ProgressPanel'
import StatsPanel from './StatsPanel'
import LogPanel from './LogPanel'

export default function Sidebar() {
  const { flush, pipeline } = useApp()
  return (
    <aside className="sidebar">
      <ControlPanel />
      <ProgressPanel />
      <StatsPanel />
      <LogPanel />
      <button className="btn btn-danger" disabled={pipeline.running} onClick={flush}>
        🗑 Flush Cache &amp; Dedup
      </button>
    </aside>
  )
}
