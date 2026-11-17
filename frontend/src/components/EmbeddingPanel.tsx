import { useRef, useState } from 'react'
import { createEmbeddings, type DocumentDetail } from '../api'
import { useT } from '../i18n'

const states = { disabled: 'embeddingDisabled', pending: 'embeddingPending', processing: 'embeddingProcessing',
  ready: 'embeddingReady', failed: 'embeddingFailed' } as const

export function EmbeddingLabel({ status }: { status?: keyof typeof states }) {
  const t = useT()
  return <span className={`status-pill ${status || 'pending'}`}>{t(states[status || 'pending'])}</span>
}

export default function EmbeddingPanel({ document, busy, onUpdated }: {
  document: DocumentDetail; busy: boolean; onUpdated: () => void
}) {
  const t = useT()
  const [working, setWorking] = useState(false)
  const [error, setError] = useState(false)
  const inFlight = useRef(false)
  const state = document.embedding
  if (!state) return null

  async function generate() {
    if (inFlight.current) return
    inFlight.current = true
    setWorking(true)
    setError(false)
    try {
      await createEmbeddings(document.id)
    } catch {
      setError(true)
    } finally {
      setWorking(false)
      inFlight.current = false
      onUpdated()
    }
  }

  return <div className="embedding-panel" aria-label={t('embeddingTitle')}>
    <div className="embedding-heading"><strong>{t('embeddingTitle')}</strong><EmbeddingLabel status={working ? 'processing' : state.status} /></div>
    <p>{state.completed_chunks}/{state.total_chunks} {t('embeddingChunks')} · {state.vector_count} {t('embeddingVectors')}</p>
    <small>{t(document.status === 'ready' ? 'embeddingReadingHint' : 'embeddingWaitForDocument')}</small>
    {state.error_message && <p className="error" role="status">{state.error_message}</p>}
    {error && <p className="error" role="alert">{t('embeddingRequestError')}</p>}
    {state.status !== 'disabled' && <button disabled={busy || working || state.status === 'processing' || document.status !== 'ready'}
      onClick={() => void generate()}>{working ? t('embeddingProcessing') : state.status === 'ready' ? t('embeddingCheck') : t('embeddingGenerate')}</button>}
  </div>
}
