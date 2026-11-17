import { create } from 'zustand'

const tokenKey = 'rag.owner.token'

// Retire the old multi-user session instead of interpreting it as owner access.
localStorage.removeItem('token')
localStorage.removeItem('user')

interface AuthState {
  token: string | null
  setToken: (token: string) => void
  logout: () => void
}

export const useAuth = create<AuthState>((set) => ({
  token: localStorage.getItem(tokenKey),
  setToken: (token) => {
    localStorage.setItem(tokenKey, token)
    set({ token })
  },
  logout: () => {
    localStorage.removeItem(tokenKey)
    set({ token: null })
  },
}))
