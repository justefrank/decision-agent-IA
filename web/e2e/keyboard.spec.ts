/** Navigation au clavier, focus des dialogues, reflow à 320 px et contraste des cases à cocher natives. */
import type { Page } from '@playwright/test';

import { expect, test, type Theme } from './fixtures';
import { SEEDED } from './mock-api';

/** Nom accessible approché de l'élément qui a le focus (aria-label, sinon texte). */
const focusedName = (page: Page) =>
  page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null;
    if (!el || el === document.body) return '';
    return (el.getAttribute('aria-label') || el.innerText || el.getAttribute('placeholder') || el.tagName).trim().replace(/\s+/g, ' ');
  });

/** Appuie sur Tab jusqu'à ce que `until` soit vrai ; renvoie les noms parcourus. */
async function tabUntil(page: Page, until: (name: string) => boolean, max = 80): Promise<string[]> {
  const seen: string[] = [];
  for (let i = 0; i < max; i += 1) {
    await page.keyboard.press('Tab');
    const name = await focusedName(page);
    seen.push(name);
    if (until(name)) return seen;
  }
  throw new Error(`Focus jamais atteint après ${max} Tab. Parcouru : ${seen.join(' > ')}`);
}

test.describe('clavier', () => {
  test('lien d’évitement : premier arrêt du Tab, visible, mène au contenu', async ({ page, start }) => {
    await start('decideur');
    await page.goto('/questions');
    await expect(page.getByRole('textbox', { name: 'Votre question' })).toBeVisible();
    await page.keyboard.press('Tab');
    const skip = page.getByRole('link', { name: 'Aller au contenu' });
    await expect(skip).toBeFocused();
    await expect(skip).toBeInViewport({ ratio: 1 });
    await page.keyboard.press('Enter');
    await expect(page.locator('main#contenu')).toBeFocused();
  });

  test('Tab atteint la navigation, le contenu et les actions de la réponse', async ({ page, start }) => {
    await start('decideur');
    await page.goto(`/questions/${SEEDED.kpi[0]}`);
    await expect(page.getByRole('article', { name: 'Réponse' })).toBeVisible();
    const seen = await tabUntil(page, (n) => n.startsWith('Posez une question'));
    for (const expected of ['Aller au contenu', 'Questions', 'Indicateurs', 'Passer en thème sombre', 'Se déconnecter', 'Nouvelle conversation', 'Signaler la réponse']) {
      expect(seen.some((n) => n.includes(expected)), `« ${expected} » atteint au clavier. Parcouru : ${seen.join(' > ')}`).toBe(true);
    }
    // l'ordre suit la lecture : navigation avant contenu
    expect(seen.indexOf('Questions')).toBeLessThan(seen.findIndex((n) => n.includes('Nouvelle conversation')));
  });

  test('dialogue de signalement : focus piégé, Échap ferme, le focus revient au bouton', async ({ page, start }) => {
    await start('decideur');
    await page.goto(`/questions/${SEEDED.kpi[0]}`);
    await expect(page.getByRole('article', { name: 'Réponse' })).toBeVisible();
    await tabUntil(page, (n) => n === 'Signaler la réponse');
    const trigger = page.getByRole('button', { name: 'Signaler la réponse' });
    await expect(trigger).toBeFocused();
    await page.keyboard.press('Enter');

    const dialog = page.getByRole('dialog', { name: 'Signaler cette réponse' });
    await expect(dialog).toBeVisible();
    await expect(dialog.locator(':focus')).toHaveCount(1);
    // 12 Tab : le focus ne sort jamais du dialogue
    for (let i = 0; i < 12; i += 1) {
      await page.keyboard.press('Tab');
      await expect(dialog.locator(':focus')).toHaveCount(1);
    }
    // les contrôles du formulaire sont atteignables
    await dialog.getByRole('radio').first().focus();
    await page.keyboard.press('Space');
    await expect(dialog.getByRole('radio', { name: 'Le chiffre est faux' })).toBeChecked();

    await page.keyboard.press('Escape');
    await expect(dialog).toBeHidden();
    await expect(trigger).toBeFocused();
  });

  test('tiroir d’historique mobile : Échap ferme, le focus revient au bouton', async ({ page, start }) => {
    await start('decideur');
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/questions');
    const trigger = page.getByRole('button', { name: 'Historique' });
    await trigger.focus();
    await page.keyboard.press('Enter');
    const drawer = page.getByRole('dialog', { name: 'Historique des conversations' });
    await expect(drawer).toBeVisible();
    await expect(drawer.locator(':focus')).toHaveCount(1);
    await page.keyboard.press('Escape');
    await expect(drawer).toBeHidden();
    await expect(trigger).toBeFocused();
  });

  test('volet « Voir le calcul » : activable au clavier, bloc SQL atteignable', async ({ page, start }) => {
    await start('analyste');
    await page.goto(`/questions/${SEEDED.kpi[0]}`);
    const toggle = page.getByRole('button', { name: 'Voir le calcul' });
    await toggle.focus();
    await page.keyboard.press('Enter');
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    await page.keyboard.press('Tab');
    await expect(page.locator('pre.ui-code')).toBeFocused();
  });
});

