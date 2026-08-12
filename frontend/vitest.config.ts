import { fileURLToPath, URL } from 'node:url'

import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// Deliberately NOT built on vite.config.ts: that config exists to serve and
// bundle the app (proxy, BASE_PATH validation, tailwind), none of which a
// test run should load or be coupled to. Only the `@` alias is shared truth.
//
// The default environment is node — most tests exercise the pure modules
// (lib/build-doc.ts and friends). Component tests opt into the DOM with a
// `// @vitest-environment jsdom` docblock per file.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    include: ['src/**/*.test.{ts,tsx,mjs}'],
  },
})
