import type { SidecarReadyPayload } from '../../../../shared/types/ipc'

interface Props {
  sidecar:     SidecarReadyPayload | null
  imageCount:  number
  isSyncing:   boolean
  onOpenLogs:  () => void
}

export function StatusBar({ sidecar, imageCount, isSyncing, onOpenLogs }: Props) {
  return (
    <div data-testid="status-bar" style={{
      height: 26, display: 'flex', alignItems: 'center',
      justifyContent: 'space-between', padding: '0 12px',
      borderTop: '1px solid var(--border)',
      background: 'var(--ivory-dark)',
      fontSize: 11, color: 'var(--text-muted)',
      flexShrink: 0,
    }}>
      <span data-testid="image-count">{imageCount.toLocaleString()} images</span>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
        {isSyncing && <span style={{ color: 'var(--text)' }}>● Importing</span>}
        {sidecar && <span className="mono">v{sidecar.version}</span>}
        <button
          onClick={onOpenLogs}
          style={{ background: 'none', border: 'none', cursor: 'pointer',
                   color: 'var(--text-muted)', fontSize: 11, padding: 0 }}
        >
          Logs
        </button>
      </div>
    </div>
  )
}
