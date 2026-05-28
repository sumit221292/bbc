import { memo, useEffect, useMemo, useState } from 'react'
import { getTradeStatsByPair } from '../api.js'

// 2D heatmap of every (strategy, coin) combo's live PnL. Rows are
// strategies, columns are coins, cells are color-coded by cumulative
// PnL %. Click any cell to jump to the Live tab with that (strategy,
// coin) pre-selected so the chart re-runs against the exact setup.
//
// Pulls from /api/trades/stats-by-pair, which only includes combos
// that have at least one trade row -- so brand-new watchlist coins
// won't pollute the matrix until they actually fire.
function MatrixTab({ strategies = [], onJumpToLive }) {
  const [pairs, setPairs] = useState([])
  const [loading, setLoading] = useState(true)
  // Combos with very few trades aren't statistically meaningful. Default
  // 3 hides the noisiest entries; user can drop to 0 to see everything.
  const [minTrades, setMinTrades] = useState(3)
  // 'all' / 'profitable' / 'loss' -- narrow the cells to a focus area.
  const [filter, setFilter] = useState('all')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    const fetchOnce = async () => {
      try {
        const d = await getTradeStatsByPair()
        if (!cancelled) {
          setPairs(d.pairs || [])
          setLoading(false)
        }
      } catch {
        if (!cancelled) setLoading(false)
      }
    }
    fetchOnce()
    const id = setInterval(fetchOnce, 30000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  // Map strategy_id -> friendly name for the row headers.
  const nameById = useMemo(() => {
    const m = {}
    for (const s of strategies) m[s.id] = s.name
    return m
  }, [strategies])

  // Build distinct strategy / coin axes from the data, filtered by
  // minTrades + status filter. We sort strategies by their cumulative
  // PnL across coins (best at top) and coins by their cumulative PnL
  // across strategies (best at left) so the most interesting region
  // sits in the top-left corner of the heatmap.
  const { strategyIds, symbols, byKey, totalCombos, hiddenCount } = useMemo(() => {
    const filtered = pairs.filter(p => {
      if (p.closed < minTrades) return false
      if (filter === 'profitable' && p.total_pnl_pct <= 0) return false
      if (filter === 'loss' && p.total_pnl_pct >= 0) return false
      return true
    })
    const byKey = {}
    const stratPnl = {}
    const coinPnl = {}
    for (const p of filtered) {
      byKey[`${p.strategy_id}::${p.symbol}`] = p
      stratPnl[p.strategy_id] = (stratPnl[p.strategy_id] || 0) + p.total_pnl_pct
      coinPnl[p.symbol] = (coinPnl[p.symbol] || 0) + p.total_pnl_pct
    }
    const strategyIds = Object.keys(stratPnl).sort(
      (a, b) => stratPnl[b] - stratPnl[a],
    )
    const symbols = Object.keys(coinPnl).sort(
      (a, b) => coinPnl[b] - coinPnl[a],
    )
    return {
      strategyIds, symbols, byKey,
      totalCombos: pairs.length,
      hiddenCount: pairs.length - filtered.length,
    }
  }, [pairs, minTrades, filter])

  // PnL -> background colour (HSL gradient: red for loss, green for win).
  // Magnitude is capped at ±30% so a single outlier doesn't wash out the
  // colour scale for everything else.
  const cellColor = (pnl) => {
    if (pnl === null || pnl === undefined) return 'transparent'
    const clamped = Math.max(-30, Math.min(30, pnl))
    const hue = clamped > 0 ? 160 : 0   // green-ish vs red
    const sat = 60
    const light = 50 - Math.min(20, Math.abs(clamped))  // darker for stronger
    return `hsl(${hue}, ${sat}%, ${light}%)`
  }

  // Top 5 winners / losers (sorted by PnL) -- shown as a leaderboard
  // beneath the matrix so the user can spot extremes at a glance.
  const ranked = useMemo(() => {
    const sorted = [...pairs]
      .filter(p => p.closed >= minTrades)
      .sort((a, b) => b.total_pnl_pct - a.total_pnl_pct)
    return {
      best: sorted.slice(0, 5),
      worst: sorted.slice(-5).reverse(),
    }
  }, [pairs, minTrades])

  if (loading) {
    return (
      <div className="matrix-tab">
        <div className="panel-section-title">📐 Strategy × Coin Matrix</div>
        <div className="muted small" style={{ padding: 12 }}>Loading…</div>
      </div>
    )
  }

  if (totalCombos === 0) {
    return (
      <div className="matrix-tab">
        <div className="panel-section-title">📐 Strategy × Coin Matrix</div>
        <div className="muted small" style={{ padding: 12 }}>
          No trades in the DB yet — fire some via the worker and the matrix
          will populate.
        </div>
      </div>
    )
  }

  return (
    <div className="matrix-tab">
      <div className="panel-section-title">📐 Strategy × Coin Matrix</div>

      <div className="matrix-filters">
        <label>
          <span className="muted small">Min trades</span>
          <select value={minTrades} onChange={e => setMinTrades(Number(e.target.value))}>
            <option value={0}>0 (show all)</option>
            <option value={3}>≥ 3</option>
            <option value={5}>≥ 5</option>
            <option value={10}>≥ 10</option>
          </select>
        </label>
        <label>
          <span className="muted small">Filter</span>
          <select value={filter} onChange={e => setFilter(e.target.value)}>
            <option value="all">All combos</option>
            <option value="profitable">Profitable only</option>
            <option value="loss">Loss only</option>
          </select>
        </label>
        <div className="matrix-stats muted small">
          {strategyIds.length} strategies × {symbols.length} coins
          {hiddenCount > 0 && ` · ${hiddenCount} hidden by filter`}
        </div>
      </div>

      <div className="matrix-scroll">
        <table className="matrix-table">
          <thead>
            <tr>
              <th className="m-corner">Strategy ↓ / Coin →</th>
              {symbols.map(sym => {
                const label = sym.endsWith('USDT') ? sym.slice(0, -4) : sym
                return <th key={sym} className="m-col">{label}</th>
              })}
            </tr>
          </thead>
          <tbody>
            {strategyIds.map(sid => (
              <tr key={sid}>
                <td className="m-row" title={nameById[sid] || sid}>
                  {(nameById[sid] || sid).replace(/^[^\w]+\s*/, '').slice(0, 24)}
                </td>
                {symbols.map(sym => {
                  const p = byKey[`${sid}::${sym}`]
                  if (!p) {
                    return <td key={sym} className="m-cell empty">—</td>
                  }
                  const pnl = p.total_pnl_pct
                  const tip = `${nameById[sid] || sid} on ${sym}\n` +
                              `${p.closed} closed (${p.wins}W/${p.losses}L), ` +
                              `${p.win_rate.toFixed(1)}% WR\n` +
                              `Cumulative PnL: ${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}%\n` +
                              `Click to open in Live tab`
                  return (
                    <td
                      key={sym}
                      className="m-cell"
                      style={{ background: cellColor(pnl) }}
                      onClick={() => onJumpToLive && onJumpToLive(sid, sym, '1h')}
                      title={tip}
                    >
                      {pnl >= 0 ? '+' : ''}{pnl.toFixed(1)}%
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="matrix-leaderboards">
        <div className="m-lb">
          <div className="m-lb-title">🏆 Top 5 winners</div>
          {ranked.best.length === 0
            ? <div className="muted small">No data yet</div>
            : ranked.best.map(p => (
                <div
                  key={`b-${p.strategy_id}-${p.symbol}`}
                  className="m-lb-row pos"
                  onClick={() => onJumpToLive && onJumpToLive(p.strategy_id, p.symbol, '1h')}
                  title="Click to open in Live"
                >
                  <span className="m-lb-name">
                    {(nameById[p.strategy_id] || p.strategy_id).replace(/^[^\w]+\s*/, '').slice(0, 20)}
                    {' · '}{p.symbol.replace(/USDT$/, '')}
                  </span>
                  <span className="m-lb-meta muted small">
                    {p.closed}t · {p.win_rate.toFixed(0)}%
                  </span>
                  <span className="m-lb-pnl pos">
                    +{p.total_pnl_pct.toFixed(2)}%
                  </span>
                </div>
              ))}
        </div>
        <div className="m-lb">
          <div className="m-lb-title">💀 Worst 5 (silence these via chip)</div>
          {ranked.worst.length === 0
            ? <div className="muted small">No data yet</div>
            : ranked.worst.map(p => (
                <div
                  key={`w-${p.strategy_id}-${p.symbol}`}
                  className="m-lb-row neg"
                  onClick={() => onJumpToLive && onJumpToLive(p.strategy_id, p.symbol, '1h')}
                  title="Click to open in Live"
                >
                  <span className="m-lb-name">
                    {(nameById[p.strategy_id] || p.strategy_id).replace(/^[^\w]+\s*/, '').slice(0, 20)}
                    {' · '}{p.symbol.replace(/USDT$/, '')}
                  </span>
                  <span className="m-lb-meta muted small">
                    {p.closed}t · {p.win_rate.toFixed(0)}%
                  </span>
                  <span className="m-lb-pnl neg">
                    {p.total_pnl_pct.toFixed(2)}%
                  </span>
                </div>
              ))}
        </div>
      </div>
    </div>
  )
}

export default memo(MatrixTab)
