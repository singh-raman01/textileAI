/**
 * E2E: File system sync
 *
 * REAL DATA REQUIRED — see tests/e2e/README.md
 *
 * Tests:
 *  1. Copying a new image into a watched folder auto-indexes it
 *  2. Deleting a file marks it orphaned (does not delete DB record)
 *  3. Renaming a file preserves metadata and FAISS embedding
 *  4. Moving a folder > 80% missing → folder flagged unavailable (not mass-orphaned)
 */
import { test, expect } from '@playwright/test'
import * as fs from 'node:fs'
import * as path from 'node:path'
import { assertFixturesPresent, launchApp, waitForReady, FABRIC_IMAGES } from './helpers'

test.describe('File system sync', () => {

  test.skip('new file in watched folder is auto-indexed', async () => {
    /**
     * STUB — requires:
     *  - A watched folder already set up in the app
     *  - At least one fabric image available to copy
     *
     * To enable: remove test.skip(), ensure import test has run first.
     *
     * Test plan:
     * 1. Note current image count from status bar
     * 2. Copy a new JPEG into the watched folder
     * 3. Wait up to 10 seconds
     * 4. Verify image count increased by 1
     * 5. Verify the new image appears in the gallery
     *
     * Why 10 seconds: chokidar has a 500 ms debounce, then the import
     * worker processes the file. On CI this should complete in ~3 seconds.
     */
    assertFixturesPresent()
    const { app, page } = await launchApp()
    try {
      await waitForReady(page)

      // Get initial count
      const countEl = page.locator('[data-testid="image-count"]')
      const before = parseInt((await countEl.textContent())?.replace(/\D/g, '') ?? '0')

      // Copy a file into the watched folder
      // REPLACE THIS PATH with your actual watched folder
      const watchedFolder = process.env['TEXTILE_TEST_WATCHED_FOLDER'] ?? FABRIC_IMAGES
      const source = path.join(FABRIC_IMAGES, 'wool_001.jpg')
      const dest   = path.join(watchedFolder, `sync_test_${Date.now()}.jpg`)
      fs.copyFileSync(source, dest)

      try {
        // Wait for auto-index (chokidar debounce + import)
        await page.waitForTimeout(8_000)
        const after = parseInt((await countEl.textContent())?.replace(/\D/g, '') ?? '0')
        expect(after).toBeGreaterThan(before)
      } finally {
        // Clean up the test file
        if (fs.existsSync(dest)) fs.unlinkSync(dest)
      }
    } finally {
      await app.close()
    }
  })

  test.skip('deleting a file marks it orphaned', async () => {
    /**
     * STUB — requires pre-indexed images
     *
     * Test plan:
     * 1. Note a specific image filename from the gallery
     * 2. Delete the file from disk
     * 3. Restart the app (startup sync will detect the deletion)
     * 4. Navigate to gallery with "Show orphaned" enabled
     * 5. Verify the image appears with the "missing" badge
     * 6. Verify the DB record still exists (not deleted)
     */
    assertFixturesPresent()
    // ... implementation when fixtures are available
  })

  test.skip('renaming a file preserves all metadata', async () => {
    /**
     * STUB — requires pre-indexed images with label metadata
     *
     * Test plan:
     * 1. Note a specific image's item_no from the detail panel
     * 2. Rename the file in the watched folder
     * 3. Wait for chokidar → sync-batch
     * 4. Find the image in the gallery by new filename
     * 5. Open detail panel → verify item_no is unchanged
     * 6. Verify FAISS ID is unchanged (no re-embedding occurred)
     *
     * This verifies the MD5 rename reconciliation in sync.py.
     */
    assertFixturesPresent()
    // ... implementation when fixtures are available
  })

})
