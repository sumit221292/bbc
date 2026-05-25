import { memo, useEffect, useMemo, useState } from 'react'
import { getTrades, getTradeStatsByPair } from '../api.js'
import { fmtPrice as fmt, fmtPct as pct, timeAgo, fmtIST } from '../lib/format.js'

// Cross-coin / cross-strategy trade browser. Two dropdowns at the top let
// the user pivot freely: "Strategy=Confluence, Coin=All" shows every
// Confluence trade across coins; "Strategy=All, Coin=BTCUSDT" shows every
// strategy that ever traded BTC. Hits /api/trades with optional filters.
function TradesTab({ strategies = [] }) {
  const [strategyFilter, setStrategyFilter] = useState('')   // '' = All
  const [coinFilter, setCoinFilter] = useState('')           // '' = All
  const [data, setData] = useState({ trades: [], summary: null })
  const [pairs, setPairs] = useState([])
  const [loading, setLoading] = useState(true)

  // Pull stats-by-pair once to enumerate which coins actually appear in
  // the trade history. Better than listing the user's watchlist because
  // brand-new coins won't have any data to show yet.
  useEffect(() => {
    getTradeStatsByPair()
      .then(d => setPairs(d.pairs || []))
      .catch(() => {})
  }, [])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    const fetchOnce = async () => {
      try {
        const d = await getTrades({
          strategy: strategyFilter || undefined,
          symbol: coinFilter || undefined,
          limit: 500,
        })
        if (!cancelled) {
          setData(d)
          setLoading(false)
        }
      } catch {
        if (!cancelled) setLoading(false)
      }
    }
    fetchOnce()
    const id = setInterval(fetchOnce, 30000)
    return () => { cancelled = true; clearInterval(id) }
  }, [strategyFilter, coinFilter])

  // Distinct coins from the historical stats — sorted alphabetically.
  const allCoins = useMemo(() => {
    const set = new Set(pairs.map(p => p.symbol))
    return Array.from(set).sort()
  }, [pairs])

  // Strategy id -> friendly name map for the row labels.
  const nameById = useMemo(() => {
    const m = {}
    for (const s of strategies) m[s.id] = s.name
    return m
  }, [strategies])

  const summary = data.summary
  const trades = data.trades || []

  return (
    <div className="trades-tab">
      <div className="panel-section-title">📈 All Trades — Cross-Coin View</div>

      <div className="trades-filters">
        <label>
          <span className="muted small">Strategy</span>
          <select
            value={strategyFilter}
            onChange={e => setStrategyFilter(e.target.value)}
          >
            <option value="">All strategies</option>
            {strategies.map(s => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
        </label>
        <label>
          <span className="muted small">Coin</span>
          <select
            value={coinFilter}
            onChange={e => setCoinFilter(e.target.value)}
          >
            <option value="">All coins</option>
            {allCoins.map(sym => (
              <option key={sym} value={sym}>{sym}</option>
            ))}
          </select>
        </label>
        {(strategyFilter || coinFilter) && (
          <button
            className="trades-clear"
            onClick={() => { setStrategyFilter(''); setCoinFilter('') }}
            title="Reset filters"
          >× Clear</button>
        )}
      </div>

      {summary && (
        <div className="trades-summary">
          <div className="ts-stat">
            <div className="ts-label">Trades</div>
            <div className="ts-value">{summary.total}</div>
          </div>
          <div className="ts-stat">
            <div className="ts-label">W / L / Open</div>
            <div className="ts-value">
              <span className="pos">{summary.wins}</span>
              <span className="muted"> / </span>
              <span className="neg">{summary.losses}</span>
              <span className="muted"> / </span>
              <span>{summary.open}</span>
            </div>
          </div>
          <div className="ts-stat">
            <div className="ts-label">Win Rate</div>
            <div className="ts-value">
              {summary.closed > 0 ? `${summary.win_rate.toFixed(1)}%` : '—'}
            </div>
          </div>
          <div className="ts-stat">
            <div className="ts-label">Cumulative PnL</div>
            <div className={`ts-value ${summary.total_pnl_pct > 0 ? 'pos' : summary.total_pnl_pct < 0 ? 'neg' : ''}`}>
              {summary.closed > 0
                ? `${summary.total_pnl_pct >= 0 ? '+' : ''}${summary.total_pnl_pct.toFixed(2)}%`
                : '—'}
            </div>
          </div>
        </div>
      )}

      {loading && trades.length === 0 && (
        <div className="muted small" style={{ padding: 12 }}>Loading…</div>
      )}

      {!loading && trades.length === 0 && (
        <div className="muted small" style={{ padding: 12 }}>
          No trades match this filter yet.
        </div>
      )}

      <div className="trades-list">
        {trades.map(t => {
          const status = t.status
          const isOpen = status === 'OPEN'
          const pnl = t.pnl_pct
          const tone = isOpen ? 'open' : status === 'WIN' ? 'win' : 'loss'
          const sideClass = t.type === 'BUY' ? 'buy' : 'sell'
          const coinLabel = t.symbol.endsWith('USDT')
            ? t.symbol.slice(0, -4) + '/USDT'
            : t.symbol
          const stratLabel = nameById[t.strategy_id] || t.strategy_id
          const when = t.created_at || t.signal_time
          return (
            <div key={`${t.strategy_id}-${t.interval}-${t.symbol}-${t.signal_time}`}
                 className={`trade-row ${tone}`}>
              <div className="tr-head">
                <span className={`tr-side ${sideClass}`}>{t.type}</span>
                <span className="tr-coin">{coinLabel}</span>
                <span className="tr-strat muted">{stratLabel}</span>
                <span className={`tr-status ${tone}`}>
                  {isOpen ? 'CHAL RAHA' : status}
                </span>
              </div>
              <div className="tr-meta">
                <span>Entry <b>${fmt(t.entry)}</b></span>
                {!isOpen && t.exit_price && (
                  <span>Exit <b>${fmt(t.exit_price)}</b></span>
                )}
                {!isOpen && pnl !== null && pnl !== undefined && (
                  <span className={pnl >= 0 ? 'pos' : 'neg'}>
                    {pnl >= 0 ? '+' : ''}{pnl.toFixed(2)}%
                  </span>
                )}
                <span className="muted" title={fmtIST(when)}>{timeAgo(when)}</span>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default memo(TradesTab)
