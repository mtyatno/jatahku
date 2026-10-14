import { execSync } from 'node:child_process'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

// Commit yang sedang di-build (server deploy membangun dari checkout git).
// Ditulis ke dist/version.json supaya deploy bisa memastikan web yang tayang
// adalah build terbaru, dan ditampilkan di Settings.
function buildCommit() {
  const fromEnv = (process.env.JATAHKU_COMMIT || '').trim()
  if (/^[0-9a-f]{40}$/.test(fromEnv)) return fromEnv
  try {
    const sha = execSync('git rev-parse HEAD', { cwd: __dirname, stdio: ['ignore', 'pipe', 'ignore'] })
      .toString().trim()
    return /^[0-9a-f]{40}$/.test(sha) ? sha : 'unknown'
  } catch {
    return 'unknown'
  }
}

const COMMIT = buildCommit()
const BUILT_AT = new Date().toISOString()

function versionFile() {
  return {
    name: 'jatahku-version',
    apply: 'build',
    generateBundle() {
      this.emitFile({
        type: 'asset',
        fileName: 'version.json',
        source: `${JSON.stringify({ commit: COMMIT, built_at: BUILT_AT })}\n`,
      })
    },
  }
}

export default defineConfig({
  define: {
    __APP_COMMIT__: JSON.stringify(COMMIT),
  },
  plugins: [
    react(),
    versionFile(),
    VitePWA({
      strategies: 'injectManifest',
      srcDir: 'src',
      filename: 'sw.js',
      registerType: 'autoUpdate',
      injectRegister: null,
      manifest: false, // use our own manifest.json
      injectManifest: {
        globPatterns: ['**/*.{js,css,html,svg,png,woff2}'],
      },
      devOptions: { enabled: false },
    }),
  ],
  server: {
    proxy: {
      '/api': {
        target: 'https://api.jatahku.com',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
