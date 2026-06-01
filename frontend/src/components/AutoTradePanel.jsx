import { memo, useState } from 'react'
import { killAutoTrade, setAutoTrade, testBinanceCredentials } from '../api.js'
import SymbolPicker from './SymbolPicker.jsx'

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
  // Auto-trade target coin (legacy single-coin mode). Defaults to
  // whatever cfg.symbol currently is on the server (BTCUSDT out of the
  // box). User picks via SymbolPicker; the backend will auto-add the
  // coin to the watchlist too so signals actually fire on it.
  const [symbol, setSymbol] = useState(serverState?.symbol ?? 'BTCUSDT')
  // New multi-pair whitelist: explicit (strategy_id, symbol) combos.
  // Replaces the "one strategy on one coin" model when populated.
  const [pairs, setPairs] = useState(at?.allowed_pairs ?? [])
  // Inline builder state for the "+ Add pair" form.
  const [draftStrategy, setDraftStrategy] = useState('')
  const [draftSymbol, setDraftSymbol] = useState('')
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('')

  const addPair = () => {
    if (!draftStrategy || !draftSymbol) return
    const sym = draftSymbol.toUpperCase()
    // Dedupe -- silently swallow a re-add of the same combo.
    if (pairs.some(p => p.strategy_id === draftStrategy && p.symbol === sym)) return
    setPairs([...pairs, { strategy_id: draftStrategy, symbol: sym }])
    setDraftStrategy('')
    setDraftSymbol('')
  }
  const removePair = (idx) => {
    setPairs(pairs.filter((_, i) => i !== idx))
  }

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
        allowed_pairs: pairs,
        symbol: symbol || '',
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

  // Resolve allowed strategy IDs to human names for the live-config
  // summary -- the form list below uses IDs but the read-only summary
  // should show the same labels the rest of the app uses.
  const strategyNameMap = Object.fromEntries((strategies || []).map(s => [s.id, s.name]))
  const allowedNames = (at?.allowed_strategies || [])
    .map(id => strategyNameMap[id] || id)

  return (
    <div className="auto-trade">
      <div className={`auto-banner ${isLive ? 'live' : 'idle'}`}>
        {isLive
          ? <>🚨 <b>AUTO-TRADE LIVE</b> — orders being placed on Binance Spot. Today {at?.trades_today ?? 0}/{at?.max_trades_per_day ?? '?'} trades, loss {((at?.loss_today_pct ?? 0) * 100).toFixed(2)}%</>
          : <>⚙️ Auto-trade idle. Enable below ONLY after paper-trading and reading the warnings.</>
        }
      </div>

      {/* Server-side live configuration summary. Reflects what's actually
          saved on the backend, NOT the form-state below (which is what
          the user is about to change to). This is the panel the user
          wanted to see "what setup is live right now". */}
      {at && (
        <div className="auto-live-config">
          <div className="alc-title">📋 Current Live Configuration</div>
          <div className="alc-grid">
            <div className="alc-row">
              <span className="alc-key">State</span>
              <span className={`alc-val ${isLive ? 'pos' : 'muted'}`}>
                {isLive ? '🟢 LIVE' : '⚪ IDLE'}
              </span>
            </div>
            <div className="alc-row">
              <span className="alc-key">Target coin</span>
              <span className="alc-val">
                <b>{serverState?.symbol || '—'}</b>
              </span>
            </div>
            {(at.allowed_pairs && at.allowed_pairs.length > 0) ? (
              <div className="alc-row">
                <span className="alc-key">Allowed (strategy, coin) pairs</span>
                <span className="alc-val">
                  {at.allowed_pairs.map((p, i) => (
                    <span key={`${p.strategy_id}-${p.symbol}`} className="alc-pair-chip">
                      {strategyNameMap[p.strategy_id]?.replace(/^[^\w]+\s*/, '') || p.strategy_id}
                      <span className="muted"> on </span>
                      {p.symbol.replace(/USDT$/, '')}
                    </span>
                  ))}
                </span>
              </div>
            ) : (
              <div className="alc-row">
                <span className="alc-key">Allowed strategies (legacy)</span>
                <span className="alc-val">
                  {allowedNames.length > 0
                    ? allowedNames.join(', ')
                    : <span className="muted">none (will block all fires)</span>}
                </span>
              </div>
            )}
            <div className="alc-row">
              <span className="alc-key">Capital</span>
              <span className="alc-val">${at.capital_usd.toFixed(2)}</span>
            </div>
            <div className="alc-row">
              <span className="alc-key">Risk / trade</span>
              <span className="alc-val">{(at.risk_pct * 100).toFixed(2)}%</span>
            </div>
            <div className="alc-row">
              <span className="alc-key">Max position</span>
              <span className="alc-val">${at.max_position_usd.toFixed(2)}</span>
            </div>
            <div className="alc-row">
              <span className="alc-key">Daily trade cap</span>
              <span className="alc-val">
                {at.trades_today}/{at.max_trades_per_day}
              </span>
            </div>
            <div className="alc-row">
              <span className="alc-key">Daily loss cap</span>
              <span className="alc-val">
                {(at.loss_today_pct * 100).toFixed(2)}% /{' '}
                {(at.max_daily_loss_pct * 100).toFixed(2)}%
              </span>
            </div>
            <div className="alc-row">
              <span className="alc-key">API key</span>
              <span className={`alc-val ${at.has_api_key ? 'pos' : 'neg'}`}>
                {at.has_api_key ? '✓ stored' : '✗ missing'}
              </span>
            </div>
            <div className="alc-row">
              <span className="alc-key">API secret</span>
              <span className={`alc-val ${at.has_api_secret ? 'pos' : 'neg'}`}>
                {at.has_api_secret ? '✓ stored' : '✗ missing'}
              </span>
            </div>
            <div className="alc-row">
              <span className="alc-key">Confirmation</span>
              <span className={`alc-val ${at.has_confirmation ? 'pos' : 'neg'}`}>
                {at.has_confirmation ? '✓ valid' : '✗ not set'}
              </span>
            </div>
          </div>
          {!isLive && at.has_api_key && at.has_api_secret && allowedNames.length > 0 && !at.has_confirmation && (
            <div className="alc-hint muted small">
              💡 Everything else is set — type the confirmation phrase in
              the form below and toggle <b>"I want to enable auto-trade"</b>
              to go live.
            </div>
          )}
        </div>
      )}

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

        <div className="auto-symbol">
          <div className="title">Auto-trade target coin (orders fire here only)</div>
          <div className="auto-symbol-current">
            Current: <b>{symbol || '—'}</b>
          </div>
          <SymbolPicker
            value=""
            placeholder={`Change target (current: ${symbol || 'none'})`}
            size="compact"
            onChange={sym => sym && setSymbol(sym)}
          />
          <div className="muted small" style={{ marginTop: 4, lineHeight: 1.4 }}>
            Whichever coin you pick here is automatically added to the
            watchlist so signals fire on it. Only ONE coin can be the
            auto-trade target at a time (Spot account holds a single
            position).
          </div>
        </div>

        <div className="auto-pairs">
          <div className="title">
            (Strategy, Coin) pair whitelist
            <span className="muted small"> — only matching combos fire real orders</span>
          </div>

          {/* Current pair list */}
          {pairs.length === 0 ? (
            <div className="muted small auto-pairs-empty">
              No pairs yet. Add (strategy, coin) combos below, e.g.
              <code> mtf_2screen + ZECUSDT</code>. When set, this list
              replaces the legacy "single target + strategy whitelist"
              model below.
            </div>
          ) : (
            <div className="auto-pairs-list">
              {pairs.map((p, i) => {
                const stratLabel = (strategyNameMap[p.strategy_id] || p.strategy_id)
                  .replace(/^[^\w]+\s*/, '')
                  .slice(0, 22)
                const coinLabel = p.symbol.replace(/USDT$/, '')
                return (
                  <div key={`${p.strategy_id}-${p.symbol}-${i}`} className="auto-pair-row">
                    <span className="auto-pair-coin">{coinLabel}</span>
                    <span className="muted"> · </span>
                    <span className="auto-pair-strat">{stratLabel}</span>
                    <button type="button" className="auto-pair-remove"
                            title="Remove pair"
                            onClick={() => removePair(i)}>×</button>
                  </div>
                )
              })}
            </div>
          )}

          {/* + Add pair form */}
          <div className="auto-pair-add">
            <select
              value={draftStrategy}
              onChange={e => setDraftStrategy(e.target.value)}
              className="auto-pair-strat-select"
            >
              <option value="">Pick strategy…</option>
              {strategies.map(s => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
            <SymbolPicker
              value=""
              placeholder={draftSymbol || "Pick coin…"}
              size="compact"
              onChange={sym => sym && setDraftSymbol(sym)}
            />
            <button type="button" className="auto-pair-add-btn"
                    disabled={!draftStrategy || !draftSymbol}
                    onClick={addPair}>
              + Add pair
            </button>
          </div>
          {draftSymbol && (
            <div className="muted small auto-pair-draft">
              Draft: <b>{draftSymbol}</b> · {draftStrategy
                ? (strategyNameMap[draftStrategy] || draftStrategy)
                : 'pick a strategy →'}
            </div>
          )}
        </div>

        <div className="auto-strategies">
          <div className="title">
            Legacy: Whitelisted strategies <span className="muted small">(only used when pair list above is empty)</span>
          </div>
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
