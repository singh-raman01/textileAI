/**
 * Preload — exposes a typed window.api to the renderer via contextBridge.
 * No Electron or Node APIs are directly accessible in the renderer.
 */
import { contextBridge, ipcRenderer, IpcRendererEvent } from 'electron'
import type {
  ImportProgressEvent, AppSettings, DbStatusResponse,
  AddFolderResult, SearchResult, BrowseResult, BrowseFilters,
  ImageDetail, SidecarReadyPayload, SidecarErrorPayload,
} from '../../shared/types/ipc'

function invoke<T>(channel: string, payload?: unknown): Promise<T> {
  return ipcRenderer.invoke(channel, payload) as Promise<T>
}

function on<T>(channel: string, fn: (data: T) => void): () => void {
  const handler = (_: IpcRendererEvent, data: T) => fn(data)
  ipcRenderer.on(channel, handler)
  return () => ipcRenderer.removeListener(channel, handler)
}

const api = {
  // System
  health:    () => invoke<{ status: string; version: string; uptime_s: number }>('system:health'),
  dbStatus:  () => invoke<DbStatusResponse>('system:db-status'),
  getSettings: () => invoke<AppSettings>('settings:get-all'),
  setSetting:  (key: string, value: string) => invoke<AppSettings>('settings:set', { key, value }),

  // Import
  addFolder:    (p: { folderPath: string; displayName: string | null }) =>
    invoke<AddFolderResult>('import:add-folder', p),
  importStatus: () => invoke<ImportProgressEvent>('import:get-status'),
  pauseImport:  () => invoke<{ status: string }>('import:pause'),
  resumeImport: () => invoke<{ status: string }>('import:resume'),

  // Search
  search:   (p: { imagePath: string; k: number }) => invoke<SearchResult>('images:search', p),
  browse:   (p: BrowseFilters)                     => invoke<BrowseResult>('images:browse', p),
  getImage: (id: number)                           => invoke<ImageDetail>('images:get', { id }),

  // Dialogs
  openFolder: () => invoke<string | null>('dialog:open-folder'),
  openImage:  () => invoke<string | null>('dialog:open-image'),

  // Shell
  showInFolder: (path: string) => invoke<void>('shell:show-in-folder', { path }),
  openLogs:     () => invoke<void>('shell:open-logs'),


  // History
  logSearch:       (p: { queryImagePath: string; k: number; resultIds: number[] }) =>
    invoke<{ id: number }>('history:log', p),
  getHistory:      (limit?: number) => invoke<unknown[]>('history:list', { limit }),
  clearHistory:    () => invoke<{ deleted: number }>('history:clear'),

  // Duplicates
  getDuplicates:   (includeResolved?: boolean) => invoke<unknown[]>('duplicates:list', { includeResolved }),
  resolvePair:     (id: number) => invoke<{ status: string }>('duplicates:resolve', { id }),
  resolveAllPairs: () => invoke<{ resolved: number }>('duplicates:resolve-all'),
  dupCount:        () => invoke<{ pending: number }>('duplicates:count'),
  // Push events
  onImportProgress: (fn: (e: ImportProgressEvent) => void) =>
    on<ImportProgressEvent>('import:progress', fn),
  onSyncChange: (fn: (e: { type: string; count: number }) => void) =>
    on('sync:change', fn),
  onSidecarReady: (fn: (data: SidecarReadyPayload) => void) =>
    on<SidecarReadyPayload>('sidecar:ready', fn),
  onSidecarError: (fn: (data: SidecarErrorPayload) => void) =>
    on<SidecarErrorPayload>('sidecar:error', fn),
} as const

contextBridge.exposeInMainWorld('api', api)

export type ElectronApi = typeof api
