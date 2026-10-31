import { defineConfig } from '@playwright/test';

/**
 * Tests de bout en bout hermétiques : Vite en développement (jetons factices) + mini serveur SSE ;
 * toutes les requêtes /api sont simulées par `page.route` (e2e/mock-api.ts). Ni API, ni Postgres, ni Keycloak.
 */
const PORT = 5199;
const SSE_PORT = 5198;

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.spec.ts',
  timeout: 30_000,
  expect: { timeout: 7_000 },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: process.env.CI ? 2 : 4,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    locale: 'fr-FR',
    trace: 'off',
    screenshot: 'only-on-failure',
    video: 'off',
    viewport: { width: 1280, height: 800 },
  },
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],
  webServer: [
    {
      command: `node e2e/sse-server.mjs`,
      url: `http://127.0.0.1:${SSE_PORT}`,
      env: { SSE_PORT: String(SSE_PORT) },
      reuseExistingServer: !process.env.CI,
    },
    {
      command: `npx vite --port ${PORT} --strictPort --host 127.0.0.1`,
      url: `http://127.0.0.1:${PORT}`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      env: {
        VITE_AUTH_MODE: 'dev',
        // cwd du plugin Vite = racine du dépôt : chemin absolu vers le script.
        DEV_TOKEN_CMD: `node ${new URL('./e2e/fake-token.mjs', import.meta.url).pathname} {role}`,
        API_TARGET: `http://127.0.0.1:${SSE_PORT}`,
      },
    },
  ],
});
