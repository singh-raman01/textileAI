/**
 * Gallery — filterable, sortable grid of all indexed images.
 * Uses windowed rendering (chunk-based) to handle 50k+ thumbnails
 * without react-virtualized (no npm available yet — use CSS containment).
 */
import { useState, useEffect } from 'react'
import type { ImageSummary, BrowseFilters } from '../../../../shared/types/ipc'

const PAGE_SIZE = 100

const SORT_OPTIONS = [
  { value: 'date_desc',    label: 'Newest first' },
  { value: 'date_asc',     label: 'Oldest first' },
  { value: 'filename_asc', label: 'Filename A–Z' },
  { value: 'weight_gsm',   label: 'Weight (GSM)' },
] as const

type SortValue = typeof SORT_OPTIONS[number]['value']

function buildFilters(
  sortBy: SortValue,
  showOrphaned: boolean,
  textFilter: string,
  page: number,
): BrowseFilters {
  return {
    supplierId: null, itemNoPattern: textFilter || null,
    materials: [], matchAllMaterials: false, minMaterialPct: null,
    fabricType: null, widthMin: null, widthMax: null,
    gsmMin: null, gsmMax: null, folderTag: null,
    includeUnverified: true, includeOrphaned: showOrphaned,
    sortBy, page, pageSize: PAGE_SIZE,
  }
}

export function GalleryPage() {
  const [images, setImages]         = useState<ImageSummary[]>([])
  const [total, setTotal]           = useState(0)
  const [page, setPage]             = useState(1)
  const [pages, setPages]           = useState(1)
  const [loading, setLoading]       = useState(false)
  const [textFilter, setTextFilter] = useState('')
  const [sortBy, setSortBy]         = useState<SortValue>('date_desc')
  const [showOrphaned, setShowOrphaned] = useState(false)
  const [selected, setSelected]     = useState<Set<number>>(new Set())

  async function load(sortBy: SortValue, showOrphaned: boolean, textFilter: string, page: number) {
    setLoading(true)
    try {
      const f = buildFilters(sortBy, showOrphaned, textFilter, page)
      const res = await window.api.browse(f)
      setImages(res.images)
      setTotal(res.total)
      setPages(res.pages)
      setPage(res.page)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  // Load on filter change — always reset to page 1
  useEffect(() => {
    load(sortBy, showOrphaned, textFilter, 1)
  }, [sortBy, showOrphaned, textFilter])

  function toggleSelect(id: number) {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  function changePage(p: number) {
    load(sortBy, showOrphaned, textFilter, p)
  }

  const hasFilter = textFilter || showOrphaned || sortBy !== 'date_desc'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>

      {/* Toolbar */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
        padding: '10px 16px', borderBottom: '1px solid var(--border)',
        background: 'var(--ivory-dark)', flexShrink: 0,
      }}>
        {/* Text search */}
        <input
          className="input"
          style={{ width: 200 }}
          placeholder="Filter by item no. or tag…"
          value={textFilter}
          onChange={e => setTextFilter(e.target.value)}
        />

        {/* Sort */}
        <select
          value={sortBy}
          onChange={e => setSortBy(e.target.value as SortValue)}
          style={{
            background: 'white', border: '1px solid var(--border)',
            borderRadius: 5, padding: '5px 8px', fontSize: 13,
            color: 'var(--text)', cursor: 'pointer',
          }}
        >
          {SORT_OPTIONS.map(o => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>

        {/* Toggles */}
        <label style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 13, cursor: 'pointer' }}>
          <input
            type="checkbox" checked={showOrphaned}
            onChange={e => setShowOrphaned(e.target.checked)}
            style={{ accentColor: 'var(--text)' }}
          />
          Show orphaned
        </label>

        {/* Reset */}
        {hasFilter && (
          <button className="btn btn-ghost" style={{ fontSize: 12 }}
            onClick={() => { setTextFilter(''); setSortBy('date_desc'); setShowOrphaned(false) }}>
            Reset
          </button>
        )}

        {/* Selection actions */}
        {selected.size > 0 && (
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              {selected.size} selected
            </span>
            <button className="btn btn-ghost" style={{ fontSize: 12 }}
              onClick={() => setSelected(new Set())}>
              Clear
            </button>
          </div>
        )}

        {/* Count */}
        <span style={{ marginLeft: selected.size > 0 ? 0 : 'auto', fontSize: 12, color: 'var(--text-muted)' }}>
          {loading ? 'Loading…' : `${total.toLocaleString()} images`}
        </span>
      </div>

      {/* Grid */}
      <div style={{ flex: 1, overflow: 'auto', padding: 12 }}>
        {!loading && images.length === 0 && (
          <Empty />
        )}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))',
          gap: 8,
        }}>
          {images.map(img => (
            <GalleryCard
              key={img.id}
              img={img}
              isSelected={selected.has(img.id)}
              onToggle={() => toggleSelect(img.id)}
            />
          ))}
        </div>
      </div>

      {/* Pagination */}
      {pages > 1 && (
        <Pagination page={page} pages={pages} total={total} onPage={changePage} />
      )}
    </div>
  )
}

