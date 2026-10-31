/// <reference types="vitest/config" />
import { execFile } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import react from '@vitejs/plugin-react';
import { defineConfig, type Plugin } from 'vite';

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, '..');
const ROLES = new Set(['decideur', 'analyste', 'admin']);

/**
 * Jetons de développement (mode VITE_AUTH_MODE=dev) : le serveur Vite appelle la CLI de l'API, qui signe
 * un JWT avec la clé locale var/dev-auth/ (acceptée par `make api-dev` ou `make dev-up`).
 * Commande surchargeable par DEV_TOKEN_CMD, {role} remplacé : en conteneurs, `make -s dc-token ROLE={role}`.
 * N'existe qu'en `vite dev` : rien de tout cela n'est inclus dans le build de production.
 */
function devTokens(): Plugin {
  const template = process.env.DEV_TOKEN_CMD ?? 'uv run python -m decision_api.cli dev-token --quiet --role {role}';
  return {
    name: 'decision-dev-tokens',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use('/__dev/token', (req, res) => {
        const role = new URL(req.url ?? '', 'http://x').searchParams.get('role') ?? '';
        if (!ROLES.has(role)) {
          res.statusCode = 400;
          res.end('rôle inconnu');
          return;
        }
        const [cmd, ...args] = template.replace('{role}', role).split(/\s+/);
        execFile(cmd!, args, { cwd: repoRoot, timeout: 30_000 }, (err, stdout, stderr) => {
          const token = stdout.trim().split('\n').pop() ?? '';
          if (err || !token.startsWith('ey')) {
            res.statusCode = 500;
            res.end(`jeton indisponible : ${(stderr || String(err)).slice(0, 300)}`);
            return;
          }
          res.setHeader('Content-Type', 'text/plain; charset=utf-8');
          res.setHeader('Cache-Control', 'no-store');
          res.end(token);
        });
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), devTokens()],
  resolve: { alias: { '@': path.resolve(here, 'src') } },
  server: {
    port: 5173,
    // Même origine qu'en production derrière Caddy : /api vers l'API locale (make api-dev ou make dev-up).
    proxy: { '/api': { target: process.env.API_TARGET ?? 'http://127.0.0.1:8000', changeOrigin: false } },
  },
  build: {
    sourcemap: true,
    target: 'es2022',
    rollupOptions: {
      input: { main: path.resolve(here, 'index.html'), silent: path.resolve(here, 'silent-renew.html') },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
