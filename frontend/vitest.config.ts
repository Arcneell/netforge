import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

// Unit-test config kept separate from vite.config.ts so the dev/build config
// stays free of test-only fields. jsdom gives the store tests a real
// sessionStorage; tests live next to the code they cover as *.test.ts.
// The vue plugin compiles SFCs for component tests (@vue/test-utils).
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov'],
      include: ['src/**/*.{ts,vue}'],
      exclude: ['src/**/*.test.ts', 'src/api/schema.d.ts', 'src/env.d.ts'],
      // Anti-regression floor, NOT a quality target: only 1/65 components had
      // any coverage before this audit pass. Measured baseline the day this
      // was added — statements/lines 6.88%, branches 57.8%, functions
      // 20.2% — floored and shaved by 2pts each as anti-flaky margin. Raise
      // these (never lower without a note) as more components get tests.
      thresholds: {
        statements: 4,
        branches: 55,
        functions: 18,
        lines: 4,
      },
    },
  },
})
