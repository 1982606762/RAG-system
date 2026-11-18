import { beforeEach, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import EmbeddingPanel from '../src/components/EmbeddingPanel'
import DocumentReader from '../src/components/DocumentReader'
import { createEmbeddings, getDocument, type DocumentDetail } from '../src/api'
import { useLang } from '../src/i18n'

vi.mock('../src/api', () => ({ createEmbeddings: vi.fn(), getDocument: vi.fn(), getOriginal: vi.fn(), getPagePreview: vi.fn() }))
const document: DocumentDetail = {
  id: 'embedding-document', filename: 'notes.md', extension: '.md', size_bytes: 100,
  status: 'ready', stage: 'complete', error_code: null, error_message: null, page_count: null,
  block_count: 3, chunk_count: 3, warnings: [], created_at: '', parser_version: 'local-blocks-v2',
  chunker_version: 'structure-chars-v1', chunk_config: {}, blocks: [], chunks: [],
  embedding: { status: 'failed', model: 'gemini-embedding-001', dimensions: 768,
    completed_chunks: 1, total_chunks: 3, vector_count: 1, error_code: 'embedding_quota', error_message: '向量服务暂时达到调用额度。' },
}

beforeEach(() => { vi.resetAllMocks(); useLang.setState({ lang: 'zh' }) })

it('shows partial progress independently of document readiness', () => {
  render(<EmbeddingPanel document={document} busy={false} onUpdated={vi.fn()} />)
  expect(screen.getByText('向量未完成')).toBeVisible()
  expect(screen.getByText('1/3 个片段已完成 · 1 个向量')).toBeVisible()
  expect(screen.getByText(/原件阅读和关键词搜索可独立使用/)).toBeVisible()
  expect(screen.getByRole('status')).toHaveTextContent('达到调用额度')
})

it('resumes the existing index and refreshes persisted state when finished', async () => {
  let complete!: (value: unknown) => void
  vi.mocked(createEmbeddings).mockImplementation(() => new Promise(resolve => { complete = resolve }) as never)
  const refresh = vi.fn()
  render(<EmbeddingPanel document={document} busy={false} onUpdated={refresh} />)
  await userEvent.click(screen.getByRole('button', { name: '生成 / 继续向量化' }))
  expect(screen.getByRole('button', { name: '正在生成向量…' })).toBeDisabled()
  complete({ data: document })
  await waitFor(() => expect(refresh).toHaveBeenCalledOnce())
  expect(createEmbeddings).toHaveBeenCalledWith(document.id)
})

it('keeps timeout uncertainty and refreshes status after a failed request', async () => {
  vi.mocked(createEmbeddings).mockRejectedValue(new Error('timeout'))
  const refresh = vi.fn()
  render(<EmbeddingPanel document={document} busy={false} onUpdated={refresh} />)
  await userEvent.click(screen.getByRole('button', { name: '生成 / 继续向量化' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('服务可能仍在处理')
  expect(refresh).toHaveBeenCalledOnce()
})

it('does not offer a cloud action when no project is configured', () => {
  render(<EmbeddingPanel document={{ ...document, embedding: { ...document.embedding!, status: 'disabled' } }} busy={false} onUpdated={vi.fn()} />)
  expect(screen.getByText('向量未配置')).toBeVisible()
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
})

it('blocks indexing while a document is still being parsed', () => {
  render(<EmbeddingPanel document={{ ...document, status: 'processing' }} busy={false} onUpdated={vi.fn()} />)
  expect(screen.getByRole('button', { name: '生成 / 继续向量化' })).toBeDisabled()
})

it('retains an embedding request error while the reader refreshes saved status', async () => {
  vi.mocked(getDocument).mockResolvedValue({ data: document } as never)
  vi.mocked(createEmbeddings).mockRejectedValue(new Error('busy'))
  render(<DocumentReader id={document.id} revision={0} busy={false} onRetry={vi.fn()} onClose={vi.fn()} />)
  await userEvent.click(await screen.findByRole('button', { name: '生成 / 继续向量化' }))
  await waitFor(() => expect(getDocument).toHaveBeenCalledTimes(2))
  expect(await screen.findByRole('alert')).toHaveTextContent('刷新状态后重试')
})
