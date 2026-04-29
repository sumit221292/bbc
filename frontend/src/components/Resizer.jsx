import { useCallback } from 'react'

/** Vertical drag-handle between the chart pane and the sidebar.
 *  Dragging LEFT widens the sidebar; dragging RIGHT shrinks it.
 *  Width is clamped to [min, max] and reported via onResize. */
export default function Resizer({ current, onResize, min = 280, max = 700 }) {
  const handleMouseDown = useCallback((e) => {
    e.preventDefault()
    const startX = e.clientX
    const startWidth = current

    const onMove = (ev) => {
      const delta = startX - ev.clientX  // moving mouse left -> positive delta -> wider sidebar
      const next = Math.max(min, Math.min(max, startWidth + delta))
      onResize(next)
    }

    const onUp = () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }

    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }, [current, onResize, min, max])

  // Double-click to reset to a sensible default (380px).
  const handleDoubleClick = useCallback(() => onResize(380), [onResize])

  return (
    <div
      className="resizer"
      onMouseDown={handleMouseDown}
      onDoubleClick={handleDoubleClick}
      title="Drag to resize · double-click to reset"
    >
      <div className="resizer-grip" />
    </div>
  )
}
