import { NavLink, Outlet, Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from './store'
import { useT } from './i18n'
import LangSwitch from './components/LangSwitch'

// The app shell: top navigation bar + the active page (rendered into <Outlet/>).
// It also acts as the AUTH GUARD — with no token we redirect to /login, so
// none of the child routes can render for a logged-out user.
export default function App() {
  const { token, user, logout } = useAuth()
  const navigate = useNavigate()
  const t = useT()

  if (!token) return <Navigate to="/login" replace />

  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">{t('app.brand')}</span>
        <nav className="nav">
          <NavLink to="/chat">{t('nav.chat')}</NavLink>
          <NavLink to="/upload">{t('nav.upload')}</NavLink>
          <NavLink to="/documents">{t('nav.documents')}</NavLink>
          <NavLink to="/traces">{t('nav.traces')}</NavLink>
        </nav>
        <span className="spacer" />
        <LangSwitch />
        <span className="email">{user?.email}</span>
        <button
          className="logout"
          onClick={() => {
            logout()
            navigate('/login')
          }}
        >
          {t('app.logout')}
        </button>
      </header>
      <main className="content">
        <Outlet />
      </main>
    </div>
  )
}
