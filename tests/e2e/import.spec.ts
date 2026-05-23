/**
 * E2E: Import flow
 *
 * REAL DATA REQUIRED — see tests/e2e/README.md
 *
 * Tests:
 *  1. App starts and shows loading screen then ready state
 *  2. User adds a folder — import starts
 *  3. Progress bar appears and advances
 *  4. Import completes — image count in status bar increases
 *  5. Interrupting import and resuming restores state
 */
import { test, expect } from '@playwright/test'
import * as path from 'node:path'
import { assertFixturesPresent, launchApp, waitForReady, navigateTo, FABRIC_IMAGES } from './helpers'

// ── STUB: Replace with real fixture path when images are available ──────────
// assertFixturesPresent()

test.describe('Import flow', () => {

  test('app starts within 30 seconds', async () => {
    /**
     * REAL DATA NOTE: This test works without real images.
     * It only checks that the backend health check succeeds.
     * No model loading occurs until the first import.
     */
    const { app, page } = await launchApp()
    try {
      await waitForReady(page)
      const statusBar = page.locator('[data-testid="status-bar"]')
      await expect(statusBar).toBeVisible()
    } finally {
      await app.close()
    }
  })

  test.skip('adds a folder and shows import progress', async () => {
    /**
     * STUB — requires real images in tests/e2e/fixtures/fabric_images/
     *
     * To enable this test:
     * 1. Add at least 10 fabric JPEG images to tests/e2e/fixtures/fabric_images/
     * 2. Remove the test.skip() call
     * 3. Run: npx playwright test tests/e2e/import.spec.ts
     *
     * Expected behaviour:
     * - Click "Import" nav item
     * - Click "Add folder"
     * - Electron dialog opens → select FABRIC_IMAGES folder
     * - Progress bar appears and percentage increases
     * - Status bar image count increases from 0 to N
     * - "Search now →" button appears when done
     */
    assertFixturesPresent()
    const { app, page } = await launchApp()
    try {
      await waitForReady(page)
      await navigateTo(page, 'import')

      // Mock the dialog to return our fixture folder
      await app.evaluate(({ dialog }, folderPath) => {
        dialog.showOpenDialog = async () => ({ canceled: false, filePaths: [folderPath] })
      }, FABRIC_IMAGES)

      await page.click('[data-testid="add-folder-btn"]')

      // Progress panel should appear
      const progressBar = page.locator('[data-testid="import-progress-bar"]')
      await expect(progressBar).toBeVisible({ timeout: 5_000 })

      // Wait for completion (max 5 min for a small fixture set)
      await page.waitForSelector('[data-testid="search-now-btn"]', { timeout: 300_000 })

      // Image count should be > 0
      const count = page.locator('[data-testid="image-count"]')
      const countText = await count.textContent()
      const n = parseInt(countText?.replace(/\D/g, '') ?? '0')
      expect(n).toBeGreaterThan(0)
    } finally {
      await app.close()
    }
  })

  test.skip('interrupted import resumes correctly', async () => {
    /**
     * STUB — requires real images
     *
     * To enable:
     * 1. Add 50+ fabric images to tests/e2e/fixtures/fabric_images/
     * 2. Remove test.skip()
     *
     * Test plan:
     * 1. Start import of 50+ images
     * 2. Click "Pause" after first 10 are done
     * 3. Close the app
     * 4. Relaunch the app
     * 5. Verify import resumes automatically from where it stopped
     * 6. Verify no images are double-indexed (count matches expected total)
     */
    assertFixturesPresent()
    // ... implementation when fixtures are available
  })

})
