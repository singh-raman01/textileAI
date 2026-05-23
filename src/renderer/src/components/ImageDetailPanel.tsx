import type { ImageDetail } from '../../../../shared/types/ipc'

interface Props {
  image:           ImageDetail
  onClose:         () => void
  onSearchSimilar: (img: ImageDetail) => void
}

function Row({ label, value, mono = false }: { label: string; value: string | number | null | undefined; mono?: boolean }) {
  if (value == null || value === '') return null
  return (
    <div style={{ display: 'flex', gap: 8, padding: '5px 0', borderBottom: '1px solid var(--ivory-darker)' }}>
      <span style={{ width: 110, flexShrink: 0, fontSize: 11, color: 'var(--text-muted)' }}>{label}</span>
      <span style={{ fontSize: 12, wordBreak: 'break-all', fontFamily: mono ? 'DM Mono, monospace' : undefined }}>
        {String(value)}
      </span>
    </div>
  )
}

function tierDot(tier: 1 | 2 | 3) {
  const cls = ['', 'tier-1', 'tier-2', 'tier-3'][tier]
  return <span className={cls} style={{ marginLeft: 4, fontSize: 10 }}>●</span>
}

export function ImageDetailPanel({ image, onClose, onSearchSimilar }: Props) {
  const width = image.widthMin != null
    ? image.widthMin === image.widthMax
      ? `${image.widthMin} ${image.widthUnit ?? ''}`
      : `${image.widthMin}–${image.widthMax} ${image.widthUnit ?? ''}`
    : null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>

      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '10px 14px', borderBottom: '1px solid var(--border)',
        flexShrink: 0,
      }}>
        <span style={{ fontSize: 13, fontWeight: 600,
                       overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                       flex: 1 }}>
          {image.filename}
        </span>
        <button
          onClick={onClose}
          style={{ background: 'none', border: 'none', cursor: 'pointer',
                   color: 'var(--text-muted)', fontSize: 18, lineHeight: 1, padding: '0 0 0 8px' }}
        >
          ×
        </button>
      </div>

      {/* Scrollable body */}
      <div style={{ flex: 1, overflow: 'auto', padding: '12px 14px' }}>

        {/* Preview image */}
        {image.thumbnailPath && (
          <div style={{
            width: '100%', paddingTop: '75%', position: 'relative',
            background: 'var(--ivory-darker)', borderRadius: 6,
            overflow: 'hidden', marginBottom: 16,
          }}>
            <img
              src={`file://${image.thumbnailPath}`}
              alt={image.filename}
              style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'contain' }}
            />
          </div>
        )}

        {/* Metadata */}
        <Section label="Label">
          <Row label="Supplier"    value={image.supplierRaw} />
          <Row label="Item no."    value={image.itemNo} />
          <Row label="Order no."   value={image.orderNo} />
          <Row label="Fabric type" value={image.fabricType} />
          <Row label="Construction"value={image.construction} />
        </Section>

        {image.composition.length > 0 && (
          <Section label="Composition">
            {image.composition.map((c, i) => (
              <div key={i} style={{
                display: 'flex', justifyContent: 'space-between',
                padding: '5px 0', borderBottom: '1px solid var(--ivory-darker)',
                fontSize: 12,
              }}>
                <span>
                  {c.material}
                  {c.materialRaw !== c.material && (
                    <span style={{ fontSize: 10, color: 'var(--text-muted)', marginLeft: 4 }}>
                      ({c.materialRaw})
                    </span>
                  )}
                  {tierDot(c.tier)}
                </span>
                <span className="mono">{c.percentage}%</span>
              </div>
            ))}
          </Section>
        )}

        <Section label="Dimensions &amp; Weight">
          <Row label="Width"      value={width} />
          <Row label="Weight GSM" value={image.weightGsm != null ? `${image.weightGsm} g/m²` : null} />
          <Row label="Weight G/YD"value={image.weightGyd != null ? `${image.weightGyd} g/yd` : null} />
          <Row label="Tolerance"  value={image.tolerancePct != null ? `±${image.tolerancePct}%` : null} />
        </Section>

        <Section label="File">
          <Row label="Path"       value={image.relativePath ?? image.filePath} mono />
          <Row label="Folder"     value={image.folderName} />
          <Row label="Size"       value={image.fileSizeBytes != null
            ? `${(image.fileSizeBytes / 1024).toFixed(1)} KB` : null} />
          <Row label="Dimensions" value={
            image.widthPx && image.heightPx ? `${image.widthPx} × ${image.heightPx} px` : null
          } />
          <Row label="FAISS ID"   value={image.faissId} mono />
        </Section>

        {/* Flags */}
        {(image.needsReview || image.noLabelDetected || image.isOrphaned) && (
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
            {image.needsReview    && <Badge label="Needs review" color="#F0E6CA" text="#7A5A10" />}
            {image.noLabelDetected&& <Badge label="No label"     color="#EDD6D6" text="#7A2020" />}
            {image.isOrphaned     && <Badge label="Orphaned"     color="#EDD6D6" text="#7A2020" />}
          </div>
        )}

        {/* Tags */}
        {image.tags.length > 0 && (
          <div style={{ marginTop: 12 }}>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6,
                          fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
              Tags
            </div>
            <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
              {image.tags.map(t => (
                <span key={t.name} style={{
                  padding: '2px 8px', background: 'var(--ivory-darker)',
                  borderRadius: 3, fontSize: 11, color: 'var(--text-muted)',
                }}>
                  {t.name}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Footer actions */}
      <div style={{
        padding: '10px 14px', borderTop: '1px solid var(--border)',
        display: 'flex', gap: 8, flexShrink: 0,
      }}>
        <button className="btn btn-primary" style={{ fontSize: 12, flex: 1 }}
          onClick={() => onSearchSimilar(image)}>
          Search similar
        </button>
        <button className="btn btn-ghost" style={{ fontSize: 12 }}
          onClick={() => window.api.showInFolder(image.filePath)}>
          Show in folder
        </button>
      </div>
    </div>
  )
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  const hasContent = Array.isArray(children)
    ? children.some(c => c !== null && c !== false && c !== undefined)
    : children !== null && children !== false

  if (!hasContent) return null

  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)',
                    textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>
        {label}
      </div>
      {children}
    </div>
  )
}

function Badge({ label, color, text }: { label: string; color: string; text: string }) {
  return (
    <span style={{
      padding: '2px 8px', background: color, color: text,
      borderRadius: 3, fontSize: 11, fontWeight: 500,
    }}>
      {label}
    </span>
  )
}
