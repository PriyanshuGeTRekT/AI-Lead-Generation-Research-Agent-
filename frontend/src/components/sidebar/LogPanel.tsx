import { useEffect, useRef } from 'react'
import { useApp } from '../../store/AppContext'

export default function LogPanel() {
  const { logs } = useApp()
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight
  }, [logs])

  return (
    <div className="panel-bare">
      <div className="section-label">Pipeline Log</div>
      <div className="log-box" ref={ref}>
        {logs.length === 0 ? (
          <span className="log-empty">No run yet. Click Generate Leads to start.</span>
        ) : (
          logs.map((l, i) => (
            <div key={i} className={'log-line ' + (l.type === 'err' ? 'err' : l.type === 'warn' ? 'warn' : '')}>
              › {l.text}
            </div>
          ))
        )}
      </div>
    </div>
  )
}
