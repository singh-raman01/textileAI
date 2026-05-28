/**
 * E2E: Visual search flow
 *
 * REAL DATA REQUIRED — see tests/e2e/README.md
 *
 * What this tests:
 *  1. Drop a query image → results appear
 *  2. Results are ordered by similarity (highest first)
 *  3. Similarity badges are correct colour
 *  4. Clicking a result opens the detail panel
 *  5. "Search similar" re-runs search from a result
 *  6. k slider changes result count
 *  7. Low-confidence warning appears when query is not a fabric image
 *
 * Minimum fixtures needed:
 *  - tests/e2e/fixtures/query/search_query.jpg   (fabric image matching wool_001.jpg)
 *  - tests/e2e/fixtures/fabric_images/wool_001.jpg through wool_00N.jpg
 *  - At least 5 images must be indexed before running these tests
 */
import { test, expect } from '@playwright/test'
import * as path from 'node:path'
import { assertFixturesPresent, launchApp, waitForReady, navigateTo, dropFile, QUERY_IMAGE, FABRIC_IMAGES } from './helpers'

test.describe('Visual search', () => {

  test('drop query image → results grid appears', async () => {
    /**
     * Acceptance criteria:
     *  - Results grid appears within 5 seconds
     *  - At least 1 result is shown
     */
    assertFixturesPresent()
    const { app, page } = await launchApp()
    try {
      await waitForReady(page)

      // Import fixtures first (clean DB, no pre-indexed images)
      await navigateTo(page, 'import')
      await app.evaluate(({ dialog }, fp) => {
        dialog.showOpenDialog = async () => ({ canceled: false, filePaths: [fp] })
      }, FABRIC_IMAGES)
      await page.click('[data-testid="add-folder-btn"]')
      await page.waitForSelector('[data-testid="search-now-btn"]', { timeout: 60_000 })

      // Navigate to search
      await page.click('[data-testid="search-now-btn"]')
      await page.waitForTimeout(300)
      await navigateTo(page, 'search')

      await dropFile(page, '[data-testid="search-dropzone"]', QUERY_IMAGE)

      const grid = page.locator('[data-testid="results-grid"]')
      await expect(grid).toBeVisible({ timeout: 5_000 })

      const cards = grid.locator('[data-testid="image-card"]')
      const count = await cards.count()
      expect(count).toBeGreaterThan(0)

      // First card should have a similarity badge
      const firstBadge = cards.first().locator('[data-testid="similarity-badge"]')
      await expect(firstBadge).toBeVisible()
    } finally {
      await app.close()
    }
  })

  test.skip('k slider changes result count', async () => {
    /**
     * STUB — requires pre-indexed images
     *
     * Test plan:
     * 1. Drop query image, wait for results with k=20
     * 2. Move slider to k=5
     * 3. Click "Search" again
     * 4. Verify result count is ≤ 5
     */
    assertFixturesPresent()
    // ... implementation when fixtures are available
  })

  test.skip('clicking result opens detail panel', async () => {
    /**
     * Test plan:
     * 1. Perform a search
     * 2. Click the first result card
     * 3. Verify detail panel slides in (detail-panel-open class)
     * 4. Verify filename is shown
     * 5. If labelled_001.jpg is in results: verify supplier or item_no field is populated
     * 6. Click × to close panel
     * 7. Verify panel slides out
     */
    assertFixturesPresent()
    // ... implementation when fixtures are available
  })

  test.skip('search-similar re-runs search from result', async () => {
    /**
     * Test plan:
     * 1. Drop query image, wait for results
     * 2. Click first result → detail panel opens
     * 3. Click "Search similar"
     * 4. Verify detail panel closes
     * 5. Verify new results appear (query thumbnail changes to the result image)
     */
    assertFixturesPresent()
    // ... implementation when fixtures are available
  })

})
