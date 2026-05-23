import { useState, useEffect } from 'react'
import type { HistoryEntry } from '../../../../shared/types/ipc'

interface Props { onRerun: () => void }

export function HistoryPage({ onRerun }: Props) {
  const [entries, setEntries] = useState<HistoryEntry[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    // History endpoint is Phase 3 — show placeholder for now
    setLoading(false)
  }, [])

  if (loading) {
    return <div style={{ padding: 32, color: 'var(--text-muted)', fontSize: 13 }}>Loading…</div>
  }

  if (entries.length === 0) {
    return (
      <div style={{
        height: '100%', display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center',
        color: 'var(--text-subtle)', fontSize: 13, gap: 8,
      }}>
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" strokeWidth={1.2} strokeLinecap="round">
          <path d="M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
        </svg>
        <span>No searches yet</span>
        <button className="btn btn-ghost" style={{ fontSize: 12, marginTop: 4 }} onClick={onRerun}>
          Start searching →
        </button>
      </div>
    )
  }

  return (
    <div style={{ padding: 24, overflow: 'auto', height: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h1 style={{ fontSize: 15, fontWeight: 600 }}>Search history</h1>
        <button className="btn btn-ghost" style={{ fontSize: 12 }}>Clear all</button>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {entries.map(entry => (
          <HistoryRow key={entry.id} entry={entry} />
        ))}
      </div>
    </div>
  )
}

function HistoryRow({ entry }: { entry: HistoryEntry }) {
  const date = new Date(entry.searchedAt)
  return (
    <div style={{
      display: 'flex', gap: 14, alignItems: 'center',
      padding: '10px 14px', background: 'white',
      border: '1px solid var(--border)', borderRadius: 6,
    }}>
      {/* Query thumbnail */}
      <div style={{
        width: 48, height: 48, flexShrink: 0,
        background: 'var(--ivory-darker)', borderRadius: 4, overflow: 'hidden',
      }}>
        <img src={`file://${entry.queryImagePath}`} alt=""
          style={{ width: '100%', height: '100%', objectFit: 'cover' }}
          onError={e => { (e.target as HTMLImageElement).style.display = 'none' }}
        />
      </div>

      {/* Info */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {entry.queryImagePath.split(/[/\\]/).pop()}
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
          {entry.resultCount} results · top {entry.k}
        </div>
      </div>

      {/* Top result strip */}
      <div style={{ display: 'flex', gap: 3 }}>
        {entry.topResults.slice(0, 4).map(img => (
          <div key={img.id} style={{
            width: 36, height: 36, background: 'var(--ivory-darker)',
            borderRadius: 3, overflow: 'hidden',
          }}>
            {img.thumbnailPath && (
              <img src={`file://${img.thumbnailPath}`} alt=""
                style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
            )}
          </div>
        ))}
      </div>

      {/* Date + actions */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 6, flexShrink: 0 }}>
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          {date.toLocaleDateString()} {date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
        </span>
        <button className="btn btn-ghost" style={{ fontSize: 11, padding: '3px 8px' }}>
          Re-run
        </button>
      </div>
    </div>
  )
}
