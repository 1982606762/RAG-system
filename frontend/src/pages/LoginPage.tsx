import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { login, register, getAuthConfig } from '../api'
import { useAuth } from '../store'
import { useT, SHOW_DEMO, DEMO_EMAIL, DEMO_PASSWORD } from '../i18n'
import LangSwitch from '../components/LangSwitch'

// One form that does both login and register, toggled by the link at the
// bottom. On success we store the token and jump to the chat page.
//
// The register option only appears when the server allows self-signup
// (ALLOW_REGISTER). On a private VPS it's off, so the page shows login only.
export default function LoginPage() {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [allowRegister, setAllowRegister] = useState(false)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const setAuth = useAuth((s) => s.setAuth)
  const navigate = useNavigate()
  const t = useT()

  // Ask the server once whether registration is open.
  useEffect(() => {
    getAuthConfig()
      .then((c) => setAllowRegister(c.allow_register))
      .catch(() => setAllowRegister(false))
  }, [])

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    try {
      const fn = mode === 'login' ? login : register
      const data = await fn(email, password)
      setAuth(data.access_token, data.user)
      navigate('/chat')
    } catch (err: any) {
      setError(err.response?.data?.detail || t('login.failed'))
    }
  }

  // Prefill the form with the demo credentials so a visitor can try the app
  // with one click + Sign in.
  const fillDemo = () => {
    setEmail(DEMO_EMAIL)
    setPassword(DEMO_PASSWORD)
    setError('')
  }

  return (
    <div className="auth-wrap">
      {/* Decorative blurred blobs — pure CSS, no external image needed. */}
      <span className="blob blob-a" />
      <span className="blob blob-b" />
      <span className="blob blob-c" />

      <div className="auth-lang">
        <LangSwitch />
      </div>

      <div className="auth-panel">
        {/* Left: brand / hero copy */}
        <div className="auth-hero">
          <div className="auth-hero-logo">📁</div>
          <h2 className="auth-hero-title">{t('app.brand').replace('📁 ', '')}</h2>
          <p className="auth-hero-tag">{t('login.tagline')}</p>
        </div>

        {/* Right: the login form card */}
        <form className="auth-card" onSubmit={submit}>
          <h1>{mode === 'login' ? t('login.title') : t('login.register')}</h1>

          <input
            placeholder={t('login.email')}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <input
            type="password"
            placeholder={t('login.password')}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {error && <div className="error">{error}</div>}
          <button type="submit">
            {mode === 'login' ? t('login.title') : t('login.register')}
          </button>

          {/* Demo credentials box: shows the account and offers one-click fill. */}
          {SHOW_DEMO && DEMO_EMAIL && DEMO_PASSWORD && <div className="demo-box">
            <div className="demo-row">
              <span className="demo-label">{t('login.demoTitle')}</span>
              <button type="button" className="demo-fill" onClick={fillDemo}>
                {t('login.demoFill')}
              </button>
            </div>
            <code className="demo-cred">
              {DEMO_EMAIL} / {DEMO_PASSWORD}
            </code>
            <div className="demo-hint">{t('login.demoHint')}</div>
          </div>}

          {/* Only show the login/register toggle when signups are open. */}
          {allowRegister && (
            <p
              className="toggle"
              onClick={() => setMode(mode === 'login' ? 'register' : 'login')}
            >
              {mode === 'login' ? t('login.toRegister') : t('login.toLogin')}
            </p>
          )}
        </form>
      </div>
    </div>
  )
}