test.describe('reflow à 320 px', () => {
  test.use({ viewport: { width: 320, height: 640 } });

  const noHorizontalScroll = async (page: Page, what: string) => {
    const { scroll, client } = await page.evaluate(() => ({
      scroll: document.documentElement.scrollWidth,
      client: document.documentElement.clientWidth,
    }));
    expect(scroll, `défilement horizontal de la page : ${what}`).toBeLessThanOrEqual(client);
  };

  for (const kind of Object.keys(SEEDED) as (keyof typeof SEEDED)[]) {
    test(`réponse « ${kind} »`, async ({ page, start }) => {
      await start('analyste');
      await page.goto(`/questions/${SEEDED[kind][0]}`);
      await expect(page.getByRole('heading', { level: 2, name: SEEDED[kind][1] })).toBeVisible();
      await page.evaluate(() => document.fonts.ready);
      await noHorizontalScroll(page, kind);
    });
  }

  test('connexion et questions vide', async ({ page, start }) => {
    await start('decideur', { signedIn: false });
    await page.goto('/');
    await expect(page.getByRole('button', { name: 'Entrer comme décideur' })).toBeVisible();
    await noHorizontalScroll(page, 'connexion');
    await page.getByRole('button', { name: 'Entrer comme décideur' }).click();
    await expect(page.getByRole('heading', { name: /Posez votre question/ })).toBeVisible();
    await noHorizontalScroll(page, 'questions vide');
  });

  test('indicateurs avec analyse', async ({ page, start }) => {
    await start('analyste');
    await page.goto('/indicateurs');
    await page.getByRole('button', { name: 'Générer l’analyse' }).click();
    await expect(page.getByText('Confiance élevée')).toBeVisible();
    await noHorizontalScroll(page, 'indicateurs');
  });

  for (const [name, url, marker] of [
    ['Exploitation', '/admin', 'Sous la cible de 15,0 s'],
    ['Journal d’audit', '/admin/audit', 'f00dfeedca'],
    ['Évaluation', '/admin/evaluation', '30 sur 40'],
    ['Évaluation (détail)', '/admin/evaluation/7', 'Cible non démontrée'],
    ['Signalements', '/admin/signalements', 'Le total est bizarre'],
    ['Catalogue de KPI', '/admin/kpi', 'Part des transactions échouées.'],
    ['Couche sémantique', '/admin/semantique', 'fact_transaction'],
    ['Sécurité', '/admin/securite', 'forbidden_table'],
    ['Paramètres', '/admin/parametres', 'claude-sonnet-5-5'],
  ] as const) {
    test(`admin : ${name}`, async ({ page, start }) => {
      await start('admin');
      await page.goto(url);
      await expect(page.getByText(marker).first()).toBeVisible();
      await noHorizontalScroll(page, name);
    });
  }
});

/** Contraste non textuel (WCAG 1.4.11, 3:1) du contour des cases à cocher et boutons radio natifs : axe ne le mesure pas. */
test.describe('cases à cocher et boutons radio du signalement', () => {
  for (const theme of ['light', 'dark'] as Theme[]) {
    test(`contour visible à 3:1 au moins, thème ${theme}`, async ({ page, start }) => {
      await start('decideur', { theme });
      await page.goto(`/questions/${SEEDED.kpi[0]}`);
      await page.getByRole('button', { name: 'Signaler la réponse' }).click();
      const dialog = page.getByRole('dialog', { name: 'Signaler cette réponse' });
      await expect(dialog).toBeVisible();
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
      const controls = [dialog.getByRole('radio').first(), dialog.getByRole('checkbox')];
      for (const control of controls) {
        const png = await control.screenshot({ animations: 'disabled' });
        const ratio = await page.evaluate(async (b64) => {
          const blob = await (await fetch(`data:image/png;base64,${b64}`)).blob();
          const bmp = await createImageBitmap(blob);
          const cv = document.createElement('canvas');
          cv.width = bmp.width;
          cv.height = bmp.height;
          const ctx = cv.getContext('2d')!;
          ctx.drawImage(bmp, 0, 0);
          const { data } = ctx.getImageData(0, 0, cv.width, cv.height);
          const lum = (r: number, g: number, b: number) => {
            const f = (v: number) => ((v /= 255) <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
            return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
          };
          const bgL = lum(data[0]!, data[1]!, data[2]!); // coin : fond de la boîte de dialogue
          let best = 1;
          for (let i = 0; i < data.length; i += 4) {
            const l = lum(data[i]!, data[i + 1]!, data[i + 2]!);
            const [hi, lo] = l > bgL ? [l, bgL] : [bgL, l];
            best = Math.max(best, (hi + 0.05) / (lo + 0.05));
          }
          return best;
        }, png.toString('base64'));
        expect(ratio, `contraste du contrôle natif (thème ${theme})`).toBeGreaterThanOrEqual(3);
      }
    });
  }
});
