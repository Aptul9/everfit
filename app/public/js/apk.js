// L'app Android (android/, una Trusted Web Activity) e' solo un guscio che apre questo sito: il contenuto si aggiorna
// da se'. Il guscio no: si apre con ?apk=<versionCode> e qui lo si confronta con il JSON che la pipeline mette su servizi
// accanto all'APK. C'e' un guscio piu' nuovo: un avviso con il link, e Android lo installa sopra il vecchio (stessa firma).
// Senza ?apk (browser, iPhone, app per PC) non fa niente.

import { h } from './dom.js';

const INDICE = 'https://servizi.everbright.it/download/EverFit-Android.json';
const GIORNO = 86400000;          // il JSON si chiede al massimo una volta al giorno
const ULTIMO = 'fit.apk.ultimo';  // { ora, j }: l'ultima risposta, valida un giorno
const SALTATA = 'fit.apk.saltata';   // il versionCode per cui si e' detto "dopo": quello non si ripropone

const leggi = (k) => { try { return JSON.parse(localStorage.getItem(k)); } catch { return null; } };
const scrivi = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* memoria piena o negata */ } };

// ?apk resta solo nella prima pagina (main.js toglie la query per ?apri=fitai): per la sessione lo tiene sessionStorage
function installata() {
  const q = new URLSearchParams(location.search).get('apk');
  const valida = (v) => (/^\d{1,9}$/.test(v || '') ? Number(v) : 0);
  try {
    if (valida(q)) sessionStorage.setItem('fit.apk', q);
    return valida(sessionStorage.getItem('fit.apk'));
  } catch {
    return valida(q);
  }
}

const buona = (j) => j && Number.isInteger(j.versionCode) && j.versionCode > 0 && typeof j.version === 'string'
  && /^EverFit-Android[A-Za-z0-9._-]{0,60}\.apk$/.test(j.file || '');

async function indice() {
  const prima = leggi(ULTIMO);
  if (prima && Date.now() - prima.ora < GIORNO && Date.now() >= prima.ora) return prima.j;
  try {
    const r = await fetch(INDICE, { cache: 'no-store', credentials: 'omit', signal: AbortSignal.timeout(8000) });
    const j = r.ok ? await r.json() : null;
    scrivi(ULTIMO, { ora: Date.now(), j: buona(j) ? j : null });
    return buona(j) ? j : null;
  } catch {
    return null;   // senza rete: si riprova al prossimo rientro, il giorno non e' consumato
  }
}

function mostra(j) {
  if (document.querySelector('.apk-nuova')) return;
  const el = h('div', { class: 'apk-nuova', role: 'status' },
    h('div', { class: 'testo' }, h('b', null, "Nuova versione dell'app"), h('small', null, `EverFit ${j.version}`)),
    h('a', { class: 'scarica', href: new URL(j.file, INDICE).href }, 'Aggiorna'),
    h('button', { class: 'dopo', type: 'button', 'aria-label': 'Non ora', onclick: () => { scrivi(SALTATA, j.versionCode); el.remove(); } }, '×'));
  document.body.append(el);
}

async function controlla(versione) {
  const j = await indice();
  if (!j || j.versionCode <= versione || j.versionCode <= (Number(leggi(SALTATA)) || 0)) return;
  mostra(j);
}

export function controllaApk() {
  const versione = installata();
  if (!versione) return;
  controlla(versione);
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') controlla(versione); });
}
