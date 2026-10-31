// Faux jeton de développement pour les tests de bout en bout : jamais vérifié (l'API est simulée).
// Il doit commencer par « ey » (contrôle du plugin Vite) et porter un `exp` lointain (pas d'avertissement de session).
const role = process.argv[2] ?? 'decideur';
const b64 = (o) => Buffer.from(JSON.stringify(o)).toString('base64url');
const exp = Math.floor(Date.now() / 1000) + 8 * 3600;
process.stdout.write(`${b64({ alg: 'none', typ: 'JWT' })}.${b64({ sub: `e2e-${role}`, role, exp })}.e2e\n`);
