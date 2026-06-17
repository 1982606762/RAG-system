import { useEffect, useState } from 'react'
import {
  getDocumentDetail,
  fetchPreview,
  downloadDocument,
  deleteDocument,
} from '../api'
import { useT } from '../i18n'

// A modal that shows ONE file in full: original preview on the left, all the
// structured fields (general layer + Claude's dynamic `details`) on the right.
//
// Props:
//   fileId   which file to show
//   onClose  close the modal
//   onDeleted called after a successful delete so the list can drop the row

interface Props {
  fileId: string
  onClose: () => void
  onDeleted?: (fileId: string) => void
}

export default function FileDetailModal({ fileId, onClose, onDeleted }: Props) {
  const [doc, setDoc] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [preview, setPreview] = useState<{ url: string; mime: string } | null>(
    null,
  )
  const t = useT()

  // Load metadata + preview when the modal opens / the file changes.
  useEffect(() => {
    let revoked = false
    let objectUrl: string | null = null

    setLoading(true)
    getDocumentDetail(fileId)
      .then(setDoc)
      .finally(() => setLoading(false))

    fetchPreview(fileId)
      .then((p) => {
        if (revoked) {
          URL.revokeObjectURL(p.url) // modal closed before fetch finished
        } else {
          objectUrl = p.url
          setPreview(p)
        }
      })
      .catch(() => setPreview(null))

    // Cleanup: free the blob URL so we don't leak memory across opens.
    return () => {
      revoked = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [fileId])

  // Close on Escape for keyboard users.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const handleDelete = async () => {
    if (!confirm(t('common.confirmDelete'))) return
    try {
      await deleteDocument(fileId)
      onDeleted?.(fileId)
      onClose()
    } catch {
      alert(t('common.deleteFailed'))
    }
  }

  // The dynamic details layer: everything Claude chose to extract per doc type.
  const details: Record<string, any> = doc?.full_analysis?.details || {}

  return (
    // Click the dark backdrop (but not the card) to close.
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose} aria-label={t('detail.close')}>
          ✕
        </button>

        <div className="modal-body">
          {/* Left: original file preview */}
          <div className="modal-preview">
            {!preview && <div className="modal-hint">{t('detail.previewLoading')}</div>}
            {preview && preview.mime.startsWith('image/') && (
              <img src={preview.url} alt={t('detail.previewAlt')} />
            )}
            {preview && preview.mime === 'application/pdf' && (
              <iframe src={preview.url} title={t('detail.pdfTitle')} />
            )}
            {preview &&
              !preview.mime.startsWith('image/') &&
              preview.mime !== 'application/pdf' && (
                <div className="modal-hint">{t('detail.noPreview')}</div>
              )}
          </div>

          {/* Right: structured fields */}
          <div className="modal-meta">
            {loading ? (
              <div className="modal-hint">{t('common.loading')}</div>
            ) : (
              <>
                <h3>{doc?.vendor || doc?.doc_type || t('detail.title')}</h3>
                <dl className="meta-grid">
                  <dt>{t('docs.colType')}</dt><dd>{doc?.doc_type || '-'}</dd>
                  <dt>{t('docs.colDate')}</dt><dd>{doc?.doc_date || '-'}</dd>
                  <dt>{t('docs.colParty')}</dt><dd>{doc?.vendor || '-'}</dd>
                  <dt>{t('docs.colAmount')}</dt>
                  <dd>
                    {doc?.amount != null
                      ? `${doc.amount} ${doc.currency || ''}`
                      : '-'}
                  </dd>
                  <dt>{t('docs.colSummary')}</dt><dd>{doc?.summary || '-'}</dd>
                </dl>

                {Object.keys(details).length > 0 && (
                  <>
                    <h4>{t('detail.section')}</h4>
                    <dl className="meta-grid">
                      {Object.entries(details).map(([k, v]) => (
                        <FieldRow key={k} label={k} value={v} />
                      ))}
                    </dl>
                  </>
                )}

                <div className="modal-actions">
                  <button
                    className="btn-sm"
                    onClick={() =>
                      downloadDocument(fileId).catch(() =>
                        alert(t('common.downloadFailed')),
                      )
                    }
                  >
                    {t('common.download')}
                  </button>
                  <button className="btn-sm btn-danger" onClick={handleDelete}>
                    {t('common.delete')}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

// Render one details field. Objects/arrays (e.g. a receipt's item list) are
// shown as pretty JSON so nothing gets hidden.
function FieldRow({ label, value }: { label: string; value: any }) {
  const isComplex = value !== null && typeof value === 'object'
  return (
    <>
      <dt>{label}</dt>
      <dd>
        {isComplex ? (
          <pre className="meta-json">{JSON.stringify(value, null, 2)}</pre>
        ) : (
          String(value)
        )}
      </dd>
    </>
  )
}
