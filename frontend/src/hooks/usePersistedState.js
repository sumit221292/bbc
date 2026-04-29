import { useEffect, useState } from 'react'

/**
 * Like useState but persists the value to localStorage so it survives
 * page refresh / tab close. Used for symbol, interval, strategy.
 */
export function usePersistedState(key, defaultValue) {
  const [value, setValue] = useState(() => {
    try {
      const stored = localStorage.getItem(key)
      return stored !== null ? JSON.parse(stored) : defaultValue
    } catch {
      return defaultValue
    }
  })

  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(value))
    } catch {
      /* quota / privacy mode — silently ignore */
    }
  }, [key, value])

  return [value, setValue]
}
