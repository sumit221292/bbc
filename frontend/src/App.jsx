import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Chart from './components/Chart.jsx'
import TradingViewChart from './components/TradingViewChart.jsx'
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
  // 'native' = our Lightweight Charts with signal markers + SL/TP lines.
  // 'tradingview' = official Advanced Chart widget (no signal overlay).
  const [chartMode, setChartMode] = usePersistedState('btc.chartMode', 'native')
  // Collapse the chart pane entirely when the user wants to focus on the
  // signal sidebar (Live / All / Best / Alerts). Persisted so refresh keeps
  // the layout intent.
  const [chartVisible, setChartVisible] = usePersistedState('btc.chartVisible', true)

  // Telegram alerts now run on the backend (always-on); the AlertsTab
  // talks directly to /api/alerts/config so we don't need state here.

  const [drawMode, setDrawMode] = useState('none')
  const [error, setError] = useState(null)

  // Strategy list — fetched once.
  useEffect(() => {
    getStrategies().then(setStrategies).catch(e => setError(String(e)))
  }, [])

  // The app is restricted to 1h / 4h / 1d. Sanitise persisted localStorage
  // state on mount so users who saved an old 5m / 15m interval or a removed
  // strategy (smc_mtf, smc_momentum) get a working default instead of a
  // 404 from the API.
  useEffect(() => {
    const ALLOWED_INTERVALS = ['1h', '4h', '1d']
    const REMOVED_STRATEGIES = ['smc_mtf', 'smc_momentum']
    if (!ALLOWED_INTERVALS.includes(interval)) setInterval('1h')
    if (REMOVED_STRATEGIES.includes(strategyId)) setStrategyId('mtf_chop_aware')
    // run once on first mount only
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Auto-switch chart timeframe when the user picks an MTF strategy that is
  // tuned for 1h triggers, so the markers line up with the worker storage.
  useEffect(() => {
    if (strategyId.startsWith('mtf_') && !['1h', '4h', '1d'].includes(interval)) {
      setInterval('1h')
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

  // Telegram alerts: handled by the backend worker now (see app/alerts.py).
  // The frontend's only job is the Alerts tab UI which POSTs config to
  // /api/alerts/config.

  // Leaderboard — heavier (~5s), so only fetch when the Best tab is open.
  // Refresh every 5 minutes while the tab stays open.
  useEffect(() => {
    if (activeTab !== 'best') return
    let cancelled = false
    // Drop stale leaderboard on coin switch so the Best tab does not flash
    // the previous coin's rows while the new ones load.
    setLeaderboard(null)
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
        chartMode={chartMode} onChartModeChange={setChartMode}
        chartVisible={chartVisible} onChartVisibleChange={setChartVisible}
      />

      <StrategySelector
        strategies={strategies}
        selected={strategyId}
        onSelect={setStrategyId}
      />

      {error && <div className="error">{error}</div>}

      <main
        className={`main ${chartVisible ? '' : 'chart-collapsed'}`}
        style={{
          gridTemplateColumns: chartVisible
            ? `minmax(0, 1fr) 6px ${sidebarWidth || 380}px`
            : 'minmax(0, 1fr)',
        }}
      >
        {chartVisible && (
          <>
            <section className="chart-pane">
              {chartMode === 'tradingview'
                ? <TradingViewChart symbol={symbol} interval={interval} />
                : <Chart ref={chartRef} />}
            </section>
            <Resizer current={sidebarWidth} onResize={setSidebarWidth} />
          </>
        )}
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
                interval={interval}
                symbol={symbol}
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
                snapshot={snapshot}
              />
            )}
          </div>
        </aside>
      </main>
    </div>
  )
}
