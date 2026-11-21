import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import WorkspacePage from '../src/pages/WorkspacePage'
import DocumentReader from '../src/components/DocumentReader'
import { useLang } from '../src/i18n'
import { deleteConversation, getConversation, listConversations, saveConversationTurn, getDocument, getOriginal, getPagePreview, listDocuments, searchDocuments, uploadDocument, type DocumentDetail } from '../src/api'

vi.mock('../src/api', () => ({
  getDocument: vi.fn(), getOriginal: vi.fn(), getPagePreview: vi.fn(), listDocuments: vi.fn(),
  retryDocument: vi.fn(), uploadDocument: vi.fn(), searchDocuments: vi.fn(), createEmbeddings: vi.fn(),
  deleteConversation: vi.fn(), getConversation: vi.fn(), listConversations: vi.fn(), saveConversationTurn: vi.fn(),
}))

const document: DocumentDetail = {
  id: 'test-document', filename: 'manual.md', extension: '.md', size_bytes: 50,
  status: 'ready', stage: 'complete', error_code: null, error_message: null,
  page_count: null, block_count: 2, chunk_count: 1, warnings: [], created_at: '',
  parser_version: 'local-blocks-v1', chunker_version: 'structure-chars-v1',
  chunk_config: { unit: 'unicode_characters', target: 1600, maximum: 2400, overlap: 200 },
  blocks: [
    { index: 0, kind: 'heading', text: '维护手册', page: null, bbox: null, section: ['维护手册'], method: 'text' },
    { index: 1, kind: 'paragraph', text: '每月清洁滤网。<script>window.bad=true</script>', page: 2, bbox: null, section: ['维护手册'], method: 'text' },
  ],
  chunks: [{ index: 0, kind: 'text', text: '每月清洁滤网。', section: ['维护手册'], sources: [{ block_index: 1, page: 2, start: 0, end: 7 }] }],
}

beforeEach(() => {
  vi.resetAllMocks()
  useLang.setState({ lang: 'zh' })
  localStorage.removeItem('rag-selected-conversation')
  vi.mocked(listConversations).mockResolvedValue({ data: { items: [] } } as never)
  vi.mocked(listDocuments).mockResolvedValue({ data: { items: [], total: 0 } } as never)
  vi.mocked(getDocument).mockResolvedValue({ data: document } as never)
  vi.mocked(getOriginal).mockResolvedValue({ data: new Blob(['Original']) } as never)
  vi.mocked(getPagePreview).mockRejectedValue(new Error('Preview unavailable'))
  URL.createObjectURL = vi.fn(() => 'blob:test-original')
})

async function navigate(name: '资料库' | '搜索' | '资料问答') {
  await userEvent.click(within(screen.getByRole('navigation')).getByRole('button', { name: new RegExp(name) }))
}

