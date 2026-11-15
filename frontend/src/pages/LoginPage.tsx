import { useState, type FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { login } from '../api'
import { useAuth } from '../store'
import { useT } from '../i18n'
import LangSwitch from '../components/LangSwitch'

export default function LoginPage() {
  const token = useAuth((state) => state.token)
  const setToken = useAuth((state) => state.setToken)
  const [password, setPassword] = useState('')
  const [pending, setPending] = useState(false)
  const [failed, setFailed] = useState(false)
  const navigate = useNavigate()
  const t = useT()

  if (token) return <Navigate to="/" replace />

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (pending) return
    setPending(true)
    setFailed(false)
    try {
      setToken(await login(password))
      navigate('/', { replace: true })
    } catch {
      setFailed(true)
    } finally {
      setPending(false)
    }
  }

  return (
    <main className="login-page">
      <form className="login-card" onSubmit={submit}>
        <div className="card-heading"><span>{t('private')}</span><LangSwitch /></div>
        <h1>{t('loginTitle')}</h1>
        <label htmlFor="password">{t('password')}</label>
        <input
          id="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          required
        />
        {failed && <p className="error" role="alert">{t('loginError')}</p>}
        <button className="primary" type="submit" disabled={pending}>
          {t(pending ? 'loggingIn' : 'login')}
        </button>
      </form>
    </main>
  )
}
