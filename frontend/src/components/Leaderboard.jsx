import { memo } from 'react'

function pct(n) {
  if (n == null) return '—'
  const sign = n >= 0 ? '+' : ''
  return `${sign}${n.toFixed(2)}%`
}

function windowLabel(h) {
  if (h === 1) return 'Last 1 Hour'
  if (h < 24) return `Last ${h} Hours`
  return `Last 24 Hours`
}

const RANK_EMOJI = ['🥇', '🥈', '🥉']

function Leaderboard({ data }) {
  if (!data) {
    return (
      <div className="leaderboard">
        <div className="lb-header">
          <span className="title">🏆 Best Performers — Rolling Windows</span>
          <span className="muted">Loading… (5–10 seconds)</span>
        </div>
      </div>
    )
  }

  const { leaderboards } = data

  return (
    <div className="leaderboard">
      <div className="lb-header">
        <span className="title">🏆 Best Performers — Live Trades (DB)</span>
        <span className="muted">worker-fired only</span>
      </div>

      <div className="lb-note">
        Har time window mein <b>top 3 (strategy, timeframe)</b> combos jinhone live data pe sabse zyada profit kiya.
        Sirf actually-fired trades count hote hain — pehle 1-2 din kam dikhega, fir build-up.
      </div>

      {leaderboards.map(lb => (
        <div key={lb.window_hours} className="lb-window">
          <div className="lb-window-head">
            <span className="lb-window-title">{windowLabel(lb.window_hours)}</span>
            {!lb.any_traded && <span className="muted small">koi trade nahi hua</span>}
          </div>

          {lb.top.length === 0 ? (
            <div className="lb-empty">No strategy fired in this window.</div>
          ) : (
            <div className="lb-rows">
              {lb.top.map((row, idx) => (
                <div key={`${row.strategy_id}-${row.timeframe}`} className={`lb-row rank-${idx}`}>
                  <span className="lb-rank">{RANK_EMOJI[idx]}</span>
                  <div className="lb-name-col">
                    <div className="lb-name">{row.strategy_name}</div>
                    <div className="lb-meta">
                      <span className="lb-tf">{row.timeframe}</span>
                      <span className="muted">·</span>
                      <span className="muted">{row.trades}T · {row.wins}W / {row.losses}L</span>
                    </div>
                  </div>
                  <div className="lb-stats">
                    <div className={`lb-pnl ${row.total_pnl_pct >= 0 ? 'pos' : 'neg'}`}>
                      {pct(row.total_pnl_pct)}
                    </div>
                    <div className="lb-win muted">{row.win_rate.toFixed(0)}% win</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}

      <div className="lb-footnote muted small">
        💡 <b>Note:</b> Numbers DB se aate hain — sirf vahi trades count hote hain jo worker ne fire ki aur jo close ho chuke hain.
        Pehle 1-2 din mein zyadatar windows empty rahenge; build-up ke baad numbers reliable hote jaate hain.
      </div>
    </div>
  )
}

export default memo(Leaderboard)
