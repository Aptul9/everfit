// Ossatura dell'app: avvio, navigazione, barra in basso, barra in alto, aggiornamenti, e tutto quello che la fa
// sentire un'app e non una pagina (scorrimento dentro #app, niente selezione del testo, niente zoom, transizioni).

import { h, icona, oggi, colpetto } from './dom.js';
import { carica, ascolta, ascoltaSync, allinea, controllaNovita, P, io, serveProfilo, siAllena } from './store.js';
import { caricaMisure, aggiornaMisure, ascoltaMisure } from './misure.js';
import { ascoltaSentinella, controllaSentinella } from './bilancia.js';
import { ridisegnaFogli, chiudiFogli } from './ui.js';
import { vistaOggi } from './views/oggi.js';
import { vistaDieta } from './views/dieta.js';
import { vistaAllenamento } from './views/allenamento.js';
import { vistaSeduta, lasciaSeduta } from './views/seduta.js';
import { vistaProgressi } from './views/progressi.js';
import { vistaAltro, aggiornaSync } from './views/altro.js';
import { vistaProfilo } from './views/profilo.js';
import { apriScanner } from './views/prodotto.js';
import { apriAssistente, riprendiAssistente } from './views/assistente.js';
import { allineaNotifiche } from './notifiche.js';
import { controllaApk } from './apk.js';

const app = document.getElementById('app');         // e' lui che scorre, non la pagina
const barraSu = document.getElementById('barra-su');
const SCHEDE = [
  ['oggi', () => 'Oggi', 'home', vistaOggi],
  ['dieta', () => 'Dieta', 'fork', vistaDieta],
  ['allenamento', () => (siAllena() ? 'Gym' : 'Attività'), 'dumbbell', vistaAllenamento],
  ['progressi', () => 'Progressi', 'chart', vistaProgressi],
  ['altro', () => 'Piano', 'grid', vistaAltro],
];
const VISTE = Object.fromEntries(SCHEDE.map((x) => [x[0], x[3]]));
VISTE.seduta = vistaSeduta;
VISTE.profilo = vistaProfilo;
// nella barra in basso lo scanner sta in mezzo: le schede occupano le colonne 0, 1, 3, 4, 5
const colonna = (i) => (i < 2 ? i : i + 1);

let barra = null;
let bolla = null;
let rotta = null;
let giornoDisegnato = null;
const posizioni = new Map();   // dove si era arrivati a scorrere in ogni schermata

