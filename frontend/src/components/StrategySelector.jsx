import { memo } from 'react'

// Group strategies into logical categories with Hinglish hints.
const CATEGORIES = [
  {
    label: '🌟 Recommended (Multi-Timeframe — sabse smart)',
    ids: ['mtf_chop_aware', 'mtf_strict', 'mtf_2screen', 'mtf_chop_only'],
  },
  {
    label: '⚡ Selective (kam trade, high quality)',
    ids: ['best'],
  },
  {
    label: '🧠 Smart Money (ICT/SMC concepts — 5m/15m)',
    ids: ['smc_mtf', 'smc_momentum'],
  },
  {
    label: '📈 Trend Following (jab trend strong ho)',
    ids: ['trend_following', 'day_trading', 'adx_trend', 'macd', 'supertrend', 'ichimoku'],
  },
  {
    label: '🔁 Mean Reversion (sideways/range market)',
    ids: ['bollinger', 'stochastic', 'swing', 'scalping'],
  },
  {
    label: '🚀 Breakout (consolidation tootne pe)',
    ids: ['breakout', 'donchian'],
  },
]

function StrategySelector({ strategies, selected, onSelect }) {
  const byId = Object.fromEntries(strategies.map(s => [s.id, s]))
  const selectedMeta = byId[selected]

  return (
    <div className="strategy-selector">
      <div className="ss-row">
        <label className="ss-label">Strategy</label>
        <select
          className="ss-dropdown"
          value={selected}
          onChange={e => onSelect(e.target.value)}
        >
          {CATEGORIES.map(cat => (
            <optgroup key={cat.label} label={cat.label}>
              {cat.ids.filter(id => byId[id]).map(id => (
                <option key={id} value={id}>{byId[id].name}</option>
              ))}
            </optgroup>
          ))}
        </select>
      </div>
      {selectedMeta && (
        <div className="ss-desc">{selectedMeta.description}</div>
      )}
    </div>
  )
}

export default memo(StrategySelector)
