// Notifiche sul telefono: quando FitAI ha risposto e l'app e' chiusa, e i promemoria per segnare pranzo e cena.
// Il telefono si iscrive presso il servizio di notifiche del suo sistema e manda l'indirizzo al server, che lo sveglia
// quando c'e' qualcosa (server/spinta.py); a mostrare la notifica e' il service worker (sw.js).
// Sull'iPhone funzionano solo nell'app aperta dall'icona sulla schermata Home, e il permesso va chiesto con un tocco.
import { P } from './store.js';

const JSON_ = { 'Content-Type': 'application/json' };
export const possibili = () => 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
export const iphoneFuoriDallaHome = () => /iPhone|iPad|iPod/.test(navigator.userAgent) && !navigator.standalone;

async function iscrizione() {
  const reg = await navigator.serviceWorker.ready;
  return reg.pushManager.getSubscription();
}

// A che ora si pranza e si cena: se cambia tra giorni di palestra e di riposo vale l'ora piu' tarda
function orari() {
  const ora = (mom) => {
    const o = P.momenti?.[mom]?.ora;
    const tutte = (typeof o === 'string' ? [o] : Object.values(o || {})).filter((x) => /^\d\d:\d\d$/.test(x)).sort();
    return tutte[tutte.length - 1] || null;
  };
  return { pranzo: ora('pranzo'), cena: ora('cena') };
}

async function manda(sub, piu = {}) {
  const r = await fetch('api/notifiche/iscrizione', { method: 'POST', headers: JSON_,
    body: JSON.stringify({ indirizzo: sub.endpoint, fuso: -new Date().getTimezoneOffset(), orari: orari(), ...piu }) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.errore || 'Non riesco ad attivare le notifiche');
  return j;
}

function daBase64(testo) {
  const b = atob(testo.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (testo.length % 4)) % 4));
  return Uint8Array.from(b, (c) => c.charCodeAt(0));
}

// 'no' il telefono non le sa fare (o non da qui), 'negate' la persona le ha bloccate, 'spente', 'attive'
export async function statoNotifiche() {
  if (!possibili()) return { stato: 'no' };
  if (Notification.permission === 'denied') return { stato: 'negate' };
  try {
    const sub = Notification.permission === 'granted' ? await iscrizione() : null;
    if (!sub) return { stato: 'spente' };
    const j = await manda(sub);   // gia' che si passa: orari e fuso aggiornati
    return { stato: 'attive', promemoria: j.promemoria !== false };
  } catch { return { stato: 'spente' }; }
}

// Da chiamare da un tocco: il permesso si puo' chiedere solo cosi'.
export async function attivaNotifiche() {
  if (!possibili()) throw new Error('Questo telefono qui non le sa fare');
  const permesso = await Notification.requestPermission();
  if (permesso !== 'granted') throw new Error('Non hai dato il permesso: lo riattivi dalle impostazioni del telefono');
  const reg = await navigator.serviceWorker.ready;
  const { chiave } = await fetch('api/notifiche/chiave').then((r) => r.json());
  const sub = await reg.pushManager.getSubscription() || await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: daBase64(chiave) });
  return manda(sub, { promemoria: true });
}

export async function spegniNotifiche() {
  const sub = await iscrizione();
  if (!sub) return;
  await fetch('api/notifiche/iscrizione', { method: 'DELETE', headers: JSON_, body: JSON.stringify({ indirizzo: sub.endpoint }) }).catch(() => {});
  await sub.unsubscribe().catch(() => {});
}

export async function promemoriaPasti(acceso) {
  const sub = await iscrizione();
  if (!sub) throw new Error('Le notifiche non sono attive');
  return manda(sub, { promemoria: acceso });
}

export const provaNotifica = () => fetch('api/notifiche/prova', { method: 'POST', headers: JSON_, body: '{}' }).then((r) => r.json());

// All'avvio dell'app: se le notifiche sono attive, il server deve sapere gli orari di adesso (possono essere cambiati).
export async function allineaNotifiche() {
  try { if (possibili() && Notification.permission === 'granted') { const sub = await iscrizione(); if (sub) await manda(sub); } } catch { /* alla prossima */ }
}
