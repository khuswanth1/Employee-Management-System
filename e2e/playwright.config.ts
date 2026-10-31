import { defineConfig, devices } from '@playwright/test'

export const API = 'http://127.0.0.1:8100'
export const WEB = 'http://localhost:5273'

export default defineConfig({
  testDir: './tests',
  globalSetup: './global-setup.ts',
  fullyParallel: false, // one shared seeded database; specs that mutate use their own records
  workers: 1,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [['list'], ['html', { open: 'never' }]],
  use: { baseURL: WEB, trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    { command: 'node start-backend.mjs', url: `${API}/api/health`, timeout: 120_000, reuseExistingServer: false },
    {
      command: 'npx vite --port 5273 --strictPort',
      cwd: '../frontend',
      url: WEB,
      timeout: 120_000,
      reuseExistingServer: false,
      env: { VITE_API_PROXY: API },
    },
  ],
})
