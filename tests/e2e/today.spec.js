// Headed smoke test for everything shipped today:
//   1. Confluence meta-strategy in the StrategySelector dropdown
//   2. Phase C per-(strategy, coin) opt-out chips in the AlertsTab
//   3. Per-pair chip stats (2-line layout: symbol + WR + cumulative PnL)
//   4. Chip toggle silences a (strategy, coin) combo without breaking
//   5. New Trades tab with Strategy + Coin + Min WR filters
//   6. Min WR filter hides losing combos and recomputes the summary card
//
// Runs against the live Railway deployment by default. The test is
// resilient to "no trades yet" / "no subscription configured" states so
// it can run on a fresh DB without false negatives.
import { test, expect } from '@playwright/test'

function attachConsoleCollector(page, bag) {
  page.on('console', msg => {
    if (msg.type() !== 'error') return
    const text = msg.text()
    if (/Failed to load resource/i.test(text)) return
    bag.push(`[console.error] ${text}`)
  })
  page.on('pageerror', err => bag.push(`[pageerror] ${err.message}`))
  page.on('response', resp => {
    const url = resp.url()
    if (!url.includes('/api/')) return
    if (resp.status() >= 400) bag.push(`[http ${resp.status()}] ${url}`)
  })
}

test.describe('Today\'s features — Confluence + Phase C chips + Trades tab', () => {

  test('Confluence appears in the strategy dropdown', async ({ page }) => {
    const errors = []
    attachConsoleCollector(page, errors)
    await page.goto('/')

    await expect(page.locator('.strategy-banner-name')).toBeVisible({ timeout: 20_000 })

    const select = page.locator('.ss-dropdown')
    await expect(select).toBeVisible()

    // The Confluence option lives under its own optgroup with the
    // "🎯 Confluence" label set in StrategySelector.jsx.
    const confluenceOption = select.locator('option[value="confluence"]')
    await expect(confluenceOption).toHaveCount(1)
    await expect(confluenceOption).toContainText(/Confluence/i)

    // Pick it so the banner reflects the meta-strategy and the chart
    // re-runs against it.
    await select.selectOption('confluence')
    await expect(page.locator('.strategy-banner-name')).toContainText(/Confluence/i, { timeout: 15_000 })

    expect(errors, errors.join('\n')).toHaveLength(0)
  })

  test('Alerts tab — Phase C coin chips render under subscribed strategies', async ({ page }) => {
    const errors = []
    attachConsoleCollector(page, errors)
    await page.goto('/')

    await page.locator('button.tab', { hasText: 'Alerts' }).click()
    await expect(page.locator('.alerts-tab')).toBeVisible({ timeout: 20_000 })

    // Wait for the subscriptions list to render. Section title is
    // "Subscribed Strategies".
    await expect(page.locator('.alerts-subs-head .title', { hasText: 'Subscribed Strategies' }))
      .toBeVisible({ timeout: 15_000 })

    // If no strategy is subscribed yet, tick the first one so the chip
    // matrix appears. This keeps the test self-contained on fresh installs.
    const firstRow = page.locator('.alerts-sub-row').first()
    await expect(firstRow).toBeVisible({ timeout: 10_000 })
    const isOn = await firstRow.evaluate(el => el.classList.contains('on'))
    if (!isOn) {
      await firstRow.locator('input[type="checkbox"]').click()
      await page.waitForTimeout(500)
    }

    // The subscribed row must expand with .asr-coins block + per-coin chips.
    const subscribed = page.locator('.alerts-sub-row.on').first()
    await expect(subscribed.locator('.asr-coins')).toBeVisible()
    const chips = subscribed.locator('.asr-coin')
    await expect(chips.first()).toBeVisible()

    // Each chip must be the new 2-line layout: symbol on top + stat below.
    const firstChip = chips.first()
    await expect(firstChip.locator('.asr-coin-sym')).toBeVisible()
    await expect(firstChip.locator('.asr-coin-stat')).toBeVisible()

    // The stat text is either "new" (no trades) or "{wr}% · {+/-pnl}%".
    const statText = (await firstChip.locator('.asr-coin-stat').textContent())?.trim() || ''
    expect(statText.length).toBeGreaterThan(0)

    expect(errors, errors.join('\n')).toHaveLength(0)
  })

  test('Alerts tab — clicking a coin chip toggles its exclusion state', async ({ page }) => {
    const errors = []
    attachConsoleCollector(page, errors)
    await page.goto('/')

    await page.locator('button.tab', { hasText: 'Alerts' }).click()
    await expect(page.locator('.alerts-subs-head .title', { hasText: 'Subscribed Strategies' }))
      .toBeVisible({ timeout: 15_000 })

    // Make sure at least one row is subscribed.
    const firstRow = page.locator('.alerts-sub-row').first()
    await expect(firstRow).toBeVisible({ timeout: 10_000 })
    const isOn = await firstRow.evaluate(el => el.classList.contains('on'))
    if (!isOn) {
      await firstRow.locator('input[type="checkbox"]').click()
      await page.waitForTimeout(500)
    }

    const subscribed = page.locator('.alerts-sub-row.on').first()
    const chip = subscribed.locator('.asr-coin').first()
    await expect(chip).toBeVisible()

    // The chip starts in "on" state (fires on this coin). Click flips
    // it to "off" (silenced). Class transitions are the source of truth.
    const beforeClass = await chip.getAttribute('class')
    expect(beforeClass).toContain('on')

    await chip.click()
    await page.waitForTimeout(300)

    const afterClass = await chip.getAttribute('class')
    expect(afterClass).toContain('off')

    // The header should now show the -N coins hint.
    await expect(subscribed.locator('.asr-excl-count')).toBeVisible()
    await expect(subscribed.locator('.asr-excl-count')).toContainText(/−1 coin|-1 coin/)

    // Restore -- click again so we don't leave a stray exclusion on the
    // shared live config.
    await chip.click()
    await page.waitForTimeout(300)
    const restoredClass = await chip.getAttribute('class')
    expect(restoredClass).toContain('on')

    expect(errors, errors.join('\n')).toHaveLength(0)
  })

  test('Trades tab — exists, renders header + 3 filter dropdowns', async ({ page }) => {
    const errors = []
    attachConsoleCollector(page, errors)
    await page.goto('/')

    // The new Trades tab was added between All and Best.
    const tradesTab = page.locator('button.tab', { hasText: 'Trades' })
    await expect(tradesTab).toBeVisible()
    await tradesTab.click()

    await expect(page.locator('.trades-tab')).toBeVisible({ timeout: 15_000 })
    await expect(page.locator('.trades-tab .panel-section-title'))
      .toContainText(/All Trades.*Cross-Coin/i)

    // Three filter dropdowns: Strategy, Coin, Min WR.
    const selects = page.locator('.trades-filters select')
    await expect(selects).toHaveCount(3)

    // Each dropdown's default option must be "All …" / "Any".
    await expect(selects.nth(0).locator('option').first()).toContainText(/All strategies/i)
    await expect(selects.nth(1).locator('option').first()).toContainText(/All coins/i)
    await expect(selects.nth(2).locator('option').first()).toContainText(/Any/i)

    // The summary card with 4 stat cells must render (even if zero trades).
    await expect(page.locator('.trades-summary')).toBeVisible({ timeout: 15_000 })
    await expect(page.locator('.ts-stat')).toHaveCount(4)

    expect(errors, errors.join('\n')).toHaveLength(0)
  })

  test('Trades tab — strategy filter narrows the list to that strategy', async ({ page }) => {
    const errors = []
    attachConsoleCollector(page, errors)
    await page.goto('/')

    await page.locator('button.tab', { hasText: 'Trades' }).click()
    await expect(page.locator('.trades-tab')).toBeVisible({ timeout: 15_000 })

    // Pick the first NON-"All" strategy (whichever has options).
    const strategySelect = page.locator('.trades-filters select').nth(0)
    const options = strategySelect.locator('option')
    // Wait for the /api/strategy/list fetch to land and populate the
    // dropdown beyond the default "All strategies" option. Without this
    // poll the count() check races the fetch and we false-skip.
    await expect.poll(
      async () => await options.count(),
      { timeout: 15_000, message: 'strategies never populated the dropdown' },
    ).toBeGreaterThan(1)
    const targetValue = await options.nth(1).getAttribute('value')
    await strategySelect.selectOption(targetValue)
    await page.waitForTimeout(1500)  // let the fetch land

    // Either rows appear (whose .tr-strat text matches the picked label)
    // or the empty-state message renders -- both are valid live outcomes.
    const rows = page.locator('.trade-row')
    const empty = page.getByText(/No trades match this filter yet/i)
    const hasRows = await rows.count() > 0
    const hasEmpty = await empty.isVisible().catch(() => false)
    expect(hasRows || hasEmpty).toBeTruthy()

    if (hasRows) {
      // Every visible row's strategy label should equal the selected one.
      const targetLabel = await options.nth(1).textContent()
      const firstStrat = (await rows.first().locator('.tr-strat').textContent())?.trim()
      expect(targetLabel.trim()).toContain(firstStrat || '')
    }

    // Clear and confirm the Clear button removes the filter.
    await page.locator('.trades-clear', { hasText: /Clear/ }).click()
    await page.waitForTimeout(500)
    await expect(strategySelect).toHaveValue('')

    expect(errors, errors.join('\n')).toHaveLength(0)
  })

  test('Trades tab — Min WR filter applies and recomputes the summary', async ({ page }) => {
    const errors = []
    attachConsoleCollector(page, errors)
    await page.goto('/')

    await page.locator('button.tab', { hasText: 'Trades' }).click()
    await expect(page.locator('.trades-tab')).toBeVisible({ timeout: 15_000 })

    // Read trade count BEFORE the WR filter so we can compare after.
    await page.waitForTimeout(1500)
    const tradesCountBefore = parseInt(
      (await page.locator('.ts-stat').first().locator('.ts-value').textContent()) || '0',
      10,
    )

    // Crank the WR filter up to 60% -- almost guaranteed to hide some
    // combos given the backtest's spread of win-rates.
    const wrSelect = page.locator('.trades-filters select').nth(2)
    await wrSelect.selectOption('60')
    await page.waitForTimeout(1000)

    const tradesCountAfter = parseInt(
      (await page.locator('.ts-stat').first().locator('.ts-value').textContent()) || '0',
      10,
    )

    // The summary's trade count must be <= the unfiltered count. With
    // zero history both sides are 0 -- still consistent.
    expect(tradesCountAfter).toBeLessThanOrEqual(tradesCountBefore)

    // If some combos got hidden, the hint banner must appear.
    if (tradesCountAfter < tradesCountBefore) {
      await expect(page.locator('.trades-hint')).toBeVisible()
      await expect(page.locator('.trades-hint')).toContainText(/Hiding \d+ trade/i)
    }

    // Clear -- WR returns to "Any".
    await page.locator('.trades-clear', { hasText: /Clear/ }).click()
    await page.waitForTimeout(500)
    await expect(wrSelect).toHaveValue('0')

    expect(errors, errors.join('\n')).toHaveLength(0)
  })

  test('API — /api/trades/stats-by-pair returns rolled-up rows', async ({ request }) => {
    const r = await request.get('/api/trades/stats-by-pair')
    expect(r.status()).toBe(200)
    const data = await r.json()
    expect(data).toHaveProperty('pairs')
    expect(Array.isArray(data.pairs)).toBe(true)

    // If there's any data, sanity-check the row shape so future renames
    // of these field names get caught here, not in the UI at runtime.
    if (data.pairs.length > 0) {
      const p = data.pairs[0]
      for (const key of ['strategy_id', 'symbol', 'total', 'wins', 'losses',
                          'closed', 'win_rate', 'total_pnl_pct', 'last_signal_time']) {
        expect(p, `field "${key}" missing on stats-by-pair row`).toHaveProperty(key)
      }
    }
  })
})
