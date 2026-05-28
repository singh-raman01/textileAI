/**
 * E2E test helpers for TextileSearch Playwright tests.
 *
 * REAL DATA REQUIRED — see README.md in this directory before running.
 */
import { ElectronApplication, Page, _electron as electron } from '@playwright/test'
import * as path from 'node:path'
import * as fs from 'node:fs'
import * as os from 'node:os'

export const FIXTURES = path.join(__dirname, 'fixtures')
export const FABRIC_IMAGES = path.join(FIXTURES, 'fabric_images')
export const QUERY_IMAGE   = path.join(FIXTURES, 'query', 'search_query.jpg')
export const LABEL_IMAGE   = path.join(FIXTURES, 'labels', 'fafa_label.jpg')

/**
 * Validate that test fixture images are present.
 * Call this at the top of every test file.
 */
export function assertFixturesPresent(): void {
  const required = [
    path.join(FABRIC_IMAGES, 'wool_001.jpg'),
    path.join(FABRIC_IMAGES, 'cotton_001.jpg'),
    QUERY_IMAGE,
    LABEL_IMAGE,
  ]
  const missing = required.filter(p => !fs.existsSync(p))
  if (missing.length > 0) {
    throw new Error(
      `E2E test fixtures missing. See tests/e2e/README.md for setup.\n` +
      `Missing:\n${missing.map(p => `  ${p}`).join('\n')}`
    )
  }
}

/** Launch the Electron app and return the main window. */
export async function launchApp(): Promise<{ app: ElectronApplication; page: Page }> {
  const tmpDir = path.join(os.tmpdir(), `textile-e2e-${Date.now()}`)
  const app = await electron.launch({
    args: ['.'],
    env: {
      ...process.env,
      TEXTILE_USE_MOCK_ML: 'true',   // mock ML for import/sync; switch to real for search accuracy
      NODE_ENV: 'test',
      TEXTILE_DATA_DIR: tmpDir,
    },
  })
  const page = await app.firstWindow()
  return { app, page }
}

/** Wait for the backend health poll to succeed (up to 30 s). */
export async function waitForReady(page: Page): Promise<void> {
  // The app polls /health every 1 s and transitions from loading to ready
  await page.waitForSelector('[data-testid="app-ready"]', { timeout: 30_000 })
}

/** Navigate to a page by clicking its sidebar nav item. */
export async function navigateTo(
  page: Page,
  section: 'search' | 'gallery' | 'import' | 'history' | 'duplicates' | 'settings'
): Promise<void> {
  await page.click(`[data-nav="${section}"]`)
  await page.waitForTimeout(200)
}

/** Drop a file onto an element by simulating drag-and-drop. */
export async function dropFile(page: Page, selector: string, filePath: string): Promise<void> {
  const dataTransfer = await page.evaluateHandle((fp: string) => {
    const dt = new DataTransfer()
    const file = new File([''], fp.split('/').pop() ?? 'file', { type: 'image/jpeg' })
    // Inject the real path so Electron can read it
    Object.defineProperty(file, 'path', { value: fp })
    dt.items.add(file)
    return dt
  }, filePath)

  await page.dispatchEvent(selector, 'dragover', { dataTransfer })
  await page.dispatchEvent(selector, 'drop', { dataTransfer })
}
