import { useEffect, useRef, useState } from 'react'
import { searchDocuments, type SearchHit } from '../api'
import { useT } from '../i18n'

export default function SearchPanel({ onSelect }: { onSelect: (id: string, block: number | null) => void }) {
  const t = useT()
  const [input, setInput] = useState('')
  const [query, setQuery] = useState('')
  const [items, setItems] = useState<SearchHit[]>([])
  const [offset, setOffset] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(false)
  const [searched, setSearched] = useState(false)
  const request = useRef<AbortController | null>(null)
  useEffect(() => () => request.current?.abort(), [])

  async function search(value: string, start = 0) {
    request.current?.abort()
    const controller = new AbortController()
    request.current = controller
    setQuery(value)
    setOffset(start)
    setLoading(true)
    setError(false)
    setItems([])
    setHasMore(false)
    setSearched(true)
    try {
      const { data } = await searchDocuments(value, start, controller.signal)
      if (controller.signal.aborted) return
      setItems(data.items)
      setHasMore(data.has_more)
    } catch {
      if (!controller.signal.aborted) setError(true)
    } finally {
      if (!controller.signal.aborted) setLoading(false)
    }
  }

  return <section className="library-panel search-panel" aria-label={t('search')}>
    <form onSubmit={event => { event.preventDefault(); if (input.trim()) void search(input.trim()) }}>
      <label htmlFor="document-search">{t('search')}</label>
      <div className="search-controls">
        <input id="document-search" type="search" value={input} maxLength={200}
          placeholder={t('searchHint')} onChange={event => setInput(event.target.value)} required />
        <button className="accent-button" disabled={!input.trim()}>{t('searchAction')}</button>
      </div>
      <small>{t('searchScope')}</small>
    </form>
    {loading ? <p role="status">{t('searching')}</p>
      : error ? <p role="alert">{t('searchError')}</p>
      : searched && <div aria-live="polite">
        <p>{t('searchResults')} «{query}»{items.length ? ` · ${offset + 1}–${offset + items.length}` : ''}</p>
        {items.length === 0 && <p>{t('noResults')}</p>}
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
          <button disabled={offset === 0} onClick={() => void search(query, Math.max(0, offset - 30))}>{t('previous')}</button>
          <button disabled={!hasMore || offset >= 9990} onClick={() => void search(query, offset + 30)}>{t('next')}</button>
        </div>}
      </div>}
  </section>
}
