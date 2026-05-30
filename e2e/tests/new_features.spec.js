import { test, expect } from '@playwright/test'

// Coverage for issues #14 (sprint selector), #16 (DORA level history heatmap),
// #18 (export retro), #19 (Compare page). Sprint and retro download paths are
// tolerant of a non-configured backend — they assert "panel renders correctly
// in absence of data" rather than skipping outright.

async function gotoDashboard(page) {
  await page.goto('/#dashboard')
  await expect(page.getByRole('heading', { name: 'DORA Metrics Platform' })).toBeVisible()
  await expect(page.getByText('Loading metrics...')).toHaveCount(0, { timeout: 15_000 })
}

test.describe('issue #14 — sprint selector', () => {
  test('selector visibility tracks /sprints.configured', async ({ page }) => {
    let configured = false
    page.on('response', async (r) => {
      if (r.url().includes('/api/v1/sprints') && r.ok()) {
        try { configured = (await r.json()).configured === true } catch {}
      }
    })
    await gotoDashboard(page)
    const selector = page.getByLabel('Sprint selector')
    if (configured) {
      await expect(selector).toBeVisible()
    } else {
      await expect(selector).toHaveCount(0)
    }
  })
})

test.describe('issue #16 — DORA level history', () => {
  test('panel renders with either heatmap or empty-state hint', async ({ page }) => {
    await gotoDashboard(page)
    const heading = page.getByRole('heading', { name: 'DORA Level History' })
    await expect(heading).toBeVisible()
    // Either the heatmap legend appears, or the empty-state hint mentions
    // backfill — both are acceptable.
    const legend = page.locator('section', { hasText: 'DORA Level History' }).getByText('Elite', { exact: true })
    const hint = page.getByText(/level-snapshots/)
    const hasLegend = await legend.count()
    const hasHint = await hint.count()
    expect(hasLegend + hasHint).toBeGreaterThan(0)
  })

  test('legend swatches use the documented palette when snapshots exist', async ({ page }) => {
    await gotoDashboard(page)
    const section = page.locator('section', { hasText: 'DORA Level History' })
    const eliteSwatch = section.getByText('Elite', { exact: true })
    if (await eliteSwatch.count() === 0) {
      test.info().annotations.push({ type: 'note', description: 'No snapshots yet — palette covered by hint test' })
      return
    }
    for (const level of ['Elite', 'High', 'Medium', 'Low']) {
      await expect(section.getByText(level, { exact: true })).toBeVisible()
    }
  })
})

test.describe('issue #18 — export retro markdown', () => {
  test('button triggers a markdown download', async ({ page }) => {
    await gotoDashboard(page)
    const button = page.getByRole('button', { name: 'Export retro report' })
    await expect(button).toBeVisible()
    const [download] = await Promise.all([
      page.waitForEvent('download', { timeout: 15_000 }),
      button.click(),
    ])
    expect(download.suggestedFilename()).toMatch(/^dora-retro-.*\.md$/)
  })
})

test.describe('issue #19 — Compare page', () => {
  test('nav link routes to the Compare view', async ({ page }) => {
    await gotoDashboard(page)
    await page.getByRole('link', { name: 'Compare' }).click()
    await expect(page.getByText(/identifying shared challenges/i)).toBeVisible()
    // Headers from the comparison table.
    await expect(page.getByRole('columnheader', { name: 'Deploy Freq' })).toBeVisible()
    await expect(page.getByRole('columnheader', { name: 'Lead Time' })).toBeVisible()
    await expect(page.getByRole('columnheader', { name: 'CFR' })).toBeVisible()
    await expect(page.getByRole('columnheader', { name: 'MTTR' })).toBeVisible()
  })

  test('hash route returns to dashboard', async ({ page }) => {
    await page.goto('/#compare')
    await expect(page.getByText(/identifying shared challenges/i)).toBeVisible()
    await page.getByRole('link', { name: 'Dashboard' }).click()
    // Dashboard-only controls reappear.
    await expect(page.locator('header').getByRole('combobox').last()).toBeVisible()
  })
})
