import { useEffect, useState } from 'react'
import {
  listDocuments,
  searchDocuments,
  deleteDocument,
  downloadDocument,
} from '../api'
import FileDetailModal from '../components/FileDetailModal'
import { useT } from '../i18n'

// File list with two ways to find things:
//   1. browse everything (newest first), or
//   2. natural-language search (vector) — "去年的宜家收据" works without exact
//      keywords. Click a row to open the detail modal; each row can also be
//      downloaded or deleted inline.
export default function DocumentsPage() {
  const [docs, setDocs] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [query, setQuery] = useState('')
  const [searching, setSearching] = useState(false)
  const [openId, setOpenId] = useState<string | null>(null) // detail modal target
  const t = useT()

  useEffect(() => {
    reload()
  }, [])

  const reload = async () => {
    setLoading(true)
    try {
      setDocs(await listDocuments())
    } finally {
      setLoading(false)
    }
  }

  const runSearch = async () => {
    if (!query.trim()) {
      reload() // empty query -> back to the full list
      return
    }
    setSearching(true)
    try {
      setDocs(await searchDocuments(query))
    } finally {
      setSearching(false)
    }
  }

  const clearSearch = () => {
    setQuery('')
    reload()
  }

  const removeFromList = (fileId: string) =>
    setDocs((prev) => prev.filter((d) => d.file_id !== fileId))

  const handleDelete = async (fileId: string) => {
    if (!confirm(t('common.confirmDelete'))) return
    try {
      await deleteDocument(fileId)
      removeFromList(fileId)
    } catch {
      alert(t('common.deleteFailed'))
    }
  }

  return (
    <div className="page">
      <h2>{t('docs.title', { n: docs.length })}</h2>

      <div className="search-bar">
        <input
          placeholder={t('docs.searchPlaceholder')}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.nativeEvent.isComposing) runSearch()
          }}
        />
        <button onClick={runSearch} disabled={searching}>
          {searching ? t('docs.searching') : t('docs.search')}
        </button>
        {query && (
          <button className="btn-ghost" onClick={clearSearch}>
            {t('docs.clear')}
          </button>
        )}
      </div>

      {loading ? (
        <div>{t('common.loading')}</div>
      ) : (
        <table className="docs">
          <thead>
            <tr>
              <th>{t('docs.colType')}</th>
              <th>{t('docs.colDate')}</th>
              <th>{t('docs.colParty')}</th>
              <th>{t('docs.colAmount')}</th>
              <th>{t('docs.colSummary')}</th>
              <th>{t('docs.colActions')}</th>
            </tr>
          </thead>
          <tbody>
            {docs.map((d) => (
              <tr
                key={d.file_id}
                className="doc-row"
                onClick={() => setOpenId(d.file_id)}
              >
                <td>{d.doc_type || '-'}</td>
                <td>{d.doc_date || '-'}</td>
                <td>{d.vendor || '-'}</td>
                <td>{d.amount ? `${d.amount} ${d.currency || ''}` : '-'}</td>
                <td>{d.summary || '-'}</td>
                {/* i18n: cells fall back to '-' which is language-neutral */}
                {/* stopPropagation so clicking a button doesn't also open the modal */}
                <td className="row-actions" onClick={(e) => e.stopPropagation()}>
                  <button
                    className="btn-sm"
                    onClick={() =>
                      downloadDocument(d.file_id).catch(() =>
                        alert('下载失败，请重试'),
                      )
                    }
                  >
                    {t('common.download')}
                  </button>
                  <button
                    className="btn-sm btn-danger"
                    onClick={() => handleDelete(d.file_id)}
                  >
                    {t('common.delete')}
                  </button>
                </td>
              </tr>
            ))}
            {docs.length === 0 && (
              <tr>
                <td colSpan={6} className="empty-row">
                  {query ? t('docs.noMatch') : t('docs.noFiles')}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}

      {openId && (
        <FileDetailModal
          fileId={openId}
          onClose={() => setOpenId(null)}
          onDeleted={removeFromList}
        />
      )}
    </div>
  )
}
