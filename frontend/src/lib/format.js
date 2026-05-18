// Shared number formatters. Adaptive precision: BTC at $77,000 only needs
// two decimals, but DOGE at $0.10579 needs four to be useful and SHIB at
// $0.00000789 needs eight. The previous hard-coded 2-decimal default
// rendered three different prices as $0.10, $0.10, $0.11 -- unusable.

export function fmtPrice(n, fixed) {
  if (n == null || Number.isNaN(n)) return '—'
  let d = fixed
  if (d === undefined) {
    const abs = Math.abs(n)
    if (abs >= 1) d = 2
    else if (abs >= 0.01) d = 4
    else if (abs >= 0.0001) d = 6
    else d = 8
  }
  return Number(n).toLocaleString(undefined, {
    minimumFractionDigits: d,
    maximumFractionDigits: d,
  })
}

export function fmtPct(n, d = 2) {
  if (n == null || Number.isNaN(n)) return '—'
  const sign = n >= 0 ? '+' : ''
  return `${sign}${n.toFixed(d)}%`
}
