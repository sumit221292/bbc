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

export async function getStrategySnapshot(symbol = 'BTCUSDT') {
  const r = await fetch(`${BASE}/api/strategy/snapshot?symbol=${symbol}`)
  if (!r.ok) throw new Error(`snapshot: ${r.status}`)
  return r.json()
}

export async function getLeaderboard(symbol = 'BTCUSDT') {
  const r = await fetch(`${BASE}/api/strategy/leaderboard?symbol=${symbol}`)
  if (!r.ok) throw new Error(`leaderboard: ${r.status}`)
  return r.json()
}
