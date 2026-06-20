import { useMemo, useState, useEffect } from 'react'
import { useApp } from '../../store/AppContext'
import { leadKey } from '../../lib/format'
import LeadCard from './LeadCard'

const PAGE = 24

export default function LeadsGrid() {
  const { visibleLeads, leads } = useApp()
  const [page, setPage] = useState(1)

  // Stable lead → display-number map (avoids O(n²) indexOf per card).
  const numByKey = useMemo(() => {
    const m = new Map<string, number>()
    leads.forEach((l, i) => m.set(leadKey(l), i + 1))
    return m
  }, [leads])

  const totalPages = Math.max(1, Math.ceil(visibleLeads.length / PAGE))
  useEffect(() => { if (page > totalPages) setPage(1) }, [page, totalPages])
  const pageLeads = visibleLeads.slice((page - 1) * PAGE, page * PAGE)

  if (!visibleLeads.length) {
    return (
      <div className="empty-state">
        <div className="es-icon">{leads.length ? '🔍' : '🎯'}</div>
        <p>
          {leads.length ? (
            'No leads match this filter or search.'
          ) : (
            <>
              No leads yet.
              <br />
              Enter a keyword and click <strong>Generate Leads</strong> — or open the{' '}
              <strong>CRM</strong> to browse the full database.
            </>
          )}
        </p>
      </div>
    )
  }

  return (
    <>
      <div className="leads-grid">
        {pageLeads.map((lead, i) => (
          <LeadCard
            key={leadKey(lead)}
            lead={lead}
            num={numByKey.get(leadKey(lead)) || (page - 1) * PAGE + i + 1}
            total={visibleLeads.length}
            index={i}
          />
        ))}
      </div>
      {totalPages > 1 && (
        <div className="crm-pager">
          <button disabled={page <= 1} onClick={() => setPage(1)}>« First</button>
          <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>‹ Prev</button>
          <span className="pager-info">
            {(((page - 1) * PAGE) + 1).toLocaleString()}–{Math.min(page * PAGE, visibleLeads.length).toLocaleString()} of {visibleLeads.length.toLocaleString()}
          </span>
          <button disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>Next ›</button>
          <button disabled={page >= totalPages} onClick={() => setPage(totalPages)}>Last »</button>
        </div>
      )}
    </>
  )
}
