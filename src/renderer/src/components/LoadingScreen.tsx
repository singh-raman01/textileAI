interface Props { error: string | null }

export function LoadingScreen({ error }: Props) {
  return (
    <div style={{
      height: '100vh', display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center',
      background: 'var(--ivory)', gap: 12,
    }}>
      <span style={{ fontSize: 15, fontWeight: 600, color: 'var(--text)' }}>TextileSearch</span>
      {error ? (
        <span style={{ fontSize: 12, color: 'var(--danger)', maxWidth: 320, textAlign: 'center' }}>
          {error}
        </span>
      ) : (
        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Starting…</span>
      )}
    </div>
  )
}
