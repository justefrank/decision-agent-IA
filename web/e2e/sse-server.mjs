// Mini serveur de flux SSE pour les tests (hermétique, local). Vite lui renvoie `POST /api/conversations/*/messages`
// (variable API_TARGET) ; `route.fetch` de Playwright ne diffuse pas en continu, or les étapes doivent
// rester visibles entre deux événements. Le corps de la requête porte la séquence à émettre :
// { steps: StepEvent[], final: AssistantMessage | null, stepDelayMs, finalDelayMs }.
import http from 'node:http';

const port = Number(process.env.SSE_PORT ?? 5198);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const send = (res, event, data) => res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);

http
  .createServer((req, res) => {
    if (req.method !== 'POST') {
      res.writeHead(200, { 'Content-Type': 'text/plain' });
      res.end('ok');
      return;
    }
    let raw = '';
    req.on('data', (c) => (raw += c));
    req.on('end', async () => {
      const plan = JSON.parse(raw || '{}');
      res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-store' });
      for (const s of plan.steps ?? []) {
        send(res, 'step', s);
        await sleep(plan.stepDelayMs ?? 350);
      }
      await sleep(plan.finalDelayMs ?? 500);
      if (plan.final) send(res, 'final', plan.final);
      res.end();
    });
  })
  .listen(port, '127.0.0.1');
