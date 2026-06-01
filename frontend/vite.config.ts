import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// During `npm run dev` the frontend runs on :3000 and proxies every /api
// request to the FastAPI backend on :8001. The browser therefore sees a
// single origin, so there are no CORS headers to configure.
//
// In production we don't use this proxy at all — Nginx (step 6) serves the
// built files and forwards /api to the backend instead.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api': 'http://localhost:8001',
    },
  },
})
