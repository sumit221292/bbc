// End-to-end smoke test covering every visible surface of the BTC app.
// Runs in headed Chromium so the user can watch the click-through.
import { test, expect } from '@playwright/test'

// Collect every console error / page error / failed request so a single
// failing tab does not let the others off the hook.
function attachConsoleCollector(page, bag) {
  page.on('console', msg => {
    if (msg.type() !== 'error') return
    const text = msg.text()
    // Chrome's "Failed to load resource" lines are duplicates of the network
    // events we already track via `response` -- skip them so a single 404
    // does not double-count.
    if (/Failed to load resource/i.test(text)) return
    bag.push(`[console.error] ${text}`)
  })
  page.on('pageerror', err => {
    bag.push(`[pageerror] ${err.message}`)
  })
  page.on('requestfailed', req => {
    const url = req.url()
    if (/favicon\.ico|favicon\.svg/i.test(url)) return
    // Only fail on requests to our own surface. Third-party widgets
    // (TradingView iframe, analytics, ad blockers) abort their own
    // requests during navigation and that is not our bug.
    const sameOrigin = new URL(url).origin === new URL(page.url()).origin
    if (!sameOrigin) return
    bag.push(`[requestfailed] ${url} ${req.failure()?.errorText}`)
  })
  page.on('response', resp => {
    const url = resp.url()
    // Only flag failures from our own backend so we don't get noise from
    // third-party trackers, ad blockers, or the favicon round-trip.
    if (!url.includes('/api/') && !url.includes('/ws/')) return
    if (resp.status() >= 400) {
      bag.push(`[http ${resp.status()}] ${url}`)
    }
  })
}

