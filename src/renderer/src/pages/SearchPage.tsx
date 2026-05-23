import { useState, useCallback, useRef } from 'react'
import type { ImageSummary, ImageDetail } from '../../../../shared/types/ipc'
import { ImageDetailPanel } from '../components/ImageDetailPanel'

type SearchState = 'idle' | 'searching' | 'results' | 'error'

function simClass(s: number | null): string {
  if (s === null) return ''
  if (s >= 0.90) return 'sim-high'
  if (s >= 0.70) return 'sim-mid'
  return 'sim-low'
}

function simLabel(s: number | null): string {
  if (s === null) return ''
  return `${Math.round(s * 100)}%`
}

export function SearchPage() {
  const [state, setState]           = useState<SearchState>('idle')
  const [results, setResults]       = useState<ImageSummary[]>([])
  const [queryPath, setQueryPath]   = useState<string | null>(null)
  const [queryThumb, setQueryThumb] = useState<string | null>(null)
  const [k, setK]                   = useState(20)
  const [selected, setSelected]     = useState<ImageDetail | null>(null)
  const [error, setError]           = useState<string | null>(null)
  const [isDragOver, setIsDragOver] = useState(false)
  const dropRef = useRef<HTMLDivElement>(null)

  const runSearch = useCallback(async (imagePath: string) => {
    setState('searching')
    setError(null)
    setResults([])
    setSelected(null)
    try {
      const res = await window.api.search({ imagePath, k })
      setResults(res.images)
      setState('results')
    } catch (e) {
      setError(String(e))
      setState('error')
    }
  }, [k])

  async function handlePickImage() {
    const path = await window.api.openImage()
    if (!path) return
    setQueryPath(path)
    setQueryThumb(`file://${path}`)
    runSearch(path)
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    setIsDragOver(false)
    const file = e.dataTransfer.files[0]
    if (!file) return
    const path = (file as { path?: string }).path ?? ''
    if (!path) return
    setQueryPath(path)
    setQueryThumb(`file://${path}`)
    runSearch(path)
  }

  async function handleCardClick(img: ImageSummary) {
    try {
      const detail = await window.api.getImage(img.id)
      setSelected(detail)
    } catch { setSelected(null) }
  }

  async function handleSearchSimilar(img: ImageDetail) {
    setSelected(null)
    setQueryPath(img.filePath)
    setQueryThumb(img.thumbnailPath ? `file://${img.thumbnailPath}` : null)
    runSearch(img.filePath)
  }

  const isEmpty = state === 'idle'

  return (
    <div style={{ display: 'flex', flex: 1, overflow: 'hidden', position: 'relative' }}>

      {/* Left: query + results */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

        {/* Query area */}
        <div style={{
          padding: '16px 20px',
          borderBottom: '1px solid var(--border)',
          display: 'flex', alignItems: 'center', gap: 16, flexShrink: 0,
        }}>
          {/* Drop zone / thumbnail */}
          <div
            ref={dropRef}
            className={isDragOver ? 'dropzone-active' : ''}
            onDragOver={e => { e.preventDefault(); setIsDragOver(true) }}
            onDragLeave={() => setIsDragOver(false)}
            onDrop={handleDrop}
            onClick={handlePickImage}
            style={{
              width: 72, height: 72,
              border: '1px dashed var(--border-dark)',
              borderRadius: 6,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              cursor: 'pointer', overflow: 'hidden', flexShrink: 0,
              background: 'white',
            }}
          >
            {queryThumb ? (
              <img src={queryThumb} alt="query"
                style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
            ) : (
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none"
                stroke="var(--text-subtle)" strokeWidth={1.5} strokeLinecap="round">
                <rect x="3" y="3" width="18" height="18" rx="2" />
                <circle cx="8.5" cy="8.5" r="1.5" />
                <path d="m21 15-5-5L5 21" />
              </svg>
            )}
          </div>

          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }}>
              {queryPath
                ? queryPath.split(/[/\\]/).pop()
                : 'Drop an image or click to pick one'}
            </div>

            {/* k slider */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ fontSize: 11, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
                Top results
              </span>
              <input
                type="range" min={5} max={100} step={5} value={k}
                onChange={e => setK(Number(e.target.value))}
                style={{ width: 100, accentColor: 'var(--text)' }}
              />
              <span className="mono" style={{ fontSize: 12, minWidth: 28 }}>{k}</span>

              {queryPath && (
                <button className="btn btn-ghost" style={{ fontSize: 12, marginLeft: 8 }}
                  onClick={() => runSearch(queryPath!)}>
                  Search
                </button>
              )}
            </div>
          </div>

          {/* Result count */}
          {state === 'results' && (
            <span style={{ fontSize: 12, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
              {results.length} results
            </span>
          )}
        </div>

        {/* Results area */}
        <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
          {isEmpty && (
            <div style={{
              height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center',
              color: 'var(--text-subtle)', fontSize: 13,
            }}>
              Drop or pick a fabric image to search
            </div>
          )}
          {state === 'searching' && (
            <div style={{ color: 'var(--text-muted)', fontSize: 13, padding: 20 }}>
              Searching…
            </div>
          )}
          {error && (
            <div style={{
              padding: '10px 14px', background: '#FFF0F0', border: '1px solid #EDD6D6',
              borderRadius: 5, fontSize: 12, color: 'var(--danger)', margin: 4,
            }}>
              {error}
            </div>
          )}
          {state === 'results' && results.length === 0 && (
            <div style={{ color: 'var(--text-muted)', fontSize: 13, padding: 20 }}>
              No results found.
            </div>
          )}
          {state === 'results' && results.length > 0 && (
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))',
              gap: 10,
            }}>
              {results.map(img => (
                <ImageCard
                  key={img.id}
                  img={img}
                  isSelected={selected?.id === img.id}
                  onClick={() => handleCardClick(img)}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Right: detail panel */}
      <div
        className={`detail-panel ${selected ? 'detail-panel-open' : 'detail-panel-closed'}`}
        style={{
          position: 'absolute', right: 0, top: 0, bottom: 0,
          width: 320,
          borderLeft: '1px solid var(--border)',
          background: 'var(--ivory)',
          overflow: 'hidden',
        }}
      >
        {selected && (
          <ImageDetailPanel
            image={selected}
            onClose={() => setSelected(null)}
            onSearchSimilar={handleSearchSimilar}
          />
        )}
      </div>
    </div>
  )
}

/* ── Image card ──────────────────────────────────────────────────────────────── */
interface CardProps {
  img:        ImageSummary
  isSelected: boolean
  onClick:    () => void
}

function ImageCard({ img, isSelected, onClick }: CardProps) {
  return (
    <div
      className={`img-card${isSelected ? ' selected' : ''}`}
      onClick={onClick}
      style={{
        background: 'white',
        border: '1px solid var(--border)',
        borderRadius: 6,
        overflow: 'hidden',
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
          <div style={{
            position: 'absolute', inset: 0, display: 'flex',
            alignItems: 'center', justifyContent: 'center',
          }}>
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none"
              stroke="var(--border-dark)" strokeWidth={1.5}>
              <rect x="3" y="3" width="18" height="18" rx="2" />
              <circle cx="8.5" cy="8.5" r="1.5" />
              <path d="m21 15-5-5L5 21" />
            </svg>
          </div>
        )}
        {/* Similarity badge */}
        {img.similarity !== null && (
          <span
            className={simClass(img.similarity)}
            style={{
              position: 'absolute', top: 5, right: 5,
              padding: '2px 6px', borderRadius: 3,
              fontSize: 11, fontWeight: 600,
            }}
          >
            {simLabel(img.similarity)}
          </span>
        )}
        {/* Review badge */}
        {img.needsReview && (
          <span style={{
            position: 'absolute', top: 5, left: 5,
            background: '#F0E6CA', color: '#7A5A10',
            padding: '2px 6px', borderRadius: 3, fontSize: 10,
          }}>
            Review
          </span>
        )}
      </div>

      {/* Caption */}
      <div style={{ padding: '7px 8px' }}>
        <div style={{
          fontSize: 11, fontWeight: 500,
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}>
          {img.filename}
        </div>
        {(img.supplierRaw || img.fabricType) && (
          <div style={{
            fontSize: 10, color: 'var(--text-muted)', marginTop: 2,
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>
            {[img.supplierRaw, img.fabricType].filter(Boolean).join(' · ')}
          </div>
        )}
      </div>
    </div>
  )
}
