// Diagnose what happens when the user picks a coin via the new SymbolPicker.
import { test, expect } from '@playwright/test'

test('SymbolPicker: type and select changes the chart symbol', async ({ page }) => {
  const errors = []
  page.on('console', msg => {
    if (msg.type() === 'error') errors.push(`[console.error] ${msg.text()}`)
  })
  page.on('pageerror', e => errors.push(`[pageerror] ${e.message}`))
  page.on('response', r => {
    const u = r.url()
    if ((u.includes('/api/') || u.includes('/ws/')) && r.status() >= 400) {
      errors.push(`[http ${r.status()}] ${u}`)
    }
  })

  await page.goto('/')
  await page.waitForLoadState('networkidle')

  // The new picker -- input with placeholder
  const picker = page.locator('.toolbar .symbol-picker .sp-input').first()
  await expect(picker).toBeVisible({ timeout: 10_000 })

  // Click it to open the dropdown
  await picker.click()
  await page.waitForTimeout(500)

  // The dropdown should populate with top-volume pairs
  const results = page.locator('.toolbar .sp-results .sp-row')
  await expect(results.first()).toBeVisible({ timeout: 8_000 })
  const firstSymbolText = await results.first().locator('.sp-label').textContent()
  console.log('First result:', firstSymbolText)

  // Type ETH to filter
  await picker.fill('ETH')
  await page.waitForTimeout(800)
  const ethRow = results.filter({ hasText: 'ETH/USDT' }).first()
  await expect(ethRow).toBeVisible({ timeout: 5_000 })

  // Click ETH/USDT
  await ethRow.click()
  await page.waitForTimeout(2_000)

  // After selection, the input should show ETH/USDT and a new strategy run
  // should have fired for ETHUSDT.
  const inputValue = await picker.inputValue()
  console.log('After pick, input value:', inputValue)

  // Check that the strategy banner / chart has updated. We don't know what
  // appears -- just dump the current state.
  const liveCard = page.locator('.signal-card').first()
  const isCardVisible = await liveCard.isVisible().catch(() => false)
  console.log('Live card visible?', isCardVisible)
  if (isCardVisible) {
    const cardText = await liveCard.textContent()
    console.log('Live card text (first 200ch):', cardText?.slice(0, 200))
  }

  // Screenshot for visual debugging.
  await page.screenshot({ path: 'test-results/coin_picker_after_eth.png', fullPage: true })
  console.log('Screenshot saved to test-results/coin_picker_after_eth.png')

  if (errors.length) {
    console.warn('Issues detected:')
    errors.forEach(e => console.warn('  -', e))
  }
})
