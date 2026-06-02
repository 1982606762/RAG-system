import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'

import App from './App'
import LoginPage from './pages/LoginPage'
import ChatPage from './pages/ChatPage'
import UploadPage from './pages/UploadPage'
import DocumentsPage from './pages/DocumentsPage'
import TracesPage from './pages/TracesPage'
import './index.css'

// Route table:
//   /login            -> the only public page
//   /  (App shell)    -> everything else, guarded by App (redirects if no token)
//        /chat, /upload, /documents, /traces
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<App />}>
          <Route index element={<Navigate to="/chat" replace />} />
          <Route path="chat" element={<ChatPage />} />
          <Route path="upload" element={<UploadPage />} />
          <Route path="documents" element={<DocumentsPage />} />
          <Route path="traces" element={<TracesPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
)
