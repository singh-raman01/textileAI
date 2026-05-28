# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: sync.spec.ts >> File system sync >> new file in watched folder is auto-indexed
- Location: tests/e2e/sync.spec.ts:19:7

# Error details

```
Error: expect(received).toBeGreaterThan(expected)

Expected: > 0
Received:   0
```

# Test source

```ts
  1  | /**
  2  |  * E2E: File system sync
  3  |  *
  4  |  * REAL DATA REQUIRED — see tests/e2e/README.md
  5  |  *
  6  |  * Tests:
  7  |  *  1. Copying a new image into a watched folder auto-indexes it
  8  |  *  2. Deleting a file marks it orphaned (does not delete DB record)
  9  |  *  3. Renaming a file preserves metadata and FAISS embedding
  10 |  *  4. Moving a folder > 80% missing → folder flagged unavailable (not mass-orphaned)
  11 |  */
  12 | import { test, expect } from '@playwright/test'
  13 | import * as fs from 'node:fs'
  14 | import * as path from 'node:path'
  15 | import { assertFixturesPresent, launchApp, waitForReady, FABRIC_IMAGES } from './helpers'
  16 | 
  17 | test.describe('File system sync', () => {
  18 | 
  19 |   test('new file in watched folder is auto-indexed', async () => {
  20 |     /**
  21 |      * Test plan:
  22 |      * 1. Note current image count from status bar
  23 |      * 2. Copy a new JPEG into the watched folder
  24 |      * 3. Wait up to 10 seconds
  25 |      * 4. Verify image count increased by 1
  26 |      * 5. Verify the new image appears in the gallery
  27 |      *
  28 |      * Why 10 seconds: chokidar has a 500 ms debounce, then the import
  29 |      * worker processes the file. On CI this should complete in ~3 seconds.
  30 |      */
  31 |     assertFixturesPresent()
  32 |     const { app, page } = await launchApp()
  33 |     try {
  34 |       await waitForReady(page)
  35 | 
  36 |       // Get initial count
  37 |       const countEl = page.locator('[data-testid="image-count"]')
  38 |       const before = parseInt((await countEl.textContent())?.replace(/\D/g, '') ?? '0')
  39 | 
  40 |       // Copy a file into the watched folder
  41 |       // REPLACE THIS PATH with your actual watched folder
  42 |       const watchedFolder = process.env['TEXTILE_TEST_WATCHED_FOLDER'] ?? FABRIC_IMAGES
  43 |       const source = path.join(FABRIC_IMAGES, 'wool_001.jpg')
  44 |       const dest   = path.join(watchedFolder, `sync_test_${Date.now()}.jpg`)
  45 |       fs.copyFileSync(source, dest)
  46 | 
  47 |       try {
  48 |         // Wait for auto-index (chokidar debounce + import)
  49 |         await page.waitForTimeout(8_000)
  50 |         const after = parseInt((await countEl.textContent())?.replace(/\D/g, '') ?? '0')
> 51 |         expect(after).toBeGreaterThan(before)
     |                       ^ Error: expect(received).toBeGreaterThan(expected)
  52 |       } finally {
  53 |         // Clean up the test file
  54 |         if (fs.existsSync(dest)) fs.unlinkSync(dest)
  55 |       }
  56 |     } finally {
  57 |       await app.close()
  58 |     }
  59 |   })
  60 | 
  61 |   test.skip('deleting a file marks it orphaned', async () => {
  62 |     /**
  63 |      * STUB — requires pre-indexed images
  64 |      *
  65 |      * Test plan:
  66 |      * 1. Note a specific image filename from the gallery
  67 |      * 2. Delete the file from disk
  68 |      * 3. Restart the app (startup sync will detect the deletion)
  69 |      * 4. Navigate to gallery with "Show orphaned" enabled
  70 |      * 5. Verify the image appears with the "missing" badge
  71 |      * 6. Verify the DB record still exists (not deleted)
  72 |      */
  73 |     assertFixturesPresent()
  74 |     // ... implementation when fixtures are available
  75 |   })
  76 | 
  77 |   test.skip('renaming a file preserves all metadata', async () => {
  78 |     /**
  79 |      * STUB — requires pre-indexed images with label metadata
  80 |      *
  81 |      * Test plan:
  82 |      * 1. Note a specific image's item_no from the detail panel
  83 |      * 2. Rename the file in the watched folder
  84 |      * 3. Wait for chokidar → sync-batch
  85 |      * 4. Find the image in the gallery by new filename
  86 |      * 5. Open detail panel → verify item_no is unchanged
  87 |      * 6. Verify FAISS ID is unchanged (no re-embedding occurred)
  88 |      *
  89 |      * This verifies the MD5 rename reconciliation in sync.py.
  90 |      */
  91 |     assertFixturesPresent()
  92 |     // ... implementation when fixtures are available
  93 |   })
  94 | 
  95 | })
  96 | 
```