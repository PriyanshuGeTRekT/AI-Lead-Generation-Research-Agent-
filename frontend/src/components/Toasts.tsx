import { useApp } from '../store/AppContext'

export default function Toasts() {
  const { toasts, dismissToast } = useApp()
  return (
    <div className="toast-stack">
      {toasts.map((t) => (
        <div key={t.id} className={'toast ' + t.type} onClick={() => dismissToast(t.id)}>
          {t.msg}
        </div>
      ))}
    </div>
  )
}
