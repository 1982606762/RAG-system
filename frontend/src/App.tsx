import { useEffect, useState } from 'react'
import { Navigate, Outlet } from 'react-router-dom'
import { getSession } from './api'
import { useAuth } from './store'
import { useT } from './i18n'
import Icon from './components/Icon'

export default function App() {
  const { token, logout } = useAuth()
  const [verifiedToken, setVerifiedToken] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const t = useT()

  useEffect(() => {
    if (!token) return
    let active = true
    setFailed(false)
    getSession()
      .then(() => { if (active) setVerifiedToken(token) })
      .catch(() => { if (active) setFailed(true) })
    return () => { active = false }
  }, [token, attempt])

  if (!token) return <Navigate to="/login" replace />

  return (
    <div className="app">
      <main className="content">
        {verifiedToken === token ? <Outlet /> : failed ? (
          <div className="session-state" role="alert">
            <span className="brand-mark"><Icon name="logo" size={26} /></span>
            <p>{t('sessionError')}</p>
            <button onClick={() => setAttempt((value) => value + 1)}>{t('retry')}</button>
            <button className="subtle-button" onClick={logout}>{t('logout')}</button>
          </div>
        ) : <div className="session-state" role="status"><span className="brand-mark"><Icon name="logo" size={26} /></span><p>{t('loading')}</p></div>}
      </main>
    </div>
  )
}
