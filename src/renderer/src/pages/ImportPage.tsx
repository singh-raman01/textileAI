import { useState, useEffect } from 'react'
import type { ImportProgressEvent } from '../../../../shared/types/ipc'

interface Props { onDone: () => void }

export function ImportPage({ onDone }: Props) {
  const [progress, setProgress] = useState<ImportProgressEvent | null>(null)
  const [folders, setFolders]   = useState<string[]>([])
  const [error, setError]       = useState<string | null>(null)
  const [scanning, setScanning] = useState<string | null>(null)

  // Listen for progress push events
  useEffect(() => {
    const off = window.api.onImportProgress(setProgress)
    // Get initial status
    window.api.importStatus().then(setProgress).catch(() => {})
    return off
  }, [])

  async function handleAddFolder() {
    setError(null)
    try {
      const folderPath = await window.api.openFolder()
      if (!folderPath) return
      // Show "Scanning folder…" right away so the user sees feedback
      // during the (potentially slow) backend folder walk + DB insert.
      setScanning(folderPath)
      await window.api.addFolder({ folderPath, displayName: null })
      setFolders(prev => [...prev, folderPath])
      // Trigger status refresh
      const status = await window.api.importStatus()
      setProgress(status)
    } catch (e) {
      setError(String(e))
    } finally {
      setScanning(null)
    }
  }

  const pct  = progress?.percentDone ?? 0
  const done = progress?.done ?? 0
  const total= progress?.totalQueued ?? 0
  const running = progress?.isRunning ?? false

  return (
    <div style={{ padding: 32, maxWidth: 560 }}>
      <h1 style={{ fontSize: 16, fontWeight: 600, marginBottom: 6 }}>Import Library</h1>
      <p style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 24 }}>
        Add a folder of fabric images. All subfolders are scanned automatically.
        New files are picked up in real time — no need to re-import.
      </p>

      {/* Add folder button */}
      <button
        data-testid="add-folder-btn"
        className="btn btn-primary"
        onClick={handleAddFolder}
        disabled={scanning !== null}
        style={{ marginBottom: 24, opacity: scanning !== null ? 0.6 : 1 }}
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 4v16m8-8H4" />
        </svg>
        {scanning ? 'Scanning…' : 'Add folder'}
      </button>

      {scanning && (
        <div style={{ padding: '8px 12px', background: '#F0F7FF', border: '1px solid #D6E2ED',
                      borderRadius: 5, fontSize: 12, color: 'var(--text-muted)', marginBottom: 16,
                      display: 'flex', alignItems: 'center', gap: 8 }}>
          <span className="spinner" style={{
            width: 12, height: 12, border: '2px solid #C5D2DD', borderTopColor: 'var(--accent, #4A6FA5)',
            borderRadius: '50%', display: 'inline-block', animation: 'spin 0.8s linear infinite',
          }} />
          <span>Scanning <span className="mono">{scanning}</span> for images…</span>
        </div>
      )}

      {error && (
        <div style={{ padding: '8px 12px', background: '#FFF0F0', border: '1px solid #EDD6D6',
                      borderRadius: 5, fontSize: 12, color: 'var(--danger)', marginBottom: 16 }}>
          {error}
        </div>
      )}

      {/* Watched folders */}
      {folders.length > 0 && (
        <div style={{ marginBottom: 24 }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)',
                        textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>
            Watched folders
          </div>
          {folders.map(f => (
            <div key={f} style={{
              padding: '7px 10px', background: 'white', border: '1px solid var(--border)',
              borderRadius: 5, fontSize: 12, marginBottom: 4,
              display: 'flex', alignItems: 'center', gap: 8,
            }}>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                <path d="M3 7a2 2 0 0 1 2-2h4l2 3h8a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
              </svg>
              <span className="mono" style={{ color: 'var(--text-muted)' }}>{f}</span>
            </div>
          ))}
        </div>
      )}

      {/* Progress panel — shown while running */}
      {(running || total > 0) && (
        <div data-testid="import-progress-bar" style={{
          padding: 20, background: 'white', border: '1px solid var(--border)',
          borderRadius: 6,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between',
                        alignItems: 'baseline', marginBottom: 10 }}>
            <span style={{ fontSize: 13, fontWeight: 500 }}>
              {running ? 'Importing…' : 'Complete'}
            </span>
            <span className="mono" style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              {done} / {total}
            </span>
          </div>

          <div className="progress-track" style={{ marginBottom: 10 }}>
            <div className="progress-fill" style={{ width: `${pct}%` }} />
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between',
                        fontSize: 11, color: 'var(--text-muted)' }}>
            <span>{progress?.currentFile
              ? progress.currentFile.split(/[/\\]/).pop()
              : running ? 'Starting…' : 'Done'
            }</span>
            <span>
              {progress?.failed ? (
                <span style={{ color: 'var(--danger)' }}>{progress.failed} failed</span>
              ) : null}
              {progress?.speedPerMin ? ` · ${Math.round(progress.speedPerMin)}/min` : ''}
            </span>
          </div>

          {/* Actions */}
          <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
            {running && !progress?.isPaused && (
              <button className="btn btn-ghost" style={{ fontSize: 12 }}
                onClick={() => window.api.pauseImport()}>
                Pause
              </button>
            )}
            {running && progress?.isPaused && (
              <button className="btn btn-ghost" style={{ fontSize: 12 }}
                onClick={() => window.api.resumeImport()}>
                Resume
              </button>
            )}
            {!running && done > 0 && (
              <button data-testid="search-now-btn" className="btn btn-primary" style={{ fontSize: 12 }} onClick={onDone}>
                Search now →
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
