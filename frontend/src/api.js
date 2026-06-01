// Tiny fetch wrapper. The Vite dev proxy forwards /api → backend on :8000.

const BASE = ''

export async function getKlines({ symbol = 'BTCUSDT', interval = '1m', limit = 500 } = {}) {
  const r = await fetch(`${BASE}/api/market/klines?symbol=${symbol}&interval=${interval}&limit=${limit}`)
  if (!r.ok) throw new Error(`klines: ${r.status}`)
  return r.json()
}

export async function getIndicators({ symbol = 'BTCUSDT', interval = '1m', limit = 500 } = {}) {
  const r = await fetch(`${BASE}/api/market/indicators?symbol=${symbol}&interval=${interval}&limit=${limit}`)
  if (!r.ok) throw new Error(`indicators: ${r.status}`)
  return r.json()
}

export async function getStrategies() {
  const r = await fetch(`${BASE}/api/strategy/list`)
  if (!r.ok) throw new Error(`strategy/list: ${r.status}`)
  return r.json()
}

export async function runStrategy({ id, symbol = 'BTCUSDT', interval = '1m', limit = 500 }) {
  const r = await fetch(`${BASE}/api/strategy/run?id=${id}&symbol=${symbol}&interval=${interval}&limit=${limit}`)
  if (!r.ok) throw new Error(`strategy/run: ${r.status}`)
  return r.json()
}

export async function getOutlook(symbol = 'BTCUSDT') {
  const r = await fetch(`${BASE}/api/outlook?symbol=${symbol}`)
  if (!r.ok) throw new Error(`outlook: ${r.status}`)
  return r.json()
}

export async function getStrategySnapshot(symbol = 'BTCUSDT', interval = '1h') {
  const r = await fetch(`${BASE}/api/strategy/snapshot?symbol=${symbol}&interval=${interval}`)
  if (!r.ok) throw new Error(`snapshot: ${r.status}`)
  return r.json()
}

export async function getLeaderboard(symbol = 'BTCUSDT') {
  const r = await fetch(`${BASE}/api/strategy/leaderboard?symbol=${symbol}`)
  if (!r.ok) throw new Error(`leaderboard: ${r.status}`)
  return r.json()
}

// All alert/auto-trade endpoints sit behind require_auth on the
// backend. credentials:'include' makes the browser send the session
// cookie so the protected routes accept the request.

export async function getAlertsConfig() {
  const r = await fetch(`${BASE}/api/alerts/config`, { credentials: 'include' })
  if (!r.ok) throw new Error(`alerts/config: ${r.status}`)
  return r.json()
}

export async function setAlertsConfig(payload) {
  const r = await fetch(`${BASE}/api/alerts/config`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(payload),
  })
  if (!r.ok) throw new Error(`alerts/config: ${r.status}`)
  return r.json()
}

export async function sendBackendTest({ token, chat_id, chat_ids = [] }) {
  const r = await fetch(`${BASE}/api/alerts/test`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ token, chat_id, chat_ids }),
  })
  const data = await r.json().catch(() => ({}))
  if (!r.ok) return { ok: false, description: data.detail || `HTTP ${r.status}` }
  return { ok: true, summary: data.summary, targets: data.targets }
}

export async function setAutoTrade(payload) {
  const r = await fetch(`${BASE}/api/alerts/auto`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(payload),
  })
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`)
  return data
}

export async function testBinanceCredentials({ api_key, api_secret }) {
  const r = await fetch(`${BASE}/api/alerts/auto/test`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ api_key, api_secret }),
  })
  return r.json().catch(() => ({ ok: false, message: 'parse error' }))
}

export async function killAutoTrade() {
  const r = await fetch(`${BASE}/api/alerts/auto/kill`, {
    method: 'POST',
    credentials: 'include',
  })
  return r.json().catch(() => ({ ok: false }))
}

// --- Auth helpers ---

export async function getAuthStatus() {
  const r = await fetch(`${BASE}/api/auth/status`, { credentials: 'include' })
  if (!r.ok) throw new Error(`auth/status: ${r.status}`)
  return r.json()  // { authenticated: bool, auth_disabled: bool }
}

export async function logout() {
  await fetch(`${BASE}/api/auth/logout`, {
    method: 'POST',
    credentials: 'include',
  })
}

export async function getTrades({ strategy, interval, symbol, limit = 200 } = {}) {
  const params = new URLSearchParams()
  if (strategy) params.set('strategy', strategy)
  if (interval) params.set('interval', interval)
  if (symbol) params.set('symbol', symbol)
  params.set('limit', String(limit))
  const r = await fetch(`${BASE}/api/trades?${params.toString()}`)
  if (!r.ok) throw new Error(`trades: ${r.status}`)
  return r.json()
}

// clearTrades() removed -- the backend DELETE /api/trades endpoint was
// also removed so trade history cannot be wiped over HTTP. Use the
// Railway volume directly if a manual reset is ever required.

// window: '7d' / '15d' / '30d' / 'all' (default). The Matrix tab uses
// this to flip between weekly / 15-day / monthly / all-time views.
export async function getTradeStatsByPair({ window = 'all' } = {}) {
  const r = await fetch(`${BASE}/api/trades/stats-by-pair?window=${encodeURIComponent(window)}`)
  if (!r.ok) throw new Error(`stats-by-pair: ${r.status}`)
  return r.json()
}

// Which Binance market the backend is currently reading from (spot /
// futures). Drives the header badge so the user knows which price
// feed they're looking at.
export async function getMarketInfo() {
  const r = await fetch(`${BASE}/api/market/info`)
  if (!r.ok) throw new Error(`market/info: ${r.status}`)
  return r.json()
}

// Live trade prices for the OPEN-row PnL badge. Pass an array of
// symbols to keep the response small; omit to get every USDT pair.
// Backend caches 10s so polling every 15s costs Binance ~0 weight.
export async function getLivePrices(symbols = []) {
  const qs = symbols.length ? `?symbols=${symbols.join(',')}` : ''
  const r = await fetch(`${BASE}/api/market/prices${qs}`)
  if (!r.ok) throw new Error(`prices: ${r.status}`)
  return r.json()
}

export async function searchSymbols({ q = '', limit = 20 } = {}) {
  const params = new URLSearchParams()
  if (q) params.set('q', q)
  params.set('limit', String(limit))
  const r = await fetch(`${BASE}/api/market/symbols/search?${params.toString()}`)
  if (!r.ok) throw new Error(`symbols/search: ${r.status}`)
  return r.json()
}
