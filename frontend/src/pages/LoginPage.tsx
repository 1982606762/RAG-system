import { useState, type FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { login } from '../api'
import { useAuth } from '../store'
import { useT } from '../i18n'
import LangSwitch from '../components/LangSwitch'
import Icon from '../components/Icon'

export default function LoginPage() {
  const token = useAuth((state) => state.token)
  const setToken = useAuth((state) => state.setToken)
  const [password, setPassword] = useState('')
  const [pending, setPending] = useState(false)
  const [failed, setFailed] = useState(false)
  const [visible, setVisible] = useState(false)
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
      <section className="login-story">
        <div className="sidebar-brand"><span className="brand-mark"><Icon name="logo" size={25} /></span><div><strong>{t('brand')}</strong><span>KNOWLEDGE SPACE</span></div></div>
        <div className="login-story-content"><p className="eyebrow">A LITTLE SPACE. A WORLD OF IDEAS.</p><h2>{t('loginHeadline')}</h2><p className="login-description">{t('loginDescription')}</p>
          <div className="login-illustration" aria-hidden="true"><div className="illustration-orbit" /><div className="illustration-document"><Icon name="file" size={29} /><span /><span /><span /><span /></div><div className="illustration-connection"><Icon name="link" size={24} /></div><div className="illustration-answer"><Icon name="sparkle" size={22} /><span /><span /></div></div>
          <ul className="login-features">{(['loginFeatureOne', 'loginFeatureTwo', 'loginFeatureThree'] as const).map(key => <li key={key}><Icon name="check" size={16} />{t(key)}</li>)}</ul>
        </div>
        <p className="login-story-footer">PERSONAL KNOWLEDGE, CONNECTED.</p>
      </section>
      <div className="login-form-area"><div className="login-language"><LangSwitch /></div>
      <form className="login-card" onSubmit={submit}>
        <span className="login-lock"><Icon name="lock" size={22} /></span>
        <p className="eyebrow">{t('private')}</p>
        <h1>{t('loginTitle')}</h1>
        <p className="login-subtitle">{t('loginSubtitle')}</p>
        <label htmlFor="password">{t('password')}</label>
        <div className="password-field">
        <input
          id="password"
          type={visible ? 'text' : 'password'}
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          readOnly={pending}
          aria-invalid={failed || undefined}
          aria-describedby={failed ? 'login-error' : undefined}
          required
        />
        <button className="icon-button" type="button" aria-label={t(visible ? 'hidePassword' : 'showPassword')} aria-pressed={visible} onClick={() => setVisible(value => !value)}><Icon name={visible ? 'eyeOff' : 'eye'} size={18} /></button>
        </div>
        {failed && <p id="login-error" className="error" role="alert">{t('loginError')}</p>}
        <button className="primary" type="submit" disabled={pending || !password}>
          {pending && <span className="spinner" />}{t(pending ? 'loggingIn' : 'login')}
        </button>
        <p className="login-card-footer"><Icon name="lock" size={13} />{t('loginFooter')}</p>
      </form>
      </div>
    </main>
  )
}
