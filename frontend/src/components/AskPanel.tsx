import { useEffect, useRef, useState } from 'react'
import { isAxiosError } from 'axios'
import {
  deleteConversation, getConversation, listConversations, saveConversationTurn,
  type AnswerDepth, type Conversation, type SavedConversation,
} from '../api'
import { useT } from '../i18n'
import Icon, { type IconName } from './Icon'

const errorMessages = new Map([
  ['answer_disabled', 'askDisabled'],
  ['answer_configuration', 'askConfiguration'],
  ['answer_timeout', 'askTimeout'],
  ['conversation_conflict', 'conversationConflict'],
  ['conversation_missing', 'conversationMissing'],
] as const)

const selectedKey = 'rag-selected-conversation'

export default function AskPanel({ onSelect, onBrowse, hasDocuments = true }: {
  onSelect: (id: string, block: number | null) => void; onBrowse?: () => void; hasDocuments?: boolean
}) {
  const t = useT()
  const [input, setInput] = useState('')
  const [depth, setDepth] = useState<AnswerDepth>('auto')
  const [conversations, setConversations] = useState<SavedConversation[]>([])
  const [active, setActive] = useState<Conversation>()
  const [busy, setBusy] = useState<'history' | 'answer' | 'delete' | null>('history')
  const [error, setError] = useState<Parameters<typeof t>[0]>()
  const request = useRef<AbortController>()
  const pending = useRef<{ question: string; depth: AnswerDepth; id: string; after?: string }>()
  const textarea = useRef<HTMLTextAreaElement>(null)
  const latest = useRef<HTMLElement>(null)
  const suggestions: { title: 'suggestSummary' | 'suggestCompare' | 'suggestDates'; hint: 'suggestSummaryHint' | 'suggestCompareHint' | 'suggestDatesHint'; question: 'promptSummary' | 'promptCompare' | 'promptDates'; icon: IconName }[] = [
    { title: 'suggestSummary', hint: 'suggestSummaryHint', question: 'promptSummary', icon: 'file' },
    { title: 'suggestCompare', hint: 'suggestCompareHint', question: 'promptCompare', icon: 'compare' },
    { title: 'suggestDates', hint: 'suggestDatesHint', question: 'promptDates', icon: 'calendar' },
  ]

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
      window.requestAnimationFrame(() => {
        latest.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
        textarea.current?.focus({ preventScroll: true })
      })
    })
  }

  return <section className="ask-panel" aria-label={t('askTitle')}>
    <div className="conversation-controls">
      <Icon name="chat" size={17} />
      <label className="sr-only" htmlFor="saved-conversation">{t('conversations')}</label>
      <select id="saved-conversation" value={active?.id ?? ''} disabled={!!busy} title={t('conversations')}
        onChange={event => open(event.target.value)}>
        <option value="">{t('conversationNew')}</option>
        {conversations.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}
      </select>
      <button className="subtle-button new-conversation" disabled={!!busy || (!active && !input)} onClick={() => { select(); textarea.current?.focus() }}><Icon name="plus" size={16} />{t('conversationNew')}</button>
      {active && <button className="icon-button danger-button" disabled={!!busy} onClick={remove} aria-label={t('conversationDelete')} title={t('conversationDelete')}><Icon name="trash" size={17} /></button>}
    </div>
    {busy === 'history' && <p className="inline-status" role="status"><span className="spinner" />{t('conversationLoading')}</p>}
    {!active?.turns.length && busy !== 'history' && <div className="ask-welcome">
      <div className="welcome-symbol"><Icon name="sparkle" size={31} /></div>
      <h2>{t('askWelcome')}</h2><p>{t('askWelcomeHint')}</p>
      <div className="suggestion-grid">{suggestions.map(item => <button className="suggestion-card" key={item.title} disabled={!!busy}
        onClick={() => { setInput(t(item.question)); textarea.current?.focus() }}>
        <Icon name={item.icon} size={20} /><strong>{t(item.title)}</strong><span>{t(item.hint)}</span>
      </button>)}</div>
      {!hasDocuments && onBrowse && <p className="first-document-hint">{t('askEmptyHint')} <button className="text-button" onClick={onBrowse}>{t('addFirstDocument')}</button></p>}
    </div>}
    <div className="conversation-turns" aria-live="polite">{active?.turns.map((turn, turnIndex) => <article className="ask-answer" key={turn.id} ref={turnIndex === active.turns.length - 1 ? latest : undefined}>
      <h3 className="question-bubble">{turn.question}</h3>
      <div className="answer-label"><span className="answer-symbol"><Icon name="sparkle" size={16} /></span>{t('answerFromDocuments')}</div>
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
    {busy === 'answer' && <div className="answer-progress" role="status"><p className="question-bubble">{input.trim()}</p><span className="spinner" />{t('asking')}</div>}
    <form className="conversation-form" onSubmit={event => { event.preventDefault(); void ask() }}>
      <div className="ask-composer">
      <label className="sr-only" htmlFor="document-question">{t('askTitle')}</label>
      <textarea ref={textarea} id="document-question" value={input} onChange={event => setInput(event.target.value)}
        maxLength={2000} required placeholder={t('askPlaceholder')} aria-describedby="ask-hint" readOnly={!!busy}
        onKeyDown={event => { if (event.key === 'Enter' && (event.metaKey || event.ctrlKey) && !event.nativeEvent.isComposing) { event.preventDefault(); if (!busy) ask() } }} />
      <div className="ask-actions">
        <Icon name="sparkle" size={16} />
        <label className="sr-only" htmlFor="answer-depth">{t('askDepth')}</label>
        <select id="answer-depth" value={depth} disabled={!!busy}
          onChange={event => setDepth(event.target.value as AnswerDepth)}>
          <option value="auto">{t('askAuto')}</option>
          <option value="deep">{t('askDeep')}</option>
        </select>
        <span className="keyboard-hint">⌘ / Ctrl + Enter</span>
        <button className="accent-button" disabled={!!busy || !input.trim()}><Icon name="send" size={16} />{t('askButton')}</button>
      </div>
      </div>
      <small id="ask-hint"><Icon name="lock" size={12} />{t('askHint')}</small>
    </form>
    {error && <p className="feedback error" role="alert">{t(error)}</p>}
    {error === 'conversationConflict' && active && <button onClick={reload}>{t('refresh')}</button>}
  </section>
}