function leggiRotta() {
  // un account appena creato non ha ancora un piano: prima di tutto le domande su di lui
  if (serveProfilo()) return { nome: 'profilo', parti: ['primo'], chiave: 'profilo/primo' };
  const parti = location.hash.replace(/^#\/?/, '').split('/').filter(Boolean);
  const nome = VISTE[parti[0]] ? parti[0] : 'oggi';
  return { nome, parti: parti.slice(1), chiave: `${nome}/${parti.slice(1).join('/')}` };
}
// quanto si e' "dentro": le schede sono a 0, una schermata aperta da una scheda a 1, la seduta guidata a 2
const profondita = (r) => (r.nome === 'seduta' ? 2 : r.nome === 'profilo' || r.parti.length ? 1 : 0);
const senzaBarre = (r) => r.nome === 'seduta' || r.nome === 'profilo' || (r.nome === 'allenamento' && r.parti.length > 0);

// Mette la schermata nuova al posto della vecchia. Quello che ha `data-tieni` (il video di un esercizio) resta dov'e'
// se c'e' anche nella nuova: toglierlo e rimetterlo lo farebbe ripartire da capo a ogni spunta.
function monta(vista, stessa) {
  const vecchia = app.firstElementChild;
  const tenuti = stessa && vecchia ? [...vecchia.children].filter((el) => el.dataset.tieni) : [];
  const nuovi = [...vista.children];
  if (!tenuti.length || !tenuti.every((el) => nuovi.some((n) => n.dataset.tieni === el.dataset.tieni))) {
    app.replaceChildren(vista);
    return vista;
  }
  vecchia.className = vista.className;
  for (const el of [...vecchia.children]) if (!tenuti.includes(el)) el.remove();
  let fermo = vecchia.firstElementChild;   // il prossimo elemento tenuto, davanti al quale vanno i nuovi
  for (const n of nuovi) {
    if (fermo && n.dataset.tieni === fermo.dataset.tieni) fermo = fermo.nextElementSibling;
    else vecchia.insertBefore(n, fermo);
  }
  return vecchia;
}

function disegna(entrata = false) {
  const r = leggiRotta();
  const cambiata = !rotta || rotta.chiave !== r.chiave;
  if (cambiata && rotta?.nome === 'seduta' && r.nome !== 'seduta') lasciaSeduta();
  // da dove si arriva decide come entra la schermata: all'avvio a cascata, tra schede in dissolvenza, avanti e indietro di lato
  const verso = !rotta ? 'apre'
    : !cambiata ? (entrata ? 'scheda' : null)
      : profondita(r) > profondita(rotta) ? 'avanti' : profondita(r) < profondita(rotta) ? 'indietro' : 'scheda';
  if (rotta && cambiata) posizioni.set(rotta.chiave, app.scrollTop);
  rotta = r;
  giornoDisegnato = oggi();
  const nudo = senzaBarre(r);
  let figli;
  try {
    figli = [].concat(VISTE[r.nome](r.parti, disegna)).flat(Infinity).filter((x) => x && x.nodeType);
  } catch (e) {
    // una schermata che si rompe non deve lasciare lo schermo vuoto
    console.error(e);
    figli = [h('div', { class: 'card vuoto', style: { marginTop: '30px' } }, h('b', null, 'Qui qualcosa si è rotto'), 'Il resto dell\'app funziona. Se ricaricando succede ancora, dimmelo.',
      h('button', { class: 'btn', style: { marginTop: '14px' }, onclick: () => location.reload() }, 'Ricarica'))];
  }
  let vista = h('div', { class: `view${verso ? ` v-${verso}` : ''}` }, figli);
  if (verso === 'apre') figli.forEach((el, i) => el.style?.setProperty('--i', Math.min(i, 9)));
  app.classList.toggle('nudo', nudo);
  document.documentElement.classList.toggle('nuda', nudo);
  vista = monta(vista, !cambiata && !verso);
  if (cambiata) {
    // tornando su una scheda la si ritrova dov'era; andando avanti si parte dall'alto
    app.scrollTop = verso === 'avanti' || verso === 'apre' ? 0 : (posizioni.get(r.chiave) || 0);
    chiudiFogli();
  }
  if (verso) setTimeout(() => vista.classList.remove(`v-${verso}`), 1100);
  // nella barra in alto va il nome della scheda ("Oggi"), non il titolo grande ("Ciao, Admin")
  const scheda = SCHEDE.find((x) => x[0] === r.nome);
  barraSu.querySelector('b').textContent = (!r.parti.length && scheda?.[1]()) || vista.querySelector('.top h1')?.textContent || '';
  barraSu.classList.toggle('via', nudo);
  aggiornaBarraSu();
  if (barra) {
    barra.classList.toggle('via', nudo);
    const i = SCHEDE.findIndex((x) => x[0] === r.nome);
    barra.querySelectorAll('button[data-scheda]').forEach((b, k) => {
      b.classList.toggle('on', k === i);
      b.lastElementChild.textContent = SCHEDE[k][1]();
    });
    if (i >= 0) barra.querySelector('.pillola').style.transform = `translateX(${colonna(i) * 100}%)`;
    // l'assistente c'e' per chi ha una chiave; al capo si vede sempre, cosi' sa che esiste e dove accenderlo
    bolla.classList.toggle('via', nudo || !(io.ai || io.capo));
  }
}

// La barra in alto compare quando il titolo grande e' scorso via, come nelle app di iOS.
function aggiornaBarraSu() {
  barraSu.classList.toggle('su', app.scrollTop > 40 && !!barraSu.querySelector('b').textContent);
  // in cima alla pagina sotto l'orologio non c'e' niente da coprire: la sfumatura serve solo quando si e' scorso (vedi app.css)
  document.documentElement.classList.toggle('scorso', app.scrollTop > 4);
}

function costruisciBarra() {
  const scheda = ([id, nome, ic]) => h('button', { 'data-scheda': id, 'aria-label': nome(), onclick: () => {
    colpetto();
    if (leggiRotta().nome === id && !leggiRotta().parti.length) app.scrollTo({ top: 0, behavior: 'smooth' });
    else location.hash = `#/${id}`;
  } }, icona(ic), h('span', null, nome()));
  barra = h('nav', { id: 'tabbar', 'aria-label': 'Sezioni' },
    h('span', { class: 'pillola' }),
    scheda(SCHEDE[0]), scheda(SCHEDE[1]),
    h('button', { class: 'scanner', 'aria-label': 'Scansiona un prodotto', onclick: () => apriScanner() }, h('i', null, icona('scan'))),
    scheda(SCHEDE[2]), scheda(SCHEDE[3]), scheda(SCHEDE[4]));
  bolla = h('button', { id: 'bolla', class: 'via', 'aria-label': 'Chiedi a FitAI', onclick: () => apriAssistente() }, icona('sparkle'));
  document.body.append(barra, bolla);
}

// Quello che in una pagina web e' normale e in un'app no: menu al tocco lungo, zoom, trascinamento delle immagini.
function daApp() {
  const campo = (el) => !!el?.closest?.('input, textarea, [contenteditable]');
  document.addEventListener('contextmenu', (e) => { if (!campo(e.target)) e.preventDefault(); });
  document.addEventListener('dragstart', (e) => { if (!campo(e.target)) e.preventDefault(); });
  document.addEventListener('gesturestart', (e) => e.preventDefault());   // pizzico su iOS
  document.addEventListener('touchstart', () => {}, { passive: true });   // senza, su iOS :active non scatta
  // (il doppio tocco che ingrandisce lo spegne `touch-action` nel CSS: fermarlo qui mangerebbe i tocchi veloci sui tasti + e -)
  app.addEventListener('scroll', aggiornaBarraSu, { passive: true });
  // senza rete l'app continua a funzionare: basta dirlo
  const rete = () => document.documentElement.classList.toggle('senza-rete', navigator.onLine === false);
  addEventListener('online', rete); addEventListener('offline', rete); rete();
  document.documentElement.classList.toggle('installata', matchMedia('(display-mode: standalone)').matches || navigator.standalone === true || !!window.pywebview);
  // Quando esce la tastiera l'iPhone non rimpicciolisce la pagina: la copre. --tastiera dice quanto, cosi' i fogli
  // con un campo in fondo (la chat) si alzano sopra di lei invece di finirci sotto.
  const vv = window.visualViewport;
  if (vv) {
    const misura = () => {
      // dove la finestra e' piu' bassa dello schermo (html.alta, vedi index.html) i fogli si misurano dal fondo dello
      // schermo, non della finestra: la tastiera va contata da li'
      const fondo = document.documentElement.classList.contains('alta') ? window.fitSchermo.schermo : innerHeight;
      const alta = Math.max(0, Math.round(fondo - vv.height - vv.offsetTop));
      document.documentElement.style.setProperty('--tastiera', `${alta > 80 ? alta : 0}px`);
      document.documentElement.classList.toggle('con-tastiera', alta > 80);
      if (alta > 80) diagnosi('tastiera');
    };
    vv.addEventListener('resize', misura); vv.addEventListener('scroll', misura);
  }
}

// Le misure dello schermo come le vede questo dispositivo, mandate al registro del server una volta per avvio (e una
// la prima volta che esce la tastiera). Su un iPhone vero finestra, fasce di sistema e tastiera non si comportano come
// nell'anteprima, e da qui si capisce cosa sta succedendo senza chiedere uno screenshot. Niente di personale: solo numeri.
const detto = new Set();
function diagnosi(quando) {
  if (detto.has(quando)) return;
  detto.add(quando);
  try {
    const radice = document.documentElement, vv = window.visualViewport;
    // le fasce di sistema (orologio in alto, lineetta in basso) si leggono da un elemento di prova
    const sonda = document.createElement('div');
    sonda.style.cssText = 'position:fixed;left:0;top:0;width:0;visibility:hidden;pointer-events:none;box-sizing:content-box;height:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)';
    document.body.append(sonda);
    const stile = getComputedStyle(sonda);
    const sopra = parseFloat(stile.height) || 0, sotto = parseFloat(stile.paddingBottom) || 0;
    sonda.remove();
    const rett = (el) => { const r = el?.getBoundingClientRect(); return r ? [Math.round(r.top), Math.round(r.bottom)] : null; };
    const dati = {
      quando, app: navigator.standalone === true || matchMedia('(display-mode: standalone)').matches, pc: !!window.pywebview,
      schermo: [screen.width, screen.height], finestra: [innerWidth, innerHeight], radice: [radice.clientWidth, radice.clientHeight],
      vv: vv ? [Math.round(vv.width), Math.round(vv.height), Math.round(vv.offsetTop)] : null,
      sopra, sotto, corretto: window.fitSchermo || null, alta: radice.classList.contains('alta'),
      corpo: rett(document.body), guscio: rett(document.getElementById('guscio')), barra: rett(barra), foglio: rett([...document.querySelectorAll('.foglio')].pop()),
      tastiera: radice.style.getPropertyValue('--tastiera') || null, tema: radice.dataset.tema || 'scuro', dpr: devicePixelRatio,
      dove: location.hash.slice(0, 30), ua: navigator.userAgent.slice(0, 140),
    };
    fetch('api/diagnosi', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(dati), keepalive: true }).catch(() => {});
  } catch { /* e' solo un aiuto: se non riesce pazienza */ }
}

