// Il codice a barre si legge dal vivo, con la fotocamera dentro l'app. Chi preferisce puo' scattare una foto (il campo
// "file" apre la fotocamera di sistema e non chiede permessi): e' una scelta che resta sul dispositivo.
import { h, icona } from './dom.js';
import { leggiFoto } from './codice.js';

// (la prima versione, sull'iPhone, partiva dalla foto: non piaceva. Con la chiave nuova si riparte tutti dal vivo)
const CHIAVE = 'fit-scanner2';
export function conLaFoto() {
  try { return localStorage.getItem(CHIAVE) === 'foto'; } catch { return false; }
}
export function ricordaScanner(modo) { try { localStorage.setItem(CHIAVE, modo); } catch { /* pazienza */ } }

export const TESTO_FOTO = 'Fotografa il codice a barre da vicino, tenendolo dritto e a fuoco.';
export const TESTO_VIVO = 'Inquadra il codice a barre tenendolo dritto, a una spanna dal telefono.';
export const PASSA_ALLA_FOTO = 'Preferisco scattare una foto';
export const PASSA_AL_VIVO = 'Torna alla fotocamera dal vivo';

// Sull'iPhone, nell'app aperta dalla schermata Home, il permesso della fotocamera dura finche' l'app resta aperta: alla
// riapertura iOS lo richiede, e un'app web non puo' ricordarselo (WebKit, bug 215884). Si toglie una volta per tutte
// dalle Impostazioni del telefono, dicendo a Safari di consentire la fotocamera: lo si scrive qui, sotto la fotocamera,
// finche' il permesso risulta ancora da chiedere o finche' la persona non dice che l'ha letto.
const LETTO = 'fit-permesso-letto';
export function notaPermesso() {
  if (!navigator.standalone) return null;
  try { if (localStorage.getItem(LETTO)) return null; } catch { /* si mostra */ }
  const nota = h('div', { class: 'nota', style: { margin: '2px 0 4px' } }, icona('info'),
    h('span', null, 'L\'iPhone richiede il permesso della fotocamera ogni volta che riapri l\'app. Per non vederlo più: ',
      h('b', null, 'Impostazioni → App → Safari → Fotocamera → Consenti'), '. ',
      h('button', { class: 'testo-link', style: { display: 'inline', margin: 0, padding: 0, width: 'auto' }, onclick: () => {
        try { localStorage.setItem(LETTO, '1'); } catch { /* pazienza */ }
        nota.remove();
      } }, 'Non mostrarlo più')));
  // il permesso c'e' gia' (l'ha appena dato, o Safari e' gia' su "Consenti"): niente da spiegare
  navigator.permissions?.query?.({ name: 'camera' }).then((p) => { if (p.state === 'granted') nota.remove(); }).catch(() => {});
  return nota;
}

// Il tasto "Fotografa il codice" con il suo campo nascosto. `stato` e' il paragrafo dove si scrive come va;
// alCodice(cifre) quando il codice e' stato letto.
export function tastoFoto(stato, alCodice) {
  const campo = h('input', { type: 'file', accept: 'image/*', capture: 'environment', hidden: true });
  const tasto = h('button', { class: 'btn primo', onclick: () => campo.click() }, icona('camera'), 'Fotografa il codice a barre');
  campo.addEventListener('change', async () => {
    const file = campo.files?.[0];
    campo.value = '';
    if (!file) return;
    stato.textContent = 'Leggo il codice dalla foto…';
    tasto.disabled = true;
    let codice = null;
    try { codice = await leggiFoto(file); } catch { codice = null; }
    tasto.disabled = false;
    if (codice) alCodice(codice);
    else stato.textContent = 'Non sono riuscito a leggerlo. Riprova più da vicino, con il codice dritto e a fuoco, oppure scrivi i numeri qui sotto.';
  });
  return { tasto, campo, apri: () => campo.click() };
}
