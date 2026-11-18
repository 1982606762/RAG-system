import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import DocumentReader from '../src/components/DocumentReader'
import OriginalText from '../src/components/OriginalText'
import { getDocument, getOriginal, getPagePreview, type DocumentDetail, type SourceLocation } from '../src/api'
import { useLang } from '../src/i18n'

vi.mock('../src/api', () => ({ getDocument: vi.fn(), getOriginal: vi.fn(), getPagePreview: vi.fn(), createEmbeddings: vi.fn() }))

const text = '# 😀手册\r\n\r\n  清洁滤网。<script>bad()</script>  \r\n'
const textLocation: SourceLocation = { type: 'text', start: 9, end: Array.from(text).length - 2, start_line: 3, end_line: 3 }
const document: DocumentDetail = {
  id: 'source-document', filename: 'manual.md', extension: '.md', size_bytes: 100,
  status: 'ready', stage: 'complete', error_code: null, error_message: null, page_count: null,
  block_count: 1, chunk_count: 1, warnings: [], created_at: '', parser_version: 'local-blocks-v2',
  chunker_version: 'structure-chars-v1', chunk_config: {},
  blocks: [{ index: 0, kind: 'paragraph', text: '清洁滤网。', page: null, bbox: null, section: [], method: 'text', location: textLocation }],
  chunks: [{ index: 0, kind: 'text', text: '清洁滤网。', section: [], sources: [{ block_index: 0, page: null, start: 0, end: 5 }] }],
}

beforeEach(() => {
  vi.resetAllMocks()
  useLang.setState({ lang: 'zh' })
  vi.mocked(getDocument).mockResolvedValue({ data: document } as never)
  const blob = new Blob([text])
  Object.defineProperty(blob, 'text', { value: async () => text })
  vi.mocked(getOriginal).mockResolvedValue({ data: blob } as never)
  vi.mocked(getPagePreview).mockResolvedValue({ data: new Blob(['png']) } as never)
  URL.createObjectURL = vi.fn(() => 'blob:source')
})

describe('Original source navigation', () => {
  it('opens a search source in the original and highlights code points after an emoji and CRLF', async () => {
    const { container } = render(<DocumentReader id={document.id} initialBlock={0} revision={0} busy={false} onRetry={vi.fn()} onClose={vi.fn()} />)
    await waitFor(() => expect(container.querySelector('mark')).toHaveTextContent('清洁滤网。<script>bad()</script>'))
    expect(container.querySelector('mark')?.textContent).toBe('  清洁滤网。<script>bad()</script>  ')
    expect(container.querySelector('script')).toBeNull()
    expect(screen.getByText('原件行号 3–3')).toBeVisible()
    expect(screen.getByRole('button', { name: '原件', exact: true })).toHaveAttribute('aria-pressed', 'true')
  })

  it('opens a chunk source in the original instead of losing its location', async () => {
    const { container } = render(<DocumentReader id={document.id} revision={0} busy={false} onRetry={vi.fn()} onClose={vi.fn()} />)
    await screen.findByText('清洁滤网。')
    await userEvent.click(screen.getByRole('button', { name: '分块结果' }))
    await userEvent.click(screen.getByRole('button', { name: '查看来源 · 内容块 1' }))
    await waitFor(() => expect(container.querySelector('mark')).toBeInTheDocument())
  })

  it('uses the extracted block as an explicit fallback for legacy text', async () => {
    vi.mocked(getDocument).mockResolvedValue({ data: { ...document, blocks: [{ ...document.blocks[0], location: undefined }] } } as never)
    const { container } = render(<DocumentReader id={document.id} initialBlock={0} revision={0} busy={false} onRetry={vi.fn()} onClose={vi.fn()} />)
    await screen.findByText(/没有可靠的原件位置/)
    expect(container.querySelector('.text-block.highlighted')).toHaveTextContent('清洁滤网。')
    expect(getOriginal).not.toHaveBeenCalled()
  })

  it('does not highlight invalid out-of-range text offsets', () => {
    const { container } = render(<OriginalText text="short" location={{ ...textLocation, end: 1000 }} />)
    expect(container.querySelector('mark')).toBeNull()
    expect(screen.getByText('short')).toBeVisible()
  })

  it('highlights a PDF source on the right page and clears the region when paging', async () => {
    vi.mocked(getDocument).mockResolvedValue({ data: { ...document, extension: '.pdf', filename: 'manual.pdf', page_count: 3,
      blocks: [{ ...document.blocks[0], page: 2, location: { type: 'page', page: 2, bbox: [.1, .2, .6, .4] } }] } } as never)
    const { container } = render(<DocumentReader id={document.id} initialBlock={0} revision={0} busy={false} onRetry={vi.fn()} onClose={vi.fn()} />)
    const image = await screen.findByRole('img', { name: 'manual.pdf · 页 2' })
    fireEvent.load(image)
    expect(await screen.findByRole('img', { name: '引用的原文区域' })).toHaveStyle({ left: '10%', top: '20%', width: '50%', height: '20%' })
    expect(getPagePreview).toHaveBeenCalledWith(document.id, 2, expect.any(AbortSignal))
    await userEvent.click(screen.getByRole('button', { name: '下一页' }))
    expect(await screen.findByRole('img', { name: 'manual.pdf · 页 3' })).toBeVisible()
    expect(container.querySelector('.source-region')).toBeNull()
    expect(screen.getByRole('button', { name: '下一页' })).toBeDisabled()
  })

  it('opens a legacy PDF page without inventing a highlight', async () => {
    vi.mocked(getDocument).mockResolvedValue({ data: { ...document, extension: '.pdf', filename: 'manual.pdf', page_count: 3,
      blocks: [{ ...document.blocks[0], page: 2, location: null }] } } as never)
    const { container } = render(<DocumentReader id={document.id} initialBlock={0} revision={0} busy={false} onRetry={vi.fn()} onClose={vi.fn()} />)
    fireEvent.load(await screen.findByRole('img', { name: 'manual.pdf · 页 2' }))
    expect(screen.getByText(/已打开来源页/)).toBeVisible()
    expect(container.querySelector('.source-region')).toBeNull()
  })

  it('scrolls and focuses the reader again for the same PDF citation without a region', async () => {
    vi.mocked(getDocument).mockResolvedValue({ data: { ...document, extension: '.pdf', filename: 'manual.pdf', page_count: 3,
      blocks: [{ ...document.blocks[0], page: 2, location: null }] } } as never)
    const props = { id: document.id, initialBlock: 0, revision: 0, busy: false, onRetry: vi.fn(), onClose: vi.fn() }
    const { rerender } = render(<DocumentReader {...props} />)
    await screen.findByRole('img', { name: 'manual.pdf · 页 2' })
    const reader = screen.getByRole('region', { name: 'manual.pdf' })
    expect(reader).toHaveFocus()
    const scroll = vi.spyOn(reader, 'scrollIntoView')
    scroll.mockClear()
    reader.blur()

    // Clicking the identical source increments revision without remounting the reader.
    rerender(<DocumentReader {...props} revision={1} />)
    await waitFor(() => expect(getDocument).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(scroll).toHaveBeenCalledWith({ behavior: 'smooth', block: 'start' }))
    expect(reader).toHaveFocus()
    expect(screen.getByText('页 2 / 3')).toBeVisible()
    expect(screen.queryByRole('img', { name: '引用的原文区域' })).not.toBeInTheDocument()
  })
})
