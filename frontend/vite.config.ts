import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const backendUrl = env.VITE_BACKEND_URL || 'http://localhost:8000'

  return {
    plugins: [vue()],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    server: {
      port: 5173,
      strictPort: true,
      proxy: {
        '/api': {
          target: backendUrl,
          changeOrigin: true,
          secure: false,
          // The Ask AI SSE endpoint streams `text/event-stream` chunks
          // and must NOT be buffered by the proxy. http-proxy default
          // pipes responses through, but Node keeps small chunks in the
          // socket buffer until the next write piles on. Disabling Nagle
          // on the proxy response socket lets each SSE frame flush
          // immediately, so Ask AI renders token-by-token instead of
          // appearing all at once.
          configure: (proxy) => {
            proxy.on('proxyRes', (proxyRes, _req, res) => {
              const isSse = (proxyRes.headers['content-type'] || '').includes(
                'text/event-stream',
              )
              if (isSse) {
                // Flush response headers immediately so the browser
                // exposes `resp.body` as a readable stream right away
                // instead of buffering until the first chunk lands.
                if (typeof res.flushHeaders === 'function') {
                  res.flushHeaders()
                }
                const sock = res.socket
                if (sock && typeof (sock as { setNoDelay?: (b: boolean) => void }).setNoDelay === 'function') {
                  ;(sock as { setNoDelay: (b: boolean) => void }).setNoDelay(true)
                }
              }
            })
          },
        },
      },
    },
    build: {
      outDir: 'dist',
      sourcemap: false,
      target: 'es2022',
    },
  }
})
