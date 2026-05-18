// Shared number formatters.
//
// fmtPrice picks decimals from the price's magnitude so the actual value
// is preserved instead of being rounded to a meaningless 2dp. Examples:
//   BTC  77083.142  ->  77,083.14   (2dp, default for >= 1000)
//   ETH  2117.4523  ->  2,117.45    (2dp)
//   SOL  170.4321   ->  170.43      (2dp)
//   DOGE 0.10579    ->  0.10579     (5dp -- 5 significant figures)
//   PEPE 0.0000123  ->  0.00001230  (8dp -- 5 sig figs past the leading zeros)
//   SHIB 0.00000789 ->  0.00000789  (8dp)
// User asked for the "actual price" on low-priced coins, so for sub-dollar
// values we extend decimals to keep ~5 significant digits.

const SIG_FIGS_FOR_SMALL = 5
const MAX_DECIMALS = 10

export function fmtPrice(n, fixed) {
  if (n == null || Number.isNaN(n)) return '—'
  let d = fixed
  if (d === undefined) {
    const abs = Math.abs(Number(n))
    if (abs === 0) {
      d = 2
    } else if (abs >= 1000) {
      d = 2
    } else if (abs >= 1) {
      d = 2
    } else {
      // For sub-dollar, count leading zeros after the decimal so we keep
      // SIG_FIGS_FOR_SMALL meaningful digits. log10(0.10579) ~= -0.98 ->
      // floor(-log10) = 0 leading zeros -> 0 + 5 = 5 decimals.
      const leadingZeros = Math.max(0, Math.floor(-Math.log10(abs)))
      d = Math.min(leadingZeros + SIG_FIGS_FOR_SMALL, MAX_DECIMALS)
    }
  }
  // For >= 1 prices we want a stable 2dp look (BTC 77,083.14 vs 77,083.1).
  // For sub-dollar we strip trailing zeros so PEPE shows 0.0000123 not
  // 0.000012300 -- the user asked for "the actual price" without padding.
  const stripTrailing = Math.abs(Number(n)) < 1
  return Number(n).toLocaleString(undefined, {
    minimumFractionDigits: stripTrailing ? 0 : d,
    maximumFractionDigits: d,
  })
}

export function fmtPct(n, d = 2) {
  if (n == null || Number.isNaN(n)) return '—'
  const sign = n >= 0 ? '+' : ''
  return `${sign}${n.toFixed(d)}%`
}

// Relative time -- "2d 23h ago" is much more honest than "2d ago" when the
// trade is actually 71 hours old. Granularity grows with the gap.
export function timeAgo(ts) {
  if (!ts) return ''
  const diff = Math.floor(Date.now() / 1000 - ts)
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) {
    const hrs = Math.floor(diff / 3600)
    const mins = Math.floor((diff % 3600) / 60)
    return mins > 0 ? `${hrs}h ${mins}m ago` : `${hrs}h ago`
  }
  const days = Math.floor(diff / 86400)
  const hrs = Math.floor((diff % 86400) / 3600)
  return hrs > 0 ? `${days}d ${hrs}h ago` : `${days}d ago`
}

// Absolute time in IST. Browser `toLocaleString()` falls back to the
// system locale which is often US ("5/15/2026, 7:30 PM"). The Indian
// reader expects "15 May 2026, 7:30 PM IST" -- explicit timezone +
// day-month-year ordering. Pinning to Asia/Kolkata also makes the
// label stable for users abroad.
export function fmtIST(ts) {
  if (!ts) return ''
  return new Date(ts * 1000).toLocaleString('en-IN', {
    timeZone: 'Asia/Kolkata',
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit', hour12: true,
  }) + ' IST'
}
