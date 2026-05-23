/**
 * Settings — language, defaults, toggles.
 * All settings are persisted via PATCH /settings through window.api.setSetting.
 */
import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import type { AppSettings } from '../../../../shared/types/ipc'

export function SettingsPage() {
  const { i18n } = useTranslation()
  const [settings, setSettings] = useState<AppSettings>({})
  const [saving, setSaving] = useState<string | null>(null)

  useEffect(() => {
    window.api.getSettings().then(setSettings).catch(console.error)
  }, [])

  async function save(key: string, value: string) {
    setSaving(key)
    try {
      const updated = await window.api.setSetting(key, value)
      setSettings(updated)
      if (key === 'language') {
        await i18n.changeLanguage(value)
      }
    } catch (e) {
      console.error(e)
    } finally {
      setSaving(null)
    }
  }

  function val(key: string, fallback: string) {
    return settings[key] ?? fallback
  }

  return (
    <div style={{ padding: 32, maxWidth: 480, overflow: 'auto', height: '100%' }}>
      <h1 style={{ fontSize: 16, fontWeight: 600, marginBottom: 24 }}>Settings</h1>

      <Section label="Interface">
        <Row label="Language">
          <select
            value={val('language', 'en')}
            onChange={e => save('language', e.target.value)}
            style={selectStyle}
          >
            <option value="en">English</option>
            <option value="zh-TW">繁體中文</option>
          </select>
          {saving === 'language' && <Saving />}
        </Row>
      </Section>

      <Section label="Search">
        <Row label="Default results (k)">
          <select
            value={val('default_k', '20')}
            onChange={e => save('default_k', e.target.value)}
            style={selectStyle}
          >
            {[5, 10, 20, 50, 100].map(n => (
              <option key={n} value={String(n)}>{n}</option>
            ))}
          </select>
          {saving === 'default_k' && <Saving />}
        </Row>

        <Row label="Duplicate threshold">
          <select
            value={val('duplicate_threshold', '0.97')}
            onChange={e => save('duplicate_threshold', e.target.value)}
            style={selectStyle}
          >
            <option value="0.99">0.99 — near-identical only</option>
            <option value="0.97">0.97 — default</option>
            <option value="0.95">0.95 — more matches</option>
            <option value="0.90">0.90 — aggressive</option>
          </select>
          {saving === 'duplicate_threshold' && <Saving />}
        </Row>
      </Section>

      <Section label="Gallery">
        <Row label="Show orphaned images">
          <Toggle
            checked={val('show_orphaned', 'false') === 'true'}
            onChange={v => save('show_orphaned', String(v))}
          />
          {saving === 'show_orphaned' && <Saving />}
        </Row>

        <Row label="Thumbnail cache">
          <select
            value={val('thumbnail_cache_max_mb', '2048')}
            onChange={e => save('thumbnail_cache_max_mb', e.target.value)}
            style={selectStyle}
          >
            <option value="512">512 MB</option>
            <option value="1024">1 GB</option>
            <option value="2048">2 GB (default)</option>
            <option value="4096">4 GB</option>
          </select>
          {saving === 'thumbnail_cache_max_mb' && <Saving />}
        </Row>
      </Section>

      <Section label="About">
        <Row label="Data folder">
          <span className="mono" style={{ fontSize: 11, color: 'var(--text-muted)',
                                          wordBreak: 'break-all' }}>
            {val('data_dir', '—')}
          </span>
        </Row>
        <Row label="Version">
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            {val('app_version', '—')}
          </span>
        </Row>
        <Row label="Logs">
          <button className="btn btn-ghost" style={{ fontSize: 12 }}
            onClick={() => window.api.openLogs()}>
            Open log folder
          </button>
        </Row>
      </Section>
    </div>
  )
}

const selectStyle: React.CSSProperties = {
  background: 'white', border: '1px solid var(--border)', borderRadius: 5,
  padding: '5px 8px', fontSize: 13, color: 'var(--text)', cursor: 'pointer',
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 28 }}>
      <div style={{
        fontSize: 11, fontWeight: 600, color: 'var(--text-muted)',
        textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10,
      }}>
        {label}
      </div>
      <div style={{
        background: 'white', border: '1px solid var(--border)',
        borderRadius: 6, overflow: 'hidden',
      }}>
        {children}
      </div>
    </div>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '10px 14px', borderBottom: '1px solid var(--ivory-darker)',
      gap: 16,
    }}>
      <span style={{ fontSize: 13 }}>{label}</span>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>{children}</div>
    </div>
  )
}

function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      onClick={() => onChange(!checked)}
      style={{
        width: 36, height: 20, borderRadius: 10,
        background: checked ? 'var(--text)' : 'var(--border-dark)',
        border: 'none', cursor: 'pointer', position: 'relative',
        transition: 'background 150ms',
      }}
    >
      <span style={{
        position: 'absolute', top: 2,
        left: checked ? 18 : 2,
        width: 16, height: 16, borderRadius: '50%',
        background: 'white',
        transition: 'left 150ms',
        display: 'block',
      }} />
    </button>
  )
}

function Saving() {
  return <span style={{ fontSize: 11, color: 'var(--text-subtle)' }}>Saving…</span>
}
