// Anunță listele deschise că documentele s-au schimbat (salvare, înregistrare, anulare).

const EVENT = "contahub:documents-changed";

export function notifyDocumentsChanged(route: string): void {
  window.dispatchEvent(new CustomEvent(EVENT, { detail: route }));
}

export function onDocumentsChanged(route: string, handler: () => void): () => void {
  const listener = (e: Event) => {
    if ((e as CustomEvent<string>).detail === route) handler();
  };
  window.addEventListener(EVENT, listener);
  return () => window.removeEventListener(EVENT, listener);
}
