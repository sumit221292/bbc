import { useEffect, useImperativeHandle, useRef, forwardRef } from 'react'
import { createChart, CrosshairMode, LineStyle } from 'lightweight-charts'

/**
 * Chart owns the lightweight-charts instance and a thin drawing-tools layer
 * implemented as a transparent <canvas> on top.
 *
 * Imperative API (via ref):
 *   setCandles(candles)
 *   updateCandle(candle)         — for live tick updates
 *   setEmas({ ema20, ema50, ema200, time })
 *   setVolume(candles)
 *   setMarkers(signals)
 *   setLevels({ entry, stop, target })
 *   setDrawingMode(mode)         — 'none' | 'trend' | 'hline' | 'free'
 *   clearDrawings()
 */
const Chart = forwardRef(function Chart(_, ref) {
  const containerRef = useRef(null)
  const chartRef = useRef(null)
  const candleRef = useRef(null)
  const volRef = useRef(null)
  const emaRefs = useRef({ ema20: null, ema50: null, ema200: null })
  const levelLinesRef = useRef([])
  // Tracks the time range of the currently loaded candle data so that
  // markers from a different-TF strategy (e.g. MTF on 1h while chart shows
  // 1m) don't pile up at the chart edge.
  const candleRangeRef = useRef({ start: 0, end: 0 })

  // Drawing state
  const overlayRef = useRef(null)
  const drawModeRef = useRef('none')
  const drawingsRef = useRef([])           // { type, points: [{time, price}, ...] }
  const draftRef = useRef(null)
  const isDrawingRef = useRef(false)

  // ---------- chart setup ----------
  useEffect(() => {
    const chart = createChart(containerRef.current, {
      layout: { background: { color: '#0e1117' }, textColor: '#d1d4dc' },
      grid: {
        vertLines: { color: '#1c1f26' },
        horzLines: { color: '#1c1f26' },
      },
      rightPriceScale: { borderColor: '#2a2e39' },
      timeScale: { borderColor: '#2a2e39', timeVisible: true, secondsVisible: false },
      crosshair: { mode: CrosshairMode.Normal },
      autoSize: true,
    })
    chartRef.current = chart

    candleRef.current = chart.addCandlestickSeries({
      upColor: '#26a69a', downColor: '#ef5350',
      wickUpColor: '#26a69a', wickDownColor: '#ef5350',
      borderVisible: false,
    })

    volRef.current = chart.addHistogramSeries({
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
      color: '#26a69a',
    })
    chart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 }, // pin to bottom 20%
    })

    emaRefs.current.ema20 = chart.addLineSeries({ color: '#f1c40f', lineWidth: 1, priceLineVisible: false, lastValueVisible: false })
    emaRefs.current.ema50 = chart.addLineSeries({ color: '#3498db', lineWidth: 1, priceLineVisible: false, lastValueVisible: false })
    emaRefs.current.ema200 = chart.addLineSeries({ color: '#e74c3c', lineWidth: 1, priceLineVisible: false, lastValueVisible: false })

    // ---------- drawings overlay ----------
    const overlay = document.createElement('canvas')
    overlay.style.position = 'absolute'
    overlay.style.inset = '0'
    overlay.style.pointerEvents = 'none'
    containerRef.current.appendChild(overlay)
    overlayRef.current = overlay

    const sizeOverlay = () => {
      const r = containerRef.current.getBoundingClientRect()
      overlay.width = r.width
      overlay.height = r.height
      redraw()
    }
    sizeOverlay()
    const ro = new ResizeObserver(sizeOverlay)
    ro.observe(containerRef.current)

    chart.timeScale().subscribeVisibleTimeRangeChange(redraw)
    chart.subscribeCrosshairMove(() => {
      if (isDrawingRef.current) redraw()
    })

    // mouse events on container (overlay is pointer-events:none)
    const onDown = (e) => {
      if (drawModeRef.current === 'none') return
      overlay.style.pointerEvents = 'auto' // capture future moves
      const pt = pickPoint(e)
      if (!pt) return
      isDrawingRef.current = true
      if (drawModeRef.current === 'free') {
        draftRef.current = { type: 'free', points: [pt] }
      } else {
        draftRef.current = { type: drawModeRef.current, points: [pt, pt] }
      }
    }
    const onMove = (e) => {
      if (!isDrawingRef.current || !draftRef.current) return
      const pt = pickPoint(e)
      if (!pt) return
      const d = draftRef.current
      if (d.type === 'free') d.points.push(pt)
      else if (d.type === 'hline') d.points = [{ time: d.points[0].time, price: pt.price }, { time: pt.time, price: pt.price }]
      else d.points[1] = pt
      redraw()
    }
    const onUp = () => {
      if (!isDrawingRef.current) return
      isDrawingRef.current = false
      overlay.style.pointerEvents = 'none'
      if (draftRef.current) {
        drawingsRef.current.push(draftRef.current)
        draftRef.current = null
      }
      redraw()
    }
    containerRef.current.addEventListener('mousedown', onDown)
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)

    function pickPoint(e) {
      const rect = containerRef.current.getBoundingClientRect()
      const x = e.clientX - rect.left
      const y = e.clientY - rect.top
      const time = chart.timeScale().coordinateToTime(x)
      const price = candleRef.current.coordinateToPrice(y)
      if (time == null || price == null) return null
      return { time, price, x, y }
    }

    function project(pt) {
      const x = chart.timeScale().timeToCoordinate(pt.time)
      const y = candleRef.current.priceToCoordinate(pt.price)
      return { x, y }
    }

    function redraw() {
      const ctx = overlay.getContext('2d')
      ctx.clearRect(0, 0, overlay.width, overlay.height)
      const all = [...drawingsRef.current]
      if (draftRef.current) all.push(draftRef.current)
      for (const d of all) {
        ctx.beginPath()
        ctx.lineWidth = 2
        ctx.strokeStyle = d.type === 'hline' ? '#9b59b6' : d.type === 'free' ? '#1abc9c' : '#f39c12'
        const pts = d.points.map(project).filter(p => p.x != null && p.y != null)
        if (pts.length < 2) continue
        ctx.moveTo(pts[0].x, pts[0].y)
        for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y)
        ctx.stroke()
      }
    }

    // expose redraw for parent calls via ref methods below
    chartRef.current._redrawDrawings = redraw

    return () => {
      ro.disconnect()
      containerRef.current && containerRef.current.removeEventListener('mousedown', onDown)
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
      chart.remove()
    }
  }, [])

  useImperativeHandle(ref, () => ({
    setCandles(candles) {
      candleRef.current.setData(candles.map(c => ({
        time: c.time, open: c.open, high: c.high, low: c.low, close: c.close,
      })))
      // Track loaded range so setMarkers can filter out signals from
      // outside this window (which would otherwise stack at the edge).
      if (candles.length > 0) {
        candleRangeRef.current = {
          start: candles[0].time,
          end: candles[candles.length - 1].time,
        }
      }
      chartRef.current.timeScale().fitContent()
    },
    updateCandle(c) {
      candleRef.current.update({ time: c.time, open: c.open, high: c.high, low: c.low, close: c.close })
      volRef.current.update({
        time: c.time, value: c.volume,
        color: c.close >= c.open ? 'rgba(38,166,154,0.6)' : 'rgba(239,83,80,0.6)',
      })
    },
    setEmas({ time, ema20, ema50, ema200 }) {
      const pack = (arr) => time
        .map((t, i) => arr[i] == null ? null : { time: t, value: arr[i] })
        .filter(Boolean)
      emaRefs.current.ema20.setData(pack(ema20))
      emaRefs.current.ema50.setData(pack(ema50))
      emaRefs.current.ema200.setData(pack(ema200))
    },
    setVolume(candles) {
      volRef.current.setData(candles.map(c => ({
        time: c.time, value: c.volume,
        color: c.close >= c.open ? 'rgba(38,166,154,0.6)' : 'rgba(239,83,80,0.6)',
      })))
    },
    setMarkers(signals) {
      // 1) Only keep markers whose time falls inside the loaded chart window.
      //    This is critical for MTF strategies (signals are 1h-timestamped)
      //    being viewed on a different chart timeframe (e.g. 1m).
      // 2) Then show at most the last 20 to keep things readable.
      const { start, end } = candleRangeRef.current
      const inRange = start && end
        ? signals.filter(s => s.time >= start && s.time <= end)
        : signals
      const recent = inRange.slice(-20)

      const colorFor = (s) => {
        if (s.status === 'WIN') return '#00d4a3'
        if (s.status === 'LOSS') return '#ff4d4d'
        if (s.status === 'OPEN') return '#3498db'
        return s.type === 'BUY' ? '#26a69a' : '#ef5350'
      }
      candleRef.current.setMarkers(recent.map(s => ({
        time: s.time,
        position: s.type === 'BUY' ? 'belowBar' : 'aboveBar',
        color: colorFor(s),
        shape: s.type === 'BUY' ? 'arrowUp' : 'arrowDown',
        text: s.type,
      })))
    },
    setLevels({ entry, stop, target } = {}) {
      // remove old price lines
      for (const line of levelLinesRef.current) candleRef.current.removePriceLine(line)
      levelLinesRef.current = []
      const add = (price, color, title) => {
        if (price == null) return
        const line = candleRef.current.createPriceLine({
          price, color, lineWidth: 1, lineStyle: LineStyle.Dashed,
          axisLabelVisible: true, title,
        })
        levelLinesRef.current.push(line)
      }
      add(entry, '#3498db', 'Entry')
      add(stop, '#ef5350', 'Stop')
      add(target, '#26a69a', 'Target')
    },
    setDrawingMode(mode) {
      drawModeRef.current = mode
      // when in 'none', we leave overlay non-interactive so the chart can pan/zoom.
    },
    clearDrawings() {
      drawingsRef.current = []
      draftRef.current = null
      chartRef.current._redrawDrawings && chartRef.current._redrawDrawings()
    },
  }), [])

  return <div ref={containerRef} className="chart-container" />
})

export default Chart
