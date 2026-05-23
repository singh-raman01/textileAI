/**
 * TextileSearch — File System Watcher
 *
 * Manages chokidar watchers for all registered folders.
 * Events are accumulated in a buffer and flushed to the Python sidecar
 * after a 500 ms debounce window — prevents hammering the DB with
 * individual events during large folder operations (copy, rename, move).
 *
 * Design:
 *  - One chokidar FSWatcher instance per watched folder (allows per-folder stop)
 *  - Added/removed events are buffered in-memory (deduped by path)
 *  - Flush sends a POST /import/sync-batch to the sidecar
 *  - Renames are NOT detected here — chokidar fires unlink+add, and the
 *    sidecar's MD5 reconciliation detects the rename from the matching hash
 */

import chokidar, { FSWatcher } from "chokidar";
import log from "electron-log";
import { BrowserWindow } from "electron";

import type { SyncChangeEvent } from "../../shared/types/ipc";

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

const SUPPORTED_EXTENSIONS = new Set([
  ".jpg", ".jpeg", ".png", ".webp",
  ".tiff", ".tif", ".bmp",
]);

const DEBOUNCE_MS = 500;

// ─────────────────────────────────────────────────────────────────────────────
// State
// ─────────────────────────────────────────────────────────────────────────────

/** Active watcher instances, keyed by the absolute folder path */
const _watchers = new Map<string, FSWatcher>();

/** Pending event buffer */
const _buffer = {
  added:   new Set<string>(),
  removed: new Set<string>(),
};

let _debounceTimer: ReturnType<typeof setTimeout> | null = null;
let _sidecarPort = 8765;

// ─────────────────────────────────────────────────────────────────────────────
// Public API
// ─────────────────────────────────────────────────────────────────────────────

export function setWatcherSidecarPort(port: number): void {
  _sidecarPort = port;
}

/**
 * Start watching a folder.  Idempotent — calling twice for the same path
 * is a no-op.
 */
export function watchFolder(folderPath: string): void {
  if (_watchers.has(folderPath)) {
    log.info("Already watching folder", { folderPath });
    return;
  }

  log.info("Starting folder watcher", { folderPath });

  const watcher = chokidar.watch(folderPath, {
    ignored:        /(^|[/\\])\../,  // ignore dotfiles
    persistent:     true,
    ignoreInitial:  true,            // don't fire for files already on disk at start
    depth:          99,
    awaitWriteFinish: {
      stabilityThreshold: 300,       // wait 300 ms after last write event
      pollInterval:        100,
    },
  });

  watcher
    .on("add",    (path) => _onAdded(path))
    .on("unlink", (path) => _onRemoved(path))
    .on("error",  (err)  => log.error("Watcher error", { folderPath, err: String(err) }));

  _watchers.set(folderPath, watcher);
}

/**
 * Stop watching a folder and remove it from the active set.
 */
export async function unwatchFolder(folderPath: string): Promise<void> {
  const watcher = _watchers.get(folderPath);
  if (!watcher) return;
  await watcher.close();
  _watchers.delete(folderPath);
  log.info("Stopped watching folder", { folderPath });
}

/**
 * Stop all watchers (called at app quit).
 */
export async function stopAllWatchers(): Promise<void> {
  for (const [path, watcher] of _watchers) {
    await watcher.close();
    log.info("Watcher closed", { path });
  }
  _watchers.clear();
  if (_debounceTimer) clearTimeout(_debounceTimer);
}

// ─────────────────────────────────────────────────────────────────────────────
// Internal event handlers
// ─────────────────────────────────────────────────────────────────────────────

function _isSupportedImage(filePath: string): boolean {
  const ext = filePath.slice(filePath.lastIndexOf(".")).toLowerCase();
  return SUPPORTED_EXTENSIONS.has(ext);
}

function _onAdded(filePath: string): void {
  if (!_isSupportedImage(filePath)) return;
  _buffer.removed.delete(filePath);   // cancel a pending remove for the same path
  _buffer.added.add(filePath);
  _schedulFlush();
}

function _onRemoved(filePath: string): void {
  if (!_isSupportedImage(filePath)) return;
  _buffer.added.delete(filePath);     // cancel a pending add for the same path
  _buffer.removed.add(filePath);
  _schedulFlush();
}

function _schedulFlush(): void {
  if (_debounceTimer) clearTimeout(_debounceTimer);
  _debounceTimer = setTimeout(() => void _flush(), DEBOUNCE_MS);
}

async function _flush(): Promise<void> {
  if (_buffer.added.size === 0 && _buffer.removed.size === 0) return;

  const added   = [..._buffer.added];
  const removed = [..._buffer.removed];
  _buffer.added.clear();
  _buffer.removed.clear();
  _debounceTimer = null;

  log.info("Flushing watcher batch", { added: added.length, removed: removed.length });

  try {
    const res = await fetch(`http://127.0.0.1:${_sidecarPort}/import/sync-batch`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ added, removed }),
    });

    if (!res.ok) {
      log.error("sync-batch rejected", { status: res.status });
      return;
    }

    const result = await res.json() as {
      queued: number; orphaned: number; renamed: number; errors: string[];
    };

    log.info("sync-batch complete", result);

    // Notify renderer of file system changes
    const win = BrowserWindow.getAllWindows()[0];
    if (win) {
      if (added.length > 0) {
        const event: SyncChangeEvent = { type: "added",   path: added[0],   count: added.length };
        win.webContents.send("sync:change", event);
      }
      if (removed.length > 0) {
        const event: SyncChangeEvent = { type: "removed", path: removed[0], count: removed.length };
        win.webContents.send("sync:change", event);
      }
      if (result.renamed > 0) {
        const event: SyncChangeEvent = { type: "renamed", path: "",          count: result.renamed };
        win.webContents.send("sync:change", event);
      }
    }
  } catch (err) {
    // Sidecar may be starting — re-buffer the paths for next flush
    log.warn("sync-batch flush failed — re-buffering", { err: String(err) });
    for (const p of added)   _buffer.added.add(p);
    for (const p of removed) _buffer.removed.add(p);
    // Retry after 5 s
    _debounceTimer = setTimeout(() => void _flush(), 5000);
  }
}
