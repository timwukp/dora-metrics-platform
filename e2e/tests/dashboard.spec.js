import { test, expect } from '@playwright/test'

const SCORE_CARDS = [
  'Deployment Frequency',
  'Lead Time for Changes',
  'Change Failure Rate',
  'Mean Time to Recovery',
]

const TREND_TITLES = [
  /Deployment Frequency Trend/,
  /Lead Time Trend/,
  /Change Failure Rate Trend/,
  /MTTR Trend/,
]

async function waitForDashboardReady(page) {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'DORA Metrics Platform' })).toBeVisible()
  // Wait until the loading placeholder disappears (or never appeared).
  await expect(page.getByText('Loading metrics...')).toHaveCount(0, { timeout: 15_000 })
}

test.describe('P0 — core display', () => {
  test('header renders with no error banner', async ({ page }) => {
    await waitForDashboardReady(page)
    await expect(page.getByText(/Could not load metrics/)).toHaveCount(0)
  })

  test('all four DORA score cards render with values', async ({ page }) => {
    await waitForDashboardReady(page)
    for (const title of SCORE_CARDS) {
      const card = page.locator('div', { has: page.getByText(title, { exact: true }) }).first()
      await expect(card).toBeVisible()
    }
    // Score cards must not show literal NaN / undefined.
    await expect(page.getByText(/\bNaN\b/)).toHaveCount(0)
    await expect(page.getByText(/\bundefined\b/)).toHaveCount(0)
  })

  test('all four trend charts render', async ({ page }) => {
    await waitForDashboardReady(page)
    for (const re of TREND_TITLES) {
      await expect(page.getByText(re).first()).toBeVisible()
    }
    // Recharts paints SVG <path>; ensure the chart area has rendered SVG nodes.
    const svgCount = await page.locator('section svg').count()
    expect(svgCount).toBeGreaterThanOrEqual(4)
  })

  test('merged-PR fallback banner appears when no formal deployments', async ({ page }) => {
    await waitForDashboardReady(page)
    const banner = page.getByText(/Trends use merged PRs as a deploy proxy/)
    if (await banner.count()) {
      await expect(banner.first()).toBeVisible()
      await expect(page.getByText(/Deployment Frequency Trend \(proxy: merged PRs\)/)).toBeVisible()
    } else {
      test.info().annotations.push({ type: 'note', description: 'No fallback banner — formal deploys present' })
    }
  })
})

test.describe('P1 — interactions', () => {
  test('time-range selector triggers a fresh /metrics/dora call', async ({ page }) => {
    await waitForDashboardReady(page)
    const dora = page.waitForResponse(
      r => r.url().includes('/api/v1/metrics/dora') && r.url().includes('days=7'),
      { timeout: 10_000 },
    )
    const selects = page.locator('header select')
    // The days dropdown is the last select in the header (repo selector may or may not be present).
    await selects.last().selectOption('7')
    const resp = await dora
    expect(resp.ok()).toBeTruthy()
  })

  test('repo selector switches data when present', async ({ page }) => {
    await waitForDashboardReady(page)
    const repoSelect = page.locator('header select').first()
    const optionCount = await repoSelect.locator('option').count()
    test.skip(optionCount < 2, 'Only one repo configured — nothing to switch to')
    const before = await page.locator('text=/deploys in period/').first().textContent()
    await repoSelect.selectOption({ index: 1 })
    await page.waitForResponse(r => r.url().includes('/api/v1/metrics/dora'))
    const after = await page.locator('text=/deploys in period/').first().textContent()
    expect(after).not.toEqual(before)
  })

  test('Claude Code panel renders', async ({ page }) => {
    await waitForDashboardReady(page)
    await expect(page.getByText(/Claude Code/i).first()).toBeVisible()
  })

  test('Review panel renders', async ({ page }) => {
    await waitForDashboardReady(page)
    await expect(page.getByText(/Review/i).first()).toBeVisible()
  })
})

test.describe('P2 — resilience and quality', () => {
  test('no console errors during load', async ({ page }) => {
    const errors = []
    page.on('console', msg => {
      if (msg.type() === 'error') errors.push(msg.text())
    })
    page.on('pageerror', err => errors.push(`pageerror: ${err.message}`))
    await waitForDashboardReady(page)
    // Filter out noisy 3rd-party warnings (none expected here, but kept for safety).
    const fatal = errors.filter(e => !/Recharts/.test(e))
    expect(fatal, `Console errors:\n${fatal.join('\n')}`).toEqual([])
  })

  test('all dashboard API calls return 2xx', async ({ page }) => {
    const failed = []
    page.on('response', r => {
      const u = r.url()
      if (u.includes('/api/v1/') && r.status() >= 400) {
        failed.push(`${r.status()} ${u}`)
      }
    })
    await waitForDashboardReady(page)
    await page.waitForLoadState('networkidle')
    expect(failed, `Non-2xx API responses:\n${failed.join('\n')}`).toEqual([])
  })

  test('mobile viewport stacks cards into a single column', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await waitForDashboardReady(page)
    const cards = page.locator('section').first().locator('> div')
    const count = await cards.count()
    expect(count).toBeGreaterThanOrEqual(4)
    const firstBox = await cards.nth(0).boundingBox()
    const secondBox = await cards.nth(1).boundingBox()
    // Stacked vertically: second card's top is below first card's bottom.
    expect(secondBox.y).toBeGreaterThan(firstBox.y + firstBox.height - 5)
  })

  test('503 retry banner appears when backend returns 503', async ({ page }) => {
    // Intercept the first dora call only and return 503; subsequent calls pass through.
    let intercepted = 0
    await page.route('**/api/v1/metrics/dora**', route => {
      intercepted += 1
      if (intercepted === 1) {
        return route.fulfill({
          status: 503,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'starting' }),
        })
      }
      return route.continue()
    })
    await page.goto('/')
    await expect(page.getByText(/Backend is starting or its database isn/)).toBeVisible({ timeout: 10_000 })
    // Banner clears once retry succeeds.
    await expect(page.getByText(/Backend is starting or its database isn/)).toHaveCount(0, { timeout: 15_000 })
  })
})
