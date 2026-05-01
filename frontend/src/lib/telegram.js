/** Fetch the most recent chats that have messaged the bot. Used by the
 *  Alerts tab to auto-detect the user's chat ID without needing
 *  @userinfobot. The user just sends any message to their bot, then
 *  clicks "Auto-detect Chat ID".
 *  Returns { ok, chats: [{ id, name, username, type }], description }.
 */
export async function getTelegramUpdates(token) {
  try {
    const url = `https://api.telegram.org/bot${token}/getUpdates`
    const res = await fetch(url)
    const data = await res.json()
    if (!data.ok) {
      return { ok: false, chats: [], description: data.description || 'unknown' }
    }
    const seen = new Map()
    for (const u of data.result || []) {
      const msg = u.message || u.edited_message || u.channel_post || {}
      const chat = msg.chat || {}
      if (chat.id != null && !seen.has(chat.id)) {
        seen.set(chat.id, {
          id: chat.id,
          name: [chat.first_name, chat.last_name].filter(Boolean).join(' ') || chat.title || '',
          username: chat.username || '',
          type: chat.type || '',
        })
      }
    }
    return { ok: true, chats: Array.from(seen.values()), description: '' }
  } catch (e) {
    return { ok: false, chats: [], description: String(e) }
  }
}


/** Send a message to a Telegram chat directly from the browser.
 *  Telegram's Bot API allows CORS so no backend proxy is needed.
 *  Returns { ok: boolean, description: string }.
 */
export async function sendTelegram(token, chatId, text) {
  try {
    const url = `https://api.telegram.org/bot${token}/sendMessage`
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        chat_id: chatId,
        text,
        parse_mode: 'Markdown',
        disable_web_page_preview: true,
      }),
    })
    const data = await res.json()
    return { ok: !!data.ok, description: data.description || '' }
  } catch (e) {
    return { ok: false, description: String(e) }
  }
}

/** Format a strategy snapshot row into a clean Telegram message. */
export function formatSignalMessage(row, symbol) {
  const sign = row.signal === 'BUY' ? '🟢' : row.signal === 'SELL' ? '🔴' : '⏸'
  const action = row.signal === 'BUY' ? 'BUY (Khareedo)' :
                 row.signal === 'SELL' ? 'SELL (Becho)' : 'WAIT'
  const fmt = (n) => n == null ? '—' :
    Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  const pct = (n) => n == null ? '—' : (n >= 0 ? '+' : '') + n.toFixed(2) + '%'

  let lossPct = null, profitPct = null, rr = null
  if (row.entry && row.stop_loss && row.target) {
    const dir = row.signal === 'BUY' ? 1 : -1
    profitPct = dir * (row.target - row.entry) / row.entry * 100
    lossPct = dir * (row.stop_loss - row.entry) / row.entry * 100
    rr = Math.abs(profitPct / lossPct)
  }

  // Markdown-safe formatting (escape underscores in strategy names if any).
  const cleanName = (row.name || '').replace(/_/g, '\\_').replace(/\*/g, '\\*')

  return [
    `${sign} *${action}* — \`${symbol}\``,
    `*Strategy:* ${cleanName}`,
    '',
    row.entry  ? `*Entry:*  \`$${fmt(row.entry)}\`` : null,
    row.stop_loss ? `*Stop:*   \`$${fmt(row.stop_loss)}\` (${pct(lossPct)})` : null,
    row.target ? `*Target:* \`$${fmt(row.target)}\` (${pct(profitPct)})` : null,
    rr != null ? `*RR:* 1 : ${rr.toFixed(2)}` : null,
  ].filter(Boolean).join('\n')
}
