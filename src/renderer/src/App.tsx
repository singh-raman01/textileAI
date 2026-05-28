import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { LoadingScreen } from './components/LoadingScreen'
import { StatusBar } from './components/StatusBar'
import { SearchPage } from './pages/SearchPage'
import { ImportPage } from './pages/ImportPage'
import { HistoryPage } from './pages/HistoryPage'
import { GalleryPage } from './pages/GalleryPage'
import { DuplicatesPage } from './pages/DuplicatesPage'
import { SettingsPage } from './pages/SettingsPage'
import type { SidecarReadyPayload, ImportProgressEvent } from '../../../shared/types/ipc'

type Page = 'search' | 'gallery' | 'import' | 'history' | 'duplicates' | 'settings'
type AppState = 'loading' | 'ready' | 'error'

const NAV_ICONS: Record<string, string> = {
  search:     'M21 21l-5.2-5.2m0 0A7.5 7.5 0 1 0 5.2 5.2a7.5 7.5 0 0 0 10.6 10.6Z',
  gallery:    'M3.75 6A2.25 2.25 0 0 1 6 3.75h2.25A2.25 2.25 0 0 1 10.5 6v2.25a2.25 2.25 0 0 1-2.25 2.25H6a2.25 2.25 0 0 1-2.25-2.25V6ZM3.75 15.75A2.25 2.25 0 0 1 6 13.5h2.25a2.25 2.25 0 0 1 2.25 2.25V18a2.25 2.25 0 0 1-2.25 2.25H6A2.25 2.25 0 0 1 3.75 18v-2.25ZM13.5 6a2.25 2.25 0 0 1 2.25-2.25H18A2.25 2.25 0 0 1 20.25 6v2.25A2.25 2.25 0 0 1 18 10.5h-2.25a2.25 2.25 0 0 1-2.25-2.25V6ZM13.5 15.75a2.25 2.25 0 0 1 2.25-2.25H18a2.25 2.25 0 0 1 2.25 2.25V18A2.25 2.25 0 0 1 18 20.25h-2.25A2.25 2.25 0 0 1 13.5 18v-2.25Z',
  import:     'M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5m-13.5-9L12 3m0 0 4.5 4.5M12 3v13.5',
  history:    'M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z',
  duplicates: 'M15.75 17.25v3.375c0 .621-.504 1.125-1.125 1.125h-9.75a1.125 1.125 0 0 1-1.125-1.125V7.875c0-.621.504-1.125 1.125-1.125H6.75a9.06 9.06 0 0 1 1.5.124m7.5 10.376h3.375c.621 0 1.125-.504 1.125-1.125V11.25c0-4.46-3.243-8.161-7.5-8.876a9.06 9.06 0 0 0-1.5-.124H9.375c-.621 0-1.125.504-1.125 1.125v3.5m7.5 10.375H9.375a1.125 1.125 0 0 1-1.125-1.125v-9.25m12 6.625v-1.875a3.375 3.375 0 0 0-3.375-3.375h-1.5a1.125 1.125 0 0 1-1.125-1.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H9.75',
  settings:   'M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z',
}

