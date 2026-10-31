import AxeBuilder from '@axe-core/playwright';
import { expect, test as base, type Page } from '@playwright/test';

import type { Role } from '../src/api/types';

import { installMockApi, type MockApi } from './mock-api';

export type Theme = 'light' | 'dark';

export interface StartOptions {
  /** Thème préenregistré (localStorage) ; absent : l'appli choisit seule. */
  theme?: Theme;
  /** Schéma de couleurs du navigateur (pages hors session comprises). */
  scheme?: Theme;
  /** Reprise d'une session de développement (par défaut) ; `false` : page de connexion. */
  signedIn?: boolean;
}

interface Fixtures {
  /** Installe l'API simulée, prépare la session et le thème ; vérifie en fin de test qu'aucun appel n'est resté sans réponse. */
  start: (role?: Role, opts?: StartOptions) => Promise<MockApi>;
}

const b64 = (o: unknown) => Buffer.from(JSON.stringify(o)).toString('base64url');
const fakeToken = (role: Role) =>
  `${b64({ alg: 'none', typ: 'JWT' })}.${b64({ sub: `e2e-${role}`, role, exp: Math.floor(Date.now() / 1000) + 8 * 3600 })}.e2e`;

export const test = base.extend<Fixtures>({
  start: async ({ page }, provide) => {
    const mocks: MockApi[] = [];
    await provide(async (role = 'decideur', opts = {}) => {
      const mock = await installMockApi(page, role);
      mocks.push(mock);
      await page.emulateMedia({ colorScheme: opts.scheme ?? opts.theme ?? 'light', reducedMotion: 'reduce' });
      const seed = { token: fakeToken(role), role, signedIn: opts.signedIn !== false, theme: opts.theme ?? null };
      // Une seule fois par onglet : une déconnexion ou un rechargement ne doit pas rejouer la préparation.
      await page.addInitScript((s) => {
        if (sessionStorage.getItem('e2e-seeded')) return;
        sessionStorage.setItem('e2e-seeded', '1');
        if (s.signedIn) sessionStorage.setItem('decision.devToken', JSON.stringify({ token: s.token, role: s.role }));
        if (s.theme) localStorage.setItem('decision.theme', s.theme);
      }, seed);
      return mock;
    });
    for (const m of mocks) expect(m.unhandled, 'appels /api non simulés').toEqual([]);
  },
});
export { expect };

const WCAG = ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'];

/** Contrôle axe-core WCAG 2.2 AA sur la page entière : zéro violation, avec le détail lisible en cas d'échec. */
export async function expectAccessible(page: Page, context: string): Promise<void> {
  const { violations } = await new AxeBuilder({ page } as unknown as ConstructorParameters<typeof AxeBuilder>[0]).withTags(WCAG).analyze();
  const report = violations.map(
    (v) =>
      `${v.id} (${v.impact}) : ${v.help}\n` +
      v.nodes.map((n) => `   ${n.target.join(' ')}\n   ${n.failureSummary?.split('\n').slice(1, 3).join(' | ')}`).join('\n'),
  );
  expect(report, `Violations d'accessibilité : ${context}`).toEqual([]);
}
