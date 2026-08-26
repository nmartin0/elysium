import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// During `npm run dev`, requests to any of the real API paths are
// proxied straight through to the backend -- from the BROWSER's
// perspective, everything appears to come from one origin, so this
// never needs CORS configured on the FastAPI side at all. In
// production, the built app is served BY FastAPI itself (see
// api/app.py), which is already the same origin for the same reason --
// CORS genuinely never enters the picture in either mode.
const API_PROXY_TARGET = process.env.VITE_API_PROXY_TARGET || 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/login': API_PROXY_TARGET,
      '/logout': API_PROXY_TARGET,
      '/logout-all': API_PROXY_TARGET,
      '/query': API_PROXY_TARGET,
      '/users': API_PROXY_TARGET,
      '/writes': API_PROXY_TARGET,
    },
  },
})
