/**
 * Duplicates — side-by-side comparison of flagged duplicate pairs.
 * Users can mark pairs as resolved. No delete button — deletion is
 * done via File Explorer; the app syncs automatically.
 */
import { useState, useEffect } from 'react'

interface DuplicatePair {
  id:          number
  imageA:      PairImage
  imageB:      PairImage
  similarity:  number
  matchType:   'exact' | 'visual'
  resolved:    boolean
}

interface PairImage {
  id:            number
  filename:      string
  filePath:      string
  thumbnailPath: string | null
  fileSizeBytes: number | null
  dateAdded:     string
  folderName:    string | null
}

export function DuplicatesPage() {
  const [pairs, setPairs]     = useState<DuplicatePair[]>([])
  const [loading, setLoading] = useState(true)
  const [showResolved, setShowResolved] = useState(false)

  useEffect(() => {
    // Phase 3: duplicates endpoint not yet wired to backend
    // Shows the UI structure with an empty state
    setLoading(false)
  }, [])

  const visible = showResolved ? pairs : pairs.filter(p => !p.resolved)

  async function markResolved(id: number) {
    setPairs(prev => prev.map(p => p.id === id ? { ...p, resolved: true } : p))
    // TODO: POST /duplicates/{id}/resolve
  }

  async function markAllResolved() {
    setPairs(prev => prev.map(p => ({ ...p, resolved: true })))
    // TODO: POST /duplicates/resolve-all
  }

  if (loading) {
    return <Centered><span style={{ color: 'var(--text-muted)' }}>Loading…</span></Centered>
  }

  if (pairs.length === 0) {
    return (
      <Centered>
        <svg width="36" height="36" viewBox="0 0 24 24" fill="none"
          stroke="var(--border-dark)" strokeWidth={1.2} strokeLinecap="round">
          <path d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
        </svg>
        <span style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 8 }}>
          No duplicates found
        </span>
        <span style={{ fontSize: 11, color: 'var(--text-subtle)' }}>
          Duplicate detection runs automatically during import
        </span>
      </Centered>
    )
  }

  const pendingCount = pairs.filter(p => !p.resolved).length

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>

      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 12,
        padding: '10px 16px', borderBottom: '1px solid var(--border)',
        background: 'var(--ivory-dark)', flexShrink: 0,
      }}>
        <span style={{ fontSize: 13, fontWeight: 600 }}>
          Duplicates
          {pendingCount > 0 && (
            <span style={{
              marginLeft: 8, background: '#F0E6CA', color: '#7A5A10',
              padding: '1px 7px', borderRadius: 10, fontSize: 11, fontWeight: 600,
            }}>
              {pendingCount}
            </span>
          )}
        </span>

        <label style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 12,
                        cursor: 'pointer', marginLeft: 'auto' }}>
          <input
            type="checkbox" checked={showResolved}
            onChange={e => setShowResolved(e.target.checked)}
            style={{ accentColor: 'var(--text)' }}
          />
          Show resolved
        </label>

        {pendingCount > 1 && (
          <button className="btn btn-ghost" style={{ fontSize: 12 }} onClick={markAllResolved}>
            Mark all resolved
          </button>
        )}
      </div>

      {/* Pairs list */}
      <div style={{ flex: 1, overflow: 'auto', padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
        {visible.map(pair => (
          <PairCard key={pair.id} pair={pair} onResolve={() => markResolved(pair.id)} />
        ))}
        {visible.length === 0 && (
          <div style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: 13, paddingTop: 40 }}>
            All pairs resolved
          </div>
        )}
      </div>
    </div>
  )
}

/* ── Pair card ──────────────────────────────────────────────────────────────── */

function PairCard({ pair, onResolve }: { pair: DuplicatePair; onResolve: () => void }) {
  return (
    <div style={{
      background: 'white', border: '1px solid var(--border)', borderRadius: 6,
      overflow: 'hidden', opacity: pair.resolved ? 0.5 : 1,
    }}>
      {/* Header row */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '8px 14px', borderBottom: '1px solid var(--ivory-darker)',
        background: 'var(--ivory-dark)',
      }}>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <Badge
            label={pair.matchType === 'exact' ? 'Exact' : 'Visual'}
            bg={pair.matchType === 'exact' ? '#EDD6D6' : '#D6EAD8'}
            text={pair.matchType === 'exact' ? '#7A2020' : '#1F4A2E'}
          />
          {pair.matchType === 'visual' && (
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              {Math.round(pair.similarity * 100)}% similar
            </span>
          )}
        </div>

        <div style={{ display: 'flex', gap: 8 }}>
          {!pair.resolved && (
            <button className="btn btn-ghost" style={{ fontSize: 12 }} onClick={onResolve}>
              Mark resolved
            </button>
          )}
          {pair.resolved && (
            <span style={{ fontSize: 12, color: 'var(--text-subtle)' }}>Resolved</span>
          )}
        </div>
      </div>

      {/* Side by side */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1px 1fr' }}>
        <ImagePanel img={pair.imageA} />
        <div style={{ background: 'var(--border)' }} />
        <ImagePanel img={pair.imageB} />
      </div>
    </div>
  )
}

function ImagePanel({ img }: { img: PairImage }) {
  const sizeMb = img.fileSizeBytes != null
    ? `${(img.fileSizeBytes / 1024).toFixed(0)} KB`
    : null

  return (
    <div style={{ padding: 14 }}>
      {/* Thumbnail */}
      <div style={{
        width: '100%', paddingTop: '75%', position: 'relative',
        background: 'var(--ivory-darker)', borderRadius: 4, overflow: 'hidden', marginBottom: 10,
      }}>
        {img.thumbnailPath ? (
          <img src={`file://${img.thumbnailPath}`} alt={img.filename}
            style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'contain' }} />
        ) : (
          <div style={{ position: 'absolute', inset: 0, display: 'flex',
                        alignItems: 'center', justifyContent: 'center' }}>
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none"
              stroke="var(--border-dark)" strokeWidth={1.5}>
              <rect x="3" y="3" width="18" height="18" rx="2" />
            </svg>
          </div>
        )}
      </div>

      {/* Info */}
      <div style={{ fontSize: 12, fontWeight: 500, marginBottom: 4,
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {img.filename}
      </div>
      <div style={{ fontSize: 11, color: 'var(--text-muted)', display: 'flex', flexDirection: 'column', gap: 2 }}>
        {img.folderName && <span>{img.folderName}</span>}
        {sizeMb && <span>{sizeMb}</span>}
        <span>{new Date(img.dateAdded).toLocaleDateString()}</span>
      </div>
      <button
        className="btn btn-ghost"
        style={{ fontSize: 11, marginTop: 8, padding: '3px 8px' }}
        onClick={() => window.api.showInFolder(img.filePath)}
      >
        Show in folder
      </button>
    </div>
  )
}

function Badge({ label, bg, text }: { label: string; bg: string; text: string }) {
  return (
    <span style={{
      padding: '2px 8px', background: bg, color: text,
      borderRadius: 3, fontSize: 11, fontWeight: 600,
    }}>
      {label}
    </span>
  )
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      height: '100%', display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center', gap: 6,
    }}>
      {children}
    </div>
  )
}
