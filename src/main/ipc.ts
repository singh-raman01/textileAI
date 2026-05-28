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
        processed: number;
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
        done: r.processed,
        failed: r.failed,
        isRunning: r.is_running,
        isPaused: r.is_paused,
        currentFile: r.current_file,
        speedPerMin: r.speed_per_min,
        percentDone: total > 0 ? Math.round((r.processed / total) * 100) : 0,
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

  ipcMain.handle("system:health", async () => {
    // Renderer polls this on a 1s timer until the sidecar is ready. While
    // the Python process is still loading models (can take 60-120s on a
    // cold start), every fetch errors with ECONNREFUSED. Return a sentinel
    // instead of throwing so Electron doesn't log a stack trace per poll.
    try {
      return await get<{ status: string; version: string; uptime_s: number }>("/health");
    } catch {
      return { status: "starting", version: "", uptime_s: 0 };
    }
  });

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
        display_name: displayName ?? "",
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
      processed: number;
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
      done: r.processed,
      failed: r.failed,
      // skipped: r.skipped,
      isRunning: r.is_running,
      isPaused: r.is_paused,
      currentFile: r.current_file,
      speedPerMin: r.speed_per_min,
      percentDone: total > 0 ? Math.round((r.processed / total) * 100) : 0,
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
      const raw = await res.json() as { results: Array<{ image: { id: number; filename: string; abs_path: string; thumbnail_path: string | null; import_status: string; is_orphaned: boolean; date_added: string; metadata: { supplier: string | null; item_no: string | null; weight_gsm: number | null; fabric_type: string | null; needs_review: boolean } | null }; score: number | null }>; total: number };
      const images: SearchResult["images"] = raw.results.map(r => ({
        id: r.image.id,
        filename: r.image.filename,
        filePath: r.image.abs_path,
        thumbnailPath: r.image.thumbnail_path,
        importStatus: r.image.import_status,
        isOrphaned: r.image.is_orphaned,
        dateAdded: r.image.date_added,
        tags: [],
        supplierRaw: r.image.metadata?.supplier ?? null,
        itemNo: r.image.metadata?.item_no ?? null,
        weightGsm: r.image.metadata?.weight_gsm ?? null,
        fabricType: r.image.metadata?.fabric_type ?? null,
        needsReview: r.image.metadata?.needs_review ?? false,
        similarity: r.score,
      }));
      return { images };
    },
  );

  ipcMain.handle(
    "images:browse",
    async (_e: IpcMainInvokeEvent, filters: BrowseFilters) => {
      // Map BrowseFilters (camelCase, frontend conventions) → backend ImageFilters (snake_case, API spec)
      const body: Record<string, unknown> = {};
      if (filters.fabricType != null)      body["fabric_type"]  = filters.fabricType;
      if (filters.gsmMin != null)          body["min_gsm"]      = filters.gsmMin;
      if (filters.gsmMax != null)          body["max_gsm"]      = filters.gsmMax;
      if (filters.widthMin != null)        body["min_width"]    = filters.widthMin;
      if (filters.widthMax != null)        body["max_width"]    = filters.widthMax;
      // verified_only is the inverse of includeUnverified
      if (!filters.includeUnverified)      body["verified_only"] = true;
      // itemNoPattern → item_no partial match (backend extended field)
      if (filters.itemNoPattern != null)   body["item_no_pattern"] = filters.itemNoPattern;
      // include_orphaned (backend extended field)
      if (filters.includeOrphaned)         body["include_orphaned"] = true;
      // sort_by (backend extended field)
      if (filters.sortBy)                  body["sort_by"] = filters.sortBy;

      // Pagination: backend uses limit/offset query params
      const limit  = filters.pageSize || 100;
      const offset = ((filters.page || 1) - 1) * limit;

      type RawImage = {
        id: number; filename: string; abs_path: string;
        thumbnail_path: string | null; import_status: string;
        is_orphaned: boolean; date_added: string;
        metadata: {
          supplier: string | null; item_no: string | null;
          weight_gsm: number | null; fabric_type: string | null;
          needs_review: boolean;
        } | null;
      };
      const rawUrl = url(`/images/browse?limit=${limit}&offset=${offset}`);
      const res = await fetch(rawUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const detail = await res.text().catch(() => "");
        throw new Error(`POST /images/browse → ${res.status}: ${detail}`);
      }
      const raw = await res.json() as { results: Array<{ image: RawImage; score: number | null }>; total: number };

      const total = raw.total;
      const page  = filters.page || 1;
      const pages = Math.max(1, Math.ceil(total / limit));

      const images = raw.results.map((r) => ({
        id:           r.image.id,
        filename:     r.image.filename,
        filePath:     r.image.abs_path,
        thumbnailPath:r.image.thumbnail_path,
        importStatus: r.image.import_status,
        isOrphaned:   r.image.is_orphaned,
        dateAdded:    r.image.date_added,
        tags:         [],
        supplierRaw:  r.image.metadata?.supplier ?? null,
        itemNo:       r.image.metadata?.item_no ?? null,
        weightGsm:    r.image.metadata?.weight_gsm ?? null,
        fabricType:   r.image.metadata?.fabric_type ?? null,
        needsReview:  r.image.metadata?.needs_review ?? false,
        similarity:   r.score,
      }));

      const result: BrowseResult = { total, page, pages, images };
      return result;
    },
  );

  ipcMain.handle(
    "images:get",
    async (_e: IpcMainInvokeEvent, { id }: { id: number }) => {
      type RawBackendImage = {
        id: number; abs_path: string; filename: string;
        thumbnail_path: string | null; import_status: string;
        is_orphaned: boolean; date_added: string | null;
        faiss_id: number | null; model_version: string | null;
        file_hash: string | null; file_size_bytes: number | null;
        width_px: number | null; height_px: number | null;
        relative_path: string | null; folder_name: string | null;
        metadata: {
          supplier: string | null; item_no: string | null; order_no: string | null;
          fabric_type: string | null; construction: string | null;
          width_min: number | null; width_max: number | null; width_unit: string | null;
          weight_gsm: number | null; weight_gyd: number | null; tolerance_pct: number | null;
          needs_review: boolean; no_label_detected: boolean;
          composition: Array<{
            material: string; material_raw: string;
            percentage: number; confidence_tier: number;
          }>;
        } | null;
      };
      const raw = await get<RawBackendImage>(`/images/${id}`);
      const detail: ImageDetail = {
        id:            raw.id,
        filename:      raw.filename,
        filePath:      raw.abs_path,
        thumbnailPath: raw.thumbnail_path,
        importStatus:  raw.import_status,
        isOrphaned:    raw.is_orphaned,
        dateAdded:     raw.date_added ?? "",
        tags:          [],
        supplierRaw:   raw.metadata?.supplier ?? null,
        itemNo:        raw.metadata?.item_no ?? null,
        weightGsm:     raw.metadata?.weight_gsm ?? null,
        fabricType:    raw.metadata?.fabric_type ?? null,
        needsReview:   raw.metadata?.needs_review ?? false,
        similarity:    null,
        orderNo:       raw.metadata?.order_no ?? null,
        construction:  raw.metadata?.construction ?? null,
        widthMin:      raw.metadata?.width_min ?? null,
        widthMax:      raw.metadata?.width_max ?? null,
        widthUnit:     raw.metadata?.width_unit ?? null,
        weightGyd:     raw.metadata?.weight_gyd ?? null,
        tolerancePct:  raw.metadata?.tolerance_pct ?? null,
        composition:   (raw.metadata?.composition ?? []).map(c => ({
          material:    c.material,
          materialRaw: c.material_raw,
          percentage:  c.percentage,
          tier:        c.confidence_tier as 1 | 2 | 3,
        })),
        noLabelDetected:  raw.metadata?.no_label_detected ?? false,
        manuallyReviewed: false,
        fileHash:         raw.file_hash,
        fileSizeBytes:    raw.file_size_bytes,
        widthPx:          raw.width_px,
        heightPx:         raw.height_px,
        faissId:          raw.faiss_id,
        relativePath:     raw.relative_path,
        folderName:       raw.folder_name,
      };
      return detail;
    },
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
