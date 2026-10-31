import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { Link } from 'react-router';

import { api } from '@/api/client';
import { fmtDateTime } from '@/shared/format';
import { announce, Button, Dialog, DialogClose, Drawer, EmptyState, Field, PageHead, Segmented } from '@/shared/ui';

import { useAdmin, type FeedbackItem, type FeedbackPage, type FeedbackStatus } from './adminApi';
import { Ledger, Line, Loaded, Mark, Pager, shortId } from './common';

const PAGE_SIZE = 25;
const CATEGORIES: Record<string, string> = {
  chiffre_faux: 'Chiffre faux',
  mauvaise_comprehension: 'Question mal comprise',
  periode_ou_perimetre: 'Période ou périmètre',
  refus_injustifie: 'Refus injustifié',
  autre: 'Autre',
};

function StatusMark({ item }: { item: FeedbackItem }) {
  if (item.status === 'nouveau') return <Mark kind="warn">Nouveau</Mark>;
  if (item.status === 'rejete') return <Mark kind="bad">Rejeté</Mark>;
  return <Mark kind="ok">{item.promoted_to_dev ? 'Traité, ajouté au jeu de développement' : 'Traité'}</Mark>;
}

type Action = 'traiter' | 'rejeter' | 'promouvoir';
const DONE: Record<Action, string> = {
  traiter: 'Signalement marqué comme traité.',
  rejeter: 'Signalement rejeté.',
  promouvoir: 'Question ajoutée au jeu de développement. Le jeu de test n’est jamais modifié.',
};

