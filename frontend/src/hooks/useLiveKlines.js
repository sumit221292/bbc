import { useEffect, useRef, useState } from 'react'

/** Subscribe to the backend WS feed; returns the last received candle. */
export function useLiveKlines({ symbol = 'BTCUSDT', interval = '1m' } = {}) {
  const [last, setLast] = useState(null)
  const wsRef = useRef(null)

  useEffect(() => {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const url = `${proto}://${window.location.host}/ws/klines?symbol=${symbol}&interval=${interval}`
    let alive = true
    let ws

    const connect = () => {
      ws = new WebSocket(url)
      wsRef.current = ws
      ws.onmessage = (e) => {
        try { setLast(JSON.parse(e.data)) } catch {}
      }
      ws.onclose = () => {
        if (alive) setTimeout(connect, 1500) // simple reconnect
      }
      ws.onerror = () => ws.close()
    }
    connect()

    return () => {
      alive = false
      try { ws && ws.close() } catch {}
    }
  }, [symbol, interval])

  return last
}
