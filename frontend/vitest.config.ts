import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vitest/config'

// Unit-test config kept separate from vite.config.ts so the dev/build config
// stays free of test-only fields. jsdom gives the store tests a real
// sessionStorage; tests live next to the code they cover as *.test.ts.
export default defineConfig({
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.ts'],
  },
})
