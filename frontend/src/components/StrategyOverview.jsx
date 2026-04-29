import { memo, useMemo } from 'react'

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
  const grouped = useMemo(() => {
    if (!data) return []
    const map = {}
    for (const r of data.strategies) {
      if (!map[r.category]) map[r.category] = []
      map[r.category].push(r)
    }
    // Stable category order
    const order = ['Recommended (Multi-TF)', 'Selective', 'Trend', 'Mean Reversion', 'Breakout', 'Other']
    return order.filter(c => map[c]).map(c => [c, map[c]])
  }, [data])

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

  const active = data.strategies.filter(r => r.signal !== 'HOLD').length

  return (
    <div className="overview">
      <div className="ov-header">
        <span className="title">📊 All Strategies — Live Status</span>
        <span className="muted">{active} active / {data.strategies.length} total</span>
      </div>

      <div className="ov-table">
        <div className="ov-row ov-head">
          <span className="c-name">Strategy</span>
          <span className="c-sig">Signal</span>
          <span className="c-pnl">PnL</span>
          <span className="c-stat">Win·Trades</span>
        </div>
        {grouped.map(([cat, rows]) => (
          <div key={cat}>
            <div className="ov-cat">{cat}</div>
            {rows.map(r => (
              <button
                key={r.id}
                className={`ov-row clickable ${selectedId === r.id ? 'selected' : ''}`}
                onClick={() => onSelect(r.id)}
                title={`Click to view ${r.name} details`}
              >
                <span className="c-name">
                  {selectedId === r.id && <span className="check">●</span>}
                  {r.name}
                </span>
                <span className="c-sig">{signalCell(r)}</span>
                <span className={`c-pnl ${r.pnl_pct == null ? '' : r.pnl_pct >= 0 ? 'pos' : 'neg'}`}>
                  {r.pnl_pct == null ? '—' : pct(r.pnl_pct)}
                </span>
                <span className="c-stat">
                  <span className="muted">{r.win_rate.toFixed(0)}%·{r.total_trades}T</span>
                </span>
              </button>
            ))}
          </div>
        ))}
      </div>

      <div className="ov-footnote muted small">
        💡 Sab strategies 1h candles pe run hote hain. Row click karke switch karo.
      </div>
    </div>
  )
}

export default memo(StrategyOverview)
