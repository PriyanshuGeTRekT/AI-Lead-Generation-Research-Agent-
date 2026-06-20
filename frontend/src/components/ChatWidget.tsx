import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'

interface Msg {
  role: 'user' | 'assistant'
  content: string
}

const GREETING: Msg = {
  role: 'assistant',
  content: "Hi, I'm Maxi 👋 — I help teams sort out HR software. How are you managing HR right now — Excel, another tool, or manually?",
}

export default function ChatWidget() {
  const [open, setOpen] = useState(false)
  const [msgs, setMsgs] = useState<Msg[]>([GREETING])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const bodyRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight
  }, [msgs, open])

  const send = async () => {
    const text = input.trim()
    if (!text || busy) return
    const next = [...msgs, { role: 'user' as const, content: text }]
    setMsgs(next)
    setInput('')
    setBusy(true)
    try {
      const { reply } = await api.chat(next.map((m) => ({ role: m.role, content: m.content })))
      setMsgs((m) => [...m, { role: 'assistant', content: reply }])
    } catch {
      setMsgs((m) => [
        ...m,
        {
          role: 'assistant',
          content:
            "I can't reach the model right now (add an LLM key in Settings ⚙). Meanwhile — what's your team size and biggest HR headache?",
        },
      ])
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <button className={'chat-fab' + (open ? ' open' : '')} onClick={() => setOpen((o) => !o)} aria-label="Chat with Maxi">
        {open ? '✕' : '💬'}
      </button>
      {open && (
        <div className="chat-panel">
          <div className="chat-head">
            <span className="chat-avatar">M</span>
            <div>
              <div className="chat-name">Maxi</div>
              <div className="chat-sub">HumanMaximizer assistant</div>
            </div>
          </div>
          <div className="chat-body" ref={bodyRef}>
            {msgs.map((m, i) => (
              <div key={i} className={'chat-msg ' + m.role}>
                {m.content}
              </div>
            ))}
            {busy && <div className="chat-msg assistant typing">…</div>}
          </div>
          <div className="chat-input-row">
            <input
              className="chat-input"
              placeholder="Ask about HR software…"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && send()}
            />
            <button className="chat-send" onClick={send} disabled={busy}>
              ➤
            </button>
          </div>
        </div>
      )}
    </>
  )
}
