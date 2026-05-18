// Coin picker with typeahead. Hits /api/market/symbols/search every keystroke
// (debounced lightly). Empty query returns the top USDT pairs by 24h volume,
// so the picker is useful without typing.
import { useEffect, useMemo, useRef, useState } from 'react'
import { searchSymbols } from '../api.js'

function humanVol(v) {
  if (!v) return ''
  if (v >= 1e9) return `${(v / 1e9).toFixed(1)}B`
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`
  if (v >= 1e3) return `${(v / 1e3).toFixed(1)}K`
  return v.toFixed(0)
}

export default function SymbolPicker({
  value,
  onChange,
  placeholder = 'Search coin (e.g. BTC, PEPE, LINK)',
  size = 'normal',  // 'normal' or 'compact' (for inline use in AlertsTab add row)
}) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [highlight, setHighlight] = useState(0)
  const inputRef = useRef(null)
  const wrapRef = useRef(null)

  // Fetch as the user types. Tiny 120ms debounce so typing "BTCUSDT" fast
  // doesn't fire 7 requests.
  useEffect(() => {
    if (!open) return
    let cancelled = false
    setLoading(true)
    const t = setTimeout(async () => {
      try {
        const data = await searchSymbols({ q: query, limit: 30 })
        if (!cancelled) {
          setResults(data.pairs || [])
          setHighlight(0)
        }
      } catch {
        if (!cancelled) setResults([])
      } finally {
        if (!cancelled) setLoading(false)
      }
    }, 120)
    return () => { cancelled = true; clearTimeout(t) }
  }, [query, open])

  // Close the dropdown when the user clicks anywhere outside the picker.
  useEffect(() => {
    if (!open) return
    const onDocClick = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [open])

  const choose = (sym) => {
    onChange(sym)
    setQuery('')
    setOpen(false)
    inputRef.current?.blur()
  }

  const onKey = (e) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setHighlight(h => Math.min(h + 1, results.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setHighlight(h => Math.max(h - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (results[highlight]) choose(results[highlight].symbol)
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  const displayValue = useMemo(() => {
    if (open) return query
    // Show the friendly base/USDT label when collapsed if we know it.
    if (!value) return ''
    return value.endsWith('USDT') ? `${value.slice(0, -4)}/USDT` : value
  }, [open, query, value])

  return (
    <div ref={wrapRef} className={`symbol-picker size-${size}`}>
      <input
        ref={inputRef}
        type="text"
        className="sp-input"
        value={displayValue}
        placeholder={placeholder}
        onFocus={() => setOpen(true)}
        onChange={e => { setQuery(e.target.value); setOpen(true) }}
        onKeyDown={onKey}
      />
      {open && (
        <ul className="sp-results">
          {loading && results.length === 0 && (
            <li className="sp-empty muted">Searching…</li>
          )}
          {!loading && results.length === 0 && (
            <li className="sp-empty muted">No matches.</li>
          )}
          {results.map((p, i) => (
            <li
              key={p.symbol}
              className={`sp-row ${i === highlight ? 'highlight' : ''} ${p.symbol === value ? 'selected' : ''}`}
              onMouseDown={() => choose(p.symbol)}
              onMouseEnter={() => setHighlight(i)}
            >
              <span className="sp-label">{p.label}</span>
              <span className="sp-vol muted">vol {humanVol(p.volume_24h)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
