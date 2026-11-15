import { useCallback, useEffect, useRef, useState } from 'react'
import axios from 'axios'
import { DocumentRecord, listDocuments, retryDocument, uploadDocument } from '../api'
import { useT } from '../i18n'
import DocumentReader from '../components/DocumentReader'

export default function WorkspacePage() {
  const t = useT()
  const [documents, setDocuments] = useState<DocumentRecord[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState<string | null>(null)
  const [revision, setRevision] = useState(0)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState(0)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState<'duplicate' | 'uploaded' | 'uploadFailed' | null>(null)
  const input = useRef<HTMLInputElement>(null)
  const requestVersion = useRef(0)

  const refresh = useCallback(async () => {
    const version = ++requestVersion.current
    setLoading(true)
    try {
      const { data } = await listDocuments(offset)
      if (version !== requestVersion.current) return
      setDocuments(data.items)
      setTotal(data.total)
      setError('')
    } catch (err) {
      if (version !== requestVersion.current) return
      setError(axios.isAxiosError(err) && err.response?.data?.code === 'schema_missing' ? 'schemaMissing' : 'loadError')
    } finally {
      if (version === requestVersion.current) setLoading(false)
    }
  }, [offset])

  useEffect(() => { void refresh(); return () => { requestVersion.current++ } }, [refresh])

  async function ingest(file: File) {
    if (busy) return
    if (file.size > 20 * 1024 * 1024) { setError('fileTooLarge'); return }
    setBusy(true)
    setProgress(0)
    setNotice(null)
    setError('')
    try {
      const { data } = await uploadDocument(file, setProgress)
      setSelected(data.document.id)
      setRevision(value => value + 1)
      setNotice(data.duplicate ? 'duplicate' : data.document.status === 'ready' ? 'uploaded' : 'uploadFailed')
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
      setBusy(false)
      if (input.current) input.current.value = ''
    }
  }

  async function retry(id: string) {
    setBusy(true)
    setProgress(100)
    setError('')
    setNotice(null)
    try {
      const { data } = await retryDocument(id)
      setNotice(data.status === 'ready' ? 'uploaded' : 'uploadFailed')
    } catch (err) {
      setError(axios.isAxiosError(err) && err.response?.data?.code === 'busy' ? 'busy' : 'actionError')
    } finally {
      setBusy(false)
      setRevision(value => value + 1)
      const { data } = await listDocuments(offset).catch(() => ({ data: null }))
      if (data) { setDocuments(data.items); setTotal(data.total) }
    }
  }

  const errorKeys = ['schemaMissing', 'loadError', 'fileTooLarge', 'actionError', 'timeoutError', 'busy'] as const
  const errorKey = errorKeys.find(key => key === error)

  return (
    <>
      <div className="workspace-title">
        <div><p className="eyebrow">{t('private')}</p><h1>{t('library')}</h1></div>
        <span className="muted">{total} {t('documents')}</span>
      </div>
      <section className="upload-panel" aria-label={t('upload')}>
        <div><h2>{t('upload')}</h2><p>{t('uploadHint')}</p><small>{t('localProcessing')}</small></div>
        <input ref={input} type="file" accept=".pdf,.txt,.md,.png,.jpg,.jpeg,.webp" hidden
          onChange={event => { const file = event.target.files?.[0]; if (file) void ingest(file) }} />
        <button className="accent-button" disabled={busy} onClick={() => input.current?.click()}>{t('uploadAction')}</button>
        {busy && <div className="upload-progress" role="status"><progress max={100} value={progress < 100 ? progress : undefined} />
          <span>{progress < 100 ? `${t('uploading')} ${progress}%` : t('processing')}</span></div>}
      </section>
      {error && <div className="feedback error" role="alert">{errorKey ? t(errorKey) : error}</div>}
      {notice && <div className="feedback" role="status">{t(notice)}</div>}
      <section className="library-panel" aria-label={t('library')}>
        <div className="panel-heading"><h2>{t('library')}</h2><button disabled={loading} onClick={() => { void refresh(); setRevision(v => v + 1) }}>{t('refresh')}</button></div>
        {loading && documents.length === 0 ? <p className="empty-state" role="status">{t('loadingDocument')}</p>
          : documents.length === 0 ? <div className="empty-state"><h2>{t('emptyLibrary')}</h2><p>{t('emptyHint')}</p></div>
          : <div className="table-scroll"><table className="document-table"><thead><tr><th>{t('filename')}</th><th>{t('status')}</th><th>{t('chunks')}</th><th>{t('size')}</th></tr></thead><tbody>
            {documents.map(doc => <tr key={doc.id} className={selected === doc.id ? 'selected' : ''}>
              <td><button className="document-name" aria-pressed={selected === doc.id} onClick={() => { setSelected(doc.id); setRevision(v => v + 1) }}>
                <span className="file-type">{doc.extension.slice(1).toUpperCase()}</span><span>{doc.filename}</span></button></td>
              <td><span className={`status-pill ${doc.status}`}>{t(doc.status === 'processing' ? 'working' : doc.status)}</span></td>
              <td>{doc.chunk_count}</td><td className="muted">{doc.size_bytes < 1024 * 1024 ? `${Math.ceil(doc.size_bytes / 1024)} KB` : `${(doc.size_bytes / 1024 / 1024).toFixed(1)} MB`}</td>
            </tr>)}
          </tbody></table></div>}
        {total > 30 && <div className="pagination"><button disabled={offset === 0 || loading} onClick={() => setOffset(v => Math.max(0, v - 30))}>{t('previous')}</button>
          <span>{offset + 1}–{Math.min(offset + 30, total)} / {total}</span>
          <button disabled={offset + 30 >= total || loading} onClick={() => setOffset(v => v + 30)}>{t('next')}</button></div>}
      </section>
      {selected && <DocumentReader key={selected} id={selected} revision={revision} busy={busy}
        onRetry={() => void retry(selected)} onClose={() => setSelected(null)} />}
    </>
  )
}
