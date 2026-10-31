/** Composants partagés : boutons, badges, champs, tableaux, panneaux, états. Styles dans ui.css. */
import * as RDialog from '@radix-ui/react-dialog';
import {
  forwardRef,
  useId,
  useRef,
  type ButtonHTMLAttributes,
  type ReactElement,
  type ReactNode,
} from 'react';

import { Icon, type IconName } from './Icon';

import './ui.css';

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  size?: 'md' | 'sm';
  icon?: IconName;
};

export const Button = forwardRef<HTMLButtonElement, BtnProps>(function Button(
  { variant = 'primary', size = 'md', icon, children, type = 'button', ...rest },
  ref,
) {
  return (
    <button ref={ref} type={type} className="ui-btn" data-variant={variant} data-size={size} {...rest}>
      {icon ? <Icon name={icon} size={size === 'sm' ? 16 : 18} /> : null}
      {children}
    </button>
  );
});

export const IconButton = forwardRef<
  HTMLButtonElement,
  ButtonHTMLAttributes<HTMLButtonElement> & { icon: IconName; label: string }
>(function IconButton({ icon, label, type = 'button', ...rest }, ref) {
  return (
    <button ref={ref} type={type} className="ui-icon-btn" aria-label={label} title={label} {...rest}>
      <Icon name={icon} size={20} />
    </button>
  );
});

export function Badge({
  tone,
  children,
}: {
  tone?: 'ok' | 'bad' | 'warn' | 'info' | 'neutral';
  children: ReactNode;
}) {
  return (
    <span className="ui-badge" data-tone={tone ?? 'neutral'}>
      {children}
    </span>
  );
}

export function Field({
  label,
  help,
  error,
  children,
}: {
  label: string;
  help?: string;
  error?: string | null;
  children: (props: { id: string; 'aria-describedby'?: string; 'aria-invalid'?: boolean }) => ReactElement;
}) {
  const id = useId();
  const helpId = help ? `${id}-help` : undefined;
  const errId = error ? `${id}-err` : undefined;
  const describedBy = [helpId, errId].filter(Boolean).join(' ') || undefined;
  return (
    <div className="ui-field">
      <label htmlFor={id}>{label}</label>
      {children({ id, 'aria-describedby': describedBy, 'aria-invalid': error ? true : undefined })}
      {help ? (
        <p id={helpId} className="ui-help">
          {help}
        </p>
      ) : null}
      {error ? (
        <p id={errId} className="ui-error">
          {error}
        </p>
      ) : null}
    </div>
  );
}

export function PageHead({
  title,
  description,
  actions,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="ui-page-head">
      <div>
        <h1>{title}</h1>
        {description ? <p>{description}</p> : null}
      </div>
      {actions ? <div className="ui-page-actions">{actions}</div> : null}
    </header>
  );
}

/**
 * Radix ne rend le focus qu'à un `Dialog.Trigger` ; nos panneaux sont pilotés par un état, sans déclencheur
 * Radix. On retient donc l'élément qui avait le focus à l'ouverture et on le lui rend à la fermeture (WCAG 2.4.3),
 * ou, s'il a disparu entre-temps, au contenu principal.
 */
function useReturnFocus() {
  const from = useRef<HTMLElement | null>(null);
  return {
    onOpenAutoFocus: () => {
      from.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    },
    onCloseAutoFocus: (e: Event) => {
      e.preventDefault();
      const el = from.current?.isConnected ? from.current : document.getElementById('contenu');
      el?.focus();
      from.current = null;
    },
  };
}

/**
 * Attributs d'une zone qui défile (grand tableau, bloc de code) : focalisable pour que le défilement reste
 * possible au clavier (WCAG 2.1.1, règle axe `scrollable-region-focusable`), nommée pour être annoncée.
 * À étaler : `<div className="ui-table-wrap" {...scrollable('Signalements')}>`.
 */
export const scrollable = (label: string) => ({ role: 'region', tabIndex: 0, 'aria-label': label }) as const;

/** Panneau latéral (détail d'un élément). Focus piégé, Échap ferme, focus rendu au déclencheur. */
export function Drawer({
  open,
  onOpenChange,
  title,
  description,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  children: ReactNode;
}) {
  const focus = useReturnFocus();
  return (
    <RDialog.Root open={open} onOpenChange={onOpenChange}>
      <RDialog.Portal>
        <RDialog.Overlay className="ui-overlay" />
        <RDialog.Content className="ui-drawer" {...focus} aria-describedby={description ? undefined : undefined}>
          <div className="ui-drawer-head">
            <div>
              <RDialog.Title asChild>
                <h2>{title}</h2>
              </RDialog.Title>
              {description ? (
                <RDialog.Description className="ui-help">{description}</RDialog.Description>
              ) : (
                <RDialog.Description className="sr-only">{title}</RDialog.Description>
              )}
            </div>
            <RDialog.Close asChild>
              <IconButton icon="close" label="Fermer" />
            </RDialog.Close>
          </div>
          <div className="ui-drawer-body">{children}</div>
        </RDialog.Content>
      </RDialog.Portal>
    </RDialog.Root>
  );
}

export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  children: ReactNode;
}) {
  const focus = useReturnFocus();
  return (
    <RDialog.Root open={open} onOpenChange={onOpenChange}>
      <RDialog.Portal>
        <RDialog.Overlay className="ui-overlay" />
        <RDialog.Content className="ui-dialog" {...focus}>
          <RDialog.Title asChild>
            <h2>{title}</h2>
          </RDialog.Title>
          {description ? (
            <RDialog.Description className="ui-help">{description}</RDialog.Description>
          ) : (
            <RDialog.Description className="sr-only">{title}</RDialog.Description>
          )}
          {children}
        </RDialog.Content>
      </RDialog.Portal>
    </RDialog.Root>
  );
}

export const DialogClose = RDialog.Close;

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="ui-state">
      <h2>{title}</h2>
      {children ? <p>{children}</p> : null}
      {action}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof Error ? error.message : 'Une erreur est survenue.';
  return (
    <div className="ui-state" role="alert">
      <h2>Impossible d’afficher cette page</h2>
      <p>{message}</p>
      {onRetry ? (
        <Button variant="secondary" icon="refresh" onClick={onRetry}>
          Réessayer
        </Button>
      ) : null}
    </div>
  );
}

export function Skeleton({ height = 20, width = '100%' }: { height?: number | string; width?: number | string }) {
  return <div className="ui-skeleton" style={{ height, width }} aria-hidden="true" />;
}

export function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: readonly { value: T; label: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <div className="ui-segmented" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" aria-pressed={o.value === value} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export { Icon, type IconName } from './Icon';
export { announce, LiveRegion } from './live';
