import { memo } from 'react'
import SymbolPicker from './SymbolPicker.jsx'

// Restricted to 1h+ -- lower TFs are too noisy for the strategy suite,
// and the worker stores all live trades at 1h/4h/1d partitions.
const INTERVALS = ['1h', '4h', '1d']

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
        <SymbolPicker value={symbol} onChange={onSymbolChange} />
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
