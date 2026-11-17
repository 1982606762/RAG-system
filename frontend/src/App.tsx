import { useEffect, useState } from 'react'
import { Navigate, Outlet } from 'react-router-dom'
import { getSession } from './api'
import { useAuth } from './store'
import { useT } from './i18n'
import LangSwitch from './components/LangSwitch'

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
      <header className="topbar">
        <span className="brand">{t('brand')}</span>
        <div className="header-actions"><LangSwitch /><button onClick={logout}>{t('logout')}</button></div>
      </header>
      <main className="content">
        {verifiedToken === token ? <Outlet /> : failed ? (
          <div role="alert">
            <p>{t('sessionError')}</p>
            <button onClick={() => setAttempt((value) => value + 1)}>{t('retry')}</button>
          </div>
        ) : <p role="status">{t('loading')}</p>}
      </main>
    </div>
  )
}