// Il benvenuto sta in index.html e copre tutto dal primo fotogramma: quando l'app e' pronta sale e la scopre.
// Resta almeno un secondo abbondante, il tempo di leggere il nome.
function chiudiBenvenuto() {
  const el = document.getElementById('benvenuto');
  if (!el) return;
  if (io.nome) el.querySelector('b').textContent = io.nome;
  setTimeout(() => {
    el.classList.add('via');
    setTimeout(() => el.remove(), 750);
  }, Math.max(0, 1200 - (Date.now() - (window.fitAvvio || 0))));
}

// ---------- copia sul dispositivo e aggiornamenti ----------
// L'app si apre dalla copia tenuta sul dispositivo (sw.js). Quando sul server ce n'e' una nuova, il service worker la
// scarica e resta in attesa: e' la pagina a dirgli quando prendere il posto di quello vecchio, e subito dopo si
// ricarica. Cosi' non capita mai di avere mezza app vecchia e mezza nuova.
let inAttesa = null;   // la copia nuova, gia' scaricata, che aspetta il via
function ricarica() {
  try {
    if (Date.now() - Number(sessionStorage.getItem('fit.ricarica') || 0) < 10000) return;   // mai due volte di fila
    sessionStorage.setItem('fit.ricarica', String(Date.now()));
  } catch { /* senza memoria si ricarica e basta */ }
  location.reload();
}
// Il via si da' subito se l'app e' appena partita (c'e' ancora il benvenuto) o se nessuno la sta guardando;
// altrimenti alla prossima volta che va in secondo piano: ricaricare sotto le dita di chi la usa no.
function nuovaCopia(sw) {
  inAttesa = sw;
  if (document.visibilityState !== 'visible' || Date.now() - (window.fitAvvio || 0) < 6000) sw.postMessage({ tipo: 'attiva' });
}

