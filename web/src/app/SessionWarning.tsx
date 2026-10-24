/** Avertissement avant la fin de session, avec prolongation (WCAG 2.2.1). */
import { useAuth } from '@/auth/useAuth';
import { Button, Dialog } from '@/shared/ui';

export function SessionWarning() {
  const { expiresIn, extend, logout } = useAuth();
  const open = expiresIn !== null;
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) void extend();
      }}
      title="Votre session va se terminer"
      description={
        expiresIn !== null
          ? `Sans action de votre part, vous serez déconnecté dans ${expiresIn} secondes.`
          : undefined
      }
    >
      <div className="ui-dialog-actions">
        <Button variant="secondary" onClick={() => void logout()}>
          Se déconnecter
        </Button>
        <Button onClick={() => void extend()}>Rester connecté</Button>
      </div>
    </Dialog>
  );
}
