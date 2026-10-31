/**
 * Accessibilité (axe-core, WCAG 2.2 AA : wcag2a, wcag2aa, wcag21aa, wcag22aa) : zéro violation sur chaque page et
 * chaque état important, en thème clair et sombre, à 1280 et 390 px.
 */
import type { Page } from '@playwright/test';

import { expect, expectAccessible, test, type Theme } from './fixtures';
import { SEEDED, type SeededKind } from './mock-api';

const THEMES: Theme[] = ['light', 'dark'];
const VIEWPORTS = [
  { name: '1280 px', width: 1280, height: 800 },
  { name: '390 px', width: 390, height: 844 },
];

/** Page stable : thème appliqué, polices chargées. */
async function settled(page: Page, theme: Theme, shell = true) {
  if (shell) await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
  await page.evaluate(() => document.fonts.ready);
}

for (const theme of THEMES) {
  for (const vp of VIEWPORTS) {
    test.describe(`${theme}, ${vp.name}`, () => {
      test.use({ viewport: { width: vp.width, height: vp.height } });
      const mobile = vp.width < 600;

      test('connexion', async ({ page, start }) => {
        await start('decideur', { signedIn: false, scheme: theme });
        await page.goto('/');
        await expect(page.getByRole('button', { name: 'Entrer comme décideur' })).toBeVisible();
        await settled(page, theme, false);
        await expectAccessible(page, 'connexion');
      });

      test('déconnecté', async ({ page, start }) => {
        await start('decideur', { signedIn: false, scheme: theme });
        await page.goto('/deconnecte');
        await expect(page.getByRole('heading', { level: 1, name: 'Vous êtes déconnecté' })).toBeVisible();
        await expectAccessible(page, 'déconnecté');
      });

      test('session expirée', async ({ page, start }) => {
        const mock = await start('decideur', { theme });
        await page.goto('/indicateurs');
        await expect(page.getByRole('table')).toBeVisible();
        mock.expire();
        await page.getByLabel('Région').selectOption('Kolda');
        await expect(page.getByRole('heading', { level: 1, name: 'Votre session a expiré' })).toBeVisible();
        await expectAccessible(page, 'session expirée');
      });

      test('questions : état vide', async ({ page, start }) => {
        await start('decideur', { theme });
        await page.goto('/questions');
        await expect(page.getByRole('heading', { name: /Posez votre question/ })).toBeVisible();
        await expect(page.getByRole('navigation', { name: 'Historique des conversations' }).getByRole('link').first()).toBeVisible().catch(() => undefined);
        await settled(page, theme);
        await expectAccessible(page, 'questions vide');
      });

      for (const kind of Object.keys(SEEDED) as SeededKind[]) {
        test(`questions : réponse « ${kind} »`, async ({ page, start }) => {
          await start('analyste', { theme });
          await page.goto(`/questions/${SEEDED[kind][0]}`);
          await expect(page.getByRole('heading', { level: 2, name: SEEDED[kind][1] })).toBeVisible();
          await expect(page.locator('.cv-turn').getByText(/\S/).nth(3)).toBeVisible();
          await settled(page, theme);
          await expectAccessible(page, `réponse ${kind}`);
        });
      }

      test('questions : volet « Voir le calcul » ouvert', async ({ page, start }) => {
        await start('analyste', { theme });
        await page.goto(`/questions/${SEEDED.kpi[0]}`);
        await page.getByRole('button', { name: 'Voir le calcul' }).click();
        await expect(page.locator('pre.ui-code')).toBeVisible();
        await settled(page, theme);
        await expectAccessible(page, 'volet SQL');
      });

      test('questions : réponse du décideur (sans SQL)', async ({ page, start }) => {
        await start('decideur', { theme });
        await page.goto(`/questions/${SEEDED.kpi[0]}`);
        await expect(page.getByRole('article', { name: 'Réponse' })).toBeVisible();
        await settled(page, theme);
        await expectAccessible(page, 'réponse décideur');
      });

      test('questions : calcul en cours (étapes)', async ({ page, start }) => {
        await start('decideur', { theme });
        await page.goto('/questions');
        await page.getByRole('textbox', { name: 'Votre question' }).fill('Quelle est la valeur transférée en septembre ?');
        await page.getByRole('button', { name: 'Envoyer' }).click();
        await expect(page.getByRole('list', { name: 'Étapes du calcul' }).getByText('Lecture des indicateurs')).toBeVisible();
        await settled(page, theme);
        await expectAccessible(page, 'étapes du calcul');
      });

      test('questions : dialogue de signalement', async ({ page, start }) => {
        await start('decideur', { theme });
        await page.goto(`/questions/${SEEDED.kpi[0]}`);
        await page.getByRole('button', { name: 'Signaler la réponse' }).click();
        const dialog = page.getByRole('dialog', { name: 'Signaler cette réponse' });
        await expect(dialog).toBeVisible();
        await settled(page, theme);
        await expectAccessible(page, 'dialogue de signalement (vide)');
        // avec une option cochée et l'erreur affichée
        await dialog.getByRole('button', { name: 'Envoyer le signalement' }).click();
        await expect(dialog.getByRole('alert')).toBeVisible();
        await expectAccessible(page, 'dialogue de signalement (erreur)');
        await dialog.getByRole('radio', { name: 'Le chiffre est faux' }).check();
        await dialog.getByRole('checkbox', { name: /Joindre ma question/ }).check();
        await expectAccessible(page, 'dialogue de signalement (rempli)');
      });

      test('questions : dialogue de suppression', async ({ page, start }) => {
        await start('decideur', { theme });
        await page.goto('/questions');
        const hist = page.getByRole('navigation', { name: 'Historique des conversations' }).filter({ visible: true });
        if (mobile) {
          await page.getByRole('button', { name: 'Historique' }).click();
          await expect(page.getByRole('dialog', { name: 'Historique des conversations' })).toBeVisible();
        }
        await hist.last().getByRole('button', { name: /Supprimer la conversation « Taux d’échec par région »/ }).click();
        await expect(page.getByRole('dialog', { name: 'Supprimer cette conversation ?' })).toBeVisible();
        await settled(page, theme);
        await expectAccessible(page, 'dialogue de suppression');
      });

      if (mobile) {
        test('questions : tiroir d’historique', async ({ page, start }) => {
          await start('decideur', { theme });
          await page.goto('/questions');
          await page.getByRole('button', { name: 'Historique' }).click();
          const drawer = page.getByRole('dialog', { name: 'Historique des conversations' });
          await expect(drawer.getByRole('link', { name: /Valeur transférée en septembre/ })).toBeVisible();
          await settled(page, theme);
          await expectAccessible(page, 'tiroir d’historique');
        });

        test('menu de navigation ouvert', async ({ page, start }) => {
          await start('admin', { theme });
          await page.goto('/questions');
          await page.getByRole('button', { name: 'Ouvrir le menu' }).click();
          await expect(page.getByRole('link', { name: 'Paramètres' })).toBeVisible();
          await settled(page, theme);
          await expectAccessible(page, 'menu mobile');
        });
      }

      test('indicateurs : relevé', async ({ page, start }) => {
        await start('decideur', { theme });
        await page.goto('/indicateurs');
        await expect(page.getByRole('row', { name: /Taux d’échec/ })).toBeVisible();
        await settled(page, theme);
        await expectAccessible(page, 'indicateurs');
      });

      test('indicateurs : analyse générée, source mise en évidence', async ({ page, start }) => {
        await start('analyste', { theme });
        await page.goto('/indicateurs');
        await page.getByRole('button', { name: 'Générer l’analyse' }).click();
        await expect(page.getByText('Confiance élevée')).toBeVisible();
        await expectAccessible(page, 'analyse');
        await page.getByRole('button', { name: 'Voir la ligne Volume de transactions dans le relevé' }).click();
        await expect(page.getByRole('row', { name: /Volume de transactions/ })).toHaveAttribute('data-highlight', 'true');
        await expectAccessible(page, 'analyse, ligne mise en évidence');
      });

      test('accès réservé', async ({ page, start }) => {
        await start('decideur', { theme });
        await page.goto('/admin');
        await expect(page.getByRole('heading', { level: 1, name: 'Accès réservé' })).toBeVisible();
        await settled(page, theme);
        await expectAccessible(page, 'accès réservé');
      });

      const ADMIN: [string, string, string][] = [
        ['Exploitation', '/admin', 'Sous la cible de 15,0 s'],
        ['Journal d’audit', '/admin/audit', 'f00dfeedca'],
        ['Évaluation', '/admin/evaluation', '30 sur 40'],
        ['Évaluation (détail)', '/admin/evaluation/7', 'Cible non démontrée'],
        ['Signalements', '/admin/signalements', 'Le total est bizarre'],
        ['Catalogue de KPI', '/admin/kpi', 'Part des transactions échouées.'],
        ['Couche sémantique', '/admin/semantique', 'fact_transaction'],
        ['Sécurité', '/admin/securite', 'forbidden_table'],
        ['Paramètres', '/admin/parametres', 'claude-sonnet-5-5'],
      ];
      for (const [name, url, marker] of ADMIN) {
        test(`admin : ${name}`, async ({ page, start }) => {
          await start('admin', { theme });
          await page.goto(url);
          await expect(page.getByText(marker).first()).toBeVisible();
          await settled(page, theme);
          await expectAccessible(page, `admin ${name}`);
        });
      }

      test('admin : onglets de la couche sémantique', async ({ page, start }) => {
        await start('admin', { theme });
        await page.goto('/admin/semantique');
        for (const [tab, marker] of [['Glossaire', 'Au moins une transaction dans le mois.'], ['Exemples', 'Combien de clients à Dakar ?']] as const) {
          await page.getByRole('button', { name: tab }).click();
          await expect(page.getByText(marker).first()).toBeVisible();
          await expectAccessible(page, `sémantique ${tab}`);
        }
      });

      test('admin : tiroirs et dialogues', async ({ page, start }) => {
        await start('admin', { theme });
        await page.goto('/admin/audit');
        await page.getByRole('button', { name: /Ouvrir le détail de la trace/ }).click();
        const trace = page.getByRole('dialog', { name: 'Détail d’un appel' });
        await expect(trace.getByText(/SELECT count/)).toBeVisible();
        await settled(page, theme);
        await expectAccessible(page, 'tiroir d’audit');
        await page.keyboard.press('Escape');

        await page.goto('/admin/signalements');
        await page.getByRole('button', { name: /Ouvrir le signalement/ }).click();
        const fb = page.getByRole('dialog', { name: 'Signalement' });
        await expect(fb).toBeVisible();
        await expectAccessible(page, 'tiroir de signalement');
        await fb.getByRole('button', { name: 'Rejeter' }).click();
        await expect(page.getByRole('dialog', { name: 'Rejeter ce signalement' })).toBeVisible();
        await expectAccessible(page, 'dialogue de rejet');
      });
    });
  }
}