async function servizio() {
  const locale = location.hostname === 'localhost' || location.hostname === '127.0.0.1';
  if (!('serviceWorker' in navigator) || !(location.protocol === 'https:' || locale)) return;
  const sw = navigator.serviceWorker;
  const giaInstallata = !!sw.controller;
  sw.addEventListener('controllerchange', () => { if (giaInstallata) ricarica(); });
  try {
    const reg = await sw.register('sw.js');
    const segui = (nuovo) => nuovo?.addEventListener('statechange', () => { if (nuovo.state === 'installed' && giaInstallata) nuovaCopia(nuovo); });
    if (reg.waiting && giaInstallata) nuovaCopia(reg.waiting);
    // una copia che si stava gia' scaricando quando la pagina e' partita non fa piu' scattare "updatefound": va seguita da qui
    segui(reg.installing);
    reg.addEventListener('updatefound', () => segui(reg.installing));
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') reg.update().catch(() => {});
      else if (inAttesa) inAttesa.postMessage({ tipo: 'attiva' });
    });
    const pronto = await sw.ready;
    const immagini = [
      ...Object.values(P.ricette).filter((r) => r.img).map((r) => `img/food/${r.img}.jpg`),
      ...Object.keys(P.esercizi).flatMap((id) => [`img/ex/${id}-0.jpg`, `img/ex/${id}-1.jpg`]),
    ];
    pronto.active?.postMessage({ tipo: 'immagini', lista: [...new Set(immagini)] });
  } catch { /* senza service worker l'app funziona lo stesso, solo non senza rete */ }
}

