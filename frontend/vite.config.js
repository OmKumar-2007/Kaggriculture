import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { env } from 'node:process'

const backendTarget = env.VITE_BACKEND_URL || env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'
const apiProxy = Object.fromEntries(
  ['/api', '/botlab', '/jobs', '/teams', '/sandbox', '/replays', '/starter', '/event', '/tournament', '/players', '/leaderboard', '/register', '/validate', '/guide', '/health', '/ready']
    .map((path) => [path, { target: backendTarget, changeOrigin: true }]),
)

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: { proxy: apiProxy },
  preview: { proxy: apiProxy },
})
