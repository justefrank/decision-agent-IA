import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'react-router';

import type { ConversationOut } from '@/api/types';
import { fmtDateTime } from '@/shared/format';
import { Button, Dialog, DialogClose, ErrorState, IconButton, Skeleton, announce } from '@/shared/ui';

import { conversationsKey, deleteConversation, listConversations } from './conversationApi';

export function History({
  activeId,
  onNavigate,
  onDeletedActive,
}: {
  activeId?: string;
  onNavigate?: () => void;
  onDeletedActive?: () => void;
}) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: conversationsKey, queryFn: listConversations });
  const [target, setTarget] = useState<ConversationOut | null>(null);
  const del = useMutation({
    mutationFn: (id: string) => deleteConversation(id),
    onSuccess: (_d, id) => {
      void qc.invalidateQueries({ queryKey: conversationsKey });
      qc.removeQueries({ queryKey: ['conversation', id] });
      setTarget(null);
      announce('Conversation supprimée.');
      if (id === activeId) onDeletedActive?.();
    },
  });

  return (
    <nav className="cv-hist" aria-label="Historique des conversations">
      <h2>Historique</h2>
      {q.isPending ? (
        <div className="cv-hist-skeleton" aria-busy="true">
          <Skeleton height={44} />
          <Skeleton height={44} />
          <Skeleton height={44} />
        </div>
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : q.data.length === 0 ? (
        <p className="ui-help">Aucune conversation pour l’instant. Vos questions apparaîtront ici.</p>
      ) : (
        <ul>
          {q.data.map((c) => {
            const title = c.title?.trim() || 'Conversation sans titre';
            return (
              <li key={c.id} data-active={c.id === activeId}>
                <Link to={`/questions/${c.id}`} aria-current={c.id === activeId ? 'page' : undefined} onClick={onNavigate}>
                  <span className="cv-hist-title">{title}</span>
                  <span className="cv-hist-date num">{fmtDateTime(c.updated_at)}</span>
                </Link>
                <IconButton icon="trash" label={`Supprimer la conversation « ${title} »`} onClick={() => setTarget(c)} />
              </li>
            );
          })}
        </ul>
      )}

      <Dialog
        open={target !== null}
        onOpenChange={(o) => {
          if (!o) {
            setTarget(null);
            del.reset();
          }
        }}
        title="Supprimer cette conversation ?"
        description="La conversation et toutes ses réponses seront supprimées. Cette action est définitive."
      >
        {del.isError ? (
          <p className="ui-error" role="alert">
            La suppression n’a pas abouti. Réessayez.
          </p>
        ) : null}
        <div className="ui-dialog-actions">
          <DialogClose asChild>
            <Button variant="secondary">Annuler</Button>
          </DialogClose>
          <Button variant="danger" disabled={del.isPending} onClick={() => target && del.mutate(target.id)}>
            Supprimer
          </Button>
        </div>
      </Dialog>
    </nav>
  );
}
