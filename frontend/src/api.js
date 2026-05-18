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

export async function getAlertsConfig() {
  const r = await fetch(`${BASE}/api/alerts/config`)
  if (!r.ok) throw new Error(`alerts/config: ${r.status}`)
  return r.json()
}

export async function setAlertsConfig(payload) {
  const r = await fetch(`${BASE}/api/alerts/config`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!r.ok) throw new Error(`alerts/config: ${r.status}`)
  return r.json()
}

export async function sendBackendTest({ token, chat_id, chat_ids = [] }) {
  const r = await fetch(`${BASE}/api/alerts/test`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
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
    body: JSON.stringify({ api_key, api_secret }),
  })
  return r.json().catch(() => ({ ok: false, message: 'parse error' }))
}

export async function killAutoTrade() {
  const r = await fetch(`${BASE}/api/alerts/auto/kill`, { method: 'POST' })
  return r.json().catch(() => ({ ok: false }))
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

export async function clearTrades() {
  const r = await fetch(`${BASE}/api/trades`, { method: 'DELETE' })
  return r.json().catch(() => ({ ok: false }))
}

export async function searchSymbols({ q = '', limit = 20 } = {}) {
  const params = new URLSearchParams()
  if (q) params.set('q', q)
  params.set('limit', String(limit))
  const r = await fetch(`${BASE}/api/market/symbols/search?${params.toString()}`)
  if (!r.ok) throw new Error(`symbols/search: ${r.status}`)
  return r.json()
}
