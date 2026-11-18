import { useEffect, useRef, useState } from 'react'
import { isAxiosError } from 'axios'
import { askDocuments, type AnswerDepth, type DocumentAnswer } from '../api'
import { useT } from '../i18n'

const errorMessages = new Map([
  ['answer_disabled', 'askDisabled'],
  ['answer_configuration', 'askConfiguration'],
  ['answer_timeout', 'askTimeout'],
] as const)

export default function AskPanel({ onSelect }: { onSelect: (id: string, block: number | null) => void }) {
  const t = useT()
  const [input, setInput] = useState('')
  const [depth, setDepth] = useState<AnswerDepth>('auto')
  const [answer, setAnswer] = useState<DocumentAnswer>()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<Parameters<typeof t>[0]>()
  const request = useRef<AbortController>()
  useEffect(() => () => request.current?.abort(), [])

  async function ask() {
    const question = input.trim()
    if (!question || request.current) return
    const controller = new AbortController()
    request.current = controller
    setLoading(true)
    setAnswer(undefined)
    setError(undefined)
    try {
      const { data } = await askDocuments(question, depth, controller.signal)
      if (!controller.signal.aborted) setAnswer(data)
    } catch (error) {
      if (controller.signal.aborted) return
      if (!isAxiosError(error)) setError('askError')
      else if (error.code === 'ECONNABORTED') setError('askTimeout')
      else setError(errorMessages.get(error.response?.data?.code) ?? 'askError')
    } finally {
      request.current = undefined
      if (!controller.signal.aborted) setLoading(false)
    }
  }

  return <section className="library-panel ask-panel" aria-labelledby="ask-title">
    <h2 id="ask-title"><label htmlFor="document-question">{t('askTitle')}</label></h2>
    <form onSubmit={event => { event.preventDefault(); void ask() }}>
      <textarea id="document-question" value={input} onChange={event => setInput(event.target.value)}
        maxLength={2000} required placeholder={t('askPlaceholder')} aria-describedby="ask-hint"
        readOnly={loading} />
      <small id="ask-hint">{t('askHint')}</small>
      <div className="ask-actions">
        <label htmlFor="answer-depth">{t('askDepth')}</label>
        <select id="answer-depth" value={depth} disabled={loading}
          onChange={event => setDepth(event.target.value as AnswerDepth)}>
          <option value="auto">{t('askAuto')}</option>
          <option value="deep">{t('askDeep')}</option>
        </select>
        <button className="accent-button" disabled={loading || !input.trim()}>{t('askButton')}</button>
      </div>
    </form>
    {loading && <p role="status">{t('asking')}</p>}
    {error && <p role="alert">{t(error)}</p>}
    {answer && <div className="ask-answer" aria-live="polite">
      <h3>{t('askAnswer')}</h3>
      {!answer.paragraphs.length && !answer.limitations && <p>{t('askNoEvidence')}</p>}
      {answer.paragraphs.map((paragraph, index) => <div key={index}>
        <p>{paragraph.text}</p>
        <div className="source-links">
          {paragraph.source_ids.map(sourceId => {
            const citation = answer.citations[sourceId]
            if (!citation) return null
            const label = `[${sourceId}] ${citation.filename}`
            return citation.locations.length
              ? citation.locations.map(location => <button key={`${sourceId}-${location.block_index}`}
                onClick={() => onSelect(citation.document_id, location.block_index)}>
                {label} · {location.page !== null ? `${t('page')} ${location.page} · ` : ''}
                {t('block')} {location.block_index + 1}
              </button>)
              : <button key={sourceId} onClick={() => onSelect(citation.document_id, null)}>{label}</button>
          })}
        </div>
      </div>)}
      {answer.limitations && <><h3>{t('askLimitations')}</h3><p>{answer.limitations}</p></>}
    </div>}
  </section>
}
