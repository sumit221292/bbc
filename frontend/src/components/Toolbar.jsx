import { memo } from 'react'

const INTERVALS = ['1m', '5m', '15m', '1h', '4h', '1d']
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
}) {
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
    </div>
  )
}

export default memo(Toolbar)
