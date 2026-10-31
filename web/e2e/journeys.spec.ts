/** Parcours utilisateur de bout en bout, API simulée. */
import { expect, test } from './fixtures';
import { Q } from './mock-api';

const ask = async (page: import('@playwright/test').Page, question: string) => {
  await page.getByRole('textbox', { name: 'Votre question' }).fill(question);
  await page.getByRole('button', { name: 'Envoyer' }).click();
};

test.describe('connexion et déconnexion', () => {
  test('connexion en décideur par la page de connexion, puis déconnexion', async ({ page, start }) => {
    await start('decideur', { signedIn: false });
    await page.goto('/');
    await expect(page.getByRole('heading', { level: 1, name: 'Interrogez vos transactions en français' })).toBeVisible();
    // le jeton passe par le vrai plugin Vite (faux script de jeton), l'identité par /me simulé
    await page.getByRole('button', { name: 'Entrer comme décideur' }).click();
    await expect(page).toHaveURL(/\/questions$/);
    const nav = page.getByRole('navigation', { name: 'Navigation principale' });
    await expect(nav.getByText('Awa Diallo')).toBeVisible();
    await expect(nav.getByRole('link', { name: 'Journal d’audit' })).toHaveCount(0);

    await nav.getByRole('button', { name: 'Se déconnecter' }).click();
    await expect(page).toHaveURL(/\/deconnecte$/);
    await expect(page.getByRole('heading', { level: 1, name: 'Vous êtes déconnecté' })).toBeVisible();
    await page.getByRole('link', { name: 'Se reconnecter' }).click();
    await expect(page.getByRole('button', { name: 'Entrer comme analyste' })).toBeVisible();
  });

  test('session expirée : une réponse 401 mène à « Votre session a expiré »', async ({ page, start }) => {
    const mock = await start('decideur');
    await page.goto('/indicateurs');
    await expect(page.getByRole('table')).toBeVisible();
    mock.expire();
    await page.getByLabel('Région').selectOption('Kolda');
    await expect(page.getByRole('heading', { level: 1, name: 'Votre session a expiré' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Se reconnecter' })).toBeVisible();
  });
});

test.describe('questions', () => {
  test('décideur : étapes puis reçu avec chaîne de preuve, sans volet SQL', async ({ page, start }) => {
    const mock = await start('decideur');
    await page.goto('/questions');
    await expect(page.getByRole('heading', { name: 'Posez votre question, le chiffre arrive avec sa preuve' })).toBeVisible();

    await ask(page, Q.kpi);
    const steps = page.getByRole('list', { name: 'Étapes du calcul' });
    await expect(steps.getByText('Lecture des indicateurs')).toBeVisible();
    await expect(steps.getByText('Vérification des chiffres')).toBeVisible();

    const receipt = page.getByRole('article', { name: 'Réponse' });
    await expect(receipt).toBeVisible();
    await expect(steps).toHaveCount(0);
    await expect(receipt.getByText('1,23 milliard FCFA').first()).toBeVisible();
    const proof = receipt.getByRole('region', { name: 'Origine du calcul' });
    for (const [label, value] of [
      ['Table', 'Transactions réussies'],
      ['Filtre', 'Statut : réussie'],
      ['Période', 'Du 1er au 30 septembre 2026'],
      ['Opération', 'Somme des montants'],
    ]) {
      await expect(proof.getByRole('term').filter({ hasText: new RegExp(`^${label}$`) })).toBeVisible();
      await expect(proof.getByText(value, { exact: true })).toBeVisible();
    }
    await expect(page.getByRole('button', { name: 'Voir le calcul' })).toHaveCount(0);
    await expect(page.getByText('SELECT SUM')).toHaveCount(0);
    await expect(page).toHaveURL(/\/questions\/99999999-/);
    expect(mock.asked).toEqual([Q.kpi]);
  });

  test('analyste : le volet « Voir le calcul » montre le SQL', async ({ page, start }) => {
    await start('analyste');
    await page.goto('/questions');
    await ask(page, Q.kpi);
    const toggle = page.getByRole('button', { name: 'Voir le calcul' });
    await expect(toggle).toBeVisible();
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    await expect(page.locator('pre.ui-code')).toContainText('SELECT SUM(t.amount_xof)');
    await expect(page.getByRole('button', { name: 'Copier le SQL' })).toBeVisible();
  });

  test('précision demandée : un clic sur une option relance la question', async ({ page, start }) => {
    const mock = await start('decideur');
    await page.goto('/questions');
    await ask(page, Q.clarification);
    const card = page.getByRole('region', { name: 'Précision demandée' });
    await expect(card.getByText('Que voulez-vous dire par « région » ?')).toBeVisible();
    await card.getByRole('button', { name: 'Région de l’agent' }).click();
    await expect(page.getByText('Dakar arrive en tête avec 412 300 transactions')).toBeVisible();
    expect(mock.asked).toEqual([Q.clarification, 'Région de l’agent']);
  });

  test('refus : explique et propose des questions possibles', async ({ page, start }) => {
    await start('decideur');
    await page.goto('/questions');
    await ask(page, Q.refusal);
    const card = page.getByRole('region', { name: 'Question non traitée' });
    await expect(card.getByText('Cette question ne peut pas être traitée')).toBeVisible();
    await expect(card.getByRole('group', { name: 'Questions possibles' }).getByRole('button').first()).toBeEnabled();
  });

  test('signalement avec consentement : envoyé avec la question jointe', async ({ page, start }) => {
    const mock = await start('decideur');
    await page.goto('/questions');
    await ask(page, Q.kpi);
    await expect(page.getByRole('article', { name: 'Réponse' })).toBeVisible();
    await page.getByRole('button', { name: 'Signaler la réponse' }).click();
    const dialog = page.getByRole('dialog', { name: 'Signaler cette réponse' });
    await expect(dialog).toBeVisible();

    // sans choix : message d'erreur, rien n'est envoyé
    await dialog.getByRole('button', { name: 'Envoyer le signalement' }).click();
    await expect(dialog.getByRole('alert')).toHaveText('Choisissez ce qui ne va pas.');
    expect(mock.feedbacks).toHaveLength(0);

    await dialog.getByRole('radio', { name: 'Le chiffre est faux' }).check();
    await dialog.getByLabel('Précisions (facultatif)').fill('Le total ne correspond pas au relevé.');
    await dialog.getByRole('checkbox', { name: /Joindre ma question/ }).check();
    await dialog.getByRole('button', { name: 'Envoyer le signalement' }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByText('Signalement envoyé', { exact: true })).toBeVisible();
    expect(mock.feedbacks).toEqual([
      expect.objectContaining({ category: 'chiffre_faux', consent_question: true, comment: 'Le total ne correspond pas au relevé.' }),
    ]);
    expect(mock.feedbacks[0]!.message_id).toBe('99999999-a0');
  });

  test('signalement sans consentement : la question n’est pas jointe', async ({ page, start }) => {
    const mock = await start('decideur');
    await page.goto(`/questions/bbbbbbbb-bbbb-4bbb-8bbb-000000000001`);
    await page.getByRole('button', { name: 'Signaler la réponse' }).click();
    const dialog = page.getByRole('dialog', { name: 'Signaler cette réponse' });
    await dialog.getByRole('radio', { name: 'Autre problème' }).check();
    await dialog.getByRole('button', { name: 'Envoyer le signalement' }).click();
    await expect(dialog).toBeHidden();
    expect(mock.feedbacks).toEqual([expect.objectContaining({ category: 'autre', consent_question: false, comment: null })]);
  });

  test('historique : ouvrir une conversation et en supprimer une', async ({ page, start }) => {
    await start('decideur');
    await page.goto('/questions');
    const hist = page.getByRole('navigation', { name: 'Historique des conversations' });
    await hist.getByRole('link', { name: /Valeur transférée en septembre/ }).click();
    await expect(page).toHaveURL(/\/questions\/11111111-/);
    await expect(page.getByRole('article', { name: 'Réponse' })).toBeVisible();

    await hist.getByRole('button', { name: /Supprimer la conversation « Taux d’échec par région »/ }).click();
    const dialog = page.getByRole('dialog', { name: 'Supprimer cette conversation ?' });
    await dialog.getByRole('button', { name: 'Supprimer' }).click();
    await expect(dialog).toBeHidden();
    await expect(hist.getByRole('link', { name: /Taux d’échec par région/ })).toHaveCount(0);
  });
});

test.describe('indicateurs', () => {
  test('changer de période met à jour l’adresse et le relevé', async ({ page, start }) => {
    const mock = await start('decideur');
    await page.goto('/indicateurs');
    await expect(page.getByRole('heading', { name: 'Relevé de septembre 2026' })).toBeVisible();
    await expect(page.getByRole('row', { name: /Volume de transactions/ })).toBeVisible();
    await expect(page.getByRole('row')).toHaveCount(7); // en-tête + 6 indicateurs

    await page.getByLabel('Période').selectOption('2026-03');
    await expect(page).toHaveURL(/\/indicateurs\?periode=2026-03$/);
    await expect(page.getByRole('heading', { name: 'Relevé de mars 2026' })).toBeVisible();
    await page.getByLabel('Région').selectOption('Kolda');
    await expect(page).toHaveURL(/\/indicateurs\?periode=2026-03&region=Kolda$/);
    await expect.poll(() => mock.dashboardQueries).toContain('?period=2026-03&region=Kolda');
  });

  test('génération de l’analyse, source cliquable, puis question d’approfondissement', async ({ page, start }) => {
    const mock = await start('analyste');
    await page.goto('/indicateurs');
    await page.getByRole('button', { name: 'Générer l’analyse' }).click();
    await expect(page.getByText('Le volume de transactions progresse en septembre 2026.')).toBeVisible();
    expect(mock.analysisBodies).toEqual([{ period: '2026-09', region: null, regenerate: false }]);
    await expect(page.getByText('Confiance élevée')).toBeVisible();

    await page.getByRole('button', { name: 'Voir la ligne Volume de transactions dans le relevé' }).click();
    await expect(page.getByRole('row', { name: /Volume de transactions/ })).toHaveAttribute('data-highlight', 'true');

    await page.getByRole('button', { name: /Quelles régions ont le plus fort taux d’échec/ }).click();
    await expect(page).toHaveURL(/\/questions$/);
    await expect(page.getByRole('textbox', { name: 'Votre question' })).toHaveValue('Quelles régions ont le plus fort taux d’échec ?');
    expect(mock.asked).toEqual([]); // pré-remplie, jamais envoyée toute seule
  });
});

test.describe('administration', () => {
  test('un décideur qui ouvre /admin voit « Accès réservé »', async ({ page, start }) => {
    await start('decideur');
    await page.goto('/admin');
    await expect(page.getByRole('heading', { level: 1, name: 'Accès réservé' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Revenir aux questions' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Journal d’audit' })).toHaveCount(0);
  });

  test('un analyste ne voit ni Sécurité ni Paramètres', async ({ page, start }) => {
    await start('analyste');
    await page.goto('/admin/securite');
    await expect(page.getByRole('heading', { level: 1, name: 'Accès réservé' })).toBeVisible();
    const nav = page.getByRole('navigation', { name: 'Navigation principale' });
    await expect(nav.getByRole('link', { name: 'Signalements' })).toBeVisible();
    await expect(nav.getByRole('link', { name: 'Sécurité' })).toHaveCount(0);
  });

  test('l’administrateur parcourt les 8 pages du back-office', async ({ page, start }) => {
    await start('admin');
    await page.goto('/admin');
    const nav = page.getByRole('navigation', { name: 'Navigation principale' });
    const pages: [link: string, title: string, url: RegExp, marker: string][] = [
      ['Exploitation', 'Exploitation', /\/admin$/, 'Sous la cible de 15,0 s'],
      ['Journal d’audit', 'Journal d’audit', /\/admin\/audit$/, 'f00dfeedca'],
      ['Évaluation', 'Évaluation', /\/admin\/evaluation$/, '30 sur 40'],
      ['Signalements', 'Signalements', /\/admin\/signalements$/, 'Le total est bizarre'],
      ['Catalogue de KPI', 'Catalogue de KPI', /\/admin\/kpi$/, 'Part des transactions échouées.'],
      ['Couche sémantique', 'Couche sémantique', /\/admin\/semantique$/, 'fact_transaction'],
      ['Sécurité', 'Sécurité', /\/admin\/securite$/, 'forbidden_table'],
      ['Paramètres', 'Paramètres', /\/admin\/parametres$/, 'claude-sonnet-5-5'],
    ];
    for (const [link, title, url, marker] of pages) {
      await nav.getByRole('link', { name: link, exact: true }).click();
      await expect(page).toHaveURL(url);
      await expect(page.getByRole('heading', { level: 1, name: title, exact: true })).toBeVisible();
      await expect(page.getByText(marker).first()).toBeVisible();
      await expect(nav.getByRole('link', { name: link, exact: true })).toHaveAttribute('aria-current', 'page');
    }
  });

  test('le journal d’audit ouvre le détail d’un appel dans un tiroir', async ({ page, start }) => {
    await start('admin');
    await page.goto('/admin/audit');
    await page.getByRole('button', { name: /Ouvrir le détail de la trace a1b2c3d4e5f60718/ }).click();
    const drawer = page.getByRole('dialog', { name: 'Détail d’un appel' });
    await expect(drawer.getByText(/SELECT count\(\*\) FROM analytics\.dim_client/)).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(drawer).toBeHidden();
  });
});

test.describe('thème', () => {
  test('le thème sombre est mémorisé après rechargement', async ({ page, start }) => {
    await start('decideur', { scheme: 'light' });
    await page.goto('/questions');
    const html = page.locator('html');
    await expect(html).not.toHaveAttribute('data-theme', 'dark');
    await page.getByRole('button', { name: 'Passer en thème sombre' }).click();
    await expect(html).toHaveAttribute('data-theme', 'dark');
    await page.reload();
    await expect(html).toHaveAttribute('data-theme', 'dark');
    await expect(page.getByRole('button', { name: 'Passer en thème clair' })).toBeVisible();
    const bg = await page.locator('body').evaluate((el) => getComputedStyle(el).backgroundColor);
    const [r, g, b] = bg.match(/\d+/g)!.map(Number) as [number, number, number];
    expect((r + g + b) / 3).toBeLessThan(80);
  });
});
