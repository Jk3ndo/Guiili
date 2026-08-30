type Listener = () => void;

const listeners = new Set<Listener>();

/** S'abonne à « un diagnostic vient de se terminer » ; renvoie le désabonnement. */
export function onDiagnosticComplete(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function emitDiagnosticComplete(): void {
  for (const listener of listeners) listener();
}
