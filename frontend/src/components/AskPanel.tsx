import { useEffect, useRef, useState } from 'react'
import { isAxiosError } from 'axios'
import {
  deleteConversation, getConversation, listConversations, saveConversationTurn,
  type AnswerDepth, type Conversation, type SavedConversation,
} from '../api'
import { useT } from '../i18n'

const errorMessages = new Map([
  ['answer_disabled', 'askDisabled'],
  ['answer_configuration', 'askConfiguration'],
  ['answer_timeout', 'askTimeout'],
  ['conversation_conflict', 'conversationConflict'],
  ['conversation_missing', 'conversationMissing'],
] as const)

const selectedKey = 'rag-selected-conversation'

export default function AskPanel({ onSelect }: { onSelect: (id: string, block: number | null) => void }) {
  const t = useT()
  const [input, setInput] = useState('')
  const [depth, setDepth] = useState<AnswerDepth>('auto')
  const [conversations, setConversations] = useState<SavedConversation[]>([])
  const [active, setActive] = useState<Conversation>()
  const [busy, setBusy] = useState<'history' | 'answer' | 'delete' | null>('history')
  const [error, setError] = useState<Parameters<typeof t>[0]>()
  const request = useRef<AbortController>()
  const pending = useRef<{ question: string; depth: AnswerDepth; id: string; after?: string }>()

  useEffect(() => {
    const controller = new AbortController()
    async function restore() {
      const { data } = await listConversations(controller.signal)
      if (controller.signal.aborted) return
      setConversations(data.items)
      const selected = data.items.find(item => item.id === localStorage.getItem(selectedKey))
      if (selected) {
        const { data } = await getConversation(selected.id, controller.signal)
        if (!controller.signal.aborted) setActive(data)
      }
    }
    void restore().catch(() => {
      if (!controller.signal.aborted) setError('conversationLoadError')
    }).finally(() => {
      if (!controller.signal.aborted) setBusy(null)
    })
    return () => { controller.abort(); request.current?.abort() }
  }, [])

  async function run(kind: 'history' | 'answer' | 'delete', action: (signal: AbortSignal) => Promise<void>) {
    if (busy || request.current) return
    const controller = new AbortController()
    request.current = controller
    setBusy(kind)
    setError(undefined)
    try {
      await action(controller.signal)
    } catch (error) {
      if (controller.signal.aborted) return
      const code = isAxiosError(error) ? error.response?.data?.code : undefined
      setError(isAxiosError(error) && error.code === 'ECONNABORTED' && kind === 'answer'
        ? 'askTimeout' : errorMessages.get(code) ?? (kind === 'answer' ? 'askError' : 'conversationLoadError'))
    } finally {
      request.current = undefined
      if (!controller.signal.aborted) setBusy(null)
    }
  }

  function select(conversation?: Conversation) {
    setActive(conversation)
    setInput('')
    setError(undefined)
    pending.current = undefined
    if (conversation) localStorage.setItem(selectedKey, conversation.id)
    else localStorage.removeItem(selectedKey)
  }

  function open(id: string) {
    if (!id) { select(); return }
    void run('history', async signal => {
      const { data } = await getConversation(id, signal)
      if (!signal.aborted) select(data)
    })
  }

  function reload() {
    if (!active) return
    void run('history', async signal => {
      const { data } = await getConversation(active.id, signal)
      if (!signal.aborted) setActive(data)
    })
  }

  function remove() {
    if (!active || !window.confirm(t('conversationDeleteConfirm'))) return
    void run('delete', async signal => {
      await deleteConversation(active.id, signal)
      if (signal.aborted) return
      setConversations(items => items.filter(item => item.id !== active.id))
      select()
    })
  }

  function ask() {
    const question = input.trim()
    if (!question) return
    void run('answer', async signal => {
      const after = active?.turns[active.turns.length - 1]?.id
      const previous = pending.current
      const id = previous?.question === question && previous.depth === depth && previous.after === after
        ? previous.id : crypto.randomUUID()
      pending.current = { question, depth, id, after }
      const { data } = await saveConversationTurn(active?.id ?? null, question, depth, id, after, signal)
      if (signal.aborted) return
      const turns = active?.turns ?? []
      const conversation = { ...data.conversation, turns: [...turns, data.turn] }
      setConversations(items => [data.conversation, ...items.filter(item => item.id !== conversation.id)])
      select(conversation)
    })
  }

  return <section className="library-panel ask-panel" aria-labelledby="ask-title">
    <h2 id="ask-title"><label htmlFor="document-question">{t('askTitle')}</label></h2>
    <div className="conversation-controls">
      <label htmlFor="saved-conversation">{t('conversations')}</label>
      <select id="saved-conversation" value={active?.id ?? ''} disabled={!!busy}
        onChange={event => open(event.target.value)}>
        <option value="">{t('conversationNew')}</option>
        {conversations.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}
      </select>
      <button disabled={!!busy || (!active && !input)} onClick={() => select()}>{t('conversationNew')}</button>
      {active && <button disabled={!!busy} onClick={remove}>{t('conversationDelete')}</button>}
    </div>
    {busy === 'history' && <p role="status">{t('conversationLoading')}</p>}
    <div aria-live="polite">{active?.turns.map(turn => <article className="ask-answer" key={turn.id}>
      <h3>{turn.question}</h3>
      {!turn.answer.paragraphs.length && !turn.answer.limitations && <p>{t('askNoEvidence')}</p>}
      {turn.answer.paragraphs.map((paragraph, index) => <div key={index}>
        <p>{paragraph.text}</p>
        <div className="source-links">
          {paragraph.source_ids.map(sourceId => {
            const citation = turn.answer.citations[sourceId]
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
      {turn.answer.notes && <><h4>{t('askNotes')}</h4><p>{turn.answer.notes}</p></>}
      {turn.answer.limitations && <><h4>{t(turn.answer.notes === undefined && turn.answer.paragraphs.length
        ? 'askLegacyLimitations' : 'askLimitations')}</h4><p>{turn.answer.limitations}</p></>}
    </article>)}</div>
    <form className="conversation-form" onSubmit={event => { event.preventDefault(); void ask() }}>
      <textarea id="document-question" value={input} onChange={event => setInput(event.target.value)}
        maxLength={2000} required placeholder={t('askPlaceholder')} aria-describedby="ask-hint"
        readOnly={!!busy} />
      <small id="ask-hint">{t('askHint')}</small>
      <div className="ask-actions">
        <label htmlFor="answer-depth">{t('askDepth')}</label>
        <select id="answer-depth" value={depth} disabled={!!busy}
          onChange={event => setDepth(event.target.value as AnswerDepth)}>
          <option value="auto">{t('askAuto')}</option>
          <option value="deep">{t('askDeep')}</option>
        </select>
        <button className="accent-button" disabled={!!busy || !input.trim()}>{t('askButton')}</button>
      </div>
    </form>
    {busy === 'answer' && <p role="status">{t('asking')}</p>}
    {error && <p role="alert">{t(error)}</p>}
    {error === 'conversationConflict' && active && <button onClick={reload}>{t('refresh')}</button>}
  </section>
}