async function avvia() {
  daApp();
  try {
    await carica();
  } catch (e) {
    if (e?.message === 'fuori') return;   // il server non conosce questo dispositivo: si sta andando alla pagina del codice
    app.replaceChildren(h('div', { class: 'splash' }, h('div', { class: 'vuoto' }, h('b', null, 'Non riesco a caricare il piano'), 'Controlla la connessione e riapri l\'app.',
      h('button', { class: 'btn', style: { marginTop: '14px' }, onclick: () => location.reload() }, 'Riprova'))));
    document.getElementById('benvenuto')?.remove();
    return;
  }
  caricaMisure();
  costruisciBarra();
  if (!location.hash || /^#k=/.test(location.hash)) history.replaceState(null, '', '#/oggi');   // #k= e' la chiave dell'icona sulla Home
  disegna(true);
  chiudiBenvenuto();
  ascolta(() => { disegna(); ridisegnaFogli(); });
  ascoltaSync(aggiornaSync);
  // le misure arrivano dal server anche mentre l'app e' aperta: non ridisegnare sotto le dita di chi sta scrivendo
  const staScrivendo = () => /^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement?.tagName || '');
  ascoltaMisure(() => { if (!staScrivendo()) { disegna(); ridisegnaFogli(); } });
  // dal telefono la bilancia passa dal PC di casa: quando si accende o si spegne cambia la scheda Progressi
  ascoltaSentinella(() => { if (!staScrivendo() && leggiRotta().nome === 'progressi') disegna(); });
  // l'app per PC aggiunge il ponte con la bilancia un attimo dopo il caricamento della pagina
  addEventListener('pywebviewready', () => { document.documentElement.classList.add('installata'); disegna(); });
  addEventListener('hashchange', () => disegna());
  // al rientro nell'app: riallinea con il server e, se nel frattempo e' cambiato giorno, ridisegna
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState !== 'visible') return;
    allinea();
    aggiornaMisure();
    controllaSentinella(true);
    if (giornoDisegnato !== oggi()) disegna();
  });
  addEventListener('online', () => { allinea(); aggiornaMisure(); });
  // l'app per PC resta aperta per ore: senza questo ripartirebbe da quello che sapeva al mattino
  addEventListener('focus', controllaNovita);
  setInterval(() => { if (document.visibilityState === 'visible') controllaNovita(); }, 45000);
  allinea();
  aggiornaMisure();
  // si chiede subito se il PC della bilancia c'e': aprendo Progressi «Pesati ora» e' gia' li', senza il pallino grigio
  controllaSentinella(true);
  servizio();
  // una risposta di FitAI rimasta da ritirare (l'app era stata chiusa mentre lavorava), le notifiche con gli orari di
  // adesso, e il tocco su una notifica di FitAI: apre la conversazione
  riprendiAssistente();
  allineaNotifiche();
  controllaApk();
  if (/[?&]apri=fitai\b/.test(location.search)) {
    history.replaceState(null, '', location.pathname + location.hash);
    setTimeout(() => apriAssistente(), 700);
  }
  navigator.serviceWorker?.addEventListener('message', (e) => { if (e.data?.tipo === 'notifica' && /apri=fitai/.test(e.data.dove || '')) apriAssistente(); });
  setTimeout(() => diagnosi('avvio'), 2500);   // dopo il benvenuto, quando la schermata e' quella vera
}

avvia();
