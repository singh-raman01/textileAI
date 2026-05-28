import {
  IPC,
  SidecarErrorPayload,
  SidecarReadyPayload,
} from "@shared/types/ipc";
import { app, BrowserWindow, shell } from "electron";
import path from "path";
import { registerIpcHandlers, registerHistoryAndDuplicateHandlers } from "./ipc";
import { logError, logInfo, setupLogger } from "./logger";
import { startSidecar, stopSidecar } from "./sidecar";
import { stopAllWatchers } from "./watcher";

// ─────────────────────────────────────────────────────────────────────────────
// Electron Main Process
// ─────────────────────────────────────────────────────────────────────────────

// Resolve __dirname for ES module contexts (electron-vite uses CJS for main)
const isDev = !app.isPackaged;

// ── Single instance lock ───────────────────────────────────────────────────────
// If a second instance is launched, focus the existing window instead.
// Skip in test mode so each Playwright worker gets a fresh process.
if (process.env.NODE_ENV !== "test") {
  const gotLock = app.requestSingleInstanceLock();
  if (!gotLock) {
    app.quit();
    process.exit(0);
  }

  app.on("second-instance", () => {
    const win = getMainWindow();
    if (win) {
      if (win.isMinimized()) win.restore();
      win.focus();
    }
  });
}

// ── Global state ──────────────────────────────────────────────────────────────
let mainWindow: BrowserWindow | null = null;

function getMainWindow(): BrowserWindow | null {
  return mainWindow;
}

// ── App data directory ────────────────────────────────────────────────────────
// On Linux:   ~/.config/TextileSearch
// On Windows: %APPDATA%\TextileSearch
// On macOS:   ~/Library/Application Support/TextileSearch
function getDataDir(): string {
  if (process.env.TEXTILE_DATA_DIR) return process.env.TEXTILE_DATA_DIR;
  return app.getPath("userData");
}

// ── Window creation ───────────────────────────────────────────────────────────
function createWindow(): BrowserWindow {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    show: false, // shown after 'ready-to-show' to avoid white flash
    backgroundColor: "#F7F4EE",
    title: "TextileSearch",
    webPreferences: {
      preload: path.join(__dirname, "../preload/index.js"),
      contextIsolation: true,
      nodeIntegration: false, // security: renderer has no Node access
      sandbox: false, // required for preload to use contextBridge
    },
  });

  // Open external links in the system browser, not inside Electron
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("https://") || url.startsWith("http://")) {
      shell.openExternal(url);
    }
    return { action: "deny" };
  });

  // Prevent white flash on startup
  win.once("ready-to-show", () => win.show());

  // Load the renderer
  if (isDev && process.env["ELECTRON_RENDERER_URL"]) {
    win.loadURL(process.env["ELECTRON_RENDERER_URL"]);
    win.webContents.openDevTools({ mode: "detach" });
  } else {
    win.loadFile(path.join(__dirname, "../renderer/index.html"));
  }

  return win;
}

// ── Bootstrap sequence ────────────────────────────────────────────────────────
async function bootstrap(): Promise<void> {
  // Logger must be first — everything after this can use logInfo etc.
  setupLogger();
  logInfo("App starting", {
    version: app.getVersion(),
    platform: process.platform,
    arch: process.arch,
    isDev,
    dataDir: getDataDir(),
  });

  // Register all IPC handlers before the window renders
  registerIpcHandlers();
  registerHistoryAndDuplicateHandlers();

  // Create the browser window — it shows the loading screen immediately
  mainWindow = createWindow();

  // Start the Python sidecar. startSidecar() now sets the IPC + watcher
  // port itself, as soon as it's allocated, so renderer polls during
  // cold-start hit the right port (and fail silently) instead of the
  // default 8765 (which floods the log with ECONNREFUSED stack traces).
  try {
    const port = await startSidecar(getDataDir());

    // Fetch version info from the now-running sidecar
    const res = await fetch(`http://127.0.0.1:${port}/health`);
    const health = (await res.json()) as {
      status: string;
      version: string;
      db_path: string;
    };

    const payload: SidecarReadyPayload = {
      port,
      version: health.version,
      dbPath: health.db_path,
    };

    mainWindow.webContents.send(IPC.SIDECAR_READY, payload);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    logError("Failed to start sidecar", { message });

    const payload: SidecarErrorPayload = { message };
    mainWindow?.webContents.send(IPC.SIDECAR_ERROR, payload);
  }
}

// ── Lifecycle ──────────────────────────────────────────────────────────────────
app
  .whenReady()
  .then(bootstrap)
  .catch((err) => {
    console.error("Fatal error during bootstrap:", err);
    app.quit();
  });

app.on("window-all-closed", () => {
  logInfo("All windows closed — quitting");
  // On macOS apps conventionally stay active until Cmd+Q
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  logInfo("App quitting — tearing down");
  stopAllWatchers();
  stopSidecar();
});

app.on("activate", () => {
  // macOS: re-create window when dock icon clicked with no windows open
  if (BrowserWindow.getAllWindows().length === 0) {
    mainWindow = createWindow();
  }
});

// ── Auto-updater (production only) ────────────────────────────────────────────
// Checks GitHub Releases on launch. Never interrupts mid-import.
if (!isDev) {
  try {
    const { autoUpdater } = require("electron-updater");
    autoUpdater.logger = null; // use electron-log instead
    autoUpdater.autoDownload = true;
    autoUpdater.autoInstallOnAppQuit = true;
    autoUpdater.checkForUpdatesAndNotify().catch(() => {
      // Offline or GitHub unreachable — fail silently
    });
  } catch {
    // electron-updater not available in dev builds
  }
}
