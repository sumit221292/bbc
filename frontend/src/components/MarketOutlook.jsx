import { memo } from 'react'

function fmt(n, d = 2) {
  if (n == null) return '—'
  return Number(n).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d })
}

function biasInfo(bias) {
  if (bias === 'LONG')   return { cls: 'bias-long',    label: 'TEJI (BULL)',     hint: 'Sirf BUY karo' }
  if (bias === 'SHORT')  return { cls: 'bias-short',   label: 'MANDI (BEAR)',    hint: 'Sirf SELL karo' }
  return { cls: 'bias-neutral', label: 'SIDEWAYS (RANGE)', hint: 'Range trade — middle mein wait karo' }
}

function regimeLabel(r) {
  if (r === 'BULL') return 'TEJI 📈'
  if (r === 'BEAR') return 'MANDI 📉'
  if (r === 'CHOP') return 'SIDEWAYS ↔️'
  return r
}

function MarketOutlook({ data, livePrice }) {
  if (!data) {
    return (
      <div className="outlook">
        <div className="outlook-header">
          <span className="title">📋 Aaj/Kal Ka Trade Plan</span>
          <span className="muted">Loading…</span>
        </div>
      </div>
    )
  }

  const { current, regime, levels, volatility, plan } = data
  const price = livePrice ?? current.price
  const b = biasInfo(plan.bias)

  // Position of live price in the BB range (for the locator dot)
  const range = levels.bb_upper - levels.bb_lower
  const dotPos = range > 0 ? Math.max(0, Math.min(100, ((price - levels.bb_lower) / range) * 100)) : 50

  return (
    <div className="outlook">
      <div className="outlook-header">
        <span className="title">📋 Aaj/Kal Ka Trade Plan</span>
        <span className={`bias-badge ${b.cls}`}>{b.label}</span>
      </div>

      <div className="outlook-summary">
        <b>Plan: </b>{b.hint}.<br />
        <span className="muted">{plan.summary}</span>
      </div>

      <div className="outlook-section">
        <div className="section-title">📊 Market Regime (kaisa market hai)</div>
        <div className="kv-grid">
          <div><div className="k">Daily Trend</div><div className="v">{regimeLabel(regime.daily)} <span className="muted">(ADX {regime.daily_adx.toFixed(0)})</span></div></div>
          <div><div className="k">4-Hour Trend</div><div className="v">{regimeLabel(regime.h4)}</div></div>
          <div><div className="k">RSI (1d)</div><div className="v">{levels.rsi_d.toFixed(0)} <span className="muted">{levels.rsi_label}</span></div></div>
          <div><div className="k">Live Price</div><div className="v">${fmt(price)}</div></div>
        </div>
      </div>

      <div className="outlook-section">
        <div className="section-title">🎯 Important Levels (yahan dekhna hai)</div>
        <div className="levels">
          <div className="level resistance">
            <span className="lbl">UPAR Resistance</span>
            <span className="val">${fmt(levels.swing_high_20d)}</span>
            <span className="hint">20-din ka high · breakout zone</span>
          </div>
          <div className="level upper">
            <span className="lbl">Short Zone</span>
            <span className="val">${fmt(levels.bb_upper)}</span>
            <span className="hint">BB upper · sell yahan se</span>
          </div>
          <div className="level mid">
            <span className="lbl">Middle (Mean)</span>
            <span className="val">${fmt(levels.bb_middle)}</span>
            <span className="hint">target ke liye</span>
          </div>
          <div className="level lower">
            <span className="lbl">Long Zone</span>
            <span className="val">${fmt(levels.bb_lower)}</span>
            <span className="hint">BB lower · buy yahan se</span>
          </div>
          <div className="level support">
            <span className="lbl">NEECHE Support</span>
            <span className="val">${fmt(levels.swing_low_20d)}</span>
            <span className="hint">20-din ka low · breakdown zone</span>
          </div>
        </div>
      </div>

      <div className="outlook-section">
        <div className="section-title">📐 Expected Range (agle 24 ghante)</div>
        <div className="range-bar">
          <span>${fmt(volatility.expected_low)}</span>
          <div className="bar"><div className="dot" style={{ left: `${dotPos}%` }} /></div>
          <span>${fmt(volatility.expected_high)}</span>
        </div>
        <div className="muted small">
          ATR-based estimate · ±{volatility.expected_pct.toFixed(2)}% · ATR ${fmt(volatility.daily_atr)}
        </div>
      </div>

      <div className="outlook-section">
        <div className="section-title">⚡ Trade Triggers (kab enter karna hai)</div>

        <div className="trigger long">
          <div className="trigger-head">🟢 BUY (Long) — entry karo agar:</div>
          <div className="trigger-text">{plan.long_trigger}</div>
          <div className="trigger-levels">
            <span>Entry: <b>${fmt(plan.long_entry_zone)}</b></span>
            <span>Stop-Loss: <b className="neg">${fmt(plan.long_stop)}</b></span>
            <span>Target: <b className="pos">${fmt(plan.long_target)}</b></span>
          </div>
        </div>

        <div className="trigger short">
          <div className="trigger-head">🔴 SELL (Short) — entry karo agar:</div>
          <div className="trigger-text">{plan.short_trigger}</div>
          <div className="trigger-levels">
            <span>Entry: <b>${fmt(plan.short_entry_zone)}</b></span>
            <span>Stop-Loss: <b className="neg">${fmt(plan.short_stop)}</b></span>
            <span>Target: <b className="pos">${fmt(plan.short_target)}</b></span>
          </div>
        </div>

        <div className="trigger regime">
          <div className="trigger-head">🚀 BIG MOVE — daily candle close pe:</div>
          <div className="trigger-text">
            <b className="pos">${fmt(plan.regime_change_bull)}</b> ke upar close = TEJI shuru, BUY karo.<br />
            <b className="neg">${fmt(plan.regime_change_bear)}</b> ke neeche close = MANDI shuru, SELL karo.
          </div>
        </div>
      </div>

      <div className="disclaimer">
        ⚠️ Yeh prediction NAHI hai — yeh ek <b>conditional plan</b> hai.
        Matlab "AGAR price X par jaaye, TAB Y karo". Pehle se mat khareedo/becho —
        trigger ka wait karo. Stop-loss hamesha lagana.
      </div>
    </div>
  )
}

export default memo(MarketOutlook)
