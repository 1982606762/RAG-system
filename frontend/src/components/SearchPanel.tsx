import { useEffect, useRef, useState } from 'react'
import { isAxiosError } from 'axios'
import { searchDocuments, type SearchHit, type SearchMode } from '../api'
import { useT } from '../i18n'
import Icon from './Icon'

const semanticErrors = new Map([
  ['semantic_disabled', 'semanticDisabled'],
  ['semantic_index_empty', 'semanticIndexEmpty'],
  ['semantic_query_invalid', 'semanticQueryInvalid'],
  ['embedding_api_disabled', 'semanticVertexDisabled'],
] as const)

export default function SearchPanel({ onSelect }: { onSelect: (id: string, block: number | null) => void }) {
  const t = useT()
  const [input, setInput] = useState('')
  const [mode, setMode] = useState<SearchMode>('keyword')
  const [submitted, setSubmitted] = useState<{ query: string; mode: SearchMode }>()
  const [items, setItems] = useState<SearchHit[]>([])
  const [offset, setOffset] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<Parameters<typeof t>[0] | null>(null)
  const request = useRef<AbortController | null>(null)
  useEffect(() => () => request.current?.abort(), [])

  async function search(query: string, mode: SearchMode, start = 0) {
    request.current?.abort()
    const controller = new AbortController()
    request.current = controller
    setSubmitted({ query, mode })
    setOffset(start)
    setLoading(true)
    setError(null)
    setItems([])
    setHasMore(false)
    try {
      const { data } = await searchDocuments(query, start, controller.signal, mode)
      if (controller.signal.aborted) return
      setItems(data.items)
      setHasMore(data.has_more)
    } catch (error) {
      if (controller.signal.aborted) return
      const code = isAxiosError(error) ? error.response?.data?.code : undefined
      setError(mode === 'keyword' ? 'searchError' : semanticErrors.get(code) ?? 'semanticError')
    } finally {
      if (!controller.signal.aborted) setLoading(false)
    }
  }

  return <section className="search-panel" aria-label={t('search')}>
    <form onSubmit={event => { event.preventDefault(); if (input.trim()) void search(input.trim(), mode) }}>
      <label className="sr-only" htmlFor="document-search">{t('search')}</label>
      <div className="search-controls">
        <select aria-label={t('searchMode')} value={mode} onChange={event => setMode(event.target.value as SearchMode)}>
          <option value="keyword">{t('keywordSearch')}</option>
          <option value="semantic">{t('semanticSearch')}</option>
        </select>
        <div className="search-input"><Icon name="search" size={20} /><input id="document-search" type="search" value={input} maxLength={200}
          placeholder={t(mode === 'keyword' ? 'searchHint' : 'semanticHint')}
          onChange={event => setInput(event.target.value)} required /></div>
        <button className="accent-button" disabled={!input.trim()}>{t('searchAction')}</button>
      </div>
      <small>{t(mode === 'keyword' ? 'searchScope' : 'semanticScope')}</small>
    </form>
    {!submitted && <div className="search-welcome empty-state"><span className="empty-icon"><Icon name="search" size={29} /></span><h2>{t('searchWelcome')}</h2><p>{t('searchWelcomeHint')}</p>
      <div className="search-tips"><div><Icon name="search" size={18} /><strong>{t('keywordSearch')}</strong><p>{t('keywordTip')}</p></div><div><Icon name="sparkle" size={18} /><strong>{t('semanticSearch')}</strong><p>{t('semanticTip')}</p></div></div>
    </div>}
    {loading ? <p className="inline-status" role="status"><span className="spinner" />{t('searching')}</p>
      : error ? <p className="feedback error" role="alert">{t(error)}</p>
      : submitted && <div aria-live="polite">
        <p>{t(submitted.mode === 'keyword' ? 'searchResults' : 'semanticResults')} «{submitted.query}»{items.length ? ` · ${offset + 1}–${offset + items.length}` : ''}</p>
        {items.length === 0 && <p>{t(submitted.mode === 'keyword' ? 'noResults' : 'noSemanticResults')}</p>}
        {items.map(hit => <article className="chunk-card" key={`${hit.document_id}-${hit.chunk_index}`}>
          <strong>{hit.filename}</strong>
          {hit.chunk.section.length > 0 && <p className="section-path">{hit.chunk.section.join(' › ')}</p>}
          <pre>{hit.chunk.text}</pre>
          <div className="source-links">
            {[...new Set(hit.chunk.sources.map(source => source.page).filter(page => page !== null))].map(page =>
              <span key={page}>{t('page')} {page}</span>)}
            {hit.chunk.sources.length ? [...new Set(hit.chunk.sources.map(source => source.block_index))].map(block =>
              <button key={block} onClick={() => onSelect(hit.document_id, block)}>{t('source')} · {t('block')} {block + 1}</button>)
              : <button onClick={() => onSelect(hit.document_id, null)}>{t('source')}</button>}
          </div>
        </article>)}
        {(offset > 0 || hasMore) && <div className="pagination">
          <button disabled={offset === 0} onClick={() => void search(submitted.query, submitted.mode, Math.max(0, offset - 30))}>{t('previous')}</button>
          <button disabled={!hasMore || offset >= 9990} onClick={() => void search(submitted.query, submitted.mode, offset + 30)}>{t('next')}</button>
        </div>}
      </div>}
  </section>
}
