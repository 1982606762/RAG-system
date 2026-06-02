import { useEffect, useState } from 'react'
import {
  listConversations,
  createConversation,
  getMessages,
  askInConversation,
  downloadDocument,
  deleteDocument,
} from '../api'

// A file card returned alongside an answer: it's whatever vector_search hit,
// so the user can download or delete the source file without leaving the chat.
interface FileCard {
  file_id: string
  doc_type: string | null
  vendor: string | null
  summary: string | null
}
// Token usage + estimated cost the backend reports per answer (observability).
interface Usage {
  model: string
  input_tokens: number
  output_tokens: number
  tool_calls: number
  cost_usd: number
}
interface Msg {
  role: string
  content: string
  files?: FileCard[] // only present on live answers, never in stored history
  usage?: Usage // only on live answers; not persisted in conversation history
}
interface Conv {
  id: string
  title: string | null
}

// Multi-turn chat with a conversation sidebar. The backend remembers history
// per conversation, so follow-up questions like "它们多少钱？" work.
export default function ChatPage() {
  const [convs, setConvs] = useState<Conv[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)

  useEffect(() => {
    refreshConvs()
  }, [])

  const refreshConvs = async () => setConvs(await listConversations())

  const openConv = async (id: string) => {
    setActiveId(id)
    setMessages(await getMessages(id))
  }

  const newConv = async () => {
    const conv = await createConversation()
    await refreshConvs()
    setActiveId(conv.id)
    setMessages([])
  }

  const send = async () => {
    if (!input.trim() || sending) return

    // If no conversation is open yet, create one on the fly.
    let convId = activeId
    if (!convId) {
      const conv = await createConversation()
      convId = conv.id
      setActiveId(convId)
    }

    const question = input
    setInput('')
    setMessages((prev) => [...prev, { role: 'user', content: question }])
    setSending(true)
    try {
      // convId is guaranteed non-null here (set just above if it was null).
      const data = await askInConversation(convId!, question)
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: data.answer,
          files: data.files,
          usage: data.usage,
        },
      ])
      refreshConvs() // the first question may have set the conversation title
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: '（出错了，请重试）' },
      ])
    } finally {
      setSending(false)
    }
  }

  // Delete a file straight from the chat. On success, drop its card from every
  // message that referenced it so the buttons disappear immediately.
  const removeFile = async (fileId: string) => {
    if (!confirm('确定删除这个文件吗？此操作不可恢复。')) return
    try {
      await deleteDocument(fileId)
      setMessages((prev) =>
        prev.map((m) =>
          m.files
            ? { ...m, files: m.files.filter((f) => f.file_id !== fileId) }
            : m,
        ),
      )
    } catch {
      alert('删除失败，请重试')
    }
  }

  return (
    <div className="chat">
      <aside className="conv-list">
        <button className="new-conv" onClick={newConv}>
          ＋ 新对话
        </button>
        {convs.map((c) => (
          <div
            key={c.id}
            className={`conv-item ${c.id === activeId ? 'active' : ''}`}
            onClick={() => openConv(c.id)}
          >
            {c.title || '新对话'}
          </div>
        ))}
      </aside>

      <section className="chat-main">
        <div className="messages">
          {messages.length === 0 && (
            <div className="empty">问点什么吧，比如「我有哪些发票？」</div>
          )}
          {messages.map((m, i) => (
            <div key={i} className={`msg ${m.role}`}>
              <div className={`bubble ${m.role}`}>{m.content}</div>
              {m.files && m.files.length > 0 && (
                <div className="file-cards">
                  {m.files.map((f) => (
                    <div key={f.file_id} className="file-card">
                      <div className="file-card-info">
                        <span className="file-card-title">
                          {f.vendor || f.doc_type || '文件'}
                        </span>
                        {f.summary && (
                          <span className="file-card-sum">{f.summary}</span>
                        )}
                      </div>
                      <div className="file-card-actions">
                        <button
                          className="btn-sm"
                          onClick={() =>
                            downloadDocument(f.file_id).catch(() =>
                              alert('下载失败，请重试'),
                            )
                          }
                        >
                          下载
                        </button>
                        <button
                          className="btn-sm btn-danger"
                          onClick={() => removeFile(f.file_id)}
                        >
                          删除
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {/* Observability: show token usage + estimated cost for this answer */}
              {m.usage && (
                <div className="usage-line" title={`模型 ${m.usage.model}`}>
                  ${m.usage.cost_usd.toFixed(4)} · {m.usage.input_tokens}↑/
                  {m.usage.output_tokens}↓ tokens · {m.usage.tool_calls} 次工具调用
                </div>
              )}
            </div>
          ))}
          {sending && <div className="bubble assistant pending">思考中…</div>}
        </div>

        <div className="composer">
          <input
            value={input}
            placeholder="输入问题…"
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              // Enter sends, but ignore it while an IME is composing Chinese.
              if (e.key === 'Enter' && !e.nativeEvent.isComposing) send()
            }}
          />
          <button onClick={send} disabled={sending}>
            发送
          </button>
        </div>
      </section>
    </div>
  )
}
