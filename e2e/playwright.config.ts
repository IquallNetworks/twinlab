import { defineConfig, devices } from '@playwright/test'

import { stackEnv } from './lib/env'

const env = stackEnv()

// One dedicated stack, stateful ordered specs: a single worker, no parallelism.
// The SSE stream keeps a connection open for the whole authenticated session,
// so nothing here may ever wait for network idle.
export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  globalSetup: './global-setup',
  timeout: 60_000,
  // The UI settles ~300 ms after an SSE event (invalidation debounce) plus a
  // query refetch — auto-retrying assertions absorb that comfortably at 10 s.
  expect: { timeout: 10_000 },
  reporter: [['list'], ['html', { outputFolder: 'report', open: 'never' }]],
  outputDir: 'test-results',
  use: {
    ...devices['Desktop Chrome'],
    baseURL: env.baseUrl,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    // The login spec itself: asserts the login surface, then saves the admin
    // session for everything else.
    { name: 'setup', testMatch: /auth\.setup\.ts/ },
    {
      name: 'fast',
      testDir: './tests/fast',
      dependencies: ['setup'],
      use: { storageState: '.auth/admin.json' },
    },
    {
      // Depends on fast so a full run keeps the pristine-stack assertions
      // first; iterate on the journey alone with --no-deps.
      name: 'journey',
      testDir: './tests/journey',
      dependencies: ['fast'],
      use: { storageState: '.auth/admin.json' },
    },
  ],
})