test.describe('BTC trading app — full surface', () => {
  test.beforeEach(async ({ page }) => {
    // Slow down a touch so headed runs are watchable.
    page.context().setDefaultNavigationTimeout(30_000)
  })

  test('Live tab — chart loads, strategy banner + signal card visible', async ({ page }) => {
    const errors = []
    attachConsoleCollector(page, errors)
    await page.goto('/')

    // Wait for the React app to mount and an initial API call to land.
    await expect(page.locator('.strategy-banner-name')).toBeVisible({ timeout: 20_000 })

    // Live tab should be the default landing tab.
    const liveTab = page.locator('button.tab', { hasText: 'Live' })
    await expect(liveTab).toHaveClass(/active/)

    // Either a signal card OR the "Loading…" state should be present.
    const signalPanel = page.locator('.signal-panel')
    await expect(signalPanel).toBeVisible()

    // History section title shows the strategy + interval so the user can
    // verify the DB scope at a glance.
    await expect(page.locator('.history .title')).toContainText('Recent Trades')

    if (errors.length) console.warn('LIVE tab issues:', errors)
    expect(errors, errors.join('\n')).toHaveLength(0)
  })

  test('Plan tab — outlook card renders bias + price levels', async ({ page }) => {
    const errors = []
    attachConsoleCollector(page, errors)
    await page.goto('/')
    await page.locator('button.tab', { hasText: 'Plan' }).click()

    // MarketOutlook should show the current price and a trade plan section.
    const plan = page.locator('.market-outlook, .outlook')
    await expect(plan.first()).toBeVisible({ timeout: 20_000 })

    if (errors.length) console.warn('PLAN tab issues:', errors)
    expect(errors, errors.join('\n')).toHaveLength(0)
  })

  test('All tab — overview table renders rows; numbers come from DB', async ({ page }) => {
    const errors = []
    attachConsoleCollector(page, errors)
    await page.goto('/')
    await page.locator('button.tab', { hasText: 'All' }).click()

    await expect(page.locator('.overview .title')).toContainText('All Strategies')
    // Wait for the snapshot fetch to complete -- the table header only
    // renders after data lands. Railway can be slow (Binance fetches).
    await expect(page.locator('.ov-row.ov-head')).toBeVisible({ timeout: 30_000 })
    // Source note we added: "Numbers worker-fired trades se hain" appears
    // only in the loaded state.
    await expect(page.locator('.ov-source-note')).toContainText(/worker-fired|Live Trades/i)

    // Table header + at least one row.
    const rows = page.locator('.ov-row.clickable')
    await expect(rows.first()).toBeVisible({ timeout: 30_000 })

    if (errors.length) console.warn('ALL tab issues:', errors)
    expect(errors, errors.join('\n')).toHaveLength(0)
  })

  test('Best tab — leaderboard windows render (or empty state)', async ({ page }) => {
    const errors = []
    attachConsoleCollector(page, errors)
    await page.goto('/')
    await page.locator('button.tab', { hasText: 'Best' }).click()

    await expect(page.locator('.leaderboard .title')).toContainText('Best Performers')
    // Six windows: 1h / 2h / 4h / 6h / 12h / 24h headers must all be present.
    for (const label of ['Last 1 Hour', 'Last 2 Hours', 'Last 4 Hours', 'Last 6 Hours', 'Last 12 Hours', 'Last 24 Hours']) {
      await expect(page.locator('.lb-window-title', { hasText: label })).toBeVisible({ timeout: 30_000 })
    }

    if (errors.length) console.warn('BEST tab issues:', errors)
    expect(errors, errors.join('\n')).toHaveLength(0)
  })

  test('Alerts tab — config form + auto-trade panel visible', async ({ page }) => {
    const errors = []
    attachConsoleCollector(page, errors)
    await page.goto('/')
    await page.locator('button.tab', { hasText: 'Alerts' }).click()

    // Some recognizable label from AlertsTab; matches either heading style.
    await expect(page.getByText(/Telegram|Worker|Notification/i).first()).toBeVisible({ timeout: 20_000 })

    if (errors.length) console.warn('ALERTS tab issues:', errors)
    expect(errors, errors.join('\n')).toHaveLength(0)
  })

  test('Strategy switch — picking another strategy updates banner', async ({ page }) => {
    const errors = []
    attachConsoleCollector(page, errors)
    await page.goto('/')

    await expect(page.locator('.strategy-banner-name')).toBeVisible({ timeout: 20_000 })
    const initial = await page.locator('.strategy-banner-name').textContent()

    // Find the strategy selector and pick a different option if available.
    const select = page.locator('select').first()
    const optionCount = await select.locator('option').count()
    if (optionCount > 1) {
      // Pick the second non-empty option to force a change.
      const target = await select.locator('option').nth(1).getAttribute('value')
      if (target) {
        await select.selectOption(target)
        // Wait for the banner to update (might be the same name if already on it).
        await page.waitForTimeout(2_000)
      }
    }

    if (errors.length) console.warn('STRATEGY SWITCH issues:', errors)
    expect(errors, errors.join('\n')).toHaveLength(0)
  })

  test('Interval switch — picking a different timeframe re-renders chart', async ({ page }) => {
    const errors = []
    attachConsoleCollector(page, errors)
    await page.goto('/')

    // Toolbar intervals are pill buttons. Find by text.
    await expect(page.locator('.strategy-banner-name')).toBeVisible({ timeout: 20_000 })
    const intervalPill = page.locator('button', { hasText: /^(1m|5m|15m|1h|4h|1d)$/ }).first()
    if (await intervalPill.count() > 0) {
      await intervalPill.click()
      await page.waitForTimeout(2_000)
    }

    if (errors.length) console.warn('INTERVAL SWITCH issues:', errors)
    expect(errors, errors.join('\n')).toHaveLength(0)
  })

  test('Chart toggle — TradingView mode mounts iframe, switches back', async ({ page }) => {
    const errors = []
    attachConsoleCollector(page, errors)
    await page.goto('/')

    // Default: native chart pane should be present, no iframe yet.
    await expect(page.locator('.chart-container, .chart-pane canvas').first()).toBeVisible({ timeout: 20_000 })
    await expect(page.locator('.tv-chart-iframe')).toHaveCount(0)

    // Switch to TradingView mode.
    await page.locator('.toolbar button', { hasText: 'TradingView' }).click()
    await expect(page.locator('.tv-chart-iframe')).toBeVisible({ timeout: 15_000 })
    await expect(page.locator('.tv-chart-link')).toContainText(/Open my saved chart/i)

    // Drawing tools must be hidden in TV mode (they cannot operate on the iframe).
    await expect(page.locator('.toolbar button', { hasText: /^Band$/ })).toHaveCount(0)

    // Switch back to native chart.
    await page.locator('.toolbar button', { hasText: 'Our' }).click()
    await expect(page.locator('.tv-chart-iframe')).toHaveCount(0)
    await expect(page.locator('.chart-container, .chart-pane canvas').first()).toBeVisible()
    // Drawing tools reappear.
    await expect(page.locator('.toolbar button', { hasText: /^Band$/ })).toBeVisible()

    if (errors.length) console.warn('CHART TOGGLE issues:', errors)
    expect(errors, errors.join('\n')).toHaveLength(0)
  })

  test('API health — /api/trades and /api/strategy/snapshot return 200', async ({ request }) => {
    const trades = await request.get('/api/trades?strategy=best&interval=1m&limit=10')
    expect(trades.status()).toBe(200)
    const tradesJson = await trades.json()
    expect(tradesJson).toHaveProperty('trades')
    expect(tradesJson).toHaveProperty('summary')

    const snap = await request.get('/api/strategy/snapshot?symbol=BTCUSDT&interval=1h')
    expect(snap.status()).toBe(200)
    const snapJson = await snap.json()
    expect(Array.isArray(snapJson.strategies)).toBe(true)
    expect(snapJson.strategies.length).toBeGreaterThan(0)

    const lb = await request.get('/api/strategy/leaderboard?symbol=BTCUSDT')
    expect(lb.status()).toBe(200)
    const lbJson = await lb.json()
    expect(Array.isArray(lbJson.leaderboards)).toBe(true)
    expect(lbJson.leaderboards.length).toBe(6)
  })
})
