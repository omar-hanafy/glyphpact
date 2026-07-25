import { defineConfig } from '@playwright/test';

const baseURL = 'http://127.0.0.1:4321';

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL,
    browserName: 'chromium',
    colorScheme: 'dark',
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'npm run preview -- --host 127.0.0.1 --port 4321',
    url: `${baseURL}/glyphpact/`,
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
});
