import { useEffect, useState } from 'react'
import {
  listDocuments,
  searchDocuments,
  deleteDocument,
  downloadDocument,
} from '../api'

// File list with two ways to find things:
//   1. browse everything (newest first), or
//   2. natural-language search (vector) — "去年的宜家收据" works without exact
//      keywords. Each row can be downloaded or deleted.
export default function DocumentsPage() {
  const [docs, setDocs] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [query, setQuery] = useState('')
  const [searching, setSearching] = useState(false)

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

  const handleDelete = async (fileId: string) => {
    if (!confirm('确定删除这个文件吗？此操作不可恢复。')) return
    try {
      await deleteDocument(fileId)
      setDocs((prev) => prev.filter((d) => d.file_id !== fileId))
    } catch {
      alert('删除失败，请重试')
    }
  }

  return (
    <div className="page">
      <h2>我的文件（{docs.length}）</h2>

      <div className="search-bar">
        <input
          placeholder="用自然语言搜索，例如「去年的水电费发票」"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.nativeEvent.isComposing) runSearch()
          }}
        />
        <button onClick={runSearch} disabled={searching}>
          {searching ? '搜索中…' : '搜索'}
        </button>
        {query && (
          <button className="btn-ghost" onClick={clearSearch}>
            清除
          </button>
        )}
      </div>

      {loading ? (
        <div>加载中…</div>
      ) : (
        <table className="docs">
          <thead>
            <tr>
              <th>类型</th>
              <th>日期</th>
              <th>相关方</th>
              <th>金额</th>
              <th>摘要</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {docs.map((d) => (
              <tr key={d.file_id}>
                <td>{d.doc_type || '-'}</td>
                <td>{d.doc_date || '-'}</td>
                <td>{d.vendor || '-'}</td>
                <td>{d.amount ? `${d.amount} ${d.currency || ''}` : '-'}</td>
                <td>{d.summary || '-'}</td>
                <td className="row-actions">
                  <button
                    className="btn-sm"
                    onClick={() =>
                      downloadDocument(d.file_id).catch(() =>
                        alert('下载失败，请重试'),
                      )
                    }
                  >
                    下载
                  </button>
                  <button
                    className="btn-sm btn-danger"
                    onClick={() => handleDelete(d.file_id)}
                  >
                    删除
                  </button>
                </td>
              </tr>
            ))}
            {docs.length === 0 && (
              <tr>
                <td colSpan={6} className="empty-row">
                  {query ? '没有找到匹配的文件' : '还没有文件，去「上传」试试'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  )
}
