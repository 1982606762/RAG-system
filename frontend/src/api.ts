import axios from 'axios'
import { useAuth } from './store'

export const http = axios.create({ timeout: 15000 })

http.interceptors.request.use((config) => {
  const token = useAuth.getState().token
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

http.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) useAuth.getState().logout()
    return Promise.reject(error)
  },
)

export async function login(password: string): Promise<string> {
  const { data } = await http.post<{ access_token: string }>('/api/auth/login', { password })
  return data.access_token
}

export const getSession = () => http.get<{ role: 'owner' }>('/api/auth/me')
export const getHealth = () => http.get<{ postgres: boolean }>('/api/health')

export interface DocumentRecord {
  id: string
  filename: string
  extension: string
  size_bytes: number
  status: 'processing' | 'ready' | 'failed'
  stage: string
  error_code: string | null
  error_message: string | null
  page_count: number | null
  block_count: number
  chunk_count: number
  warnings: string[]
  created_at: string
  parser_version: string | null
  chunker_version: string | null
  chunk_config: { unit?: string; target?: number; maximum?: number; overlap?: number }
  embedding?: EmbeddingStatus
}

export interface EmbeddingStatus {
  status: 'disabled' | 'pending' | 'processing' | 'ready' | 'failed'
  model: string | null
  dimensions: number
  completed_chunks: number
  total_chunks: number
  vector_count: number
  error_code: string | null
  error_message: string | null
}

export interface ContentBlock {
  index: number
  kind: string
  text: string
  page: number | null
  bbox: number[] | null
  section: string[]
  method: string
  location?: SourceLocation | null
}

// Text offsets count Unicode code points after UTF-8 BOM removal, keeping CRLF.
// Page regions use top-left normalized coordinates on the displayed crop box.
export type SourceLocation =
  | { type: 'text'; start: number; end: number; start_line: number; end_line: number }
  | { type: 'page'; page: number; bbox?: [number, number, number, number] }

export interface Chunk {
  index: number
  text: string
  kind: string
  section: string[]
  sources: { block_index: number; page: number | null; start: number; end: number }[]
}

export interface DocumentDetail extends DocumentRecord {
  blocks: ContentBlock[]
  chunks: Chunk[]
}

export interface SearchHit {
  document_id: string
  filename: string
  chunk_index: number
  chunk: Chunk
}

export type SearchMode = 'keyword' | 'semantic'

export const searchDocuments = (q: string, offset: number, signal: AbortSignal, mode: SearchMode = 'keyword') =>
  http.get<{ items: SearchHit[]; has_more: boolean }>('/api/search', {
    params: { q, offset, limit: 30, mode }, signal,
    timeout: mode === 'semantic' ? 35000 : 15000,
  })

export type AnswerDepth = 'auto' | 'deep'

export interface DocumentAnswer {
  paragraphs: { text: string; source_ids: string[] }[]
  limitations: string
  notes?: string
  citations: Record<string, {
    document_id: string
    filename: string
    locations: { block_index: number; page: number | null }[]
  }>
}

export interface SavedConversation {
  id: string
  title: string
  updated_at: string
}

export interface ConversationTurn {
  id: string
  question: string
  depth: AnswerDepth
  answer: DocumentAnswer
}

export interface Conversation extends SavedConversation {
  turns: ConversationTurn[]
}

export const listConversations = (signal: AbortSignal) =>
  http.get<{ items: SavedConversation[] }>('/api/conversations', { signal })

export const getConversation = (id: string, signal: AbortSignal) =>
  http.get<Conversation>(`/api/conversations/${id}`, { signal })

export const deleteConversation = (id: string, signal: AbortSignal) =>
  http.delete(`/api/conversations/${id}`, { signal })

export const saveConversationTurn = (
  id: string | null, question: string, depth: AnswerDepth, request_id: string,
  after_turn_id: string | undefined, signal: AbortSignal,
) => http.post<{ conversation: SavedConversation; turn: ConversationTurn }>(
  id ? `/api/conversations/${id}/turns` : '/api/conversations',
  { question, depth, request_id, after_turn_id }, { signal, timeout: 125000 },
)

export const listDocuments = (offset = 0) => http.get<{ items: DocumentRecord[]; total: number }>(
  '/api/documents', { params: { limit: 30, offset } },
)
export const getDocument = (id: string, signal?: AbortSignal) => http.get<DocumentDetail>(`/api/documents/${id}`, { signal })
export const retryDocument = (id: string) => http.post<DocumentRecord>(`/api/documents/${id}/retry`, {}, { timeout: 155000 })
export const createEmbeddings = (id: string) => http.post<DocumentRecord>(`/api/documents/${id}/embeddings`, {}, { timeout: 45000 })
export const getOriginal = (id: string, signal?: AbortSignal) => http.get<Blob>(`/api/documents/${id}/original`, { responseType: 'blob', signal })
export const getPagePreview = (id: string, page: number, signal?: AbortSignal) =>
  http.get<Blob>(`/api/documents/${id}/pages/${page}/preview`, { responseType: 'blob', signal, timeout: 35000 })
export function uploadDocument(file: File, onProgress: (percent: number) => void) {
  const data = new FormData()
  data.append('file', file)
  return http.post<{ document: DocumentRecord; duplicate: boolean }>('/api/documents', data, {
    timeout: 155000,
    onUploadProgress: (event) => { if (event.total) onProgress(Math.round(event.loaded / event.total * 100)) },
  })
}
