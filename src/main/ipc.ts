/**
 * TextileSearch — Electron IPC Handlers
 *
 * All handlers live here. Each one either:
 *  (a) calls the Python sidecar via HTTP, or
 *  (b) uses an Electron API (dialog, shell)
 *
 * No business logic here — this is a typed HTTP bridge.
 */
import {
  BrowserWindow,
  dialog,
  ipcMain,
  IpcMainInvokeEvent,
  shell,
} from "electron";
import log from "electron-log";
import { readFileSync } from "node:fs";
import * as path from "node:path";

import type {
  AddFolderResult,
  AppSettings,
  BrowseFilters,
  BrowseResult,
  DbStatusResponse,
  ImageDetail,
  ImportProgressEvent,
  SearchResult,
} from "../../shared/types/ipc";

// ─────────────────────────────────────────────────────────────────────────────
// Sidecar URL
// ─────────────────────────────────────────────────────────────────────────────

let _port = 8765;

export function setSidecarPort(p: number): void {
  _port = p;
}

function url(path: string): string {
  return `http://127.0.0.1:${_port}${path}`;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(url(path));
  if (!res.ok) throw new Error(`GET ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(url(path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`POST ${path} → ${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

async function patch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(url(path), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`PATCH ${path} → ${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}
// ─────────────────────────────────────────────────────────────────────────────
// Progress broadcast
// ─────────────────────────────────────────────────────────────────────────────

let _progressTimer: ReturnType<typeof setInterval> | null = null;

export function startProgressBroadcast(): void {
  if (_progressTimer) return;
  _progressTimer = setInterval(async () => {
    const win = BrowserWindow.getAllWindows()[0];
    if (!win) return;
    try {
      const r = await get<{
        total_queued: number;
        done: number;
        failed: number;
        skipped: number;
        is_running: boolean;
        is_paused: boolean;
        current_file: string;
        speed_per_min: number;
      }>("/import/status");
      const total = r.total_queued;
      const event: ImportProgressEvent = {
        totalQueued: total,
        done: r.done,
        failed: r.failed,
        isRunning: r.is_running,
        isPaused: r.is_paused,
        currentFile: r.current_file,
        speedPerMin: r.speed_per_min,
        percentDone: total > 0 ? Math.round((r.done / total) * 100) : 0,
        // skipped: r.skipped,
      };
      win.webContents.send("import:progress", event);
      if (!r.is_running && _progressTimer) {
        clearInterval(_progressTimer);
        _progressTimer = null;
      }
    } catch {
      /* sidecar may be starting */
    }
  }, 1000);
}

// ─────────────────────────────────────────────────────────────────────────────
// Handler registration
// ─────────────────────────────────────────────────────────────────────────────

export function registerIpcHandlers(): void {
  // ── System ──────────────────────────────────────────────────────────────────

  ipcMain.handle("system:health", () =>
    get<{ status: string; version: string; uptime_s: number }>("/health"),
  );

  ipcMain.handle("system:db-status", () => get<DbStatusResponse>("/db/status"));

  ipcMain.handle("settings:get-all", () => get<AppSettings>("/settings"));

  ipcMain.handle(
    "settings:set",
    (_e: IpcMainInvokeEvent, { key, value }: { key: string; value: string }) =>
      patch<AppSettings>("/settings", { key, value }),
  );

  // ── Import ───────────────────────────────────────────────────────────────────

  ipcMain.handle(
    "import:add-folder",
    async (
      _e: IpcMainInvokeEvent,
      {
        folderPath,
        displayName,
      }: { folderPath: string; displayName: string | null },
    ) => {
      const raw = await post<{
        folder_id: number;
        queued_count: number;
        message: string;
      }>("/import/folder", {
        folder_path: folderPath,
        display_name: displayName,
      });
      startProgressBroadcast();
      const result: AddFolderResult = {
        folderId: raw.folder_id,
        queuedCount: raw.queued_count,
        message: raw.message,
      };
      return result;
    },
  );

  ipcMain.handle("import:get-status", async () => {
    const r = await get<{
      total_queued: number;
      done: number;
      failed: number;
      skipped: number;
      is_running: boolean;
      is_paused: boolean;
      current_file: string;
      speed_per_min: number;
    }>("/import/status");
    const total = r.total_queued;
    const result: ImportProgressEvent = {
      totalQueued: total,
      done: r.done,
      failed: r.failed,
      // skipped: r.skipped,
      isRunning: r.is_running,
      isPaused: r.is_paused,
      currentFile: r.current_file,
      speedPerMin: r.speed_per_min,
      percentDone: total > 0 ? Math.round((r.done / total) * 100) : 0,
    };
    return result;
  });

  ipcMain.handle("import:pause", () =>
    post<{ status: string }>("/import/pause"),
  );
  ipcMain.handle("import:resume", () =>
    post<{ status: string }>("/import/resume"),
  );

  ipcMain.handle("import:startup-sync", () =>
    post<Record<string, number>>("/import/startup-sync"),
  );

  // ── Images ───────────────────────────────────────────────────────────────────

  ipcMain.handle(
    "images:search",
    async (
      _e: IpcMainInvokeEvent,
      { imagePath, k }: { imagePath: string; k: number },
    ) => {
      const form = new FormData();
      const bytes = readFileSync(imagePath);
      const blob = new Blob([bytes]);
      const name = path.basename(imagePath);
      form.append("query_image", blob, name);

      const res = await fetch(`${url("/images/search")}?k=${k}`, {
        method: "POST",
        body: form,
      });
      if (!res.ok) throw new Error(`Search → ${res.status}`);
      return res.json() as Promise<SearchResult>;
    },
  );

  ipcMain.handle(
    "images:browse",
    (_e: IpcMainInvokeEvent, filters: BrowseFilters) => {
      const body = {
        page: filters.page,
        page_size: filters.pageSize,
        sort_by: filters.sortBy,
        include_unverified: filters.includeUnverified,
        include_orphaned: filters.includeOrphaned,
        supplier_id: filters.supplierId,
        item_no_pattern: filters.itemNoPattern,
        materials: filters.materials,
        match_all_materials: filters.matchAllMaterials,
        min_material_pct: filters.minMaterialPct,
        fabric_type: filters.fabricType,
        width_min: filters.widthMin,
        width_max: filters.widthMax,
        gsm_min: filters.gsmMin,
        gsm_max: filters.gsmMax,
        folder_tag: filters.folderTag,
      };
      return post<BrowseResult>("/images/browse", body);
    },
  );

  ipcMain.handle(
    "images:get",
    (_e: IpcMainInvokeEvent, { id }: { id: number }) =>
      get<ImageDetail>(`/images/${id}`),
  );

  // ── Dialogs ──────────────────────────────────────────────────────────────────

  ipcMain.handle("dialog:open-folder", async () => {
    const { canceled, filePaths } = await dialog.showOpenDialog({
      properties: ["openDirectory"],
    });
    return canceled ? null : (filePaths[0] ?? null);
  });

  ipcMain.handle("dialog:open-image", async () => {
    const { canceled, filePaths } = await dialog.showOpenDialog({
      properties: ["openFile"],
      filters: [
        {
          name: "Images",
          extensions: ["jpg", "jpeg", "png", "webp", "tiff", "tif", "bmp"],
        },
      ],
    });
    return canceled ? null : (filePaths[0] ?? null);
  });

  // ── Shell ────────────────────────────────────────────────────────────────────

  ipcMain.handle(
    "shell:show-in-folder",
    (_e: IpcMainInvokeEvent, { path: p }: { path: string }) => {
      shell.showItemInFolder(p);
    },
  );

  ipcMain.handle("shell:open-logs", () => {
    const logDir = path.join(
      process.env["APPDATA"] ?? process.env["HOME"] ?? "",
      "TextileSearch",
      "logs",
    );
    return shell.openPath(logDir);
  });

  log.info("IPC handlers registered");
}

// ── History + Duplicates (Phase 4) ────────────────────────────────────────────

export function registerHistoryAndDuplicateHandlers(): void {
  ipcMain.handle(
    "history:log",
    (
      _e: IpcMainInvokeEvent,
      p: { queryImagePath: string; k: number; resultIds: number[] },
    ) =>
      post<{ id: number }>("/history", {
        query_image_path: p.queryImagePath,
        k: p.k,
        result_ids: p.resultIds,
      }),
  );

  ipcMain.handle(
    "history:list",
    (_e: IpcMainInvokeEvent, { limit = 50 }: { limit?: number }) =>
      get<unknown[]>(`/history?limit=${limit}`),
  );

  ipcMain.handle("history:clear", () =>
    (async () => {
      const res = await fetch(url("/history"), { method: "DELETE" });
      if (!res.ok) throw new Error(`DELETE /history → ${res.status}`);
      return res.json();
    })(),
  );

  ipcMain.handle(
    "duplicates:list",
    (
      _e: IpcMainInvokeEvent,
      { includeResolved = false }: { includeResolved?: boolean },
    ) => get<unknown[]>(`/duplicates?include_resolved=${includeResolved}`),
  );

  ipcMain.handle(
    "duplicates:resolve",
    (_e: IpcMainInvokeEvent, { id }: { id: number }) =>
      post<{ status: string }>(`/duplicates/${id}/resolve`),
  );

  ipcMain.handle("duplicates:resolve-all", () =>
    post<{ resolved: number }>("/duplicates/resolve-all"),
  );

  ipcMain.handle("duplicates:count", () =>
    get<{ pending: number }>("/duplicates/count"),
  );
}
