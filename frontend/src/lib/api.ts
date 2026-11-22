/**
 * Jedno místo pro adresu backendu.
 *
 * Pořadí, ve kterém se adresa bere:
 *  1. NEXT_PUBLIC_API_URL – když je nastavená (např. až aplikaci vystavíš
 *     online a backend poběží na jiné adrese než frontend).
 *  2. jinak stejný hostitel, na kterém je otevřená stránka, port 8000 –
 *     funguje pro localhost, domácí síť (telefon) i tunel.
 *
 * Dá se tedy nasadit kamkoli bez zásahu do kódu: stačí nastavit proměnnou.
 */
const ENV_API = process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, '');

export const API =
  ENV_API ||
  (typeof window !== 'undefined' && window.location.hostname
    ? `${window.location.protocol}//${window.location.hostname}:8000`
    : 'http://127.0.0.1:8000');
