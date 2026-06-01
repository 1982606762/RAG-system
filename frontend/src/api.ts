import axios from 'axios'
import { useAuth } from './store'

// One axios instance for the whole app. No baseURL is needed: Vite's dev
// proxy (and Nginx in prod) forwards /api to the backend on the same origin.
export const http = axios.create()

// Attach the JWT to every outgoing request automatically.
http.interceptors.request.use((config) => {
  const token = useAuth.getState().token
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// If the backend rejects the token (401), log out so the UI returns to /login.
http.interceptors.response.use(
  (res) => res,
  (error) => {
    if (error.response?.status === 401) useAuth.getState().logout()
    return Promise.reject(error)
  },
)

// --- Auth ------------------------------------------------------------------
export const register = (email: string, password: string) =>
  http.post('/api/auth/register', { email, password }).then((r) => r.data)

export const login = (email: string, password: string) =>
  http.post('/api/auth/login', { email, password }).then((r) => r.data)

// --- Documents -------------------------------------------------------------
export const listDocuments = () =>
  http.get('/api/documents').then((r) => r.data)

// Natural-language (semantic) search -> file cards. The backend embeds the
// query and returns the closest files, so "去年的水电费" matches even without
// exact keywords.
export const searchDocuments = (query: string) =>
  http.post('/api/search', { query }).then((r) => r.data)

export const deleteDocument = (fileId: string) =>
  http.delete(`/api/documents/${fileId}`).then((r) => r.data)

// Download must go through axios (NOT a plain <a href>), because the JWT lives
// in the Authorization header — a normal link wouldn't send it and the server
// would 401. So we fetch the bytes as a blob, read the filename the backend
// put in Content-Disposition, then trigger a save via a temporary object URL.
export const downloadDocument = async (fileId: string) => {
  const res = await http.get(`/api/documents/${fileId}/download`, {
    responseType: 'blob',
  })
  const cd = (res.headers['content-disposition'] as string) || ''
  let filename = 'file'
  // RFC 5987 "filename*=UTF-8''..." (used for non-ASCII names like Chinese)
  // takes priority over the plain "filename=" form.
  const star = /filename\*=(?:UTF-8'')?([^;]+)/i.exec(cd)
  const plain = /filename="?([^";]+)"?/.exec(cd)
  if (star) filename = decodeURIComponent(star[1].replace(/["']/g, ''))
  else if (plain) filename = plain[1]

  const url = URL.createObjectURL(res.data)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

// --- Async upload + task polling ------------------------------------------
export const uploadAsync = (file: File, model?: string) => {
  const form = new FormData()
  form.append('file', file)
  if (model) form.append('model', model)
  return http.post('/api/upload_async', form).then((r) => r.data)
}

export const getTask = (taskId: string) =>
  http.get(`/api/tasks/${taskId}`).then((r) => r.data)

// --- Conversations ---------------------------------------------------------
export const listConversations = () =>
  http.get('/api/conversations').then((r) => r.data)

export const createConversation = () =>
  http.post('/api/conversations', {}).then((r) => r.data)

export const getMessages = (convId: string) =>
  http.get(`/api/conversations/${convId}/messages`).then((r) => r.data)

export const askInConversation = (convId: string, question: string, model?: string) =>
  http
    .post(`/api/conversations/${convId}/ask`, { question, model })
    .then((r) => r.data)
