import { create } from 'zustand'

// Minimal auth store. The JWT lives in localStorage so a page refresh keeps
// you logged in; the store mirrors it in memory so components re-render on
// login/logout. Anything that needs the token reads it from here.

interface User {
  id: string
  email: string
}

interface AuthState {
  token: string | null
  user: User | null
  setAuth: (token: string, user: User) => void
  logout: () => void
}

function storedUser(): User | null {
  try {
    return JSON.parse(localStorage.getItem('user') || 'null')
  } catch {
    localStorage.removeItem('user')
    localStorage.removeItem('token')
    return null
  }
}

const initialUser = storedUser()

export const useAuth = create<AuthState>((set) => ({
  token: initialUser ? localStorage.getItem('token') : null,
  user: initialUser,

  setAuth: (token, user) => {
    localStorage.setItem('token', token)
    localStorage.setItem('user', JSON.stringify(user))
    set({ token, user })
  },

  logout: () => {
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    set({ token: null, user: null })
  },
}))
