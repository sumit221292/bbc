import { memo, useMemo, useState } from 'react'

function fmt(n, d = 2) {
  if (n == null) return '—'
  return Number(n).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d })
}

function pct(n) {
  if (n == null) return '—'
  const sign = n >= 0 ? '+' : ''
  return `${sign}${n.toFixed(2)}%`
}

function signalCell(row) {
  if (row.signal === 'HOLD') {
    return <span className="ov-signal hold">WAIT</span>
  }
  const cls = row.signal === 'BUY' ? 'buy' : 'sell'
  return (
    <span className={`ov-signal ${cls}`}>
      {row.signal}
      {row.status && <span className="ov-status">· {row.status === 'OPEN' ? 'CHAL RAHA' : row.status === 'WIN' ? 'WIN' : 'STOP'}</span>}
    </span>
  )
}

function StrategyOverview({ data, selectedId, onSelect }) {
  const [profitableOnly, setProfitableOnly] = useState(false)
  const [sortBy, setSortBy] = useState('pnl')   // 'pnl' | 'category' | 'winrate'

  const rows = useMemo(() => {
    if (!data) return []
    let r = [...data.strategies]
    if (profitableOnly) {
      r = r.filter(x => x.total_pnl_pct > 0)
    }
    if (sortBy === 'pnl') {
      r.sort((a, b) => b.total_pnl_pct - a.total_pnl_pct)
    } else if (sortBy === 'winrate') {
      r.sort((a, b) => b.win_rate - a.win_rate)
    }
    return r
  }, [data, profitableOnly, sortBy])

  if (!data) {
    return (
      <div className="overview">
        <div className="ov-header">
          <span className="title">📊 All Strategies — Live Status</span>
          <span className="muted">Loading…</span>
        </div>
      </div>
    )
  }

  const profitable = data.strategies.filter(r => r.total_pnl_pct > 0).length
  const losing = data.strategies.filter(r => r.total_pnl_pct < 0).length
  const showCategory = sortBy === 'category'

  return (
    <div className="overview">
      <div className="ov-header">
        <span className="title">📊 All Strategies — Sorted by PnL</span>
      </div>

      {/* Profitability summary banner */}
      <div className="ov-summary">
        <span className="pos"><b>{profitable}</b> profitable</span>
        <span className="muted">·</span>
        <span className="neg"><b>{losing}</b> losing</span>
        <span className="muted">·</span>
        <span className="muted">{data.strategies.length - profitable - losing} flat</span>
      </div>

      {/* Filter + sort controls */}
      <div className="ov-controls">
        <button
          className={`ov-toggle ${profitableOnly ? 'on' : ''}`}
          onClick={() => setProfitableOnly(!profitableOnly)}
        >
          💰 {profitableOnly ? 'Showing only profitable' : 'Show all'}
        </button>
        <select
          className="ov-sort"
          value={sortBy}
          onChange={e => setSortBy(e.target.value)}
        >
          <option value="pnl">Sort: PnL ↓</option>
          <option value="winrate">Sort: Win Rate ↓</option>
          <option value="category">Sort: Category</option>
        </select>
      </div>

      <div className="ov-table">
        <div className="ov-row ov-head">
          <span className="c-name">Strategy</span>
          <span className="c-sig">Signal</span>
          <span className="c-pnl">PnL %</span>
          <span className="c-stat">Win·Trades</span>
        </div>

        {showCategory ? (
          // Grouped by category (original layout)
          ['Recommended (Multi-TF)', 'Selective', 'Smart Money', 'Trend', 'Mean Reversion', 'Breakout', 'Other'].map(cat => {
            const catRows = rows.filter(r => r.category === cat)
            if (catRows.length === 0) return null
            return (
              <div key={cat}>
                <div className="ov-cat">{cat}</div>
                {catRows.map(r => (
                  <StrategyRow
                    key={r.id} row={r}
                    selected={selectedId === r.id}
                    onSelect={onSelect}
                  />
                ))}
              </div>
            )
          })
        ) : (
          // Flat list (sorted by PnL or win rate)
          rows.length === 0 ? (
            <div className="ov-empty">
              {profitableOnly ? 'Koi profitable strategy nahi hai abhi.' : 'No strategies.'}
            </div>
          ) : (
            rows.map(r => (
              <StrategyRow
                key={r.id} row={r}
                selected={selectedId === r.id}
                onSelect={onSelect}
              />
            ))
          )
        )}
      </div>

      <div className="ov-footnote muted small">
        💡 <b>PnL ka matlab:</b> Agar tum is strategy ke saare signals follow karte ($1000 capital, 2% risk per trade, 0.2% fees), kitna profit/loss hota. Sirf positive PnL wale strategies subscribe karo.
      </div>
    </div>
  )
}

function StrategyRow({ row, selected, onSelect }) {
  const pnlClass = row.total_pnl_pct > 0 ? 'pos' : row.total_pnl_pct < 0 ? 'neg' : ''
  return (
    <button
      className={`ov-row clickable pnl-${pnlClass} ${selected ? 'selected' : ''}`}
      onClick={() => onSelect(row.id)}
      title={`Click to view ${row.name} details`}
    >
      <span className="c-name">
        {selected && <span className="check">●</span>}
        {row.name}
      </span>
      <span className="c-sig">{signalCell(row)}</span>
      <span className={`c-pnl ${pnlClass}`}>
        {pct(row.total_pnl_pct)}
      </span>
      <span className="c-stat">
        <span className="muted">{row.win_rate.toFixed(0)}%·{row.total_trades}T</span>
      </span>
    </button>
  )
}

export default memo(StrategyOverview)
