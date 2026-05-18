import { memo } from 'react'

// Restricted to 1h+ -- lower TFs are too noisy for the strategy suite,
// and the worker stores all live trades at 1h/4h/1d partitions.
const INTERVALS = ['1h', '4h', '1d']
// Binance is crypto-only — XAUUSDT (spot gold) doesn't exist there.
// PAXGUSDT (Pax Gold, a 1:1 gold-backed token) tracks gold price tick-for-tick
// and is the proper way to chart "gold" through Binance.
const SYMBOLS = [
  ['BTCUSDT', 'BTC/USDT'],
  ['ETHUSDT', 'ETH/USDT'],
  ['SOLUSDT', 'SOL/USDT'],
  ['BNBUSDT', 'BNB/USDT'],
  ['XRPUSDT', 'XRP/USDT'],
  ['DOGEUSDT', 'DOGE/USDT'],
  ['ADAUSDT', 'ADA/USDT'],
  ['PAXGUSDT', 'PAXG/USDT (Gold)'],
]

function Toolbar({
  symbol, onSymbolChange,
  interval, onIntervalChange,
  drawMode, onDrawModeChange,
  onClearDrawings,
  chartMode, onChartModeChange,
  chartVisible, onChartVisibleChange,
}) {
  const tvActive = chartMode === 'tradingview'
  return (
    <div className="toolbar">
      <div className="group">
        <label>Coin</label>
        <select value={symbol} onChange={e => onSymbolChange(e.target.value)}>
          {SYMBOLS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </div>
      <div className="group">
        <label>Time</label>
        <div className="seg">
          {INTERVALS.map(i => (
            <button key={i} className={interval === i ? 'on' : ''} onClick={() => onIntervalChange(i)}>{i}</button>
          ))}
        </div>
      </div>
      <div className="group">
        <label>Chart</label>
        <div className="seg">
          <button
            className={!tvActive ? 'on' : ''}
            onClick={() => onChartModeChange('native')}
            title="Apna chart with strategy markers + SL/TP lines"
          >Our</button>
          <button
            className={tvActive ? 'on' : ''}
            onClick={() => onChartModeChange('tradingview')}
            title="TradingView widget — full indicator suite, no signal overlay"
          >TradingView</button>
        </div>
      </div>
      <div className="group">
        <label>View</label>
        <button
          className={`view-toggle ${chartVisible ? '' : 'collapsed'}`}
          onClick={() => onChartVisibleChange(!chartVisible)}
          title={chartVisible
            ? 'Hide chart — focus only on the signal sidebar'
            : 'Show chart again'
          }
        >
          {chartVisible ? '⤢ Hide Chart' : '⤡ Show Chart'}
        </button>
      </div>
      {/* Drawing tools only make sense for the native chart. Hide when on
          TradingView mode so the user is not confused by inert buttons. */}
      {!tvActive && (
        <div className="group">
          <label>Draw Tool</label>
          <div className="seg">
            {[
              ['none', 'Band'],
              ['trend', 'Line'],
              ['hline', 'Hor.'],
              ['free', 'Free'],
            ].map(([m, label]) => (
              <button key={m} className={drawMode === m ? 'on' : ''} onClick={() => onDrawModeChange(m)}>{label}</button>
            ))}
            <button onClick={onClearDrawings}>Saaf</button>
          </div>
        </div>
      )}
    </div>
  )
}

export default memo(Toolbar)
