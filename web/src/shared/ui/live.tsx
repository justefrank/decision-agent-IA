/**
 * Région d'annonce permanente (role="status") pour les lecteurs d'écran : on injecte le texte dans un
 * conteneur toujours présent, une annonce à la fois (DESIGN_SYSTEM §6).
 */
import { useEffect, useState } from 'react';

type Listener = (text: string) => void;
const listeners = new Set<Listener>();

export function announce(text: string): void {
  listeners.forEach((l) => l(text));
}

export function LiveRegion() {
  const [text, setText] = useState('');
  useEffect(() => {
    const l: Listener = (t) => {
      // Vider puis réécrire : un même message répété est annoncé à nouveau.
      setText('');
      window.setTimeout(() => setText(t), 30);
    };
    listeners.add(l);
    return () => {
      listeners.delete(l);
    };
  }, []);
  return (
    <div role="status" aria-live="polite" className="sr-only">
      {text}
    </div>
  );
}