describe('Document workspace', () => {
  it('separates interpretation notes from gaps and preserves legacy saved explanations', async () => {
    const conversation = { id: 'notes-conversation', title: '合同费用', updated_at: '' }
    const answer = { paragraphs: [{ text: '合同列有每月费用预估。', source_ids: ['S1'] }], citations: {},
      limitations: '', notes: '合同预估值不代表实际扣款。' }
    const turns = [
      { id: 'estimate', question: '合同怎么写的？', depth: 'auto', answer },
      { id: 'actual', question: '实际付了多少？', depth: 'auto',
        answer: { ...answer, paragraphs: [], notes: '', limitations: '尚未找到付款凭证。' } },
      { id: 'legacy', question: '旧答案', depth: 'auto',
        answer: { paragraphs: answer.paragraphs, citations: {}, limitations: '请核实合同对应的房产。' } },
    ]
    vi.mocked(listConversations).mockResolvedValue({ data: { items: [conversation] } } as never)
    vi.mocked(getConversation).mockResolvedValue({ data: { ...conversation, turns } } as never)
    localStorage.setItem('rag-selected-conversation', conversation.id)
    render(<WorkspacePage />)
    const estimate = (await screen.findByRole('heading', { name: '合同怎么写的？' })).closest('article')!
    expect(within(estimate).getByRole('heading', { name: '说明', exact: true })).toBeVisible()
    expect(within(estimate).queryByRole('heading', { name: '资料缺口' })).not.toBeInTheDocument()
    const actual = screen.getByRole('heading', { name: '实际付了多少？' }).closest('article')!
    expect(within(actual).getByRole('heading', { name: '资料缺口' })).toBeVisible()
    expect(within(actual).getByText('尚未找到付款凭证。')).toBeVisible()
    const legacy = screen.getByRole('heading', { name: '旧答案' }).closest('article')!
    expect(within(legacy).getByRole('heading', { name: '说明与待核实信息' })).toBeVisible()
    expect(within(legacy).getByText('请核实合同对应的房产。')).toBeVisible()
  })

  it('restores three saved turns, submits a follow-up and opens its citation', async () => {
    const conversation = { id: 'test-conversation', title: '多久清洗一次？', updated_at: '' }
    const answer = {
      paragraphs: [{ text: '每月清洗一次。', source_ids: ['S1'] }],
      citations: { S1: { document_id: document.id, filename: document.filename, locations: [{ block_index: 1, page: 2 }] } },
      limitations: '特殊环境的周期未注明。',
    }
    const turns = ['多久清洗一次？', '哪里写的？', '潮湿环境呢？'].map((question, index) =>
      ({ id: `turn-${index}`, question, depth: 'auto', answer: { ...answer, paragraphs: [], limitations: '已保存的答案' } }))
    const next = { id: 'fourth', question: '那一般情况呢？', depth: 'deep', answer }
    vi.mocked(listConversations).mockResolvedValue({ data: { items: [conversation] } } as never)
    vi.mocked(getConversation).mockResolvedValue({ data: { ...conversation, turns } } as never)
    vi.mocked(saveConversationTurn).mockResolvedValue({ data: { conversation, turn: next } } as never)
    localStorage.setItem('rag-selected-conversation', conversation.id)
    const { container } = render(<WorkspacePage />)
    expect(await screen.findByRole('heading', { name: '潮湿环境呢？' })).toBeVisible()
    await userEvent.type(screen.getByRole('textbox', { name: '向资料提问' }), next.question)
    await userEvent.selectOptions(screen.getByRole('combobox', { name: '查询深度' }), 'deep')
    await userEvent.click(screen.getByRole('button', { name: '提问', exact: true }))
    expect(await screen.findByText('每月清洗一次。')).toBeVisible()
    expect(screen.getByText('特殊环境的周期未注明。')).toBeVisible()
    expect(saveConversationTurn).toHaveBeenCalledWith(conversation.id, next.question, 'deep',
      expect.any(String), 'turn-2', expect.any(AbortSignal))
    await userEvent.click(screen.getByRole('button', { name: /\[S1\] manual.md/ }))
    await waitFor(() => expect(container.querySelector('.highlighted')).toHaveTextContent('每月清洁滤网'))
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.mocked(deleteConversation).mockResolvedValue({} as never)
    try {
      await userEvent.click(screen.getByRole('button', { name: '删除会话' }))
      await waitFor(() => expect(screen.queryByText('每月清洗一次。')).not.toBeInTheDocument())
      expect(deleteConversation).toHaveBeenCalledWith(conversation.id, expect.any(AbortSignal))
      expect(localStorage.getItem('rag-selected-conversation')).toBeNull()
    } finally { confirm.mockRestore() }
  })

  it('ignores an older search response after a new search completes', async () => {
    let finishOld!: (value: unknown) => void
    vi.mocked(searchDocuments).mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve }) as never)
      .mockResolvedValueOnce({ data: { items: [], has_more: false } } as never)
    render(<WorkspacePage />)
    await navigate('搜索')
    await userEvent.selectOptions(screen.getByRole('combobox', { name: '搜索模式' }), 'keyword')
    const input = screen.getByRole('searchbox')
    await userEvent.type(input, 'old')
    await userEvent.click(within(screen.getByRole('region', { name: '搜索资料' })).getByRole('button', { name: '搜索', exact: true }))
    await userEvent.clear(input)
    await userEvent.type(input, 'new')
    await userEvent.click(within(screen.getByRole('region', { name: '搜索资料' })).getByRole('button', { name: '搜索', exact: true }))
    await screen.findByText('没有找到匹配的片段。试试更短的关键词。')
    finishOld({ data: { items: [{ document_id: document.id, filename: document.filename,
      chunk_index: 0, chunk: document.chunks[0] }], has_more: false } })
    await waitFor(() => expect(screen.queryByText('manual.md')).not.toBeInTheDocument())
    expect(screen.getByText('搜索结果 «new»')).toBeVisible()
  })

  it('searches chunks and opens the selected source after the document loads', async () => {
    vi.mocked(searchDocuments).mockResolvedValue({ data: { items: [{ document_id: document.id,
      filename: document.filename, chunk_index: 0, chunk: document.chunks[0] }], has_more: false } } as never)
    const { container } = render(<WorkspacePage />)
    await navigate('搜索')
    await userEvent.selectOptions(screen.getByRole('combobox', { name: '搜索模式' }), 'keyword')
    await userEvent.type(screen.getByRole('searchbox'), '滤网')
    await userEvent.click(within(screen.getByRole('region', { name: '搜索资料' })).getByRole('button', { name: '搜索', exact: true }))
    await userEvent.click(await screen.findByRole('button', { name: '查看来源 · 内容块 2' }))
    await waitFor(() => expect(container.querySelector('.highlighted')).toHaveTextContent('每月清洁滤网'))
    expect(searchDocuments).toHaveBeenCalledWith('滤网', 0, expect.any(AbortSignal), 'keyword')
  })

  it('keeps the submitted semantic mode while paging and opens the original source', async () => {
    const hit = { document_id: document.id, filename: document.filename, chunk_index: 0, chunk: document.chunks[0] }
    vi.mocked(searchDocuments)
      .mockResolvedValueOnce({ data: { items: [hit], has_more: true } } as never)
      .mockResolvedValueOnce({ data: { items: [{ ...hit, chunk_index: 1 }], has_more: false } } as never)
    const { container } = render(<WorkspacePage />)
    await navigate('搜索')
    await userEvent.selectOptions(screen.getByRole('combobox', { name: '搜索模式' }), 'keyword')
    const mode = screen.getByRole('combobox', { name: '搜索模式' })
    await userEvent.selectOptions(mode, 'semantic')
    await userEvent.type(screen.getByRole('searchbox'), '零件多久维护一次')
    await userEvent.click(within(screen.getByRole('region', { name: '搜索资料' })).getByRole('button', { name: '搜索', exact: true }))
    expect(await screen.findByText(/语义搜索结果 «零件多久维护一次»/)).toBeVisible()
    await userEvent.selectOptions(mode, 'keyword')
    await userEvent.click(screen.getByRole('button', { name: '下一页' }))
    expect(searchDocuments).toHaveBeenLastCalledWith('零件多久维护一次', 30, expect.any(AbortSignal), 'semantic')
    await userEvent.click(await screen.findByRole('button', { name: '查看来源 · 内容块 2' }))
    await waitFor(() => expect(container.querySelector('.highlighted')).toHaveTextContent('每月清洁滤网'))
  })

  it('explains a missing semantic index and lets the user switch back to keywords', async () => {
    vi.mocked(searchDocuments)
      .mockRejectedValueOnce({ isAxiosError: true, response: { data: { code: 'semantic_index_empty' } } })
      .mockResolvedValueOnce({ data: { items: [], has_more: false } } as never)
    render(<WorkspacePage />)
    await navigate('搜索')
    await userEvent.selectOptions(screen.getByRole('combobox', { name: '搜索模式' }), 'keyword')
    const mode = screen.getByRole('combobox', { name: '搜索模式' })
    const submit = within(screen.getByRole('region', { name: '搜索资料' })).getByRole('button', { name: '搜索', exact: true })
    await userEvent.selectOptions(mode, 'semantic')
    await userEvent.type(screen.getByRole('searchbox'), '滤网')
    await userEvent.click(submit)
    expect(await screen.findByRole('alert')).toHaveTextContent('请先为至少一份资料完成向量生成')
    await userEvent.selectOptions(mode, 'keyword')
    await userEvent.click(submit)
    expect(await screen.findByText('搜索结果 «滤网»')).toBeVisible()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('uploads a file, waits for processing, then opens the returned document', async () => {
    let complete!: (value: unknown) => void
    vi.mocked(uploadDocument).mockImplementation((file, progress) => {
      progress(100)
      return new Promise(resolve => { complete = resolve }) as never
    })
    const { container } = render(<WorkspacePage />)
    await navigate('资料库')
    await screen.findByText('从第一份资料开始')
    const file = new File(['# Manual'], 'manual.md', { type: 'text/markdown' })
    fireEvent.change(container.querySelector('input[type=file]')!, { target: { files: [file] } })
    expect(await screen.findByText('正在解析与分块，请保持页面打开…')).toBeVisible()
    expect(screen.getByRole('button', { name: '选择文件' })).toBeDisabled()
    complete({ data: { document, duplicate: false } })
    expect(await screen.findByRole('heading', { name: 'manual.md' })).toBeVisible()
    expect(screen.getByText('文档已处理，可以查看内容和片段。')).toBeVisible()
    expect(screen.getByRole('button', { name: '选择文件' })).toBeEnabled()
  })

  it('opens the existing record for duplicate uploads', async () => {
    vi.mocked(uploadDocument).mockResolvedValue({ data: { document, duplicate: true } } as never)
    const { container } = render(<WorkspacePage />)
    await navigate('资料库')
    await screen.findByText('从第一份资料开始')
    fireEvent.change(container.querySelector('input[type=file]')!, { target: { files: [new File(['same'], 'manual.md')] } })
    expect(await screen.findByText('这份文件已存在，已打开原有记录。')).toBeVisible()
    expect(await screen.findByRole('heading', { name: 'manual.md' })).toBeVisible()
  })

  it.each([
    ['answer_unavailable', 'Gemini 暂时不可用'],
    ['answer_rate_limited', '模型服务当前请求受限'],
    ['answer_response', '模型请求或答案格式异常'],
    ['database_unavailable', '会话存储暂时不可用'],
  ])('explains %s, preserves the draft, and retries the same logical turn', async (code, message) => {
    const conversation = { id: 'retry-conversation', title: '维护周期', updated_at: '' }
    vi.mocked(saveConversationTurn).mockRejectedValueOnce({ isAxiosError: true, response: { data: { code } } })
      .mockResolvedValueOnce({ data: { conversation, turn: { id: 'retry-turn', question: '维护周期？', depth: 'auto',
        answer: { paragraphs: [], citations: {}, limitations: '资料尚未说明。' } } } } as never)
    render(<WorkspacePage />)
    const input = screen.getByRole('textbox', { name: '向资料提问' })
    await waitFor(() => expect(input).not.toHaveAttribute('readonly'))
    await userEvent.type(input, '维护周期？')
    await userEvent.click(screen.getByRole('button', { name: '提问', exact: true }))
    expect(await screen.findByRole('alert')).toHaveTextContent(message)
    expect(input).toHaveValue('维护周期？')
    const first = vi.mocked(saveConversationTurn).mock.calls[0]
    await userEvent.click(within(screen.getByRole('alert')).getByRole('button', { name: '重试' }))
    expect(await screen.findByText('资料尚未说明。')).toBeVisible()
    const second = vi.mocked(saveConversationTurn).mock.calls[1]
    expect(second.slice(0, 5)).toEqual(first.slice(0, 5))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('defaults to multilingual search, shows the actual three-language plan and preserves its mode while paging', async () => {
    const queries = { zh: ['车贷 利息'], en: ['loan interest'], da: ['renteomkostninger'] }
    const hit = { document_id: document.id, filename: 'danish-agreement.pdf', chunk_index: 0, chunk: document.chunks[0] }
    vi.mocked(searchDocuments).mockResolvedValueOnce({ data: { items: [hit], has_more: true, queries } } as never)
      .mockResolvedValueOnce({ data: { items: [], has_more: false, queries } } as never)
    render(<WorkspacePage />)
    await navigate('搜索')
    const mode = screen.getByRole('combobox', { name: '搜索模式' })
    expect(mode).toHaveValue('multilingual')
    await userEvent.type(screen.getByRole('searchbox'), '车贷利息')
    await userEvent.click(within(screen.getByRole('region', { name: '搜索资料' })).getByRole('button', { name: '搜索', exact: true }))
    expect(await screen.findByText('loan interest')).toBeVisible()
    expect(screen.getByText('renteomkostninger')).toBeVisible()
    expect(screen.getByText('中文')).toBeVisible()
    expect(screen.getByText('English')).toBeVisible()
    expect(screen.getByText('Dansk')).toBeVisible()
    expect(screen.getByText('danish-agreement.pdf')).toBeVisible()
    expect(searchDocuments).toHaveBeenLastCalledWith('车贷利息', 0, expect.any(AbortSignal), 'multilingual')
    await userEvent.selectOptions(mode, 'keyword')
    await userEvent.click(screen.getByRole('button', { name: '下一页' }))
    expect(searchDocuments).toHaveBeenLastCalledWith('车贷利息', 30, expect.any(AbortSignal), 'multilingual')
    expect(await screen.findByText(/三种语言的检索词均未找到匹配片段/)).toBeVisible()
  })

  it('explains multilingual service failure without claiming no matches and allows exact keyword search', async () => {
    vi.mocked(searchDocuments).mockRejectedValueOnce({ isAxiosError: true, response: { data: { code: 'multilingual_unavailable' } } })
      .mockResolvedValueOnce({ data: { items: [], has_more: false } } as never)
    render(<WorkspacePage />)
    await navigate('搜索')
    await userEvent.type(screen.getByRole('searchbox'), '车贷利息')
    const submit = within(screen.getByRole('region', { name: '搜索资料' })).getByRole('button', { name: '搜索', exact: true })
    await userEvent.click(submit)
    expect(await screen.findByRole('alert')).toHaveTextContent('暂时无法完成中英丹搜索')
    expect(screen.queryByText(/三种语言的检索词均未找到/)).not.toBeInTheDocument()
    expect(screen.getByRole('searchbox')).toHaveValue('车贷利息')
    await userEvent.selectOptions(screen.getByRole('combobox', { name: '搜索模式' }), 'keyword')
    await userEvent.click(submit)
    expect(await screen.findByText('搜索结果 «车贷利息»')).toBeVisible()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('keeps drafts and search results when switching workspaces', async () => {
    vi.mocked(searchDocuments).mockResolvedValue({ data: { items: [], has_more: false } } as never)
    render(<WorkspacePage />)
    await waitFor(() => expect(screen.getByRole('textbox', { name: '向资料提问' })).not.toHaveAttribute('readonly'))
    await userEvent.type(screen.getByRole('textbox', { name: '向资料提问' }), '尚未发送的问题')
    await navigate('搜索')
    await userEvent.selectOptions(screen.getByRole('combobox', { name: '搜索模式' }), 'keyword')
    await userEvent.type(screen.getByRole('searchbox'), '滤网')
    await userEvent.click(within(screen.getByRole('region', { name: '搜索资料' })).getByRole('button', { name: '搜索', exact: true }))
    expect(await screen.findByText('搜索结果 «滤网»')).toBeVisible()
    await navigate('资料问答')
    expect(screen.getByRole('textbox', { name: '向资料提问' })).toHaveValue('尚未发送的问题')
    await navigate('搜索')
    await userEvent.selectOptions(screen.getByRole('combobox', { name: '搜索模式' }), 'keyword')
    expect(screen.getByRole('searchbox')).toHaveValue('滤网')
    expect(screen.getByText('搜索结果 «滤网»')).toBeVisible()
    expect(searchDocuments).toHaveBeenCalledTimes(1)
  })

  it('fills a suggested question without sending it and supports the keyboard shortcut', async () => {
    const conversation = { id: 'suggested', title: '核心观点', updated_at: '' }
    vi.mocked(saveConversationTurn).mockResolvedValue({ data: { conversation, turn: {
      id: 'summary', question: '请总结资料中的核心观点，并标出相关来源。', depth: 'auto',
      answer: { paragraphs: [], citations: {}, limitations: '尚无资料' },
    } } } as never)
    render(<WorkspacePage />)
    await userEvent.click(await screen.findByRole('button', { name: /梳理核心观点/ }))
    const question = screen.getByRole('textbox', { name: '向资料提问' })
    expect(question).toHaveFocus()
    expect(question).toHaveValue('请总结资料中的核心观点，并标出相关来源。')
    expect(saveConversationTurn).not.toHaveBeenCalled()
    fireEvent.keyDown(question, { key: 'Enter', ctrlKey: true, isComposing: true })
    expect(saveConversationTurn).not.toHaveBeenCalled()
    fireEvent.keyDown(question, { key: 'Enter', ctrlKey: true })
    expect(await screen.findByText('尚无资料')).toBeVisible()
    expect(saveConversationTurn).toHaveBeenCalledTimes(1)
  })

  it('validates drag-and-drop files and prevents concurrent uploads', async () => {
    let complete!: (value: unknown) => void
    vi.mocked(uploadDocument).mockImplementation(() => new Promise(resolve => { complete = resolve }) as never)
    const { container } = render(<WorkspacePage />)
    await navigate('资料库')
    const zone = screen.getByRole('region', { name: '上传文件' })
    const drop = (files: File[]) => fireEvent.drop(zone, { dataTransfer: { types: ['Files'], files } })
    drop([new File(['x'], 'invalid.exe')])
    expect(screen.getByRole('alert')).toHaveTextContent('暂不支持此文件格式')
    expect(uploadDocument).not.toHaveBeenCalled()
    drop([new File(['a'], 'a.md'), new File(['b'], 'b.md')])
    expect(screen.getByRole('alert')).toHaveTextContent('每次上传一份文件')
    const file = new File(['# Manual'], 'manual.md')
    drop([file])
    drop([file])
    expect(uploadDocument).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('button', { name: '选择文件' })).toBeDisabled()
    complete({ data: { document, duplicate: false } })
    expect(await screen.findByRole('dialog', { name: '资料详情' })).toBeVisible()
    await screen.findByRole('heading', { name: 'manual.md' })
    fireEvent.keyDown(container, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '选择文件' })).toBeEnabled()
  })

  it('preserves actionable schema errors and allows refreshing', async () => {
    vi.mocked(listDocuments).mockRejectedValue({ isAxiosError: true, response: { status: 503, data: { code: 'schema_missing' } } })
    render(<WorkspacePage />)
    expect(await screen.findByRole('alert')).toHaveTextContent('init-db')
    await navigate('资料库')
    vi.mocked(listDocuments).mockResolvedValue({ data: { items: [document], total: 1 } } as never)
    await userEvent.click(screen.getByRole('button', { name: '刷新' }))
    expect(await screen.findByRole('button', { name: /manual.md/ })).toBeVisible()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('shows timeout uncertainty instead of claiming that upload failed', async () => {
    vi.mocked(uploadDocument).mockRejectedValue({ isAxiosError: true, code: 'ECONNABORTED' })
    const { container } = render(<WorkspacePage />)
    await navigate('资料库')
    await screen.findByText('从第一份资料开始')
    fireEvent.change(container.querySelector('input[type=file]')!, { target: { files: [new File(['hello'], 'manual.md')] } })
    expect(await screen.findByRole('alert')).toHaveTextContent('服务可能仍在处理')
    expect(screen.getByRole('button', { name: '选择文件' })).toBeEnabled()
  })
})

describe('Document reader', () => {
  it('renders document text safely and navigates from a chunk to its source block', async () => {
    const { container } = render(<DocumentReader id={document.id} revision={0} busy={false} onRetry={vi.fn()} onClose={vi.fn()} />)
    await screen.findByRole('heading', { name: '维护手册' })
    expect(container.querySelector('script')).toBeNull()
    expect(screen.getByText(document.blocks[1].text)).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: '分块结果' }))
    expect(screen.getByText(/按字符数分块/)).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: '查看来源 · 内容块 2' }))
    expect(container.querySelector('.highlighted')).toHaveTextContent('每月清洁滤网')
    expect(screen.getByRole('button', { name: '提取内容' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('requests the authenticated PDF and links to its source page', async () => {
    vi.mocked(getDocument).mockResolvedValue({ data: { ...document, extension: '.pdf', filename: 'manual.pdf' } } as never)
    const { container } = render(<DocumentReader id={document.id} revision={0} busy={false} onRetry={vi.fn()} onClose={vi.fn()} />)
    await screen.findByRole('heading', { name: '维护手册' })
    await userEvent.click(screen.getByRole('button', { name: '页 2 ↗' }))
    await waitFor(() => expect(container.querySelector('iframe')).toHaveAttribute('src', 'blob:test-original#page=2'))
    expect(getOriginal).toHaveBeenCalledWith(document.id, expect.any(AbortSignal))
  })

  it('shows the saved processing error and triggers manual retry', async () => {
    vi.mocked(getDocument).mockResolvedValue({ data: { ...document, status: 'failed', stage: 'parsing', error_message: 'OCR 不可用' } } as never)
    const retry = vi.fn()
    render(<DocumentReader id={document.id} revision={0} busy={false} onRetry={retry} onClose={vi.fn()} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('OCR 不可用')
    await userEvent.click(screen.getByRole('button', { name: '重新处理' }))
    expect(retry).toHaveBeenCalledOnce()
  })

  it('renders English controls when the UI language changes', async () => {
    useLang.setState({ lang: 'en' })
    render(<DocumentReader id={document.id} revision={0} busy={false} onRetry={vi.fn()} onClose={vi.fn()} />)
    expect(await screen.findByRole('button', { name: 'Download original' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Chunks' })).toBeVisible()
  })
})
