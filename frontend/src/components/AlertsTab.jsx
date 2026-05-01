import { memo, useState } from 'react'
import { sendTelegram } from '../lib/telegram.js'

/** UI for setting up Telegram bot credentials and selecting which
 *  strategies should fire push notifications. */
function AlertsTab({ strategies, token, setToken, chatId, setChatId, subs, setSubs }) {
  const [testStatus, setTestStatus] = useState('')
  const [testing, setTesting] = useState(false)

  const toggle = (id) => {
    if (subs.includes(id)) {
      setSubs(subs.filter(s => s !== id))
    } else {
      setSubs([...subs, id])
      // Mark current time as last-seen so we don't notify for past signals.
      const now = Math.floor(Date.now() / 1000)
      localStorage.setItem(`btc.tg.lastSignal.${id}`, String(now))
    }
  }

  const subAll = () => {
    setSubs(strategies.map(s => s.id))
    const now = Math.floor(Date.now() / 1000)
    for (const s of strategies) {
      localStorage.setItem(`btc.tg.lastSignal.${s.id}`, String(now))
    }
  }
  const subNone = () => setSubs([])

  const sendTest = async () => {
    if (!token || !chatId) return
    setTesting(true)
    setTestStatus('Sending…')
    const res = await sendTelegram(token, chatId,
      '✅ *Test message* from Crypto Trading Dashboard\n\n' +
      'Notifications setup OK! Tum jab koi strategy subscribe karoge, ' +
      'naye signals automatically yahan aate rahenge.')
    setTesting(false)
    if (res.ok) setTestStatus('✅ Sent! Telegram pe check karo.')
    else setTestStatus('❌ Failed: ' + res.description)
  }

  return (
    <div className="alerts-tab">
      <div className="panel-section-title">🔔 Telegram Alerts</div>

      <details className="alerts-help">
        <summary>📖 Setup karne ka tareeka (one-time, ~2 minutes)</summary>
        <ol>
          <li>Telegram open karo, search <b>@BotFather</b>, "Start" karo</li>
          <li>Send <code>/newbot</code> → naam aur username choose karo</li>
          <li>BotFather ek <b>Bot Token</b> dega (looks like <code>123456:ABC-xyz...</code>) — yahan paste karo</li>
          <li>Apne naye bot ko search karo (jo username diya tha) aur <b>Start</b> click karo (ek baar message bhejna zaroori hai)</li>
          <li>Telegram pe search <b>@userinfobot</b>, Start karo, woh tumhara <b>Chat ID</b> dega — yahan paste karo</li>
          <li>"Send Test Message" click karke verify karo</li>
        </ol>
      </details>

      <div className="alerts-form">
        <label>
          <span>Bot Token</span>
          <input
            type="password"
            value={token}
            onChange={e => setToken(e.target.value)}
            placeholder="123456:ABC-xyz-your-bot-token"
          />
        </label>
        <label>
          <span>Chat ID</span>
          <input
            type="text"
            value={chatId}
            onChange={e => setChatId(e.target.value)}
            placeholder="123456789"
          />
        </label>
        <div className="alerts-actions">
          <button
            className="alerts-test"
            onClick={sendTest}
            disabled={!token || !chatId || testing}
          >
            {testing ? 'Sending…' : 'Send Test Message'}
          </button>
          {testStatus && <span className="alerts-status">{testStatus}</span>}
        </div>
      </div>

      <div className="alerts-subs">
        <div className="alerts-subs-head">
          <span className="title">Subscribed Strategies</span>
          <span className="muted">{subs.length} / {strategies.length} selected</span>
        </div>
        <div className="alerts-subs-actions">
          <button onClick={subAll}>Select All</button>
          <button onClick={subNone}>Clear All</button>
        </div>
        <div className="alerts-subs-list">
          {strategies.map(s => (
            <label key={s.id} className={`alerts-sub-row ${subs.includes(s.id) ? 'on' : ''}`}>
              <input
                type="checkbox"
                checked={subs.includes(s.id)}
                onChange={() => toggle(s.id)}
              />
              <span className="alerts-sub-name">{s.name}</span>
            </label>
          ))}
        </div>
      </div>

      <div className="alerts-foot muted small">
        💡 <b>Note:</b> Yeh notifications browser tab ke khulne par hi work karte hain.
        Tab band karne pe alerts ruk jaate hain. Always-on alerts ke liye backend
        worker chahiye — agar zarurat ho to bolo.
      </div>
    </div>
  )
}

export default memo(AlertsTab)
