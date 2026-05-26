// Cloudflare Worker proxy for Binance USDT-M Futures (fapi.binance.com).
//
// WHY: Binance Futures geo-blocks Railway / GCP / most PaaS IPs with HTTP
// 451. Cloudflare Workers run on edge IPs that Binance does NOT block, so
// fronting fapi with a Worker is the cheapest way to get Futures data into
// a Railway-deployed app. Free tier (100k requests/day) is plenty -- the
// app's price-cache fires once per 10s = ~8.6k req/day even at peak.
//
// DEPLOY (5 minutes):
//   1. Sign in at https://dash.cloudflare.com → Workers & Pages → Create
//   2. Paste this file's contents → Save and Deploy
//   3. Copy the *.workers.dev URL (e.g. fapi-proxy.<you>.workers.dev)
//   4. On Railway → Variables, add:
//        BINANCE_FUTURES_REST=https://<your-worker>.workers.dev
//        BINANCE_MARKET=futures
//   5. Redeploy. The "FUTURES" badge will go live in the header.
//
// SECURITY: This proxy only forwards GET requests to /fapi/v1/* (read-only
// data endpoints). Trading endpoints stay blocked even if someone discovers
// the worker URL -- no auth-bearing path is reachable.

const ALLOWED_PREFIX = '/fapi/v1/'
const UPSTREAM = 'https://fapi.binance.com'

export default {
  async fetch(request) {
    const url = new URL(request.url)

    // Hard gate: only allow read-only data-api paths. Trading endpoints
    // (positionMode, leverage, order, batchOrders, etc.) are not on
    // /fapi/v1/ as a class, but explicitly listing the path prefix here
    // means anything not under /fapi/v1/ is 404'd regardless.
    if (!url.pathname.startsWith(ALLOWED_PREFIX)) {
      return new Response('not found', { status: 404 })
    }

    // Allow only GET. POST/PUT/DELETE are how authenticated trading
    // operations move -- block them at the edge so we never even forward
    // a malicious signed request.
    if (request.method !== 'GET') {
      return new Response('method not allowed', { status: 405 })
    }

    const upstreamUrl = `${UPSTREAM}${url.pathname}${url.search}`
    const res = await fetch(upstreamUrl, {
      method: 'GET',
      headers: { 'User-Agent': 'btc-app-cf-proxy/1.0' },
      cf: { cacheTtl: 5, cacheEverything: false },
    })

    // Pass-through with permissive CORS so the same worker can also serve
    // the frontend directly if you ever skip the FastAPI backend.
    const headers = new Headers(res.headers)
    headers.set('access-control-allow-origin', '*')
    headers.set('cache-control', 'public, max-age=5')
    return new Response(res.body, { status: res.status, headers })
  },
}
