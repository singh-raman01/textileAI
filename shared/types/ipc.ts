/**
 * TextileSearch — IPC channel registry.
 * Single source of truth for every channel name and payload shape.
 */

// ── Sidecar lifecycle ──────────────────────────────────────────────────────────
export const IPC = {
  SIDECAR_READY:    'sidecar:ready',
  SIDECAR_ERROR:    'sidecar:error',
  IMPORT_PROGRESS:  'import:progress',
  SYNC_CHANGE:      'sync:change',
} as const

export interface SidecarReadyPayload {
  port:    number
  version: string
  dbPath:  string
}
export interface SidecarErrorPayload { message: string }

// ── Import ─────────────────────────────────────────────────────────────────────
export interface ImportProgressEvent {
  totalQueued:  number
  done:         number
  failed:       number
  isRunning:    boolean
  isPaused:     boolean
  currentFile:  string
  speedPerMin:  number
  percentDone:  number
}

export interface AddFolderResult {
  folderId:    number
  queuedCount: number
  message:     string
}

// ── Images ─────────────────────────────────────────────────────────────────────
export interface CompositionItem {
  material:    string
  materialRaw: string
  percentage:  number
  tier:        1 | 2 | 3
}

export interface FolderTag {
  name:   string
  source: 'folder' | 'manual'
  color:  string
}

export interface ImageSummary {
  id:            number
  filename:      string
  filePath:      string
  thumbnailPath: string | null
  importStatus:  string
  isOrphaned:    boolean
  dateAdded:     string
  tags:          FolderTag[]
  supplierRaw:   string | null
  itemNo:        string | null
  weightGsm:     number | null
  fabricType:    string | null
  needsReview:   boolean
  similarity:    number | null
}

export interface ImageDetail extends ImageSummary {
  orderNo:          string | null
  construction:     string | null
  widthMin:         number | null
  widthMax:         number | null
  widthUnit:        string | null
  weightGyd:        number | null
  tolerancePct:     number | null
  composition:      CompositionItem[]
  noLabelDetected:  boolean
  manuallyReviewed: boolean
  fileHash:         string | null
  fileSizeBytes:    number | null
  widthPx:          number | null
  heightPx:         number | null
  faissId:          number | null
  relativePath:     string | null
  folderName:       string | null
}

export interface BrowseFilters {
  supplierId:        number | null
  itemNoPattern:     string | null
  materials:         string[]
  matchAllMaterials: boolean
  minMaterialPct:    number | null
  fabricType:        string | null
  widthMin:          number | null
  widthMax:          number | null
  gsmMin:            number | null
  gsmMax:            number | null
  folderTag:         string | null
  includeUnverified: boolean
  includeOrphaned:   boolean
  sortBy:            'date_desc' | 'date_asc' | 'filename_asc' | 'filename_desc' | 'supplier' | 'weight_gsm'
  page:              number
  pageSize:          number
}

export interface BrowseResult {
  total:  number
  page:   number
  pages:  number
  images: ImageSummary[]
}

export interface SearchResult { images: ImageSummary[] }

// ── Search history ─────────────────────────────────────────────────────────────
export interface HistoryEntry {
  id:             number
  queryImagePath: string
  searchedAt:     string
  k:              number
  resultCount:    number
  topResults:     ImageSummary[]   // first 4 for the preview strip
}

// ── Settings ───────────────────────────────────────────────────────────────────
export interface AppSettings { [key: string]: string }
export interface DbStatusResponse {
  schema_version: number
  image_count:    number
  indexed_count:  number
  queued_count:   number
  failed_count:   number
  db_path:        string
}

// ── IpcInvokeMap — used to type invoke() calls ─────────────────────────────────
export interface IpcInvokeMap {
  'system:health':        { payload: void;                                    result: { status: string; version: string; uptime_s: number } }
  'system:db-status':     { payload: void;                                    result: DbStatusResponse }
  'settings:get-all':     { payload: void;                                    result: AppSettings }
  'settings:set':         { payload: { key: string; value: string };          result: AppSettings }
  'import:add-folder':    { payload: { folderPath: string; displayName: string | null }; result: AddFolderResult }
  'import:get-status':    { payload: void;                                    result: ImportProgressEvent }
  'import:pause':         { payload: void;                                    result: { status: string } }
  'import:resume':        { payload: void;                                    result: { status: string } }
  'import:startup-sync':  { payload: void;                                    result: Record<string, number> }
  'images:search':        { payload: { imagePath: string; k: number };        result: SearchResult }
  'images:browse':        { payload: BrowseFilters;                           result: BrowseResult }
  'images:get':           { payload: { id: number };                          result: ImageDetail }
  'dialog:open-folder':   { payload: void;                                    result: string | null }
  'dialog:open-image':    { payload: void;                                    result: string | null }
  'shell:show-in-folder': { payload: { path: string };                        result: void }
  'shell:open-logs':      { payload: void;                                    result: void }
}
