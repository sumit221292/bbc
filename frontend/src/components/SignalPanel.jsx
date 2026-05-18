import { memo, useEffect, useState } from 'react'
import { getTrades } from '../api.js'

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
function tradeOutcomes(t) {
  if (!t?.entry || !t?.stop_loss || !t?.target) return null
  const sign = t.type === 'BUY' ? 1 : -1
  const profitPct = (sign * (t.target - t.entry) / t.entry) * 100
  const lossPct = (sign * (t.stop_loss - t.entry) / t.entry) * 100
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

/** A single trade card. Used both for HOLD (the only-active-card case) and
 *  each individual OPEN trade (when multiple are active simultaneously). */
function TradeCard({ trade, livePrice, index }) {
  const tone = trade.type === 'BUY' ? 'buy' : trade.type === 'SELL' ? 'sell' : 'hold'

  let livePnl = trade.pnl_pct
  if (trade.status === 'OPEN' && trade.entry && livePrice) {
    livePnl = trade.type === 'BUY'
      ? (livePrice - trade.entry) / trade.entry * 100
      : (trade.entry - livePrice) / trade.entry * 100
  }

  const outcomes = tradeOutcomes(trade)

  return (
    <div className={`signal-card ${tone}`}>
      <div className="row">
        <span className="label">
          {index != null ? `Trade #${index + 1}` : 'Abhi Ka Price'}
        </span>
        <span className="big">${fmt(livePrice ?? trade.price)}</span>
      </div>
      <div className="row">
        <span className={`badge ${tone}`}>{actionLabel(trade.type)}</span>
        <StatusBadge status={trade.status} />
        {livePnl != null && (
          <span className={`pnl ${livePnl >= 0 ? 'pos' : 'neg'}`}>{pct(livePnl)}</span>
        )}
      </div>
      {trade.status === 'OPEN' && trade.time && (
        <div className="muted small">Trade opened {timeAgo(trade.time)}</div>
      )}
      <div className="reason">{trade.reason}</div>

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
          <div className="v">${fmt(trade.entry)}</div>
        </div>
        <div>
          <div className="k">Stop-Loss</div>
          <div className="v stop">${fmt(trade.stop_loss)}</div>
          {outcomes && <div className="sub neg">{pct(outcomes.lossPct)} loss</div>}
        </div>
        <div>
          <div className="k">Target</div>
          <div className="v target">${fmt(trade.target)}</div>
          {outcomes && <div className="sub pos">{pct(outcomes.profitPct)} profit</div>}
        </div>
      </div>
    </div>
  )
}

function SignalPanel({ result, livePrice, strategies = [], interval, symbol }) {
  // Live-persisted trades from the SQLite store, scoped to the (strategy,
  // storage_interval) pair. MTF strategies always fire on 1h, SMC MTF on 5m,
  // SMC Momentum on 15m -- regardless of the chart interval the user is
  // viewing. The storage_interval field on strategy meta tells us which
  // DB partition to read so a 4h chart of an MTF strategy still surfaces
  // the worker-fired 1h trades.
  const [stored, setStored] = useState({ trades: [], summary: null })
  const strategyId = result?.strategy
  const strategyMeta = strategies.find(s => s.id === strategyId)
  const strategyName = strategyMeta?.name || strategyId || ''
  // Fall back to the chart interval when the meta does not pin a storage TF
  // (older deployments + brand-new single-TF strategies).
  const storageInterval = strategyMeta?.storage_interval || interval

  useEffect(() => {
    // Clear stale data IMMEDIATELY when any input changes so the user does
    // not see the previous (strategy, interval, symbol) trades flashing
    // before the new ones load. This is the "blink" the user reported.
    setStored({ trades: [], summary: null })
    if (!strategyId || !storageInterval || !symbol) return
    let cancelled = false
    const fetchOnce = async () => {
      try {
        const data = await getTrades({
          strategy: strategyId, interval: storageInterval, symbol, limit: 50,
        })
        if (!cancelled) setStored(data)
      } catch {
        // swallow — DB may be empty after a fresh deploy
      }
    }
    fetchOnce()
    const t = setInterval(fetchOnce, 30_000)
    return () => { cancelled = true; clearInterval(t) }
  }, [strategyId, storageInterval, symbol])

  if (!result) return <div className="signal-panel"><div className="muted">Loading…</div></div>
  const { latest, signals, strategy: _sid } = result
  // Always show DB-backed stats (live worker-fired trades). Backtest summary
  // is ignored so numbers stay consistent across Live / All / Best tabs.
  const summary = stored.summary

  // Live Trade Signals = ONLY worker-fired DB trades. No backtest fallback
  // anywhere -- user's previous complaint was the backtest-driven CHAL RAHA
  // cards flickering as price oscillated near the stop (annotate flips
  // OPEN <-> LOSS depending on the current bar's live low). DB is stable
  // because it only updates when the worker fires or resolves a trade.
  const openTrades = (stored.trades || [])
    .filter(t => t.status === 'OPEN')
    .map(t => ({
      time: t.signal_time,
      type: t.type,
      entry: t.entry,
      stop_loss: t.stop_loss,
      target: t.target,
      status: 'OPEN',
      pnl_pct: null,        // live mark-to-market computed below from livePrice
      reason: t.reason || '',
      price: t.entry,
    }))

  // Aggregate live mark-to-market PnL across all open trades.
  let combinedLivePnl = null
  if (openTrades.length > 0 && livePrice) {
    const total = openTrades.reduce((acc, t) => {
      if (!t.entry) return acc
      const pnl = t.type === 'BUY'
        ? (livePrice - t.entry) / t.entry * 100
        : (t.entry - livePrice) / t.entry * 100
      return acc + pnl
    }, 0)
    combinedLivePnl = total / openTrades.length  // average per trade
  }

  return (
    <div className="signal-panel">
      <div className="strategy-banner">
        <span className="strategy-banner-label">🤖 STRATEGY</span>
        <span className="strategy-banner-name">{strategyName}</span>
        <span className="strategy-banner-filter" title="Trades with risk:reward below 1:2 are filtered out across all strategies and timeframes.">
          🛡 RR ≥ 1:2
        </span>
      </div>

      <div className="panel-section-title">
        Live Trade Signals
        {openTrades.length > 0 && (
          <span className="active-count">
            {openTrades.length} active · avg {pct(combinedLivePnl ?? 0)}
          </span>
        )}
      </div>

      {openTrades.length > 0
        ? openTrades.map((t, i) => (
            <TradeCard
              key={`${t.time}-${t.type}`}
              trade={t}
              livePrice={livePrice}
              index={openTrades.length > 1 ? i : null}
            />
          ))
        : (
          // No DB-tracked open trade. Show a plain "no active trade" card --
          // never use the backtest's `latest` (which could be an unfired
          // analytical setup and would mislead the user as it did before).
          <div className="signal-card hold">
            <div className="row">
              <span className="label">Abhi Ka Price</span>
              <span className="big">${livePrice ? Number(livePrice).toLocaleString(undefined, { maximumFractionDigits: 2 }) : '—'}</span>
            </div>
            <div className="row">
              <span className="badge hold">WAIT (Ruko)</span>
            </div>
            <div className="reason muted">
              Worker ne {strategyName} pe abhi tak koi trade fire nahi ki.
              Naya signal aate hi yahaan dikhega.
            </div>
          </div>
        )
      }

      {summary && (
        <div className="summary">
          <div className="title">📊 Live Performance — {symbol || '—'} · {strategyName} · {storageInterval || '—'} (worker-fired only)</div>
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
        <div className="title">
          📜 Recent Trades — {symbol || '—'} · {strategyName} · {storageInterval || '—'}
          {stored.trades.length > 0 && (
            <span className="muted small"> (saved {stored.trades.length})</span>
          )}
        </div>
        <ul>
          {stored.trades.map(t => (
            <li key={`${t.id}`}>
              <span className={`badge sm ${t.type === 'BUY' ? 'buy' : 'sell'}`}>{t.type}</span>
              <StatusBadge status={t.status} />
              <span className="px">${fmt(t.entry)}</span>
              {t.pnl_pct != null && t.status !== 'OPEN' && (
                <span className={`pnl sm ${t.pnl_pct >= 0 ? 'pos' : 'neg'}`}>{pct(t.pnl_pct)}</span>
              )}
              <span className="muted small">{new Date(t.signal_time * 1000).toLocaleString()}</span>
            </li>
          ))}
          {stored.trades.length === 0 && (
            <li className="muted">
              Abhi koi live trade save nahi hua — alert worker se naya signal aate hi yaha
              dikhega ({symbol || '—'} · {strategyName} · {storageInterval || '—'}).
            </li>
          )}
        </ul>
      </div>
    </div>
  )
}

export default memo(SignalPanel)
