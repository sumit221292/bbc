import { useState } from 'react'

// Full-screen password gate. Only renders when the backend reports
// authenticated=false (i.e. ADMIN_PASSWORD is set and the user has no
// valid session cookie). Local-dev without ADMIN_PASSWORD bypasses
// this entire component.
export default function LoginScreen({ onSuccess }) {
  const [pw, setPw] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    if (busy || !pw) return
    setBusy(true)
    setErr('')
    try {
      const r = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ password: pw }),
      })
      if (r.status === 401) {
        setErr('Wrong password')
        setBusy(false)
        setPw('')
        return
      }
      if (!r.ok) {
        setErr(`Server error (HTTP ${r.status})`)
        setBusy(false)
        return
      }
      // Cookie is HttpOnly + same-origin -- browser stored it; tell the
      // parent we're in.
      onSuccess()
    } catch (e) {
      setErr('Connection error: ' + String(e.message || e))
      setBusy(false)
    }
  }

  return (
    <div className="login-screen">
      <form className="login-card" onSubmit={submit}>
        <div className="login-logo">₿</div>
        <div className="login-title">Crypto Trading Dashboard</div>
        <div className="login-sub muted">Enter the dashboard password</div>
        <input
          className="login-input"
          type="password"
          placeholder="Password"
          value={pw}
          autoFocus
          onChange={e => setPw(e.target.value)}
          disabled={busy}
        />
        {err && <div className="login-err">{err}</div>}
        <button className="login-submit" type="submit" disabled={busy || !pw}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
        <div className="login-foot muted small">
          Session lasts 30 days. Auto-trade controls + Telegram setup
          live behind this gate.
        </div>
      </form>
    </div>
  )
}
