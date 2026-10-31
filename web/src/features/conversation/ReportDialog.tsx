import { useId, useState } from 'react';

import { Button, Dialog, DialogClose } from '@/shared/ui';

import type { FeedbackCategory, FeedbackInput } from './conversationApi';

const CATEGORIES: { value: FeedbackCategory; label: string }[] = [
  { value: 'chiffre_faux', label: 'Le chiffre est faux' },
  { value: 'mauvaise_comprehension', label: 'La question a été mal comprise' },
  { value: 'periode_ou_perimetre', label: 'La période ou le périmètre ne conviennent pas' },
  { value: 'refus_injustifie', label: 'Le refus n’est pas justifié' },
  { value: 'autre', label: 'Autre problème' },
];

export function ReportDialog({
  open,
  onOpenChange,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (f: FeedbackInput) => Promise<void>;
}) {
  const id = useId();
  const [category, setCategory] = useState<FeedbackCategory | null>(null);
  const [comment, setComment] = useState('');
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  const submit = async () => {
    if (!category) {
      setError('Choisissez ce qui ne va pas.');
      return;
    }
    setError(null);
    setSending(true);
    try {
      await onSubmit({ category, comment, consentQuestion: consent });
      onOpenChange(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Le signalement n’a pas pu être envoyé. Réessayez.');
    } finally {
      setSending(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Signaler cette réponse"
      description="Votre signalement aide l’équipe à corriger l’outil. Il est lu par l’équipe data."
    >
      <form
        className="cv-report"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <fieldset aria-describedby={error ? `${id}-err` : undefined}>
          <legend>Ce qui ne va pas</legend>
          {CATEGORIES.map((c) => (
            <label key={c.value} className="cv-choice">
              <input type="radio" name={`${id}-cat`} checked={category === c.value} onChange={() => setCategory(c.value)} />
              <span>{c.label}</span>
            </label>
          ))}
        </fieldset>
        <div className="ui-field">
          <label htmlFor={`${id}-c`}>Précisions (facultatif)</label>
          <textarea id={`${id}-c`} className="ui-textarea" maxLength={2000} value={comment} onChange={(e) => setComment(e.target.value)} />
        </div>
        <label className="cv-choice cv-consent">
          <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
          <span>
            Joindre ma question à ce signalement
            <small>Sans cette case, seule la réponse est signalée : le texte de votre question n’est pas transmis.</small>
          </span>
        </label>
        {error ? (
          <p id={`${id}-err`} className="ui-error" role="alert">
            {error}
          </p>
        ) : null}
        <div className="ui-dialog-actions">
          <DialogClose asChild>
            <Button variant="secondary">Annuler</Button>
          </DialogClose>
          <Button type="submit" disabled={sending}>
            Envoyer le signalement
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
