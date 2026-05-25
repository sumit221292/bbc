import { memo, useEffect, useState } from 'react'
import { getAlertsConfig, sendBackendTest, setAlertsConfig } from '../api.js'
import SymbolPicker from './SymbolPicker.jsx'
import { getTelegramUpdates } from '../lib/telegram.js'
import AutoTradePanel from './AutoTradePanel.jsx'
import { timeAgo as timeAgoBase } from '../lib/format.js'

// Local wrapper -- the shared helper returns '' for falsy ts, but the
// debug panel expects the literal "never" string.
function timeAgo(ts) {
  return ts ? timeAgoBase(ts) : 'never'
}

/** UI for setting up the always-on backend Telegram worker.
 *  Token + chat_id are sent to /api/alerts/config; the server polls every
 *  60 seconds and pushes Telegram on new signals — works even with the
 *  browser tab closed. */
function AlertsTab({ strategies, snapshot }) {
  const [token, setToken] = useState('')
  // Chat IDs entered as comma-separated; parsed to list on save.
  const [chatIdsText, setChatIdsText] = useState('')
  const [enabled, setEnabled] = useState(true)
  const [subs, setSubs] = useState([])    // [{ strategy_id, interval }]
  const [serverState, setServerState] = useState(null)
  const [testStatus, setTestStatus] = useState('')
  const [saving, setSaving] = useState(false)
  const [detectedChats, setDetectedChats] = useState([])
  const [detectStatus, setDetectStatus] = useState('')
  // Multi-coin watchlist. The worker fires signals for every (symbol,
  // strategy) pair every tick. Auto-trade still uses serverState.symbol.
  const [watchSymbols, setWatchSymbols] = useState(['BTCUSDT'])

  // Pull current config on mount
  useEffect(() => {
    getAlertsConfig().then(s => {
      setServerState(s)
      // Merge legacy chat_id + new chat_ids into a single text representation
      const all = []
      if (s.chat_id) all.push(s.chat_id)
      for (const c of s.chat_ids || []) if (!all.includes(c)) all.push(c)
      setChatIdsText(all.join(', '))
      setEnabled(s.enabled)
      setSubs(s.subscriptions || [])
      setWatchSymbols(s.symbols && s.symbols.length > 0 ? s.symbols : [s.symbol || 'BTCUSDT'])
    }).catch(() => { /* offline ok */ })
    const id = setInterval(() => {
      getAlertsConfig().then(setServerState).catch(() => {})
    }, 30000)
    return () => clearInterval(id)
  }, [])

  const parseChatIds = () => chatIdsText.split(',')
    .map(s => s.trim()).filter(Boolean)

  const subIds = new Set(subs.map(s => s.strategy_id))

  const toggle = (id) => {
    if (subIds.has(id)) {
      setSubs(subs.filter(s => s.strategy_id !== id))
    } else {
      setSubs([...subs, { strategy_id: id, interval: null, excluded: [] }])
    }
  }

  const subAll = () => {
    setSubs(strategies.map(s => ({ strategy_id: s.id, interval: null, excluded: [] })))
  }
  const subNone = () => setSubs([])

  // Per-(strategy, symbol) opt-out: empty excluded = fires everywhere.
  // Clicking a coin chip flips its membership in that strategy's list.
  const isExcluded = (sid, sym) => {
    const sub = subs.find(s => s.strategy_id === sid)
    return (sub?.excluded || []).includes(sym)
  }

  const toggleExclusion = (sid, sym) => {
    setSubs(subs.map(s => {
      if (s.strategy_id !== sid) return s
      const ex = s.excluded || []
      return {
        ...s,
        excluded: ex.includes(sym) ? ex.filter(x => x !== sym) : [...ex, sym],
      }
    }))
  }

  const save = async () => {
    setSaving(true)
    try {
      const chatIds = parseChatIds()
      const cleaned = {
        token: token || '',           // empty = keep existing on server
        chat_id: '',                  // we use the new list field now
        chat_ids: chatIds,
        enabled,
        symbol: serverState?.symbol || 'BTCUSDT',  // auto-trade target
        symbols: watchSymbols,                      // multi-coin watchlist
        subscriptions: subs,
      }
      const updated = await setAlertsConfig(cleaned)
      setServerState(updated)
      setTestStatus(`✅ Saved to backend (${chatIds.length} recipient${chatIds.length === 1 ? '' : 's'})`)
      setToken('')  // clear local copy after saving (it's stored server-side)
    } catch (e) {
      setTestStatus(`❌ Save failed: ${e}`)
    }
    setSaving(false)
  }

  const sendTest = async () => {
    const chatIds = parseChatIds()
    if (chatIds.length === 0) {
      setTestStatus('❌ Need at least 1 chat_id')
      return
    }
    if (!token) {
      setTestStatus('❌ Token must be entered in the form for the test')
      return
    }
    setTestStatus('Sending…')
    const res = await sendBackendTest({ token, chat_id: '', chat_ids: chatIds })
    if (res.ok) {
      setTestStatus(`✅ ${res.summary || 'Sent'} — check all Telegram chats.`)
    } else {
      setTestStatus('❌ ' + res.description)
    }
  }

  const detectChatId = async () => {
    if (!token) {
      setDetectStatus('❌ Pehle bot token paste karo (form mein).')
      return
    }
    setDetectStatus('Checking…')
    setDetectedChats([])
    const res = await getTelegramUpdates(token)
    if (!res.ok) { setDetectStatus('❌ ' + res.description); return }
    if (res.chats.length === 0) {
      setDetectStatus(
        '⚠️ No chats found. Pehle apne bot ko message karo, fir yahan re-click karo.'
      )
      return
    }
    setDetectedChats(res.chats)
    setDetectStatus(`✅ ${res.chats.length} chat(s) found:`)
  }

  const lastPollAge = serverState?.last_poll
    ? timeAgo(serverState.last_poll)
    : 'never'
  const workerActive = serverState?.has_token && serverState?.enabled && (serverState?.subscriptions?.length ?? 0) > 0
  const hasFullConfig = serverState?.has_token && serverState?.chat_id && (serverState?.subscriptions?.length ?? 0) > 0
  const paused = hasFullConfig && !serverState?.enabled

  return (
    <div className="alerts-tab">
      <div className="panel-section-title">🔔 Telegram Alerts (Always-On)</div>

      {/* Worker status banner */}
      <div className={`worker-status ${workerActive ? 'active' : paused ? 'paused' : 'idle'}`}>
        <span className="ws-dot" />
        <span>
          {workerActive
            ? <>Backend worker <b>ACTIVE</b> · last poll <b>{lastPollAge}</b> · browser band ho to bhi alerts aayenge</>
            : paused
              ? <>⚠️ Config complete but worker is <b>PAUSED</b> — check the box below and Save to enable</>
              : <>Backend worker <b>idle</b> · token + chat_id + at least 1 subscription needed</>
          }
        </span>
      </div>
      {paused && (
        <button
          className="alerts-test"
          onClick={async () => {
            setEnabled(true)
            // Save immediately with enabled=true
            const cfg = { token: '', chat_id: chatId, enabled: true, subscriptions: subs }
            try {
              await setAlertsConfig(cfg)
              const fresh = await getAlertsConfig()
              setServerState(fresh)
              setTestStatus('✅ Worker enabled')
            } catch (e) {
              setTestStatus('❌ ' + e)
            }
          }}
          style={{ width: '100%', marginBottom: '10px' }}
        >
          ▶️ Enable Worker Now
        </button>
      )}
      {serverState?.last_error && (
        <div className="worker-error">⚠️ Last error: {serverState.last_error}</div>
      )}

      <details className="alerts-help">
        <summary>📖 Setup karne ka tareeka (one-time, ~2 minutes)</summary>
        <ol>
          <li>Telegram open karo, search <b>@BotFather</b>, "Start" karo</li>
          <li>Send <code>/newbot</code> → naam aur username choose karo</li>
          <li>BotFather <b>Bot Token</b> dega — yahan paste karo</li>
          <li>Apne naye bot ko search karke <b>Start</b> click karo (ek baar message bhejna zaroori hai)</li>
          <li>"Auto-detect Chat ID" button dabao OR @userinfobot se chat_id le aao</li>
          <li>"Save" click karo — backend mein store ho jaayega</li>
          <li>"Send Test Message" se verify karo</li>
        </ol>
      </details>

      <details className="alerts-help">
        <summary>👥 Multiple users ko alerts kaise bhejen?</summary>
        <p><b>Easiest way — Telegram Group (sabko ek saath):</b></p>
        <ol>
          <li>Telegram pe ek <b>group</b> create karo (e.g., "BTC Signals")</li>
          <li>Group mein apne bot ko add karo (Settings → Add Members → search bot username)</li>
          <li>Group ke saare members add karo</li>
          <li>Group ko ek message bhejo (e.g., "hello"). Yeh zaroori hai pehle baar.</li>
          <li>Dashboard pe <b>🔍 Auto-detect Chat ID</b> click karo — group ka ID dikhega
              (negative number like <code>-1001234567890</code>)</li>
          <li>Add it as the (only) chat ID → Save</li>
          <li>Bot ke saare messages group mein aayenge, sabhi members ko visible</li>
        </ol>
        <p><b>OR — Individual chat IDs (separate chats):</b></p>
        <ol>
          <li>Har user apne bot ko personally <b>Start</b> karega + message bhejega</li>
          <li>Tum auto-detect karke saare chat IDs collect karo</li>
          <li>Comma-separated list mein paste karo: <code>123, 456, -1001234</code></li>
          <li>Save — har message ko parallel mein sabko bheja jaayega</li>
        </ol>
        <p><b>Group ke fayde:</b> sabko ek saath dikhega, group chat ke saath discuss kar sakte ho.<br/>
        <b>Individual ke fayde:</b> private alerts, alag-alag log alag dekhenge.</p>
      </details>

      <div className="alerts-form">
        <label>
          <span>Bot Token {serverState?.has_token && <em className="muted small">(stored on server)</em>}</span>
          <input
            type="password"
            value={token}
            onChange={e => setToken(e.target.value)}
            placeholder={serverState?.has_token ? '••••••••• (re-enter to change)' : '123456:ABC-xyz...'}
          />
        </label>
        <label>
          <span>Chat IDs <em className="muted small">(comma-separated for multiple recipients)</em></span>
          <input
            type="text"
            value={chatIdsText}
            onChange={e => setChatIdsText(e.target.value)}
            placeholder="123456789, -1001234567890, 987654321"
          />
        </label>

        <label className="alerts-checkbox">
          <input
            type="checkbox"
            checked={enabled}
            onChange={e => setEnabled(e.target.checked)}
          />
          <span>Worker enabled (uncheck to pause without losing config)</span>
        </label>

        <div className="alerts-actions">
          <button className="alerts-test secondary" onClick={detectChatId} disabled={!token}>
            🔍 Auto-detect Chat ID
          </button>
          <button className="alerts-test secondary" onClick={sendTest}
                  disabled={parseChatIds().length === 0 || !token}>
            Send Test (all chats)
          </button>
          <button className="alerts-test" onClick={save}
                  disabled={saving || parseChatIds().length === 0}>
            {saving ? 'Saving…' : '💾 Save to Backend'}
          </button>
        </div>
        {detectStatus && <div className="alerts-status">{detectStatus}</div>}
        {detectedChats.length > 0 && (
          <div className="alerts-detected">
            {detectedChats.map(chat => (
              <button key={chat.id} type="button" className="alerts-detected-row"
                      onClick={() => {
                        const cur = parseChatIds()
                        const id = String(chat.id)
                        if (!cur.includes(id)) {
                          setChatIdsText(cur.length ? `${chatIdsText.replace(/,\s*$/, '')}, ${id}` : id)
                          setDetectStatus(`✅ Added ${id}`)
                        } else {
                          setDetectStatus(`already in list: ${id}`)
                        }
                      }}>
                <code>{chat.id}</code>
                <span className="muted">
                  {chat.type}{chat.name && ` — ${chat.name}`}
                </span>
              </button>
            ))}
          </div>
        )}
        {testStatus && <div className="alerts-status">{testStatus}</div>}
      </div>

      <div className="alerts-subs">
        <div className="alerts-subs-head">
          <span className="title">Watch Coins</span>
          <span className="muted">{watchSymbols.length} selected</span>
        </div>
        {/* Chips for the current watchlist. Auto-trade target chip is locked
            so the user can't accidentally drop the coin their money is on. */}
        <div className="watch-chips">
          {watchSymbols.map(sym => {
            const locked = sym === serverState?.symbol
            const label = sym.endsWith('USDT') ? `${sym.slice(0, -4)}/USDT` : sym
            return (
              <span key={sym} className={`watch-chip ${locked ? 'locked' : ''}`}>
                {label}
                {locked
                  ? <span className="chip-lock" title="Auto-trade target — can't remove">🔒</span>
                  : (
                    <button
                      className="chip-x"
                      onClick={() => setWatchSymbols(watchSymbols.filter(s => s !== sym))}
                      title="Remove from watchlist"
                    >×</button>
                  )}
              </span>
            )
          })}
        </div>
        <div className="watch-add">
          <SymbolPicker
            value=""
            placeholder="+ Add coin (search any Binance USDT pair)"
            size="compact"
            onChange={sym => {
              if (sym && !watchSymbols.includes(sym)) {
                setWatchSymbols([...watchSymbols, sym])
              }
            }}
          />
        </div>
        <div className="muted small" style={{ marginBottom: 16, lineHeight: 1.4 }}>
          Worker har coin pe har subscribed strategy fire karega. Signals + Telegram + DB.
          Auto-trade sirf <b>{serverState?.symbol || 'BTCUSDT'}</b> pe chalega (single position).
        </div>

        <div className="alerts-subs-head">
          <span className="title">Subscribed Strategies</span>
          <span className="muted">{subs.length} / {strategies.length}</span>
        </div>
        <div className="alerts-subs-actions">
          <button onClick={subAll}>Select All</button>
          <button onClick={subNone}>Clear All</button>
          <button className="primary" onClick={save}
                  disabled={saving || parseChatIds().length === 0}>
            {saving ? '…' : '💾 Save'}
          </button>
        </div>
        <div className="alerts-subs-list">
          {strategies.map(s => {
            const on = subIds.has(s.id)
            const sub = subs.find(x => x.strategy_id === s.id)
            const excludedCount = (sub?.excluded || []).length
            return (
              <div key={s.id} className={`alerts-sub-row ${on ? 'on' : ''}`}>
                <label className="asr-head">
                  <input type="checkbox" checked={on} onChange={() => toggle(s.id)} />
                  <span className="alerts-sub-name">{s.name}</span>
                  {on && excludedCount > 0 && (
                    <span className="asr-excl-count muted small">
                      −{excludedCount} coin{excludedCount === 1 ? '' : 's'}
                    </span>
                  )}
                </label>
                {on && watchSymbols.length > 0 && (
                  <div className="asr-coins">
                    <span className="asr-coins-label muted small">Coins:</span>
                    {watchSymbols.map(sym => {
                      const off = isExcluded(s.id, sym)
                      const label = sym.endsWith('USDT') ? sym.slice(0, -4) : sym
                      return (
                        <button
                          key={sym}
                          type="button"
                          className={`asr-coin ${off ? 'off' : 'on'}`}
                          onClick={() => toggleExclusion(s.id, sym)}
                          title={off
                            ? `Click to enable ${s.name} on ${sym}`
                            : `Click to silence ${s.name} on ${sym}`}
                        >
                          {label}
                        </button>
                      )
                    })}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {serverState?.subscriptions?.length > 0 && snapshot && (
        <div className="alerts-debug">
          <div className="alerts-debug-title">🔍 Server-side state</div>
          <div className="alerts-debug-list">
            {serverState.subscriptions.map(sub => {
              const lastSeen = serverState.last_seen?.[sub.strategy_id] || 0
              const row = snapshot.strategies?.find(r => r.id === sub.strategy_id)
              return (
                <div key={sub.strategy_id} className="alerts-debug-row">
                  <div className="adr-name">{row?.name || sub.strategy_id}</div>
                  <div className="adr-meta muted">
                    last sent: <b>{lastSeen ? timeAgo(lastSeen) : 'never'}</b>
                    {row?.last_signal_time && (
                      <> · last signal: <b>{timeAgo(row.last_signal_time)}</b></>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      <AutoTradePanel
        strategies={strategies}
        serverState={serverState}
        onConfigChange={() => {
          getAlertsConfig().then(setServerState).catch(() => {})
        }}
      />

      <div className="alerts-foot muted small">
        ✅ <b>Always-on:</b> notifications backend se aate hain. Browser band ya tab change kuch farak nahi padta.
        Server every 60s polls every subscribed strategy.
      </div>
    </div>
  )
}

export default memo(AlertsTab)
