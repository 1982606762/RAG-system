import { useCallback, useEffect, useRef, useState, type DragEvent } from 'react'
import axios from 'axios'
import { type DocumentRecord, listDocuments, retryDocument, uploadDocument } from '../api'
import { useT } from '../i18n'
import { useAuth } from '../store'
import DocumentReader from '../components/DocumentReader'
import ReaderDrawer from '../components/ReaderDrawer'
import SearchPanel from '../components/SearchPanel'
import LangSwitch from '../components/LangSwitch'
import Icon, { type IconName } from '../components/Icon'
import { EmbeddingLabel } from '../components/EmbeddingPanel'

type View = 'library' | 'search'
const navigation: { view: View; label: 'library' | 'navSearch'; icon: IconName }[] = [
  { view: 'library', label: 'library', icon: 'library' },
  { view: 'search', label: 'navSearch', icon: 'search' },
]

export default function WorkspacePage() {
  const t = useT()
  const logout = useAuth(state => state.logout)
  const [view, setView] = useState<View>('library')
  const [documents, setDocuments] = useState<DocumentRecord[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState<string | null>(null)
  const [sourceBlock, setSourceBlock] = useState<number | null>(null)
  const [revision, setRevision] = useState(0)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [progress, setProgress] = useState(0)
  const [error, setError] = useState('')
  const [loadError, setLoadError] = useState<'schemaMissing' | 'loadError'>()
  const [notice, setNotice] = useState<'duplicate' | 'uploaded' | 'uploadFailed' | 'processing' | null>(null)
  const input = useRef<HTMLInputElement>(null)
  const requestVersion = useRef(0)
  const currentOffset = useRef(offset)
  currentOffset.current = offset
  const operation = useRef(false)
  const dragDepth = useRef(0)

  const refresh = useCallback(async () => {
    if (offset !== currentOffset.current) return
    const version = ++requestVersion.current
    setLoading(true)
    try {
      const { data } = await listDocuments(offset)
      if (version !== requestVersion.current) return
      setDocuments(data.items)
      setTotal(data.total)
      setLoadError(undefined)
    } catch (err) {
      if (version !== requestVersion.current) return
      setLoadError(axios.isAxiosError(err) && err.response?.data?.code === 'schema_missing' ? 'schemaMissing' : 'loadError')
    } finally {
      if (version === requestVersion.current) setLoading(false)
    }
  }, [offset])

  useEffect(() => { void refresh(); return () => { requestVersion.current++ } }, [refresh])

  async function ingest(file: File) {
    if (operation.current) return
    setNotice(null)
    if (!/\.(pdf|txt|md|png|jpe?g|webp)$/i.test(file.name)) { setError('unsupportedFile'); return }
    if (file.size > 20 * 1024 * 1024) { setError('fileTooLarge'); return }
    operation.current = true
    setBusy(true)
    setProgress(0)
    setError('')
    try {
      const { data } = await uploadDocument(file, setProgress)
      setSelected(data.document.id)
      setSourceBlock(null)
      setRevision(value => value + 1)
      setNotice(data.duplicate ? 'duplicate' : data.document.status === 'ready' ? 'uploaded'
        : data.document.status === 'processing' ? 'processing' : 'uploadFailed')
      await refresh()
    } catch (err) {
      await refresh()
      if (axios.isAxiosError(err)) {
        const code = err.response?.data?.code
        setError(code === 'busy' ? 'busy' : code === 'schema_missing' ? 'schemaMissing'
          : code === 'file_too_large' ? 'fileTooLarge' : err.code === 'ECONNABORTED' ? 'timeoutError'
          : typeof err.response?.data?.detail === 'string' ? err.response.data.detail : 'actionError')
      } else setError('actionError')
    } finally {
      operation.current = false
      setBusy(false)
      if (input.current) input.current.value = ''
    }
  }

  async function retry(id: string) {
    if (operation.current) return
    operation.current = true
    setBusy(true)
    setProgress(100)
    setError('')
    setNotice(null)
    try {
      const { data } = await retryDocument(id)
      setNotice(data.status === 'ready' ? 'uploaded' : data.status === 'processing' ? 'processing' : 'uploadFailed')
    } catch (err) {
      setError(axios.isAxiosError(err) && err.response?.data?.code === 'busy' ? 'busy' : 'actionError')
    } finally {
      operation.current = false
      setBusy(false)
      setRevision(value => value + 1)
      await refresh()
    }
  }

  function openSource(id: string, block: number | null) {
    setSelected(id)
    setSourceBlock(block)
    setRevision(value => value + 1)
  }

  function drop(event: DragEvent) {
    if (!event.dataTransfer.types.includes('Files')) return
    event.preventDefault()
    dragDepth.current = 0
    setDragging(false)
    if (operation.current) return
    const files = event.dataTransfer.files
    if (files.length !== 1) { setError('singleFileOnly'); return }
    void ingest(files[0])
  }

  const errorKeys = ['schemaMissing', 'loadError', 'fileTooLarge', 'unsupportedFile', 'singleFileOnly', 'actionError', 'timeoutError', 'busy'] as const
  const errorKey = errorKeys.find(key => key === error)
  const current = navigation.find(item => item.view === view)!

  return <>
    <div className="workspace-shell">
      <aside className="sidebar">
        <div className="sidebar-brand"><span className="brand-mark"><Icon name="logo" size={25} /></span>
          <div><strong>{t('brand')}</strong><span>KNOWLEDGE SPACE</span></div>
        </div>
        <div className="sidebar-section-label">{t('workspace')}</div>
        <nav className="workspace-nav" aria-label={t('workspaceNavigation')}>
          {navigation.map(item => <button key={item.view} aria-current={view === item.view ? 'page' : undefined}
            onClick={() => setView(item.view)}>
            <Icon name={item.icon} /><span>{t(item.label)}</span>
            {item.view === 'library' && <span className="nav-count">{loading && !total ? '–' : total}</span>}
          </button>)}
        </nav>
        <div className="sidebar-note"><span className="note-icon"><Icon name="link" size={18} /></span>
          <strong>{t('sidebarNoteTitle')}</strong><p>{t('sidebarNote')}</p>
        </div>
        <div className="sidebar-footer">
          <div className="workspace-owner"><span className="avatar">W</span><div><strong>{t('myWorkspace')}</strong><small>{t('personalAccount')}</small></div></div>
          <div className="account-actions"><LangSwitch /><button className="icon-button" onClick={logout} aria-label={t('logout')} title={t('logout')}><Icon name="logout" size={18} /></button></div>
        </div>
      </aside>
      <div className="workspace-main">
        <header className="workspace-toolbar"><div className="breadcrumb"><span>{t('workspace')}</span><span className="breadcrumb-divider">/</span><Icon name={current.icon} size={16} /><strong>{t(current.label)}</strong></div>
          <span className="private-label"><Icon name="lock" size={13} />{t('private')}</span>
        </header>
        <div className={`workspace-body view-${view}`}>
          <div className="page-heading">
            <div><p className="eyebrow">{t(view === 'library' ? 'libraryEyebrow' : 'searchEyebrow')}</p>
              <h1>{t(view === 'library' ? 'library' : 'searchPageTitle')}</h1>
              <p className="page-description">{t(view === 'library' ? 'libraryIntro' : 'searchDescription')}</p></div>
            <button className="accent-button upload-shortcut" disabled={busy} onClick={() => { setView('library'); input.current?.click() }}><Icon name="plus" size={17} />{t('upload')}</button>
          </div>
          {loadError && <div className="feedback error" role="alert">{t(loadError)}<button onClick={() => void refresh()}>{t('retry')}</button></div>}
          {error && <div className="feedback error" role="alert">{errorKey ? t(errorKey) : error}</div>}
          {busy && view !== 'library' && <div className="feedback" role="status"><span className="spinner" />{progress < 100 ? `${t('uploading')} ${progress}%` : t('processing')}</div>}
          {notice && <div className={`feedback ${notice === 'uploadFailed' ? 'warning' : 'success'}`} role="status"><Icon name={notice === 'uploadFailed' ? 'file' : 'check'} size={17} />{t(notice)}<button className="icon-button" aria-label={t('dismiss')} onClick={() => setNotice(null)}><Icon name="close" size={15} /></button></div>}
          <div hidden={view !== 'search'}><SearchPanel onSelect={openSource} /></div>
          <div hidden={view !== 'library'}>
            <section className={`upload-panel ${dragging ? 'is-dragging' : ''} ${busy ? 'is-busy' : ''}`} aria-label={t('upload')}
              onDragEnter={event => { if (event.dataTransfer.types.includes('Files')) { event.preventDefault(); dragDepth.current++; setDragging(true) } }}
              onDragOver={event => { if (event.dataTransfer.types.includes('Files')) { event.preventDefault(); event.dataTransfer.dropEffect = busy ? 'none' : 'copy' } }}
              onDragLeave={event => { if (event.dataTransfer.types.includes('Files')) { dragDepth.current = Math.max(0, dragDepth.current - 1); if (!dragDepth.current) setDragging(false) } }}
              onDrop={drop}>
              <span className="upload-icon"><Icon name="upload" size={26} /></span>
              <div className="upload-copy"><h2>{t(dragging ? 'dropToUpload' : 'dropTitle')}</h2><p>{t('uploadHint')}</p><small>{t('localProcessing')}</small></div>
              <input ref={input} type="file" accept=".pdf,.txt,.md,.png,.jpg,.jpeg,.webp" hidden
                onChange={event => { const file = event.target.files?.[0]; if (file) { void ingest(file); event.target.value = '' } }} />
              <button className="upload-file-button" disabled={busy} onClick={() => input.current?.click()}><Icon name="plus" size={17} />{t('uploadAction')}</button>
              {busy && <div className="upload-progress" role="status"><progress max={100} value={progress < 100 ? progress : undefined} />
                <span>{progress < 100 ? `${t('uploading')} ${progress}%` : t('processing')}</span></div>}
            </section>
            <section className="library-panel document-library" aria-label={t('library')} aria-busy={loading}>
              <div className="panel-heading"><div className="library-heading"><h2>{t('allDocuments')}</h2><span className="count-badge">{total}</span></div>
                <button className="subtle-button" disabled={loading} onClick={() => { void refresh(); setRevision(v => v + 1) }}><Icon name="refresh" size={15} className={loading ? 'spinning' : ''} />{t('refresh')}</button></div>
              {loading && documents.length === 0 ? <div className="empty-state" role="status"><span className="spinner" />{t('loadingDocument')}</div>
                : documents.length === 0 && !loadError ? <div className="empty-state"><span className="empty-icon"><Icon name="library" size={30} /></span><h2>{t('emptyLibrary')}</h2><p>{t('emptyHint')}</p><button disabled={busy} onClick={() => input.current?.click()}>{t('upload')}</button></div>
                : <div className="table-scroll"><table className="document-table"><thead><tr><th>{t('filename')}</th><th>{t('status')}</th><th>{t('chunks')}</th><th>{t('size')}</th></tr></thead><tbody>
                  {documents.map(doc => <tr key={doc.id} className={selected === doc.id ? 'selected' : ''}>
                    <td><button className="document-name" aria-pressed={selected === doc.id} onClick={() => openSource(doc.id, null)}>
                      <span className={`file-type type-${doc.extension.slice(1)}`}><Icon name="file" size={20} /><small>{doc.extension.slice(1).toUpperCase()}</small></span><span>{doc.filename}</span></button></td>
                    <td><div className="document-status"><span className={`status-pill ${doc.status}`}>{doc.status === 'ready' && <Icon name="check" size={12} />}{t(doc.status === 'processing' ? 'working' : doc.status)}</span>
                      {doc.status === 'ready' && doc.embedding && <EmbeddingLabel status={doc.embedding.status} />}</div></td>
                    <td className="tabular">{doc.chunk_count}</td><td className="muted tabular">{doc.size_bytes < 1024 * 1024 ? `${Math.ceil(doc.size_bytes / 1024)} KB` : `${(doc.size_bytes / 1024 / 1024).toFixed(1)} MB`}</td>
                  </tr>)}
                </tbody></table></div>}
              {total > 30 && <div className="pagination"><span>{offset + 1}–{Math.min(offset + 30, total)} / {total}</span><button disabled={offset === 0 || loading} onClick={() => setOffset(v => Math.max(0, v - 30))}>{t('previous')}</button>
                <button disabled={offset + 30 >= total || loading} onClick={() => setOffset(v => v + 30)}>{t('next')}</button></div>}
            </section>
            <p className="library-footnote"><Icon name="link" size={14} />{t('libraryFootnote')}</p>
          </div>
        </div>
      </div>
    </div>
    {selected && <ReaderDrawer onClose={() => setSelected(null)}><DocumentReader key={selected} id={selected} revision={revision} busy={busy}
      initialBlock={sourceBlock} onEmbeddingUpdated={() => void refresh()}
      onRetry={() => void retry(selected)} onClose={() => setSelected(null)} /></ReaderDrawer>}
  </>
}
