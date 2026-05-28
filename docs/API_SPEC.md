# TextileSearch Backend API Specification

> **Base URL:** `http://127.0.0.1:{port}` (port assigned at sidecar startup)  
> **Content-Type:** `application/json` (unless file upload)  
> **CORS:** `http://localhost:*`, `file://`

---

## Table of Contents

1. [Health & System](#1-health--system)
2. [Settings](#2-settings)
3. [Import](#3-import)
4. [Images — Browse & Get](#4-images--browse--get)
5. [Images — Visual Search](#5-images--visual-search)
6. [Search History](#6-search-history)
7. [Duplicates](#7-duplicates)
8. [Error Responses](#8-error-responses)
9. [Data Models](#9-data-models)

---

## 1. Health & System

### `GET /health`

Returns application health status.

**Response `200`:**

```json
{
  "status": "ok",
  "version": "1.0.0",
  "db_path": "/path/to/textile.db",
  "uptime_s": 42.5
}
```

| Field | Type | Description |
|-------|------|-------------|
| `status` | `string` | Always `"ok"` when running |
| `version` | `string` | App version (semver) |
| `db_path` | `string` | Absolute path to SQLite DB |
| `uptime_s` | `float` | Seconds since backend started |

---

### `GET /db/status`

Returns database statistics.

**Response `200`:**

```json
{
  "schema_version": 1,
  "image_count": 1500,
  "indexed_count": 1480,
  "orphaned_count": 3,
  "db_path": "/path/to/textile.db",
  "db_size_mb": 12.34
}
```

| Field | Type | Description |
|-------|------|-------------|
| `schema_version` | `int` | Highest migration version applied |
| `image_count` | `int` | Total image records in DB |
| `indexed_count` | `int` | Images with valid FAISS embedding |
| `orphaned_count` | `int` | Images whose file is missing from disk |
| `db_path` | `string` | Absolute path to SQLite DB |
| `db_size_mb` | `float` | Database file size in MB |

---

## 2. Settings

### `GET /settings`

Returns all application settings as a flat key-value map.

**Response `200`:**

```json
{
  "default_k": "20",
  "duplicate_threshold": "0.97",
  "history_retention_days": "365",
  "disk_space_warning_mb": "500",
  "thumbnail_cache_max_mb": "2048",
  "include_unverified_in_filters": "true",
  "language": "en",
  "theme": "system",
  "debug_logging": "false"
}
```

| Key | Default | Description |
|-----|---------|-------------|
| `default_k` | `"20"` | Default number of search results |
| `duplicate_threshold` | `"0.97"` | Cosine similarity threshold (0–1) |
| `history_retention_days` | `"365"` | Days before auto-deleting history |
| `disk_space_warning_mb` | `"500"` | Free space threshold for warning |
| `thumbnail_cache_max_mb` | `"2048"` | Max thumbnail cache size |
| `include_unverified_in_filters` | `"true"` | Include Tier 2/3 in browse results |
| `language` | `"en"` | UI language code |
| `theme` | `"system"` | UI theme (`"system"`, `"light"`, `"dark"`) |
| `debug_logging` | `"false"` | Enable debug log level |

### `PATCH /settings`

Update a single setting.

**Request:**

```json
{
  "key": "language",
  "value": "zh-TW"
}
```

**Response `200`:**

```json
{
  "ok": true
}
```

| Status | Condition |
|--------|-----------|
| `200` | Success |
| `400` | Unknown setting key |

---

## 3. Import

### `POST /import/folder`

Register a watched folder and queue all supported images for import.

**Request:**

```json
{
  "folder_path": "/Users/alice/Documents/Fabrics",
  "display_name": "My Fabrics"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `folder_path` | `string` | Yes | Absolute path to directory |
| `display_name` | `string` | No | Human-readable name (max 128 chars) |

**Response `202`:**

```json
{
  "folder_id": 1,
  "queued_count": 342,
  "message": "Folder import started (342 images)"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `folder_id` | `int` | Watched folder DB ID |
| `queued_count` | `int` | Number of newly queued images |
| `message` | `string` | Human-readable summary |

| Status | Condition |
|--------|-----------|
| `202` | Accepted (import started or already running) |
| `400` | Path is not a directory |
| `422` | Missing or invalid request body |
| `503` | Import worker not initialised |

**Notes:**
- Idempotent: re-importing the same folder returns the same `folder_id` with `queued_count = 0`
- Only processes new images not already in DB
- Supported extensions: `.jpg`, `.jpeg`, `.png`, `.webp`, `.tiff`, `.tif`, `.bmp`

---

### `GET /import/status`

Returns current import pipeline progress.

**Response `200`:**

```json
{
  "total_queued": 342,
  "processed": 120,
  "failed": 2,
  "skipped": 0,
  "is_running": true,
  "is_paused": false
}
```

| Field | Type | Description |
|-------|------|-------------|
| `total_queued` | `int` | Total images that entered the queue |
| `processed` | `int` | Successfully indexed images |
| `failed` | `int` | Failed images |
| `skipped` | `int` | Skipped images |
| `is_running` | `bool` | Worker thread is alive |
| `is_paused` | `bool` | Worker is paused |

| Status | Condition |
|--------|-----------|
| `200` | Success |
| `503` | Import worker not initialised |

---

### `POST /import/pause`

Pauses the import worker (idempotent).

**Response `200`:** (no body)

### `POST /import/resume`

Resumes the import worker (idempotent).

**Response `200`:** (no body)

---

### `POST /import/sync-batch`

Process a batch of file system events from the chokidar watcher.

**Request:**

```json
{
  "events": [
    {"event_type": "add",  "abs_path": "/path/to/new.jpg"},
    {"event_type": "unlink", "abs_path": "/path/to/removed.jpg"},
    {"event_type": "change", "abs_path": "/path/to/modified.jpg"}
  ]
}
```

| Event Type | Description |
|------------|-------------|
| `add` | New file detected |
| `unlink` | File deleted |
| `change` | File modified |

**Response `200`:**

```json
{
  "queued_for_import": 1,
  "orphaned": 1,
  "requeued": 0,
  "skipped": 0
}
```

| Field | Type | Description |
|-------|------|-------------|
| `queued_for_import` | `int` | New images queued |
| `orphaned` | `int` | Images marked as orphaned |
| `requeued` | `int` | Renamed images (re-linked by MD5) |
| `skipped` | `int` | Events ignored |

| Status | Condition |
|--------|-----------|
| `200` | Success |
| `422` | Invalid event type |

**Notes:**
- Rename detection: if an `add` and `unlink` occur with matching MD5 hashes, the path is updated in-place preserving all metadata
- Called with empty events list is a no-op

---

## 4. Images — Browse & Get

### `POST /images/browse`

List/filter all indexed images without a query image. Supports pagination and metadata filters.

**Request:**

```json
{
  "supplier": "FAFA",
  "fabric_type": "WOVEN",
  "min_gsm": 100,
  "max_gsm": 300,
  "min_width": 50,
  "max_width": 200,
  "needs_review": true,
  "verified_only": false
}
```

All fields are optional. At least one filter is NOT required (returns all images if empty).

| Field | Type | Description |
|-------|------|-------------|
| `supplier` | `string?` | Partial match on supplier name |
| `fabric_type` | `string?` | Partial match on fabric type |
| `min_gsm` | `float?` | Minimum weight (GSM) |
| `max_gsm` | `float?` | Maximum weight (GSM) |
| `min_width` | `float?` | Minimum width |
| `max_width` | `float?` | Maximum width |
| `needs_review` | `bool?` | Only images flagged for review |
| `verified_only` | `bool` | Exclude Tier 2/3 (low confidence) metadata |

**Query Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | `int` | `100` | Max results per page |
| `offset` | `int` | `0` | Pagination offset |

**Response `200`:**

```json
{
  "results": [
    {
      "image": {
        "id": 1,
        "abs_path": "/path/to/image.jpg",
        "filename": "image.jpg",
        "thumbnail_path": "/path/to/thumbnails/01/1.webp",
        "import_status": "done",
        "is_orphaned": false,
        "date_added": "2024-06-15T10:30:00",
        "faiss_id": 1,
        "model_version": "fashion-clip-v1",
        "metadata": {
          "supplier": "FAFA TEXTILES CO. LTD",
          "item_no": "FA-2024-001",
          "order_no": "PO-0001",
          "fabric_type": "WOVEN",
          "width_min": 66.0,
          "width_max": 68.0,
          "width_unit": "IN",
          "weight_gsm": 170.0,
          "weight_gyd": 286.0,
          "tolerance_pct": null,
          "needs_review": false,
          "composition": [
            {
              "material": "POLYESTER",
              "material_raw": "POLYESTER",
              "percentage": 87.0,
              "confidence_tier": 1
            },
            {
              "material": "RAYON",
              "material_raw": "RAYON",
              "percentage": 10.0,
              "confidence_tier": 1
            },
            {
              "material": "LUREX",
              "material_raw": "LUREX",
              "percentage": 2.0,
              "confidence_tier": 1
            },
            {
              "material": "SPANDEX",
              "material_raw": "SPANDEX",
              "percentage": 1.0,
              "confidence_tier": 1
            }
          ]
        }
      },
      "score": null
    }
  ],
  "total": 342,
  "truncated": false
}
```

> **Note:** `score` is always `null` for browse (no query image).

---

### `GET /images/{image_id}`

Get a single image record with full metadata.

**Path Parameters:**
| Param | Type | Description |
|-------|------|-------------|
| `image_id` | `int` | Image DB ID |

**Response `200`:**

```json
{
  "id": 1,
  "abs_path": "/path/to/image.jpg",
  "filename": "image.jpg",
  "thumbnail_path": "/path/to/thumbnails/01/1.webp",
  "import_status": "done",
  "is_orphaned": false,
  "date_added": "2024-06-15T10:30:00",
  "faiss_id": 1,
  "model_version": "fashion-clip-v1",
  "metadata": { "...same shape as browse..." }
}
```

| Status | Condition |
|--------|-----------|
| `200` | Image found |
| `404` | Image not found |

---

## 5. Images — Visual Search

### `POST /images/search`

Upload a query image and find visually similar images from the index.

**Request (multipart/form-data):**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `query_image` | `file` | Yes | — | JPEG/PNG image file |
| `k` | `int` | No | `20` | Number of results (1–200) |
| `supplier` | `string` | No | — | Post-filter by supplier |
| `fabric_type` | `string` | No | — | Post-filter by fabric type |
| `min_gsm` | `float` | No | — | Post-filter min GSM |
| `max_gsm` | `float` | No | — | Post-filter max GSM |
| `verified_only` | `bool` | No | `false` | Exclude Tier 2/3 metadata |

**Response `200`:**

```json
{
  "results": [
    {
      "image": {
        "id": 42,
        "abs_path": "/path/to/similar.jpg",
        "filename": "similar.jpg",
        "thumbnail_path": "/path/to/thumbnails/2a/42.webp",
        "import_status": "done",
        "is_orphaned": false,
        "date_added": "2024-06-15T10:30:00",
        "faiss_id": 42,
        "model_version": "fashion-clip-v1",
        "metadata": null
      },
      "score": 0.8734
    }
  ],
  "total": 20,
  "truncated": false
}
```

| Field | Type | Description |
|-------|------|-------------|
| `results[].score` | `float?` | Cosine similarity (0–1), higher = more similar |
| `total` | `int` | Number of results returned (≤ k) |
| `truncated` | `bool` | `true` if k exceeds total indexed images |

| Status | Condition |
|--------|-----------|
| `200` | Search completed |
| `422` | Missing image, embedding failed, or k out of range |
| `503` | ML models not initialised |

**Search flow:**
1. Embed query image → 512-dim FashionCLIP vector
2. FAISS ANN search with k×20 candidates
3. Post-filter by metadata filters
4. Re-rank by similarity score, return top k

---

## 6. Search History

### `POST /history`

Log a search operation. Called by the Electron main process after every search.

**Request:**

```json
{
  "query_image_path": "/path/to/query.jpg",
  "k": 20,
  "result_ids": [42, 15, 78, 3, 99]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `query_image_path` | `string` | Absolute path to the query image |
| `k` | `int` | Number of results requested |
| `result_ids` | `int[]` | Ordered result image IDs (first 20 stored) |

**Response `200`:**

```json
{
  "id": 1,
  "query_image_path": "/path/to/query.jpg",
  "searched_at": "2024-06-15T10:30:00",
  "k": 20,
  "result_count": 5,
  "top_result_ids": [42, 15, 78, 3, 99]
}
```

---

### `GET /history`

List search history entries, newest first.

**Query Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | `int` | `50` | Max entries |
| `offset` | `int` | `0` | Pagination offset |

**Response `200`:**

```json
[
  {
    "id": 1,
    "query_image_path": "/path/to/query.jpg",
    "searched_at": "2024-06-15T10:30:00",
    "k": 20,
    "result_count": 5,
    "top_result_ids": [42, 15, 78, 3, 99]
  }
]
```

---

### `DELETE /history`

Clear all search history.

**Response `200`:**

```json
{
  "deleted": 15
}
```

| Field | Type | Description |
|-------|------|-------------|
| `deleted` | `int` | Number of entries deleted |

---

### `DELETE /history/{entry_id}`

Delete a single history entry.

| Status | Condition |
|--------|-----------|
| `200` | Deleted |
| `404` | Entry not found |

**Response `200`:**

```json
{
  "status": "deleted"
}
```

---

## 7. Duplicates

### `GET /duplicates`

List duplicate pairs (pending by default).

**Query Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `include_resolved` | `bool` | `false` | Include already-resolved pairs |
| `limit` | `int` | `50` | Max pairs |
| `offset` | `int` | `0` | Pagination offset |

**Response `200`:**

```json
[
  {
    "id": 1,
    "image_a": {
      "id": 10,
      "filename": "fabric_a.jpg",
      "file_path": "/path/to/fabric_a.jpg",
      "thumbnail_path": "/path/to/thumbnails/0a/10.webp",
      "file_size_bytes": 245000,
      "date_added": "2024-06-15T10:30:00",
      "folder_name": "My Fabrics"
    },
    "image_b": {
      "id": 11,
      "filename": "fabric_b.jpg",
      "file_path": "/path/to/fabric_b.jpg",
      "thumbnail_path": "/path/to/thumbnails/0b/11.webp",
      "file_size_bytes": 248000,
      "date_added": "2024-06-15T10:31:00",
      "folder_name": "My Fabrics"
    },
    "similarity": 0.99,
    "match_type": "exact",
    "resolved": false
  }
]
```

| Field | Type | Description |
|-------|------|-------------|
| `match_type` | `string` | `"exact"` (MD5 match) or `"visual"` (cosine similarity) |

---

### `GET /duplicates/count`

Returns pending duplicate count.

**Response `200`:**

```json
{
  "pending": 3
}
```

---

### `POST /duplicates/{pair_id}/resolve`

Mark a single duplicate pair as resolved.

| Status | Condition |
|--------|-----------|
| `200` | Resolved |
| `404` | Pair not found |

**Response `200`:**

```json
{
  "status": "resolved"
}
```

---

### `POST /duplicates/resolve-all`

Mark all unresolved pairs as resolved.

**Response `200`:**

```json
{
  "resolved": 5
}
```

---

## 8. Error Responses

### Standard Error Shape

```json
{
  "detail": "Human-readable error description"
}
```

### HTTP Status Codes

| Code | Meaning | Used By |
|------|---------|---------|
| `200` | Success | All endpoints |
| `202` | Accepted (async) | `POST /import/folder` |
| `400` | Bad Request | Settings (unknown key), Import (invalid path) |
| `404` | Not Found | Images by ID, History entry, Duplicate pair |
| `405` | Method Not Allowed | Wrong HTTP method on any route |
| `422` | Validation Error | Missing fields, invalid k, bad JSON |
| `503` | Service Unavailable | ML not ready, Import worker not initialised |

### Validation Error Shape (422)

```json
{
  "detail": [
    {
      "loc": ["body", "folder_path"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

---

## 9. Data Models

### ImageResponse

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| `id` | `int` | No | Primary key |
| `abs_path` | `string` | No | Absolute file path |
| `filename` | `string` | No | File name |
| `thumbnail_path` | `string?` | Yes | Path to WebP thumbnail |
| `import_status` | `string` | No | `queued` / `processing` / `done` / `failed` |
| `is_orphaned` | `bool` | No | File no longer on disk |
| `date_added` | `string?` | Yes | ISO 8601 datetime |
| `faiss_id` | `int?` | Yes | FAISS vector ID |
| `model_version` | `string?` | Yes | Embedding model version |
| `metadata` | `ImageMetadata?` | Yes | Parsed textile metadata |

### ImageMetadata

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| `supplier` | `string?` | Yes | Supplier/manufacturer name |
| `item_no` | `string?` | Yes | Item/style number |
| `order_no` | `string?` | Yes | Purchase order number |
| `fabric_type` | `string?` | Yes | Fabric type (e.g. `WOVEN`) |
| `width_min` | `float?` | Yes | Min fabric width |
| `width_max` | `float?` | Yes | Max fabric width |
| `width_unit` | `string?` | Yes | `IN` or `CM` |
| `weight_gsm` | `float?` | Yes | Grams per square meter |
| `weight_gyd` | `float?` | Yes | Grams per yard |
| `tolerance_pct` | `float?` | Yes | Weight tolerance % |
| `needs_review` | `bool` | No | True if any field is Tier 2/3 |
| `composition` | `CompositionItem[]` | No | Fabric composition breakdown |

### CompositionItem

| Field | Type | Description |
|-------|------|-------------|
| `material` | `string` | Normalised material name (e.g. `POLYESTER`) |
| `material_raw` | `string` | Raw OCR text (e.g. `POLYSTEER`) |
| `percentage` | `float` | Percentage (0–100) |
| `confidence_tier` | `int` | 1 (high), 2 (medium/needs review), 3 (low) |

### SearchResultItem

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| `image` | `ImageResponse` | No | Image data |
| `score` | `float?` | Yes | Cosine similarity (browse returns `null`) |

### DuplicatePairResponse

| Field | Type | Description |
|-------|------|-------------|
| `id` | `int` | Duplicate pair ID |
| `image_a` | `DuplicateImageInfo` | First image |
| `image_b` | `DuplicateImageInfo` | Second image |
| `similarity` | `float` | Cosine similarity or MD5 match indicator |
| `match_type` | `string` | `"exact"` or `"visual"` |
| `resolved` | `bool` | Whether pair has been reviewed |

### DuplicateImageInfo

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| `id` | `int` | No | Image ID |
| `filename` | `string` | No | File name |
| `file_path` | `string` | No | Absolute path |
| `thumbnail_path` | `string?` | Yes | Thumbnail WebP path |
| `file_size_bytes` | `int?` | Yes | File size |
| `date_added` | `string` | No | ISO 8601 datetime |
| `folder_name` | `string?` | Yes | Watched folder display name |

### HistoryEntryResponse

| Field | Type | Description |
|-------|------|-------------|
| `id` | `int` | Entry ID |
| `query_image_path` | `string` | Query image file path |
| `searched_at` | `string` | ISO 8601 datetime |
| `k` | `int` | Number of results requested |
| `result_count` | `int` | Actual result count |
| `top_result_ids` | `int[]` | Ordered result image IDs |

---

## Frontend Integration Notes

### Preload API (window.api)

The renderer process accesses all backend APIs through the preload bridge:

| Method | Maps to | Notes |
|--------|---------|-------|
| `window.api.health()` | `GET /health` | Polled for sidecar readiness |
| `window.api.dbStatus()` | `GET /db/status` | Displays image count |
| `window.api.getSettings()` | `GET /settings` | Loaded on app start |
| `window.api.setSetting(key, value)` | `PATCH /settings` | Persisted immediately |
| `window.api.addFolder(path, name)` | `POST /import/folder` | |
| `window.api.importStatus()` | `GET /import/status` | Polled every 1s during import |
| `window.api.pauseImport()` | `POST /import/pause` | |
| `window.api.resumeImport()` | `POST /import/resume` | |
| `window.api.search(queryImage, k, filters?)` | `POST /images/search` | Multipart form |
| `window.api.browse(filters?, limit?, offset?)` | `POST /images/browse` | |
| `window.api.getImage(id)` | `GET /images/{id}` | |
| `window.api.logSearch(path, k, ids)` | `POST /history` | Auto-called after search |
| `window.api.getHistory(limit?)` | `GET /history` | |
| `window.api.clearHistory()` | `DELETE /history` | |
| `window.api.getDuplicates(resolved?)` | `GET /duplicates` | |
| `window.api.resolvePair(pairId)` | `POST /duplicates/{id}/resolve` | |
| `window.api.resolveAllPairs()` | `POST /duplicates/resolve-all` | |
| `window.api.dupCount()` | `GET /duplicates/count` | Badge on duplicates tab |

### Event listeners (window.api.on*)

| Listener | Source | Payload |
|----------|--------|---------|
| `onImportProgress(data)` | Polling `GET /import/status` every 1s | `ImportStatusResponse` |
| `onSyncChange(data)` | Chokidar events proxied via IPC | Batch sync result |
| `onSidecarReady()` | Health check success | — |
| `onSidecarError(err)` | Sidecar process error | Error message |