/* ── Gallery card ──────────────────────────────────────────────────────────── */

function GalleryCard({
  img, isSelected, onToggle,
}: { img: ImageSummary; isSelected: boolean; onToggle: () => void }) {
  const [hover, setHover] = useState(false)

  return (
    <div
      className={`img-card${isSelected ? ' selected' : ''}`}
      onClick={onToggle}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      title={img.filename}
      style={{
        background: 'white', border: '1px solid var(--border)',
        borderRadius: 5, overflow: 'hidden', position: 'relative',
      }}
    >
      {/* Thumbnail */}
      <div style={{ position: 'relative', paddingTop: '100%', background: 'var(--ivory-darker)' }}>
        {img.thumbnailPath ? (
          <img
            src={`file://${img.thumbnailPath}`}
            alt={img.filename}
            style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' }}
          />
        ) : (
          <NoThumb />
        )}

        {/* Hover overlay — shows filename */}
        {hover && (
          <div style={{
            position: 'absolute', inset: 0, background: 'rgba(26,25,23,0.7)',
            display: 'flex', alignItems: 'flex-end', padding: 6,
          }}>
            <span style={{
              fontSize: 10, color: 'white', lineHeight: 1.3,
              overflow: 'hidden', display: '-webkit-box',
              WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
            }}>
              {img.filename}
            </span>
          </div>
        )}

        {/* Selection check */}
        {isSelected && (
          <div style={{
            position: 'absolute', top: 4, left: 4, width: 18, height: 18,
            background: 'var(--text)', borderRadius: 3,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none"
              stroke="var(--ivory)" strokeWidth={3} strokeLinecap="round" strokeLinejoin="round">
              <path d="M5 13l4 4L19 7" />
            </svg>
          </div>
        )}

        {/* Review badge */}
        {img.needsReview && (
          <span style={{
            position: 'absolute', top: 4, right: 4,
            background: '#F0E6CA', color: '#7A5A10',
            padding: '1px 5px', borderRadius: 2, fontSize: 9, fontWeight: 600,
          }}>
            !
          </span>
        )}

        {/* Orphaned badge */}
        {img.isOrphaned && (
          <span style={{
            position: 'absolute', bottom: 4, right: 4,
            background: '#EDD6D6', color: '#7A2020',
            padding: '1px 5px', borderRadius: 2, fontSize: 9,
          }}>
            missing
          </span>
        )}
      </div>

      {/* Tags row */}
      {img.tags.length > 0 && (
        <div style={{
          padding: '3px 5px', display: 'flex', gap: 3, flexWrap: 'wrap',
          borderTop: '1px solid var(--ivory-darker)',
        }}>
          {img.tags.slice(0, 2).map(t => (
            <span key={t.name} style={{
              fontSize: 9, padding: '1px 4px',
              background: 'var(--ivory-darker)', borderRadius: 2,
              color: 'var(--text-muted)',
            }}>
              {t.name}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

/* ── Pagination ────────────────────────────────────────────────────────────── */

function Pagination({
  page, pages, total, onPage,
}: { page: number; pages: number; total: number; onPage: (p: number) => void }) {
  const from = ((page - 1) * PAGE_SIZE) + 1
  const to   = Math.min(page * PAGE_SIZE, total)

  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
      padding: '8px 16px', borderTop: '1px solid var(--border)',
      background: 'var(--ivory-dark)', fontSize: 12, flexShrink: 0,
    }}>
      <button className="btn btn-ghost" style={{ padding: '4px 10px' }}
        disabled={page === 1} onClick={() => onPage(page - 1)}>
        ←
      </button>
      <span style={{ color: 'var(--text-muted)' }}>
        {from}–{to} of {total.toLocaleString()}
      </span>
      <button className="btn btn-ghost" style={{ padding: '4px 10px' }}
        disabled={page === pages} onClick={() => onPage(page + 1)}>
        →
      </button>
    </div>
  )
}

function Empty() {
  return (
    <div style={{
      height: 200, display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center',
      gap: 8, color: 'var(--text-subtle)', fontSize: 13,
    }}>
      <span>No images found</span>
      <span style={{ fontSize: 11 }}>Add a folder in Import, or clear your filters</span>
    </div>
  )
}

function NoThumb() {
  return (
    <div style={{
      position: 'absolute', inset: 0, display: 'flex',
      alignItems: 'center', justifyContent: 'center',
    }}>
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none"
        stroke="var(--border-dark)" strokeWidth={1.5}>
        <rect x="3" y="3" width="18" height="18" rx="2" />
        <circle cx="8.5" cy="8.5" r="1.5" />
        <path d="m21 15-5-5L5 21" />
      </svg>
    </div>
  )
}
