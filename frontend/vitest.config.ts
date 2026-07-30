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
      // any coverage before this audit pass. Raise these (never lower without a
      // note) as more components get tests.
      //
      // Re-baselined for vitest 4. The note this replaces recorded
      // statements/lines 6.88%, branches 57.8%, functions 20.2% under vitest 2.
      // Under 4 the same test suite measures statements 6.86% and lines 6.89% —
      // unchanged — while branches reads 6.74% and functions 5.33%.
      //
      // Coverage did not regress; the denominator did. vitest 2 reported
      // branches as 271/469 (= 57.8%); vitest 4 reports the same 271 covered
      // branches out of 4015. Identical numerator, so v2 was counting branches
      // only inside files that had some coverage, and v4 counts every file in
      // `include` above. The v4 figure is the honest one — and the reason the old
      // 55% floor looked reassuring while 64 of 65 components had no tests at
      // all.
      //
      // Consequence worth stating: at 4% and 3% these two thresholds no longer
      // block much. That is what the numbers actually support today. The
      // statements/lines floors are unchanged and still anchored to a real
      // measurement.
      thresholds: {
        statements: 4,
        branches: 4,
        functions: 3,
        lines: 4,
      },
    },
  },
})
