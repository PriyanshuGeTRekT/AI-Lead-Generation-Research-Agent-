import { useEffect, useRef, useState } from 'react'

/** Smoothly animates a number from its previous value to the new one. */
export default function CountUp({ value, duration = 600 }: { value: number; duration?: number }) {
  const [display, setDisplay] = useState(value)
  const fromRef = useRef(value)
  const rafRef = useRef<number>()

  useEffect(() => {
    const from = fromRef.current
    const to = value
    fromRef.current = to
    if (from === to) {
      setDisplay(to)
      return
    }
    const start = performance.now()
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration)
      const eased = 1 - Math.pow(1 - t, 3) // easeOutCubic
      setDisplay(Math.round(from + (to - from) * eased))
      if (t < 1) rafRef.current = requestAnimationFrame(tick)
    }
    rafRef.current = requestAnimationFrame(tick)
    // Guarantee the final value even if rAF is throttled (backgrounded tab).
    const guard = setTimeout(() => setDisplay(to), duration + 120)
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current)
      clearTimeout(guard)
    }
  }, [value, duration])

  return <>{display}</>
}
