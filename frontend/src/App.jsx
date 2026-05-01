import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Chart from './components/Chart.jsx'
import StrategySelector from './components/StrategySelector.jsx'
import Toolbar from './components/Toolbar.jsx'
import SignalPanel from './components/SignalPanel.jsx'
import MarketOutlook from './components/MarketOutlook.jsx'
import StrategyOverview from './components/StrategyOverview.jsx'
import Leaderboard from './components/Leaderboard.jsx'
import AlertsTab from './components/AlertsTab.jsx'
import Resizer from './components/Resizer.jsx'
import { getIndicators, getKlines, getLeaderboard, getOutlook, getStrategies, getStrategySnapshot, runStrategy } from './api.js'
import { useLiveKlines } from './hooks/useLiveKlines.js'
import { usePersistedState } from './hooks/usePersistedState.js'
import { sendTelegram, formatSignalMessage } from './lib/telegram.js'

export default function App() {
  const chartRef = useRef(null)

  // These three persist across page refreshes via localStorage.
  const [symbol, setSymbol] = usePersistedState('btc.symbol', 'BTCUSDT')
  const [interval, setInterval] = usePersistedState('btc.interval', '1h')

  const [strategies, setStrategies] = useState([])
  const [strategyId, setStrategyId] = usePersistedState('btc.strategy', 'mtf_chop_aware')
  const [strategyResult, setStrategyResult] = useState(null)
  const [outlook, setOutlook] = useState(null)
  const [snapshot, setSnapshot] = useState(null)
  const [leaderboard, setLeaderboard] = useState(null)
  const [activeTab, setActiveTab] = usePersistedState('btc.tab', 'live')
  const [sidebarWidth, setSidebarWidth] = usePersistedState('btc.sidebarWidth', 380)

  // Telegram alert settings — persist across refreshes.
  const [tgToken, setTgToken] = usePersistedState('btc.tg.token', '')
  const [tgChat, setTgChat] = usePersistedState('btc.tg.chat', '')
  const [tgSubs, setTgSubs] = usePersistedState('btc.tg.subs', [])

  const [drawMode, setDrawMode] = useState('none')
  const [error, setError] = useState(null)

  // Strategy list — fetched once.
  useEffect(() => {
    getStrategies().then(setStrategies).catch(e => setError(String(e)))
  }, [])

  // Auto-switch chart timeframe when the user picks a strategy that's
  // designed for a specific TF, otherwise the markers won't line up.
  //   - mtf_*       runs on 1h candles
  //   - smc_mtf     runs on 5m candles (entry TF)
  //   - smc_momentum is tuned for 5m / 15m
  useEffect(() => {
    if (strategyId.startsWith('mtf_') && !['1h', '4h', '1d'].includes(interval)) {
      setInterval('1h')
    } else if (strategyId === 'smc_mtf' && interval !== '5m') {
      setInterval('5m')
    } else if (strategyId === 'smc_momentum' && !['5m', '15m'].includes(interval)) {
      setInterval('15m')
    }
    // intentionally not depending on `interval` — only react to strategy switches
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [strategyId])

  // Whenever symbol/interval changes: load history + indicators.
  useEffect(() => {
    let cancelled = false
    // Clear stale visuals immediately — markers/levels from the previous
    // (symbol, interval) would otherwise sit on the chart until the new
    // strategy run completes a moment later.
    chartRef.current?.setMarkers([])
    chartRef.current?.setLevels({})
    setStrategyResult(null)
    ;(async () => {
      try {
        setError(null)
        const [candles, ind] = await Promise.all([
          getKlines({ symbol, interval, limit: 500 }),
          getIndicators({ symbol, interval, limit: 500 }),
        ])
        if (cancelled) return
        chartRef.current?.setCandles(candles)
        chartRef.current?.setVolume(candles)
        chartRef.current?.setEmas(ind)
      } catch (e) {
        if (!cancelled) setError(String(e))
      }
    })()
    return () => { cancelled = true }
  }, [symbol, interval])

  // Strategy run — refetch on strategy/symbol/interval change AND every 30s.
  useEffect(() => {
    if (!strategyId) return
    let cancelled = false
    const fetchOnce = async () => {
      try {
        const r = await runStrategy({ id: strategyId, symbol, interval, limit: 500 })
        if (cancelled) return
        setStrategyResult(r)
        chartRef.current?.setMarkers(r.signals)
        chartRef.current?.setLevels({
          entry: r.latest?.entry,
          stop: r.latest?.stop_loss,
          target: r.latest?.target,
        })
      } catch (e) {
        if (!cancelled) setError(String(e))
      }
    }
    fetchOnce()
    const id = window.setInterval(fetchOnce, 30000)
    return () => { cancelled = true; window.clearInterval(id) }
  }, [strategyId, symbol, interval])

  // Outlook — fetch on symbol change and refresh every 5 min.
  useEffect(() => {
    let cancelled = false
    setOutlook(null)
    const fetchOnce = async () => {
      try {
        const o = await getOutlook(symbol)
        if (!cancelled) setOutlook(o)
      } catch (e) {
        if (!cancelled) setError(String(e))
      }
    }
    fetchOnce()
    const id = window.setInterval(fetchOnce, 5 * 60 * 1000)
    return () => { cancelled = true; window.clearInterval(id) }
  }, [symbol])

  // Strategy snapshot — all strategies' live state at the user's current
  // interval, refreshed every 60s. Re-fetches when interval changes so the
  // notification system stays aligned with what the user actually sees.
  useEffect(() => {
    let cancelled = false
    setSnapshot(null)
    const fetchOnce = async () => {
      try {
        const s = await getStrategySnapshot(symbol, interval)
        if (!cancelled) setSnapshot(s)
      } catch (e) {
        if (!cancelled) setError(String(e))
      }
    }
    fetchOnce()
    const id = window.setInterval(fetchOnce, 60 * 1000)
    return () => { cancelled = true; window.clearInterval(id) }
  }, [symbol, interval])

  // Telegram alerts — when a subscribed strategy fires a NEW signal, send to bot.
  // Tracks per-strategy "last seen signal time" in localStorage so a stale tab
  // doesn't keep re-notifying the same trade. Only marks 'seen' on a successful
  // Telegram response — failed sends will retry on the next poll.
  useEffect(() => {
    if (!snapshot || !tgToken || !tgChat || tgSubs.length === 0) return
    for (const row of snapshot.strategies) {
      if (!tgSubs.includes(row.id)) continue
      if (row.signal === 'HOLD' || !row.last_signal_time) continue
      const key = `btc.tg.lastSignal.${row.id}`
      const lastSeen = parseInt(localStorage.getItem(key) || '0', 10)
      if (row.last_signal_time > lastSeen) {
        const msg = formatSignalMessage(row, snapshot.symbol)
        console.info('[tg-alerts] sending', row.id, '@', row.last_signal_time, 'lastSeen', lastSeen)
        sendTelegram(tgToken, tgChat, msg).then(res => {
          if (res.ok) {
            localStorage.setItem(key, String(row.last_signal_time))
            console.info('[tg-alerts] sent', row.id)
          } else {
            console.error('[tg-alerts] FAILED', row.id, '-', res.description)
          }
        })
      }
    }
  }, [snapshot, tgToken, tgChat, tgSubs])

  // Leaderboard — heavier (~5s), so only fetch when the Best tab is open.
  // Refresh every 5 minutes while the tab stays open.
  useEffect(() => {
    if (activeTab !== 'best') return
    let cancelled = false
    const fetchOnce = async () => {
      try {
        const lb = await getLeaderboard(symbol)
        if (!cancelled) setLeaderboard(lb)
      } catch (e) {
        if (!cancelled) setError(String(e))
      }
    }
    fetchOnce()
    const id = window.setInterval(fetchOnce, 5 * 60 * 1000)
    return () => { cancelled = true; window.clearInterval(id) }
  }, [symbol, activeTab])

  // Live updates from the backend WS bridge.
  const live = useLiveKlines({ symbol, interval })
  useEffect(() => {
    if (live) chartRef.current?.updateCandle(live)
  }, [live])

  // Drawing mode -> chart
  useEffect(() => {
    chartRef.current?.setDrawingMode(drawMode)
  }, [drawMode])

  const onClearDrawings = useCallback(() => {
    chartRef.current?.clearDrawings()
  }, [])

  // When user clicks a strategy in the overview, auto-switch to the Live tab
  // so they immediately see its trade card / performance.
  const handleStrategySelect = useCallback((id) => {
    setStrategyId(id)
    setActiveTab('live')
  }, [setStrategyId, setActiveTab])

  const livePrice = useMemo(() => live?.close ?? null, [live])

  const tabs = [
    { id: 'live',   icon: '📊', label: 'Live' },
    { id: 'plan',   icon: '📋', label: 'Plan' },
    { id: 'all',    icon: '🎯', label: 'All' },
    { id: 'best',   icon: '🏆', label: 'Best' },
    { id: 'alerts', icon: '🔔', label: 'Alerts' },
  ]

  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <span className="logo">₿</span>
          <div className="brand-text">
            <div className="brand-title">Crypto Trading Dashboard</div>
            <div className="brand-sub">Real-time signals + multi-timeframe analysis</div>
          </div>
        </div>
        <div className="live-price-wrap">
          <div className="live-price-label">Live Price</div>
          <div className="live-price">
            {livePrice ? `$${Number(livePrice).toLocaleString(undefined, { maximumFractionDigits: 2 })}` : '—'}
          </div>
        </div>
      </header>

      <Toolbar
        symbol={symbol} onSymbolChange={setSymbol}
        interval={interval} onIntervalChange={setInterval}
        drawMode={drawMode} onDrawModeChange={setDrawMode}
        onClearDrawings={onClearDrawings}
      />

      <StrategySelector
        strategies={strategies}
        selected={strategyId}
        onSelect={setStrategyId}
      />

      {error && <div className="error">{error}</div>}

      <main
        className="main"
        style={{ gridTemplateColumns: `minmax(0, 1fr) 6px ${sidebarWidth || 380}px` }}
      >
        <section className="chart-pane">
          <Chart ref={chartRef} />
        </section>
        <Resizer current={sidebarWidth} onResize={setSidebarWidth} />
        <aside className="side-pane">
          <div className="tabs">
            {tabs.map(t => (
              <button
                key={t.id}
                className={`tab ${activeTab === t.id ? 'active' : ''}`}
                onClick={() => setActiveTab(t.id)}
              >
                <span className="tab-icon">{t.icon}</span>
                <span className="tab-label">{t.label}</span>
              </button>
            ))}
          </div>

          <div className="tab-content">
            {activeTab === 'live' && (
              <SignalPanel
                result={strategyResult}
                livePrice={livePrice}
                strategies={strategies}
              />
            )}
            {activeTab === 'plan' && (
              <MarketOutlook data={outlook} livePrice={livePrice} />
            )}
            {activeTab === 'all' && (
              <StrategyOverview
                data={snapshot}
                selectedId={strategyId}
                onSelect={handleStrategySelect}
              />
            )}
            {activeTab === 'best' && (
              <Leaderboard data={leaderboard} />
            )}
            {activeTab === 'alerts' && (
              <AlertsTab
                strategies={strategies}
                token={tgToken} setToken={setTgToken}
                chatId={tgChat} setChatId={setTgChat}
                subs={tgSubs} setSubs={setTgSubs}
                snapshot={snapshot}
              />
            )}
          </div>
        </aside>
      </main>
    </div>
  )
}
