import { NavLink, Outlet, Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from './store'

// The app shell: top navigation bar + the active page (rendered into <Outlet/>).
// It also acts as the AUTH GUARD — with no token we redirect to /login, so
// none of the child routes can render for a logged-out user.
export default function App() {
  const { token, user, logout } = useAuth()
  const navigate = useNavigate()

  if (!token) return <Navigate to="/login" replace />

  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">📁 家用文件知识库</span>
        <nav className="nav">
          <NavLink to="/chat">问答</NavLink>
          <NavLink to="/upload">上传</NavLink>
          <NavLink to="/documents">文件</NavLink>
          <NavLink to="/traces">轨迹</NavLink>
        </nav>
        <span className="spacer" />
        <span className="email">{user?.email}</span>
        <button
          className="logout"
          onClick={() => {
            logout()
            navigate('/login')
          }}
        >
          退出
        </button>
      </header>
      <main className="content">
        <Outlet />
      </main>
    </div>
  )
}
