import { memo } from 'react'

function fmt(n, d = 2) {
  return n == null ? '—' : Number(n).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d })
}

function pct(n) {
  if (n == null) return '—'
  const sign = n >= 0 ? '+' : ''
  return `${sign}${n.toFixed(2)}%`
}

function StatusBadge({ status }) {
  if (!status) return null
  const cls = status === 'WIN' ? 'win' : status === 'LOSS' ? 'loss' : 'open'
  const label = status === 'WIN' ? 'PROFIT' : status === 'LOSS' ? 'STOP HIT' : 'CHAL RAHA'
  return <span className={`badge sm ${cls}`}>{label}</span>
}

function actionLabel(type) {
  if (type === 'BUY') return 'BUY (Khareedo)'
  if (type === 'SELL') return 'SELL (Becho)'
  return 'WAIT (Ruko)'
}

/** Compute potential profit% (if target hits) and loss% (if stop hits)
 *  as price-move percentages, signed naturally for the trade direction. */
function tradeOutcomes(latest) {
  if (!latest?.entry || !latest?.stop_loss || !latest?.target) return null
  const sign = latest.type === 'BUY' ? 1 : -1
  const profitPct = (sign * (latest.target - latest.entry) / latest.entry) * 100
  const lossPct = (sign * (latest.stop_loss - latest.entry) / latest.entry) * 100
  const rr = Math.abs(profitPct / lossPct)
  return { profitPct, lossPct, rr }
}

function timeAgo(ts) {
  if (!ts) return ''
  const diff = Math.floor(Date.now() / 1000 - ts)
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

function SignalPanel({ result, livePrice }) {
  if (!result) return <div className="signal-panel"><div className="muted">Loading…</div></div>
  const { latest, signals, summary } = result
  const tone = latest.type === 'BUY' ? 'buy' : latest.type === 'SELL' ? 'sell' : 'hold'

  let livePnl = latest.pnl_pct
  if (latest.status === 'OPEN' && latest.entry && livePrice) {
    livePnl = latest.type === 'BUY'
      ? (livePrice - latest.entry) / latest.entry * 100
      : (latest.entry - livePrice) / latest.entry * 100
  }

  const outcomes = tradeOutcomes(latest)

  return (
    <div className="signal-panel">
      <div className="panel-section-title">🤖 Strategy Ka Live Signal</div>

      <div className={`signal-card ${tone}`}>
        <div className="row">
          <span className="label">Abhi Ka Price</span>
          <span className="big">${fmt(livePrice ?? latest.price)}</span>
        </div>
        <div className="row">
          <span className={`badge ${tone}`}>{actionLabel(latest.type)}</span>
          <StatusBadge status={latest.status} />
          {livePnl != null && (
            <span className={`pnl ${livePnl >= 0 ? 'pos' : 'neg'}`}>{pct(livePnl)}</span>
          )}
        </div>
        {latest.status === 'OPEN' && latest.time && (
          <div className="muted small">Trade opened {timeAgo(latest.time)}</div>
        )}
        <div className="reason">{latest.reason}</div>

        {outcomes && (
          <div className="rr-strip">
            <span className="rr-badge">RR 1 : {outcomes.rr.toFixed(2)}</span>
            <span className="rr-text">
              <span className="pos">{pct(outcomes.profitPct)}</span>
              <span className="muted"> profit</span>
              <span className="muted"> / </span>
              <span className="neg">{pct(outcomes.lossPct)}</span>
              <span className="muted"> loss</span>
            </span>
          </div>
        )}

        <div className="grid">
          <div>
            <div className="k">Entry</div>
            <div className="v">${fmt(latest.entry)}</div>
          </div>
          <div>
            <div className="k">Stop-Loss</div>
            <div className="v stop">${fmt(latest.stop_loss)}</div>
            {outcomes && (
              <div className="sub neg">{pct(outcomes.lossPct)} loss</div>
            )}
          </div>
          <div>
            <div className="k">Target</div>
            <div className="v target">${fmt(latest.target)}</div>
            {outcomes && (
              <div className="sub pos">{pct(outcomes.profitPct)} profit</div>
            )}
          </div>
        </div>
      </div>

      {summary && (
        <div className="summary">
          <div className="title">📊 Strategy Performance (jitna data load hua)</div>
          <div className="stats">
            <div><div className="k">Total Trades</div><div className="v">{summary.total}</div></div>
            <div><div className="k">Profit Hua</div><div className="v pos">{summary.wins}</div></div>
            <div><div className="k">Stop Hit Hua</div><div className="v neg">{summary.losses}</div></div>
            <div><div className="k">Chal Raha</div><div className="v">{summary.open}</div></div>
            <div><div className="k">Win Rate</div><div className="v">{summary.win_rate.toFixed(0)}%</div></div>
            <div><div className="k">Total P&L</div><div className={`v ${summary.total_pnl_pct >= 0 ? 'pos' : 'neg'}`}>{pct(summary.total_pnl_pct)}</div></div>
            <div><div className="k">Avg/Trade</div><div className={`v ${summary.avg_pnl_pct >= 0 ? 'pos' : 'neg'}`}>{pct(summary.avg_pnl_pct)}</div></div>
          </div>
        </div>
      )}

      <div className="history">
        <div className="title">📜 Recent Trades (last 15)</div>
        <ul>
          {signals.slice(-15).reverse().map(s => (
            <li key={`${s.time}-${s.type}`}>
              <span className={`badge sm ${s.type === 'BUY' ? 'buy' : 'sell'}`}>{s.type}</span>
              <StatusBadge status={s.status} />
              <span className="px">${fmt(s.price)}</span>
              {s.pnl_pct != null && (
                <span className={`pnl sm ${s.pnl_pct >= 0 ? 'pos' : 'neg'}`}>{pct(s.pnl_pct)}</span>
              )}
              <span className="muted small">{new Date(s.time * 1000).toLocaleString()}</span>
            </li>
          ))}
          {signals.length === 0 && <li className="muted">Abhi koi trade nahi liya — strategy selective hai, signal aane par dikhega.</li>}
        </ul>
      </div>
    </div>
  )
}

export default memo(SignalPanel)
