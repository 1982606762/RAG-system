import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { login, register } from '../api'
import { useAuth } from '../store'

// One form that does both login and register, toggled by the link at the
// bottom. On success we store the token and jump to the chat page.
export default function LoginPage() {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const setAuth = useAuth((s) => s.setAuth)
  const navigate = useNavigate()

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    try {
      const fn = mode === 'login' ? login : register
      const data = await fn(email, password)
      setAuth(data.access_token, data.user)
      navigate('/chat')
    } catch (err: any) {
      setError(err.response?.data?.detail || '操作失败，请重试')
    }
  }

  return (
    <div className="auth-wrap">
      <form className="auth-card" onSubmit={submit}>
        <h1>{mode === 'login' ? '登录' : '注册'}</h1>
        <input
          placeholder="邮箱"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <input
          type="password"
          placeholder="密码（至少 6 位）"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {error && <div className="error">{error}</div>}
        <button type="submit">{mode === 'login' ? '登录' : '注册'}</button>
        <p
          className="toggle"
          onClick={() => setMode(mode === 'login' ? 'register' : 'login')}
        >
          {mode === 'login' ? '没有账号？去注册' : '已有账号？去登录'}
        </p>
      </form>
    </div>
  )
}
