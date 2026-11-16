import { useEffect, useRef, useState } from 'react'
import { DocumentDetail, getDocument, getOriginal } from '../api'
import { useT } from '../i18n'

type Props = {
  id: string
  revision: number
  busy: boolean
  onRetry: () => void
  onClose: () => void
  initialBlock?: number | null
}

export default function DocumentReader({ id, revision, busy, onRetry, onClose, initialBlock = null }: Props) {
  const t = useT()
  const [document, setDocument] = useState<DocumentDetail | null>(null)
  const [tab, setTab] = useState<'extracted' | 'chunkView' | 'original'>('extracted')
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)
  const [originalUrl, setOriginalUrl] = useState('')
  const [originalText, setOriginalText] = useState('')
  const [originalError, setOriginalError] = useState(false)
  const [originalAttempt, setOriginalAttempt] = useState(0)
  const [page, setPage] = useState(1)
  const [sourceBlock, setSourceBlock] = useState<number | null>(initialBlock)
  const [downloading, setDownloading] = useState(false)
  const root = useRef<HTMLElement>(null)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setFailed(false)
    getDocument(id, controller.signal).then(({ data }) => { setDocument(data) })
      .catch(() => { if (!controller.signal.aborted) setFailed(true) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [id, revision])

  useEffect(() => { root.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }, [])

  useEffect(() => {
    setSourceBlock(initialBlock)
    if (initialBlock !== null) setTab('extracted')
  }, [initialBlock, revision])

  useEffect(() => {
    if (tab !== 'original' || !document) return
    const controller = new AbortController()
    let url = ''
    setOriginalError(false)
    setOriginalUrl('')
    setOriginalText('')
    getOriginal(id, controller.signal).then(async ({ data }) => {
      if (controller.signal.aborted) return
      if (['.txt', '.md'].includes(document.extension)) {
        const text = await data.text()
        if (!controller.signal.aborted) setOriginalText(text)
      }
      const types: Record<string, string> = { '.pdf': 'application/pdf', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp' }
      if (controller.signal.aborted) return
      url = URL.createObjectURL(new Blob([data], { type: types[document.extension] || 'text/plain' }))
      setOriginalUrl(url)
    }).catch(() => { if (!controller.signal.aborted) setOriginalError(true) })
    return () => { controller.abort(); if (url) URL.revokeObjectURL(url) }
  }, [id, tab, document?.extension, originalAttempt])

  useEffect(() => {
    if (tab === 'extracted' && sourceBlock !== null) {
      globalThis.document.getElementById(`block-${id}-${sourceBlock}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }, [tab, sourceBlock, id, loading, document])

  async function download() {
    if (!document) return
    setDownloading(true)
    try {
      const { data } = await getOriginal(id)
      const url = URL.createObjectURL(data)
      const link = globalThis.document.createElement('a')
      link.href = url
      link.download = document.filename
      link.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch { setOriginalError(true) }
    finally { setDownloading(false) }
  }

  function showPage(number: number) { setPage(number); setTab('original') }

  return <section className="reader" ref={root} aria-label={document?.filename || t('loadingDocument')}>
    <div className="panel-heading"><h2>{document?.filename || t('loadingDocument')}</h2><button onClick={onClose}>{t('close')}</button></div>
    {loading ? <p role="status">{t('loadingDocument')}</p> : failed || !document ? <p className="error" role="alert">{t('loadError')}</p> : <>
      <div className="reader-meta"><span>{document.block_count} {t('blocks')} · {document.chunk_count} {t('chunks')}</span>
        {document.page_count && <span>{document.page_count} {t('page')}</span>}
        <button disabled={downloading} onClick={() => void download()}>{t('download')}</button></div>
      {document.status === 'failed' && <div className="feedback error" role="alert"><p>{document.error_message}</p>
        <small>{t('failedStage')}: {document.stage}</small> <button disabled={busy} onClick={onRetry}>{t('retryProcessing')}</button></div>}
      {document.status === 'processing' && <p role="status">{t('processing')}</p>}
      {document.warnings.length > 0 && <details className="extraction-notes"><summary>{t('warnings')} ({document.warnings.length})</summary><ul>{document.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul></details>}
      <div className="reader-tabs" role="group" aria-label={t('selectDocument')}>
        {(['extracted', 'chunkView', 'original'] as const).map(value => <button key={value} aria-pressed={tab === value} onClick={() => setTab(value)}>{t(value)}</button>)}
      </div>
      {tab === 'extracted' && <div className="reading-content">{document.blocks.length === 0 ? <p>{t('noContent')}</p> : document.blocks.map(block =>
        <article id={`block-${id}-${block.index}`} key={block.index} className={`text-block ${sourceBlock === block.index ? 'highlighted' : ''}`}>
          <div className="block-meta"><span>{t('block')} {block.index + 1} · {block.kind}{block.method === 'ocr' ? ' · OCR' : ''}</span>
            {block.page && <button onClick={() => showPage(block.page!)}>{t('page')} {block.page} ↗</button>}</div>
          {block.kind === 'heading' ? <h3>{block.text}</h3> : <pre className={block.kind === 'table' || block.kind === 'code' ? 'structured-text' : ''}>{block.text}</pre>}
        </article>)}</div>}
      {tab === 'chunkView' && <div className="reading-content">
        {document.chunk_config.maximum && <p className="chunk-settings">{t('chunkSettings')} · {t('chunkTarget')} {document.chunk_config.target} · {t('chunkMaximum')} {document.chunk_config.maximum} · {t('chunkOverlap')} {document.chunk_config.overlap}</p>}
        {document.chunks.length === 0 ? <p>{t('noChunks')}</p> : document.chunks.map(chunk => <article className="chunk-card" key={chunk.index}>
          <div className="block-meta"><strong>{t('chunk')} {chunk.index + 1}</strong><span>{Array.from(chunk.text).length} {t('characters')}</span></div>
          {chunk.section.length > 0 && <p className="section-path">{chunk.section.join(' › ')}</p>}
          <pre>{chunk.text}</pre><div className="source-links">{[...new Set(chunk.sources.map(source => source.block_index))].map(index => <button key={index} onClick={() => { setSourceBlock(index); setTab('extracted') }}>{t('source')} · {t('block')} {index + 1}</button>)}
            {[...new Set(chunk.sources.map(source => source.page).filter((value): value is number => value !== null))].map(number => <button key={`page-${number}`} onClick={() => showPage(number)}>{t('page')} {number} ↗</button>)}</div>
        </article>)}
      </div>}
      {originalError && <p className="error" role="alert">{t('previewUnavailable')} <button onClick={() => setOriginalAttempt(v => v + 1)}>{t('retry')}</button></p>}
      {tab === 'original' && !originalError && (!originalUrl ? <p role="status">{t('loadingDocument')}</p>
        : document.extension === '.pdf' ? <iframe className="pdf-preview" title={document.filename} src={`${originalUrl}#page=${page}`} />
        : ['.txt', '.md'].includes(document.extension) ? <pre className="original-text">{originalText}</pre>
        : <img className="image-preview" src={originalUrl} alt={document.filename} />)}
    </>}
  </section>
}
