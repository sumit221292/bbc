// TradingView Advanced Chart Widget wrapper.
// Uses the embed URL form because it sidesteps the X-Frame-Options that
// blocks the personal /chart/<id>/ pages -- the widget host explicitly
// allows iframing.
import { memo, useMemo } from 'react'

// Our internal interval -> TradingView interval string.
const TV_INTERVAL = {
  '1m': '1', '5m': '5', '15m': '15',
  '1h': '60', '4h': '240',
  '1d': 'D', '1w': 'W',
}

function tvSymbol(symbol) {
  // Binance pairs are how we identify everything on the backend, so prefix
  // BINANCE: -- TradingView resolves these directly.
  return `BINANCE:${symbol}`
}

// User's personal saved chart layout. Cannot be iframed (TradingView blocks
// it via CSP), but a normal new-tab link works fine.
const PERSONAL_CHART_URL =
  'https://in.tradingview.com/chart/j9RDfUl2/?symbol=BITSTAMP:BTCUSD'

function TradingViewChart({ symbol = 'BTCUSDT', interval = '1h' }) {
  // Memoize so the iframe doesn't reload on every parent re-render -- only
  // when symbol/interval actually changes.
  const src = useMemo(() => {
    const params = new URLSearchParams({
      symbol: tvSymbol(symbol),
      interval: TV_INTERVAL[interval] || '60',
      theme: 'dark',
      style: '1',           // candlesticks
      locale: 'en',
      hide_side_toolbar: '0',
      allow_symbol_change: '1',
      save_image: '0',
      hide_volume: '0',
      withdateranges: '1',
      details: '1',
      timezone: 'Etc/UTC',
    })
    return `https://s.tradingview.com/widgetembed/?${params.toString()}`
  }, [symbol, interval])

  return (
    <div className="tv-chart">
      <div className="tv-chart-bar">
        <span className="tv-chart-label">TradingView · {symbol} · {interval}</span>
        <a
          className="tv-chart-link"
          href={PERSONAL_CHART_URL}
          target="_blank"
          rel="noopener noreferrer"
          title="Apna personal saved chart layout naye tab mein khole (j9RDfUl2)"
        >
          Open my saved chart ↗
        </a>
      </div>
      <iframe
        key={src}
        title={`TradingView ${symbol} ${interval}`}
        src={src}
        className="tv-chart-iframe"
        allow="fullscreen"
        loading="lazy"
      />
    </div>
  )
}

export default memo(TradingViewChart)