export default function App(): JSX.Element {
  const { t, i18n } = useTranslation()
  const [appState, setAppState]  = useState<AppState>('loading')
  const [sidecar, setSidecar]    = useState<SidecarReadyPayload | null>(null)
  const [errorMsg, setErrorMsg]  = useState<string | null>(null)
  const [page, setPage]          = useState<Page>('search')
  const [imageCount, setImageCount] = useState(0)
  const [importProgress, setImportProgress] = useState<ImportProgressEvent | null>(null)

  useEffect(() => {
    let ready = false

    function onReady(s: SidecarReadyPayload) {
      if (ready) return
      ready = true
      clearInterval(poll)
      setSidecar(s)
      setAppState('ready')
      window.api.getSettings().then(s =>
        i18n.changeLanguage(s['language'] ?? 'en')
      ).catch(() => {})
      window.api.dbStatus().then(db =>
        setImageCount(db.image_count)
      ).catch(() => {})
    }

    function onError(msg: string) {
      if (ready) return
      ready = true
      clearInterval(poll)
      setErrorMsg(msg)
      setAppState('error')
    }

    // Event-driven: main process sends sidecar:ready with the correct port
    const offReady = window.api.onSidecarReady(onReady)
    const offError = window.api.onSidecarError(({ message }) => onError(message))

    // Fallback polling in case the IPC event is missed
    let attempts = 0
    const poll = setInterval(async () => {
      attempts++
      try {
        const h = await window.api.health()
        if (h.status === 'ok') {
          onReady({ port: 0, version: h.version, dbPath: '' })
        }
      } catch {
        if (attempts >= 30) {
          onError('Backend failed to start. Check the log folder for details.')
        }
      }
    }, 1000)

    const offProgress = window.api.onImportProgress((e) => {
      setImportProgress(e)
      if (e.done > 0) {
        window.api.dbStatus().then(db => setImageCount(db.image_count)).catch(() => {})
      }
    })

    return () => { clearInterval(poll); offReady(); offError(); offProgress() }
  }, [i18n])

  if (appState === 'loading' || appState === 'error') {
    return <LoadingScreen error={errorMsg} />
  }

  const navItems: { id: Page; labelKey: string }[] = [
    { id: 'search',     labelKey: 'nav.search' },
    { id: 'gallery',    labelKey: 'nav.gallery' },
    { id: 'import',     labelKey: 'nav.import' },
    { id: 'history',    labelKey: 'nav.history' },
    { id: 'duplicates', labelKey: 'nav.duplicates' },
    { id: 'settings',   labelKey: 'nav.settings' },
  ]

  return (
      <div data-testid="app-ready" style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: 'var(--ivory)' }}>

      {/* Top bar */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        height: 42, padding: '0 16px', flexShrink: 0,
        borderBottom: '1px solid var(--border)', background: 'var(--ivory-dark)',
      }}>
        <span style={{ fontSize: 13, fontWeight: 600, letterSpacing: '-0.01em' }}>
          TextileSearch
        </span>
        <button
          onClick={() => i18n.changeLanguage(i18n.language === 'en' ? 'zh-TW' : 'en')}
          className="btn btn-ghost"
          style={{ padding: '3px 10px', fontSize: 12 }}
        >
          {i18n.language === 'en' ? '繁中' : 'EN'}
        </button>
      </div>

      {/* Body */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>

        {/* Sidebar */}
        <aside style={{
          width: 168, flexShrink: 0,
          borderRight: '1px solid var(--border)', background: 'var(--ivory-dark)',
          padding: '10px 8px', display: 'flex', flexDirection: 'column', gap: 2,
        }}>
          {navItems.map(({ id, labelKey }) => (
            <button
              key={id}
              data-nav={id}
              className={`nav-item${page === id ? ' active' : ''}`}
              onClick={() => setPage(id)}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
                stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
                <path d={NAV_ICONS[id]} />
              </svg>
              {t(labelKey)}
            </button>
          ))}

          {/* Import progress pill */}
          {importProgress?.isRunning && (
            <div style={{ marginTop: 'auto', padding: '10px 8px 2px',
                          borderTop: '1px solid var(--border)' }}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>
                {importProgress.percentDone}% — {Math.round(importProgress.speedPerMin ?? 0)}/min
              </div>
              <div className="progress-track">
                <div className="progress-fill" style={{ width: `${importProgress.percentDone}%` }} />
              </div>
            </div>
          )}
        </aside>

        {/* Content */}
        <main style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
          {page === 'search'     && <SearchPage />}
          {page === 'gallery'    && <GalleryPage />}
          {page === 'import'     && <ImportPage onDone={() => setPage('search')} />}
          {page === 'history'    && <HistoryPage onRerun={() => setPage('search')} />}
          {page === 'duplicates' && <DuplicatesPage />}
          {page === 'settings'   && <SettingsPage />}
        </main>
      </div>

      <StatusBar
        sidecar={sidecar}
        imageCount={imageCount}
        isSyncing={importProgress?.isRunning ?? false}
        onOpenLogs={() => window.api.openLogs()}
      />
    </div>
  )
}
