import { memo, useState } from 'react'
import { killAutoTrade, setAutoTrade, testBinanceCredentials } from '../api.js'

const CONFIRM_PHRASE = 'I UNDERSTAND THE RISKS'

/** Live auto-execution settings — every knob defaults to safe values, the
 *  user must explicitly tick allowed strategies AND type the confirmation
 *  phrase before the worker will actually trade. */
function AutoTradePanel({ strategies, serverState, onConfigChange }) {
  const at = serverState?.auto_trade
  const [apiKey, setApiKey] = useState('')
  const [apiSecret, setApiSecret] = useState('')
  const [capital, setCapital] = useState(at?.capital_usd ?? 100)
  const [riskPct, setRiskPct] = useState(at?.risk_pct ?? 0.01)
  const [maxPos, setMaxPos] = useState(at?.max_position_usd ?? 500)
  const [maxTrades, setMaxTrades] = useState(at?.max_trades_per_day ?? 5)
  const [maxLoss, setMaxLoss] = useState(at?.max_daily_loss_pct ?? 0.05)
  const [confirmation, setConfirmation] = useState('')
  const [allowed, setAllowed] = useState(at?.allowed_strategies ?? [])
  const [enabled, setEnabled] = useState(at?.enabled ?? false)
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('')

  const toggleAllowed = (id) => {
    setAllowed(allowed.includes(id)
      ? allowed.filter(x => x !== id)
      : [...allowed, id])
  }

  const testKey = async () => {
    if (!apiKey || !apiSecret) {
      setStatus('❌ Enter both key and secret first.')
      return
    }
    setBusy(true)
    setStatus('Testing…')
    const r = await testBinanceCredentials({ api_key: apiKey, api_secret: apiSecret })
    setStatus((r.ok ? '✅ ' : '❌ ') + r.message)
    setBusy(false)
  }

  const save = async () => {
    setBusy(true)
    setStatus('Saving…')
    try {
      const updated = await setAutoTrade({
        enabled,
        api_key: apiKey || '',
        api_secret: apiSecret || '',
        capital_usd: Number(capital),
        risk_pct: Number(riskPct),
        max_position_usd: Number(maxPos),
        max_trades_per_day: Number(maxTrades),
        max_daily_loss_pct: Number(maxLoss),
        confirmation,
        allowed_strategies: allowed,
      })
      setApiKey('')         // never keep secrets in component state after save
      setApiSecret('')
      setStatus(updated.enabled ? '✅ Auto-trade ENABLED' : '✅ Saved (worker idle)')
      onConfigChange?.()
    } catch (e) {
      setStatus('❌ ' + e.message)
    }
    setBusy(false)
  }

  const kill = async () => {
    if (!confirm('Kill switch — disable auto-trade AND cancel all open orders. Continue?')) return
    setBusy(true)
    setStatus('Killing…')
    const r = await killAutoTrade()
    setStatus(r.ok ? '🛑 Killed. Open orders cancelled. Check Binance for any remaining FILLED positions.' : '❌ Kill failed')
    onConfigChange?.()
    setBusy(false)
  }

  const isLive = at?.enabled
  const phraseMatches = confirmation === CONFIRM_PHRASE
  const pos = at?.current_position

  return (
    <div className="auto-trade">
      <div className={`auto-banner ${isLive ? 'live' : 'idle'}`}>
        {isLive
          ? <>🚨 <b>AUTO-TRADE LIVE</b> — orders being placed on Binance Spot. Today {at?.trades_today ?? 0}/{at?.max_trades_per_day ?? '?'} trades, loss {((at?.loss_today_pct ?? 0) * 100).toFixed(2)}%</>
          : <>⚙️ Auto-trade idle. Enable below ONLY after paper-trading and reading the warnings.</>
        }
      </div>

      {pos && (
        <div className="position-card">
          <div className="position-head">
            📌 Open position
            <span className={`badge sm ${pos.side === 'LONG' ? 'buy' : 'sell'}`}>{pos.side}</span>
          </div>
          <div className="position-detail">
            <span><b>{pos.qty.toFixed(6)}</b> BTC</span>
            <span className="muted">·</span>
            <span>Entry <b>${pos.entry.toFixed(2)}</b></span>
            <span className="muted">·</span>
            <span>Stop <b className="neg">${pos.stop.toFixed(2)}</b></span>
            <span className="muted">·</span>
            <span>Target <b className="pos">${pos.target.toFixed(2)}</b></span>
            <span className="muted">·</span>
            <span className="muted">opened by {pos.strategy_id}</span>
          </div>
          <div className="muted small position-foot">
            Same-direction signals will be SKIPPED. Opposite-direction signals will close this position before opening the new one.
          </div>
        </div>
      )}
      {at?.halted_reason && (
        <div className="worker-error">⛔ HALTED: {at.halted_reason}</div>
      )}
      {at?.last_trade_error && (
        <div className="worker-error">⚠️ Last error: {at.last_trade_error}</div>
      )}

      <details className="alerts-help" open>
        <summary>📖 Setup checklist (read carefully)</summary>
        <ol>
          <li>Binance pe API key banao at <a href="https://www.binance.com/en/my/settings/api-management" target="_blank">API Management</a></li>
          <li><b>Enable Spot Trading</b> — ON ✅</li>
          <li><b>Enable Withdrawals</b> — <b>OFF</b> ❌ (must be off)</li>
          <li><b>Restrict access to trusted IPs</b> — add Railway IP whitelist (find in Railway dashboard)</li>
          <li>Test key here BEFORE enabling auto-trade</li>
          <li>Start with small capital ($100). Risk ≤ 1%. Max 5 trades/day.</li>
          <li>Whitelist 1-2 strategies you've paper-tested first</li>
          <li>Type <code>{CONFIRM_PHRASE}</code> in the confirmation box exactly</li>
        </ol>
      </details>

      <div className="alerts-form">
        <label>
          <span>Binance API Key {at?.has_api_key && <em className="muted small">(stored)</em>}</span>
          <input
            type="password"
            value={apiKey}
            onChange={e => setApiKey(e.target.value)}
            placeholder={at?.has_api_key ? '••••• (re-enter to change)' : 'Paste API key'}
          />
        </label>
        <label>
          <span>Binance API Secret {at?.has_api_secret && <em className="muted small">(stored)</em>}</span>
          <input
            type="password"
            value={apiSecret}
            onChange={e => setApiSecret(e.target.value)}
            placeholder={at?.has_api_secret ? '••••• (re-enter to change)' : 'Paste API secret'}
          />
        </label>

        <button className="alerts-test secondary" onClick={testKey}
                disabled={busy || !apiKey || !apiSecret}>
          🔍 Test Credentials (no orders placed)
        </button>

        <div className="auto-grid">
          <label>
            <span>Capital ($)</span>
            <input type="number" value={capital} onChange={e => setCapital(e.target.value)} min={10} />
          </label>
          <label>
            <span>Risk % per trade (max 5%)</span>
            <input type="number" value={riskPct} onChange={e => setRiskPct(e.target.value)}
                   step="0.005" min="0.001" max="0.05" />
          </label>
          <label>
            <span>Max position ($)</span>
            <input type="number" value={maxPos} onChange={e => setMaxPos(e.target.value)} min={10} />
          </label>
          <label>
            <span>Max trades/day</span>
            <input type="number" value={maxTrades} onChange={e => setMaxTrades(e.target.value)}
                   min={1} max={50} />
          </label>
          <label>
            <span>Max daily loss %</span>
            <input type="number" value={maxLoss} onChange={e => setMaxLoss(e.target.value)}
                   step="0.005" min="0.01" max="0.20" />
          </label>
        </div>

        <div className="auto-strategies">
          <div className="title">Whitelisted strategies (only these can fire real orders)</div>
          <div className="alerts-subs-list">
            {strategies.map(s => (
              <label key={s.id} className={`alerts-sub-row ${allowed.includes(s.id) ? 'on' : ''}`}>
                <input type="checkbox" checked={allowed.includes(s.id)}
                       onChange={() => toggleAllowed(s.id)} />
                <span className="alerts-sub-name">{s.name}</span>
              </label>
            ))}
          </div>
        </div>

        <label>
          <span>Confirmation phrase {phraseMatches && <em className="pos small">✓ matches</em>}</span>
          <input type="text" value={confirmation}
                 onChange={e => setConfirmation(e.target.value)}
                 placeholder={`Type exactly: ${CONFIRM_PHRASE}`} />
        </label>

        <label className="alerts-checkbox">
          <input type="checkbox" checked={enabled}
                 onChange={e => setEnabled(e.target.checked)} />
          <span><b>I want to enable auto-trade</b> (still needs all the above to be valid)</span>
        </label>

        <div className="alerts-actions">
          <button className="alerts-test" onClick={save} disabled={busy}>
            {busy ? '…' : '💾 Save Settings'}
          </button>
          <button className="auto-kill" onClick={kill} disabled={busy}>
            🛑 KILL SWITCH
          </button>
        </div>
        {status && <div className="alerts-status">{status}</div>}
      </div>
    </div>
  )
}

export default memo(AutoTradePanel)
