import { create } from 'zustand'

// Tiny home-grown i18n — no extra dependency. A flat key->string dictionary per
// language, a zustand store holding the current language (persisted so a refresh
// keeps your choice), and a useT() hook that returns a translate function bound
// to the active language. Components re-render on language change because they
// subscribe to the store via the hook.

export type Lang = 'zh' | 'en'

interface LangState {
  lang: Lang
  setLang: (l: Lang) => void
  toggle: () => void
}

export const useLang = create<LangState>((set, get) => ({
  // Default to Chinese; honor a previously saved choice.
  lang: (localStorage.getItem('lang') as Lang) || 'zh',
  setLang: (lang) => {
    localStorage.setItem('lang', lang)
    set({ lang })
  },
  toggle: () => {
    const next: Lang = get().lang === 'zh' ? 'en' : 'zh'
    localStorage.setItem('lang', next)
    set({ lang: next })
  },
}))

// All UI strings. Keep keys flat and identical across languages.
const dict: Record<Lang, Record<string, string>> = {
  zh: {
    // app shell
    'app.brand': '📁 家用文件知识库',
    'nav.chat': '问答',
    'nav.upload': '上传',
    'nav.documents': '文件',
    'nav.traces': '轨迹',
    'app.logout': '退出',

    // shared
    'common.download': '下载',
    'common.delete': '删除',
    'common.loading': '加载中…',
    'common.confirmDelete': '确定删除这个文件吗？此操作不可恢复。',
    'common.deleteFailed': '删除失败，请重试',
    'common.downloadFailed': '下载失败，请重试',
    'common.file': '文件',

    // login
    'login.title': '登录',
    'login.register': '注册',
    'login.tagline': '用自然语言搜索和问答你的所有文件',
    'login.email': '邮箱',
    'login.password': '密码（至少 6 位）',
    'login.toRegister': '没有账号？去注册',
    'login.toLogin': '已有账号？去登录',
    'login.failed': '操作失败，请重试',
    'login.demoTitle': '体验账号',
    'login.demoFill': '一键填入',
    'login.demoHint': '点击「一键填入」后直接登录即可体验',

    // chat
    'chat.newConv': '＋ 新对话',
    'chat.convDefault': '新对话',
    'chat.empty': '问点什么吧，比如「我有哪些发票？」',
    'chat.thinking': '思考中…',
    'chat.inputPlaceholder': '输入问题…',
    'chat.send': '发送',
    'chat.error': '（出错了，请重试）',
    'chat.toolCalls': '{n} 次工具调用',

    // upload
    'upload.title': '上传文件',
    'upload.dropRelease': '松开即可上传',
    'upload.dropHint': '拖拽文件到这里，或点击选择（可多选）',
    'upload.dropSub': '支持图片或 PDF',
    'upload.camera': '📷 拍照上传',
    'upload.statusUploading': '上传中…',
    'upload.statusQueued': '排队中…',
    'upload.statusStarted': '分析中…',
    'upload.statusFailedPrefix': '✗ 失败：',
    'upload.statusDuplicate': '✓ 已存在（重复文件，已跳过）',
    'upload.statusDone': '✓ 完成',
    'upload.uploadFailed': '上传失败',
    'upload.taskQueryFailed': '查询任务状态失败',

    // documents
    'docs.title': '我的文件（{n}）',
    'docs.searchPlaceholder': '用自然语言搜索，例如「去年的水电费发票」',
    'docs.searching': '搜索中…',
    'docs.search': '搜索',
    'docs.clear': '清除',
    'docs.colType': '类型',
    'docs.colDate': '日期',
    'docs.colParty': '相关方',
    'docs.colAmount': '金额',
    'docs.colSummary': '摘要',
    'docs.colActions': '操作',
    'docs.noMatch': '没有找到匹配的文件',
    'docs.noFiles': '还没有文件，去「上传」试试',

    // file detail modal
    'detail.title': '文件详情',
    'detail.close': '关闭',
    'detail.previewLoading': '预览加载中…',
    'detail.noPreview': '该文件类型不支持预览，请下载查看',
    'detail.previewAlt': '预览',
    'detail.pdfTitle': 'PDF 预览',
    'detail.section': '详细信息',

    // traces
    'traces.title': '运行轨迹 / Traces（{n}）',
    'traces.hint': '每次问答的 Agent 运行记录：调用了哪些工具、每步耗时、token 与成本。',
    'traces.colTime': '时间',
    'traces.colQuestion': '问题',
    'traces.colModel': '模型',
    'traces.colCost': '成本',
    'traces.colDuration': '耗时',
    'traces.colTurnsTools': '轮次/工具',
    'traces.colStatus': '状态',
    'traces.empty': '还没有运行记录，去「问答」问点什么',
    'traces.detail': '运行详情',
    'traces.fieldQuestion': '问题',
    'traces.fieldModel': '模型',
    'traces.fieldCost': '成本',
    'traces.fieldDuration': '耗时',
    'traces.fieldStatus': '状态',
    'traces.timeline': '步骤时间线',
    'traces.llm': '🧠 LLM',
    'traces.tool': '🛠 工具',
    'traces.stepInput': '入参：',
    'traces.stepResult': '结果：',
    'traces.finalAnswer': '最终答案',
  },
  en: {
    // app shell
    'app.brand': '📁 Home File Knowledge Base',
    'nav.chat': 'Chat',
    'nav.upload': 'Upload',
    'nav.documents': 'Files',
    'nav.traces': 'Traces',
    'app.logout': 'Log out',

    // shared
    'common.download': 'Download',
    'common.delete': 'Delete',
    'common.loading': 'Loading…',
    'common.confirmDelete': 'Delete this file? This cannot be undone.',
    'common.deleteFailed': 'Delete failed, please try again',
    'common.downloadFailed': 'Download failed, please try again',
    'common.file': 'File',

    // login
    'login.title': 'Sign in',
    'login.register': 'Sign up',
    'login.tagline': 'Search and ask questions about all your files in plain language',
    'login.email': 'Email',
    'login.password': 'Password (min 6 chars)',
    'login.toRegister': "No account? Sign up",
    'login.toLogin': 'Already have an account? Sign in',
    'login.failed': 'Something went wrong, please try again',
    'login.demoTitle': 'Demo account',
    'login.demoFill': 'Fill in',
    'login.demoHint': 'Click "Fill in", then sign in to try it out',

    // chat
    'chat.newConv': '＋ New chat',
    'chat.convDefault': 'New chat',
    'chat.empty': 'Ask me anything, e.g. "What invoices do I have?"',
    'chat.thinking': 'Thinking…',
    'chat.inputPlaceholder': 'Type your question…',
    'chat.send': 'Send',
    'chat.error': '(Something went wrong, please retry)',
    'chat.toolCalls': '{n} tool calls',

    // upload
    'upload.title': 'Upload files',
    'upload.dropRelease': 'Release to upload',
    'upload.dropHint': 'Drag files here, or click to select (multiple allowed)',
    'upload.dropSub': 'Images or PDF supported',
    'upload.camera': '📷 Take a photo',
    'upload.statusUploading': 'Uploading…',
    'upload.statusQueued': 'Queued…',
    'upload.statusStarted': 'Analyzing…',
    'upload.statusFailedPrefix': '✗ Failed: ',
    'upload.statusDuplicate': '✓ Already exists (duplicate, skipped)',
    'upload.statusDone': '✓ Done',
    'upload.uploadFailed': 'Upload failed',
    'upload.taskQueryFailed': 'Failed to query task status',

    // documents
    'docs.title': 'My files ({n})',
    'docs.searchPlaceholder': 'Search in plain language, e.g. "last year\'s utility bills"',
    'docs.searching': 'Searching…',
    'docs.search': 'Search',
    'docs.clear': 'Clear',
    'docs.colType': 'Type',
    'docs.colDate': 'Date',
    'docs.colParty': 'Party',
    'docs.colAmount': 'Amount',
    'docs.colSummary': 'Summary',
    'docs.colActions': 'Actions',
    'docs.noMatch': 'No matching files found',
    'docs.noFiles': 'No files yet — try the Upload tab',

    // file detail modal
    'detail.title': 'File details',
    'detail.close': 'Close',
    'detail.previewLoading': 'Loading preview…',
    'detail.noPreview': "This file type can't be previewed — download to view",
    'detail.previewAlt': 'Preview',
    'detail.pdfTitle': 'PDF preview',
    'detail.section': 'Details',

    // traces
    'traces.title': 'Run Traces ({n})',
    'traces.hint': 'A record of each agent run: which tools were called, time per step, tokens and cost.',
    'traces.colTime': 'Time',
    'traces.colQuestion': 'Question',
    'traces.colModel': 'Model',
    'traces.colCost': 'Cost',
    'traces.colDuration': 'Duration',
    'traces.colTurnsTools': 'Turns/Tools',
    'traces.colStatus': 'Status',
    'traces.empty': 'No runs yet — ask something in Chat',
    'traces.detail': 'Run details',
    'traces.fieldQuestion': 'Question',
    'traces.fieldModel': 'Model',
    'traces.fieldCost': 'Cost',
    'traces.fieldDuration': 'Duration',
    'traces.fieldStatus': 'Status',
    'traces.timeline': 'Step timeline',
    'traces.llm': '🧠 LLM',
    'traces.tool': '🛠 Tool',
    'traces.stepInput': 'Input: ',
    'traces.stepResult': 'Result: ',
    'traces.finalAnswer': 'Final answer',
  },
}

// Returns a translate function bound to the current language. Supports {name}
// placeholders: t('docs.title', { n: 5 }).
export function useT() {
  const lang = useLang((s) => s.lang)
  return (key: string, vars?: Record<string, string | number>) => {
    let s = dict[lang][key] ?? dict.zh[key] ?? key
    if (vars) {
      for (const k in vars) s = s.replace(`{${k}}`, String(vars[k]))
    }
    return s
  }
}

// Demo credentials shown on the login page (and offered as one-click fill).
// Create the matching account on the server with:
//   docker compose exec app python cli.py create-user demo@demo.com demo12345
export const DEMO_EMAIL = 'demo@demo.com'
export const DEMO_PASSWORD = 'demo12345'