function RejectDialog({
  open,
  onOpenChange,
  onConfirm,
  busy,
  serverError,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  onConfirm: (reason: string) => void;
  busy: boolean;
  serverError: string | null;
}) {
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  function submit(e: FormEvent) {
    e.preventDefault();
    if (!reason.trim()) {
      setError('Indiquez le motif du rejet : il est conservé avec le signalement.');
      return;
    }
    setError(null);
    onConfirm(reason.trim());
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Rejeter ce signalement" description="Le motif est obligatoire et reste visible dans le signalement.">
      <form onSubmit={submit} className="adm-form" noValidate>
        <Field label="Motif du rejet" error={error ?? serverError}>
          {(p) => <textarea className="ui-textarea" rows={4} maxLength={1000} {...p} value={reason} onChange={(e) => setReason(e.target.value)} />}
        </Field>
        <div className="ui-dialog-actions">
          <DialogClose asChild>
            <Button variant="ghost">Annuler</Button>
          </DialogClose>
          <Button type="submit" variant="danger" disabled={busy}>
            Rejeter
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

function Detail({ item, onClose }: { item: FeedbackItem; onClose: () => void }) {
  const qc = useQueryClient();
  const [rejecting, setRejecting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const m = useMutation({
    mutationFn: ({ action, reason }: { action: Action; reason?: string }) =>
      api<FeedbackItem>(`/admin/feedback/${item.id}`, { method: 'PATCH', json: { action, reason } }),
    onSuccess: async (_d, v) => {
      setRejecting(false);
      setMessage(DONE[v.action]);
      announce(DONE[v.action]);
      await qc.invalidateQueries({ queryKey: ['admin', 'feedback'] });
      if (v.action === 'rejeter') onClose();
    },
  });
  const canPromote = item.status !== 'rejete' && !item.promoted_to_dev && item.consent_question && Boolean(item.question_text);
  const err = m.error instanceof Error ? m.error.message : null;
  return (
    <>
      <Ledger label="Signalement">
        <Line label="Reçu le" value={fmtDateTime(item.ts)} />
        <Line label="Motif" value={CATEGORIES[item.category] ?? item.category} />
        <Line label="État" value={<StatusMark item={item} />} />
        {item.reject_reason ? <Line label="Motif du rejet" value={item.reject_reason} /> : null}
      </Ledger>
      <section aria-labelledby="fb-comment" className="adm-block">
        <h3 id="fb-comment">Commentaire</h3>
        <p>{item.comment || 'Aucun commentaire.'}</p>
      </section>
      <section aria-labelledby="fb-q" className="adm-block">
        <h3 id="fb-q">Question</h3>
        {item.consent_question && item.question_text ? (
          <p className="adm-quote">{item.question_text}</p>
        ) : (
          <p>L’utilisateur n’a pas consenti à partager sa question : elle n’est pas affichée.</p>
        )}
      </section>
      <section aria-labelledby="fb-proof" className="adm-block">
        <h3 id="fb-proof">Réponse et chaîne de preuve</h3>
        {item.trace_id ? (
          <p>
            Les étapes, le SQL et les durées de cette réponse sont dans la trace <code>{shortId(item.trace_id, 12)}</code>.{' '}
            <Link to={`/admin/audit/${encodeURIComponent(item.trace_id)}`}>Ouvrir la trace</Link> (l’ouverture est journalisée).
          </p>
        ) : (
          <p>Aucune trace n’est rattachée à ce signalement.</p>
        )}
      </section>

      <div className="adm-actions" role="group" aria-label="Traiter ce signalement">
        {item.status === 'nouveau' ? (
          <>
            <Button icon="check" disabled={m.isPending} onClick={() => m.mutate({ action: 'traiter' })}>
              Marquer comme traité
            </Button>
            <Button variant="secondary" icon="close" disabled={m.isPending} onClick={() => setRejecting(true)}>
              Rejeter
            </Button>
          </>
        ) : null}
        {item.status !== 'rejete' && !item.promoted_to_dev ? (
          <Button variant="secondary" icon="plus" disabled={m.isPending || !canPromote} onClick={() => m.mutate({ action: 'promouvoir' })}>
            Ajouter au jeu de développement
          </Button>
        ) : null}
      </div>
      <p className="adm-note">
        L’ajout se fait uniquement dans le jeu de développement, jamais dans le jeu de test, qui reste figé.
        {!item.consent_question && item.status !== 'rejete' ? ' Il demande le consentement de l’utilisateur à joindre sa question.' : ''}
      </p>
      {message ? (
        <p className="adm-ok" role="status">
          <Mark kind="ok">Fait</Mark> {message}
        </p>
      ) : null}
      {err && !rejecting ? (
        <p className="ui-error" role="alert">
          {err}
        </p>
      ) : null}
      <RejectDialog
        open={rejecting}
        onOpenChange={setRejecting}
        busy={m.isPending}
        serverError={rejecting ? err : null}
        onConfirm={(reason) => m.mutate({ action: 'rejeter', reason })}
      />
    </>
  );
}

export function AdminFeedbackPage() {
  const [status, setStatus] = useState<'' | FeedbackStatus>('');
  const [page, setPage] = useState(1);
  const [openId, setOpenId] = useState<string | null>(null);
  const q = useAdmin<FeedbackPage>(
    ['feedback', status, page],
    `feedback?page=${page}&page_size=${PAGE_SIZE}${status ? `&status=${status}` : ''}`,
    { keep: true },
  );
  const opened = q.data?.items.find((i) => i.id === openId) ?? null;
  return (
    <div className="adm-page">
      <PageHead
        title="Signalements"
        description="Les réponses que des utilisateurs jugent fausses ou mal comprises. Les nouveaux passent en premier."
        actions={
          <Segmented
            label="État"
            value={status}
            options={[
              { value: '', label: 'Tous' },
              { value: 'nouveau', label: 'Nouveaux' },
              { value: 'traite', label: 'Traités' },
              { value: 'rejete', label: 'Rejetés' },
            ]}
            onChange={(v) => {
              setStatus(v);
              setPage(1);
            }}
          />
        }
      />
      <Loaded query={q} rows={5}>
        {(d) =>
          d.items.length === 0 ? (
            <EmptyState title={status ? 'Aucun signalement dans cet état' : 'Aucun signalement'}>
              {status ? 'Choisissez un autre état pour voir les autres signalements.' : 'Aucun utilisateur n’a signalé de réponse pour l’instant.'}
            </EmptyState>
          ) : (
            <>
              <div className="ui-table-wrap">
                <table className="ui-table">
                  <caption className="sr-only">Signalements, nouveaux d’abord</caption>
                  <thead>
                    <tr>
                      <th scope="col">Reçu le</th>
                      <th scope="col">Motif</th>
                      <th scope="col">Commentaire</th>
                      <th scope="col">Question jointe</th>
                      <th scope="col">État</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.items.map((i) => (
                      <tr key={i.id}>
                        <td>
                          <button type="button" className="adm-link" onClick={() => setOpenId(i.id)} aria-label={`Ouvrir le signalement du ${fmtDateTime(i.ts)}`}>
                            {fmtDateTime(i.ts)}
                          </button>
                        </td>
                        <td>{CATEGORIES[i.category] ?? i.category}</td>
                        <td className="adm-clip">{i.comment || '—'}</td>
                        <td>{i.consent_question ? 'Oui' : 'Non'}</td>
                        <td>
                          <StatusMark item={i} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Pager page={d.page} pageSize={d.page_size} total={d.total} onPage={setPage} noun={d.total > 1 ? 'signalements' : 'signalement'} />
            </>
          )
        }
      </Loaded>
      <Drawer open={Boolean(opened)} onOpenChange={(o) => !o && setOpenId(null)} title="Signalement" description="Lire, puis traiter, rejeter ou ajouter au jeu de développement.">
        {opened ? <Detail item={opened} onClose={() => setOpenId(null)} /> : null}
      </Drawer>
    </div>
  );
}
