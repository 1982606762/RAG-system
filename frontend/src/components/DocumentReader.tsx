import { useEffect, useRef, useState } from 'react'
import { ContentBlock, DocumentDetail, getDocument, getOriginal } from '../api'
import { useT } from '../i18n'
import OriginalText from './OriginalText'
import PagePreview, { pageRegion, Region } from './PagePreview'
import EmbeddingPanel from './EmbeddingPanel'
import Icon from './Icon'

type Props = {
  id: string
  revision: number
  busy: boolean
  onRetry: () => void
  onClose: () => void
  initialBlock?: number | null
  onEmbeddingUpdated?: () => void
}

export default function DocumentReader({ id, revision, busy, onRetry, onClose, initialBlock = null, onEmbeddingUpdated }: Props) {
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
  const [embeddingRevision, setEmbeddingRevision] = useState(0)
  const root = useRef<HTMLElement>(null)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setFailed(false)
    getDocument(id, controller.signal).then(({ data }) => { if (!controller.signal.aborted) setDocument(data) })
      .catch(() => { if (!controller.signal.aborted) setFailed(true) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [id, revision, embeddingRevision])

  // The reader stays mounted when another citation in the same file is opened.
  // Navigate again after loading so long conversation/layout changes cannot hide it.
  useEffect(() => {
    if (loading) return
    root.current?.focus({ preventScroll: true })
    root.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [id, revision, loading])

  useEffect(() => {
    if (loading || !document) return
    setSourceBlock(initialBlock)
    if (initialBlock !== null) openSource(document.blocks.find(block => block.index === initialBlock))
  }, [initialBlock, revision, document, loading])

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
  }, [id, tab, document?.extension, revision, originalAttempt])

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

  function openSource(block?: ContentBlock) {
    if (!block) { setTab('extracted'); return }
    setSourceBlock(block.index)
    const sourcePage = block.location?.type === 'page' ? block.location.page : block.page
    if (sourcePage && !['.txt', '.md'].includes(document?.extension || '')) { setPage(sourcePage); setTab('original') }
    else setTab(block.location?.type === 'text' ? 'original' : 'extracted')
  }

  function showPage(number: number) { setSourceBlock(null); setPage(number); setTab('original') }
  const selectedBlock = document?.blocks.find(block => block.index === sourceBlock)
  const location = selectedBlock?.location

  return <section className="reader" ref={root} tabIndex={-1} aria-label={document?.filename || t('loadingDocument')}>
    <div className="panel-heading reader-heading"><span className="reader-file-icon"><Icon name="file" size={20} /></span><h2>{document?.filename || t('loadingDocument')}</h2><button className="icon-button" onClick={onClose} aria-label={t('close')} title={`${t('close')} · Esc`}><Icon name="close" size={20} /></button></div>
    {loading && !document ? <p role="status">{t('loadingDocument')}</p> : failed || !document ? <p className="error" role="alert">{t('loadError')}</p> : <>
      <div className="reader-meta"><span>{document.block_count} {t('blocks')} · {document.chunk_count} {t('chunks')}</span>
        {document.page_count && <span>{document.page_count} {t('page')}</span>}
        <button disabled={downloading} onClick={() => void download()}>{t('download')}</button></div>
      <EmbeddingPanel document={document} busy={busy} onUpdated={() => { setEmbeddingRevision(v => v + 1); onEmbeddingUpdated?.() }} />
      {document.status === 'failed' && <div className="feedback error" role="alert"><p>{document.error_message}</p>
        <small>{t('failedStage')}: {document.stage}</small> <button disabled={busy} onClick={onRetry}>{t('retryProcessing')}</button></div>}
      {document.status === 'processing' && <p role="status">{t('processing')}</p>}
      {document.warnings.length > 0 && <details className="extraction-notes"><summary>{t('warnings')} ({document.warnings.length})</summary><ul>{document.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul></details>}
      <div className="reader-tabs" role="group" aria-label={t('selectDocument')}>
        {(['extracted', 'chunkView', 'original'] as const).map(value => <button key={value} aria-pressed={tab === value} onClick={() => setTab(value)}>{t(value)}</button>)}
      </div>
      {sourceBlock !== null && tab === 'extracted' && !location && <p className="source-position">{t('sourceFallback')}</p>}
      {tab === 'extracted' && <div className="reading-content">{document.blocks.length === 0 ? <p>{t('noContent')}</p> : document.blocks.map(block =>
        <article id={`block-${id}-${block.index}`} key={block.index} className={`text-block ${sourceBlock === block.index ? 'highlighted' : ''}`}>
          <div className="block-meta"><span>{t('block')} {block.index + 1} · {block.kind}{block.method === 'ocr' ? ' · OCR' : ''}</span>
            <button onClick={() => openSource(block)}>{block.page ? `${t('page')} ${block.page} ↗` : t('openOriginalSource')}</button></div>
          {block.kind === 'heading' ? <h3>{block.text}</h3> : <pre className={block.kind === 'table' || block.kind === 'code' ? 'structured-text' : ''}>{block.text}</pre>}
        </article>)}</div>}
      {tab === 'chunkView' && <div className="reading-content">
        {document.chunk_config.maximum && <p className="chunk-settings">{t('chunkSettings')} · {t('chunkTarget')} {document.chunk_config.target} · {t('chunkMaximum')} {document.chunk_config.maximum} · {t('chunkOverlap')} {document.chunk_config.overlap}</p>}
        {document.chunks.length === 0 ? <p>{t('noChunks')}</p> : document.chunks.map(chunk => <article className="chunk-card" key={chunk.index}>
          <div className="block-meta"><strong>{t('chunk')} {chunk.index + 1}</strong><span>{Array.from(chunk.text).length} {t('characters')}</span></div>
          {chunk.section.length > 0 && <p className="section-path">{chunk.section.join(' › ')}</p>}
          <pre>{chunk.text}</pre><div className="source-links">{[...new Set(chunk.sources.map(source => source.block_index))].map(index => <button key={index} onClick={() => openSource(document.blocks.find(block => block.index === index))}>{t('source')} · {t('block')} {index + 1}</button>)}
            {[...new Set(chunk.sources.map(source => source.page).filter((value): value is number => value !== null))].map(number => <button key={`page-${number}`} onClick={() => showPage(number)}>{t('page')} {number} ↗</button>)}</div>
        </article>)}
      </div>}
      {originalError && <p className="error" role="alert">{t('previewUnavailable')} <button onClick={() => setOriginalAttempt(v => v + 1)}>{t('retry')}</button></p>}
      {tab === 'original' && document.extension === '.pdf' && <>
        <div className="page-controls"><button disabled={page <= 1} onClick={() => showPage(page - 1)}>{t('previous')}</button>
          <span>{t('page')} {page}{document.page_count ? ` / ${document.page_count}` : ''}</span>
          <button disabled={!document.page_count || page >= document.page_count} onClick={() => showPage(page + 1)}>{t('next')}</button></div>
        {sourceBlock !== null && !pageRegion(location) && <p className="source-position">{t('pageSourceFallback')}</p>}
      </>}
      {tab === 'original' && !originalError && (!originalUrl ? <p role="status">{t('loadingDocument')}</p>
        : document.extension === '.pdf' ? <PagePreview id={id} page={page} location={location} fallbackUrl={originalUrl} filename={document.filename} attempt={originalAttempt} />
        : ['.txt', '.md'].includes(document.extension) ? <OriginalText text={originalText} location={location} />
        : <div className="page-preview"><img src={originalUrl} alt={document.filename} /><Region location={location} /></div>)}
    </>}
  </section>
}
