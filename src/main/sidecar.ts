import { ChildProcess, spawn } from 'child_process'
import path from 'path'
import net from 'net'
import { app } from 'electron'
import { logInfo, logWarn, logError, logDebug } from './logger'

// ─────────────────────────────────────────────────────────────────────────────
// Sidecar Manager
// Spawns the Python FastAPI backend as a child process.
// In development:  python3 backend/main.py --port <port> --data-dir <dir>
// In production:   resources/backend/textile-search-backend --port <port> ...
// ─────────────────────────────────────────────────────────────────────────────

const HEALTH_CHECK_INTERVAL_MS = 500
const HEALTH_CHECK_TIMEOUT_MS  = 30_000   // 30 seconds max startup wait
const HEALTH_CHECK_URL         = (port: number) => `http://127.0.0.1:${port}/health`

let sidecarProcess: ChildProcess | null = null
let sidecarPort: number | null = null

// ── Port allocation ───────────────────────────────────────────────────────────

export function getFreePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = net.createServer()
    server.listen(0, '127.0.0.1', () => {
      const address = server.address()
      if (!address || typeof address === 'string') {
        reject(new Error('Could not determine free port'))
        return
      }
      const port = address.port
      server.close(() => resolve(port))
    })
    server.on('error', reject)
  })
}

// ── Spawn ─────────────────────────────────────────────────────────────────────

export async function startSidecar(dataDir: string): Promise<number> {
  if (sidecarProcess) {
    logWarn('Sidecar already running — skipping spawn')
    return sidecarPort!
  }

  const port = await getFreePort()
  sidecarPort = port

  const isDev = !app.isPackaged

  const { executable, args, cwd } = isDev
    ? {
        executable: 'python3',
        args: [
          path.join(app.getAppPath(), 'backend', 'main.py'),
          '--port', String(port),
          '--data-dir', dataDir
        ],
        cwd: path.join(app.getAppPath(), 'backend')
      }
    : {
        // Production: PyInstaller-bundled binary next to the app
        executable: path.join(process.resourcesPath, 'backend', 'textile-search-backend'),
        args: ['--port', String(port), '--data-dir', dataDir],
        cwd: path.join(process.resourcesPath, 'backend')
      }

  logInfo('Spawning Python sidecar', { executable, port, dataDir, isDev })

  sidecarProcess = spawn(executable, args, {
    cwd,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: {
      ...process.env,
      PYTHONUNBUFFERED: '1',   // ensures Python logs appear immediately
    }
  })

  // Route sidecar stdout/stderr to our logger
  sidecarProcess.stdout?.on('data', (chunk: Buffer) => {
    const lines = chunk.toString().trim().split('\n')
    for (const line of lines) {
      if (line) logDebug(`[sidecar-stdout] ${line}`)
    }
  })

  sidecarProcess.stderr?.on('data', (chunk: Buffer) => {
    const lines = chunk.toString().trim().split('\n')
    for (const line of lines) {
      if (line) logWarn(`[sidecar-stderr] ${line}`)
    }
  })

  sidecarProcess.on('error', (err) => {
    logError('Sidecar process error', { message: err.message })
  })

  sidecarProcess.on('exit', (code, signal) => {
    logWarn('Sidecar process exited', { code, signal })
    sidecarProcess = null
    sidecarPort = null
  })

  // Wait until the sidecar is ready to accept requests
  await waitForHealth(port)

  logInfo('Sidecar ready', { port })
  return port
}

// ── Health polling ────────────────────────────────────────────────────────────

async function waitForHealth(port: number): Promise<void> {
  const url = HEALTH_CHECK_URL(port)
  const deadline = Date.now() + HEALTH_CHECK_TIMEOUT_MS

  while (Date.now() < deadline) {
    try {
      // Node 18+ has built-in fetch; for older Node we use a simple http request
      const response = await fetchWithTimeout(url, 1000)
      if (response.ok) return
    } catch {
      // Not ready yet — keep polling
    }
    await sleep(HEALTH_CHECK_INTERVAL_MS)
  }

  throw new Error(`Sidecar did not become healthy within ${HEALTH_CHECK_TIMEOUT_MS / 1000}s`)
}

async function fetchWithTimeout(url: string, timeoutMs: number): Promise<{ ok: boolean }> {
  return new Promise((resolve, reject) => {
    const http = require('http') as typeof import('http')
    const req = http.get(url, (res) => {
      resolve({ ok: res.statusCode === 200 })
      res.resume() // drain the body
    })
    req.setTimeout(timeoutMs, () => {
      req.destroy()
      reject(new Error('timeout'))
    })
    req.on('error', reject)
  })
}

// ── Teardown ──────────────────────────────────────────────────────────────────

export function stopSidecar(): void {
  if (!sidecarProcess) return
  logInfo('Stopping sidecar')
  sidecarProcess.kill('SIGTERM')
  sidecarProcess = null
  sidecarPort = null
}

export function getSidecarPort(): number | null {
  return sidecarPort
}

export function isSidecarRunning(): boolean {
  return sidecarProcess !== null && sidecarPort !== null
}

// ── Utility ───────────────────────────────────────────────────────────────────

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms))
}
