import { memo, useEffect, useMemo, useState } from 'react'
import { getLivePrices, getTrades, getTradeStatsByPair } from '../api.js'
import { fmtPrice as fmt, fmtPct as pct, timeAgo, fmtIST } from '../lib/format.js'

// Cross-coin / cross-strategy trade browser. Two dropdowns at the top let
// the user pivot freely: "Strategy=Confluence, Coin=All" shows every
// Confluence trade across coins; "Strategy=All, Coin=BTCUSDT" shows every
// strategy that ever traded BTC. Hits /api/trades with optional filters.
function TradesTab({ strategies = [], onJumpToLive }) {
  const [strategyFilter, setStrategyFilter] = useState('')   // '' = All
  const [coinFilter, setCoinFilter] = useState('')           // '' = All
  // Min win-rate cutoff applied per (strategy, coin) combo. 0 = show all.
  // New combos (no closed trades yet) always pass through so insufficient
  // data isn't punished -- only proven losers get filtered out.
  const [minWR, setMinWR] = useState(0)
  const [data, setData] = useState({ trades: [], summary: null })
  const [pairs, setPairs] = useState([])
  const [loading, setLoading] = useState(true)
  // Live prices keyed by symbol. Powers the mark-to-market PnL badge on
  // every OPEN row. Refreshed every 15s in lockstep with the backend's
  // 10s cache TTL on /api/market/prices.
  const [livePrices, setLivePrices] = useState({})

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

  // Symbols with at least one currently OPEN trade in the visible list.
  // These are the only coins we need live prices for.
  const openSymbols = useMemo(() => {
    const set = new Set()
    for (const t of data.trades || []) {
      if (t.status === 'OPEN' && t.symbol) set.add(t.symbol)
    }
    return Array.from(set)
  }, [data.trades])

  // Poll live prices every 15s for the OPEN-trade coins. Re-fires
  // whenever the visible OPEN set changes (e.g. user picks a different
  // filter, or a trade resolves and disappears from OPEN).
  useEffect(() => {
    if (openSymbols.length === 0) {
      setLivePrices({})
      return
    }
    let cancelled = false
    const fetchOnce = async () => {
      try {
        const d = await getLivePrices(openSymbols)
        if (!cancelled) setLivePrices(d.prices || {})
      } catch { /* offline ok */ }
    }
    fetchOnce()
    const id = setInterval(fetchOnce, 15000)
    return () => { cancelled = true; clearInterval(id) }
  }, [openSymbols.join('|')])  // re-run on actual symbol-set change

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

  // Fast lookup keyed by "strategyId::symbol" so the WR filter can decide
  // whether each trade's combo clears the threshold in O(1).
  const pairsByKey = useMemo(() => {
    const m = {}
    for (const p of pairs) m[`${p.strategy_id}::${p.symbol}`] = p
    return m
  }, [pairs])

  const rawTrades = data.trades || []

  // Apply the WR filter on the frontend so the summary card and the
  // visible row count stay in sync. Combos with 0 closed trades pass
  // through -- we don't want a single 0/1 to permanently hide a brand-new
  // pair before it has had time to prove itself.
  const trades = useMemo(() => {
    if (!minWR) return rawTrades
    return rawTrades.filter(t => {
      const p = pairsByKey[`${t.strategy_id}::${t.symbol}`]
      if (!p || p.closed === 0) return true
      return p.win_rate >= minWR
    })
  }, [rawTrades, minWR, pairsByKey])

  // Hidden combo count -- shown as a small hint so the user knows the
  // filter is doing something even when most trades pass through.
  const hiddenCount = rawTrades.length - trades.length

  // Re-roll the summary from the FILTERED list so the totals match what
  // the user actually sees. Backend's summary was computed pre-filter.
  const summary = useMemo(() => {
    if (!minWR) return data.summary
    const wins = trades.filter(t => t.status === 'WIN').length
    const losses = trades.filter(t => t.status === 'LOSS').length
    const open = trades.filter(t => t.status === 'OPEN').length
    const closed = wins + losses
    const total_pnl_pct = trades.reduce(
      (acc, t) => acc + (t.status !== 'OPEN' ? (t.pnl_pct || 0) : 0), 0,
    )
    return {
      total: trades.length, wins, losses, open, closed,
      win_rate: closed > 0 ? (wins / closed) * 100 : 0,
      total_pnl_pct,
      avg_pnl_pct: closed > 0 ? total_pnl_pct / closed : 0,
    }
  }, [data.summary, trades, minWR])

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
        <label>
          <span className="muted small" title="Hides trades from (strategy, coin) combos whose win rate is below this. New combos (no closed trades) always show.">Min WR</span>
          <select
            value={minWR}
            onChange={e => setMinWR(Number(e.target.value))}
          >
            <option value={0}>Any</option>
            <option value={40}>≥ 40%</option>
            <option value={50}>≥ 50%</option>
            <option value={60}>≥ 60%</option>
          </select>
        </label>
        {(strategyFilter || coinFilter || minWR > 0) && (
          <button
            className="trades-clear"
            onClick={() => { setStrategyFilter(''); setCoinFilter(''); setMinWR(0) }}
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

      {minWR > 0 && hiddenCount > 0 && (
        <div className="trades-hint muted small">
          🛡 Hiding {hiddenCount} trade{hiddenCount === 1 ? '' : 's'} from
          combos with WR &lt; {minWR}%
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
          // Click jumps the user to the Live tab with the chart re-tuned
          // to the same (strategy, coin, interval) as this trade.
          const jump = () => onJumpToLive && onJumpToLive(t.strategy_id, t.symbol, t.interval)
          return (
            <div key={`${t.strategy_id}-${t.interval}-${t.symbol}-${t.signal_time}`}
                 className={`trade-row ${tone} clickable`}
                 role="button"
                 tabIndex={0}
                 onClick={jump}
                 onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') jump() }}
                 title={`Open ${stratLabel} on ${t.symbol} (${t.interval}) in Live tab`}>
              <div className="tr-head">
                <span className={`tr-side ${sideClass}`}>{t.type}</span>
                <span className="tr-coin">{coinLabel}</span>
                <span className="tr-strat muted">{stratLabel}</span>
                <span className={`tr-status ${tone}`}>
                  {isOpen ? 'CHAL RAHA' : status}
                </span>
              </div>
              {/* Live mark-to-market for OPEN rows: snapshot price from
                  /api/market/prices, compute against entry per the trade
                  direction. Worker may not have resolved the trade yet
                  even if price crossed SL/TP -- the OPEN status is the
                  source of truth, the live PnL is just a preview. */}
              {(() => {
                const livePx = isOpen ? livePrices[t.symbol] : null
                const livePnl = (livePx != null && t.entry)
                  ? (t.type === 'BUY'
                      ? (livePx - t.entry) / t.entry * 100
                      : (t.entry - livePx) / t.entry * 100)
                  : null
                return (
                  <div className="tr-meta">
                    <span>Entry <b>${fmt(t.entry)}</b></span>
                    {!isOpen && t.exit_price && (
                      <span>Exit <b>${fmt(t.exit_price)}</b></span>
                    )}
                    {isOpen && livePx != null && (
                      <span>Live <b>${fmt(livePx)}</b></span>
                    )}
                    {!isOpen && pnl != null && (
                      <span className={pnl >= 0 ? 'pos' : 'neg'}>
                        {pnl >= 0 ? '+' : ''}{pnl.toFixed(2)}%
                      </span>
                    )}
                    {isOpen && livePnl != null && (
                      <span className={`tr-live-pnl ${livePnl >= 0 ? 'pos' : 'neg'}`}
                            title="Mark-to-market: live price vs entry. Refreshes every 15s.">
                        {livePnl >= 0 ? '+' : ''}{livePnl.toFixed(2)}%
                        <span className="tr-live-tag">live</span>
                      </span>
                    )}
                    <span className="muted" title={fmtIST(when)}>{timeAgo(when)}</span>
                  </div>
                )
              })()}
              {/* Original plan -- SL + TP. Shown for every status so the
                  user can compare planned vs actual exit at a glance. The
                  hit price (= SL for a LOSS, = TP for a WIN) is the same
                  as Exit above; the two together make it obvious what
                  happened without the user needing to know the convention. */}
              {(t.stop_loss != null || t.target != null) && (
                <div className="tr-plan muted">
                  Plan:
                  {t.stop_loss != null && (
                    <>{' '}<span className="tr-sl">SL <b>${fmt(t.stop_loss)}</b></span></>
                  )}
                  {t.target != null && (
                    <>{' · '}<span className="tr-tp">TP <b>${fmt(t.target)}</b></span></>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default memo(TradesTab)
