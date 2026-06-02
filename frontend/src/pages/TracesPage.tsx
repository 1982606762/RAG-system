import { useEffect, useState } from 'react'
import { listTraces, getTrace } from '../api'

// Observability page: every agentic-RAG run is recorded as a "trace". This page
// lists recent runs (cost / latency / tool count) and lets you open one to see
// the full step-by-step timeline — what makes an otherwise black-box LLM loop
// debuggable.

interface TraceRow {
  id: string
  question: string
  model: string
  cost_usd: number | null
  tool_calls: number
  num_turns: number
  duration_ms: number
  status: string
  created_at: string
}

interface Step {
  seq: number
  type: 'llm' | 'tool'
  name: string
  duration_ms: number
  input_tokens?: number
  output_tokens?: number
  stop_reason?: string
  input?: string
  output_preview?: string
}

interface TraceDetail extends TraceRow {
  answer: string
  input_tokens: number
  output_tokens: number
  error: string | null
  steps: Step[]
}

export default function TracesPage() {
  const [rows, setRows] = useState<TraceRow[]>([])
  const [loading, setLoading] = useState(true)
  const [openId, setOpenId] = useState<string | null>(null)
  const [detail, setDetail] = useState<TraceDetail | null>(null)

  useEffect(() => {
    listTraces()
      .then(setRows)
      .finally(() => setLoading(false))
  }, [])

  const open = async (id: string) => {
    setOpenId(id)
    setDetail(null)
    setDetail(await getTrace(id))
  }

  return (
    <div className="page">
      <h2>运行轨迹 / Traces（{rows.length}）</h2>
      <p className="muted-hint">
        每次问答的 Agent 运行记录：调用了哪些工具、每步耗时、token 与成本。
      </p>

      {loading ? (
        <div>加载中…</div>
      ) : (
        <table className="docs">
          <thead>
            <tr>
              <th>时间</th>
              <th>问题</th>
              <th>模型</th>
              <th>成本</th>
              <th>耗时</th>
              <th>轮次/工具</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((t) => (
              <tr key={t.id} className="doc-row" onClick={() => open(t.id)}>
                <td>{t.created_at?.slice(0, 19).replace('T', ' ')}</td>
                <td className="trace-q">{t.question}</td>
                <td>{t.model}</td>
                <td>${(t.cost_usd ?? 0).toFixed(4)}</td>
                <td>{t.duration_ms} ms</td>
                <td>
                  {t.num_turns} / {t.tool_calls}
                </td>
                <td>
                  <span className={`badge ${t.status}`}>{t.status}</span>
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={7} className="empty-row">
                  还没有运行记录，去「问答」问点什么
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}

      {openId && (
        <div className="modal-backdrop" onClick={() => setOpenId(null)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <button className="modal-close" onClick={() => setOpenId(null)}>
              ✕
            </button>
            <div className="trace-detail">
              {!detail ? (
                <div className="modal-hint">加载中…</div>
              ) : (
                <>
                  <h3>运行详情</h3>
                  <dl className="meta-grid">
                    <dt>问题</dt><dd>{detail.question}</dd>
                    <dt>模型</dt><dd>{detail.model}</dd>
                    <dt>成本</dt><dd>${(detail.cost_usd ?? 0).toFixed(6)}</dd>
                    <dt>Tokens</dt>
                    <dd>
                      {detail.input_tokens}↑ / {detail.output_tokens}↓
                    </dd>
                    <dt>耗时</dt><dd>{detail.duration_ms} ms</dd>
                    <dt>状态</dt>
                    <dd>
                      <span className={`badge ${detail.status}`}>
                        {detail.status}
                      </span>
                      {detail.error ? ` — ${detail.error}` : ''}
                    </dd>
                  </dl>

                  <h4>步骤时间线</h4>
                  <ol className="timeline">
                    {detail.steps.map((s) => (
                      <li key={s.seq} className={`tl-item tl-${s.type}`}>
                        <div className="tl-head">
                          <span className="tl-type">
                            {s.type === 'llm' ? '🧠 LLM' : '🛠 工具'}
                          </span>
                          <span className="tl-name">{s.name}</span>
                          <span className="tl-dur">{s.duration_ms} ms</span>
                        </div>
                        {s.type === 'llm' && (
                          <div className="tl-meta">
                            {s.input_tokens}↑/{s.output_tokens}↓ tokens · stop:{' '}
                            {s.stop_reason}
                          </div>
                        )}
                        {s.type === 'tool' && (
                          <div className="tl-meta">
                            <div>入参：{s.input}</div>
                            <div className="tl-out">结果：{s.output_preview}</div>
                          </div>
                        )}
                      </li>
                    ))}
                  </ol>

                  <h4>最终答案</h4>
                  <div className="trace-answer">{detail.answer}</div>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
