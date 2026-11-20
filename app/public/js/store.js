// Chi sta usando l'app, il suo piano (sola lettura) e il suo stato: salvato sul dispositivo e copiato sul server.

import { iso, daIso, oggi, giornoSett, piuGiorni, dec, intero } from './dom.js';
import { personalizza } from './personale.js';

const CHIAVE = 'fit.stato.v1';
const CHIAVE_IO = 'fit.io';
const CHIAVE_PIANO = 'fit.piano';
const REPARTI = ['Carne e pesce', 'Frigo', 'Frutta e verdura', 'Surgelati', 'Dispensa', 'Integratori'];

export let P = null;
export const S = {};
export const sync = { stato: 'locale', quando: 0 };
// L'account: lo dice il server (api/io) e resta scritto sul dispositivo, cosi' all'avvio l'app sa gia' di chi e'.
// bilancia = puo' pesarsi dal telefono con la bilancia di casa; ai = ha una chiave per l'intelligenza artificiale.
// ai: l'assistente e' acceso; motore: il servizio con la chiave che risponde per primo; fila: chi risponde, in ordine
export const io = { id: null, nome: '', capo: false, bilancia: false, ai: false, motore: null, fila: [], piano: false, esci: false };

let base = null;      // il catalogo, uguale per tutti (data/plan.json)
let mio = null;       // il piano scritto a mano per questo account, se c'e' (api/piano)
const ascoltatori = new Set();
const ascoltatoriSync = new Set();
let attesa = null;

// Le pesate non stanno piu' qui: hanno la loro tabella sul server (vedi misure.js).
// di = l'account a cui appartiene questo stato: il server rifiuta quello di un altro.
// profilo = quello che la persona ha detto di se' al primo avvio (views/profilo.js): i suoi numeri, cosa cerca, come
//           si muove. Chi non ha un piano scritto a mano lo riceve calcolato da qui (personale.js).
// opzioni.casa = quali pezzi vuole vedere nella schermata Oggi; opzioni.orari = a che ora mangia.
// giorni[d].extra = quello che hai mangiato fuori dal piano; ogni voce dice in `via` cosa del pasto previsto ha sostituito.
// attivita = camminate, corse e altro movimento fuori dalle schede: {id, d, tipo, min, km}.
// prodotti = i cibi gia' usati nel diario (per codice a barre o scritti a mano), per ritrovarli al volo.
// scansioni = gli ultimi prodotti guardati con lo scanner, con il voto che hanno preso.
// chat = la conversazione con l'assistente: {r: 'io' | 'ai', t, q, az: quello che ha fatto nell'app (vedi azioni.js)}.
// cambi[giorno della settimana][pasto] = la ricetta messa al posto di quella del piano.
// giorni[d].ricette[pasto] = la ricetta messa al posto di quella prevista solo quel giorno ("stasera non mi va").
// giorni[d].dosi[pasto][cibo] = i grammi veri di un ingrediente quel giorno; giorni[d].saltati[pasto] = gli ingredienti
// lasciati nel piatto di un pasto fatto (vedi impostaDosi e mangiatiSolo).
// mie =i piatti creati dalla persona (per esempio con l'assistente) e i cibi che non erano nel catalogo:
//       {ricette: {id: ricetta}, cibi: {id: cibo}}, fatti come quelli del piano. Gli identificativi cominciano con "mio-".
const nuovo = () => ({
  v: 1, updatedAt: 0, giorni: {}, cambi: {}, spesa: {}, sedute: [], attiva: null, attivita: [], prodotti: {}, scansioni: [], chat: [],
  mie: { ricette: {}, cibi: {} },
  opzioni: { suono: true },
});

function adotta(obj) {
  for (const k of Object.keys(S)) delete S[k];
  Object.assign(S, nuovo(), obj);
  if (!S.opzioni || typeof S.opzioni !== 'object') S.opzioni = { suono: true };
  if (!S.mie || typeof S.mie !== 'object') S.mie = { ricette: {}, cibi: {} };
  for (const k of ['ricette', 'cibi']) if (!S.mie[k] || typeof S.mie[k] !== 'object') S.mie[k] = {};
  for (const k of ['sedute', 'attivita', 'scansioni', 'chat']) if (!Array.isArray(S[k])) S[k] = [];
  if (io.id != null) S.di = io.id;
  for (const [d, g] of Object.entries(S.giorni || {})) {
    // la camminata era una spunta del giorno: oggi e' un'attivita' come le altre, con i suoi minuti
    if (g.camminata) {
      if (!S.attivita.some((a) => a.d === d && a.tipo === 'camminata')) S.attivita.push({ id: `c${d}`, d, tipo: 'camminata', min: 30 });
      delete g.camminata;
    }
    // la prima versione del diario segnava "al posto del pasto" per tutto il pasto: oggi lo dice ogni voce (via)
    if (!g.alPosto) continue;
    for (const [mom, si] of Object.entries(g.alPosto)) {
      const prima = si && (g.extra || []).find((e) => e.mom === mom);
      if (prima && !prima.via) prima.via = ['*'];
    }
    delete g.alPosto;
  }
  if (base) { componi(); fermaPasti(); }
}

function scrivi() {
  try { localStorage.setItem(CHIAVE, JSON.stringify(S)); } catch { /* memoria piena o navigazione privata */ }
}
const leggi = (chiave) => { try { return JSON.parse(localStorage.getItem(chiave) || 'null'); } catch { return null; } };
const metti = (chiave, valore) => { try { localStorage.setItem(chiave, JSON.stringify(valore)); } catch { /* pazienza */ } };

// ---------- piano ----------
const anni = (nascita) => {
  if (!nascita) return null;
  const [a, m, g] = nascita.split('-').map(Number);
  const o = new Date();
  return o.getFullYear() - a - (o.getMonth() + 1 < m || (o.getMonth() + 1 === m && o.getDate() < g) ? 1 : 0);
};

// Il profilo di chi ha un piano scritto a mano: quello del piano, con sopra quello che ha detto lui al primo avvio.
function profiloCon(delPiano, detto) {
  const peso = detto.peso ?? delPiano.pesoIniziale ?? 70;
  // I numeri che si sanno davvero. Dove mancano i conti usano un valore di mezzo, ma il primo avvio li deve chiedere:
  // non puo' proporre come gia' scritti un'eta' e un'altezza che nessuno ha mai detto.
  const noti = {
    sesso: detto.sesso || delPiano.sesso || null,
    eta: detto.eta ?? anni(delPiano.nascita) ?? delPiano.eta ?? null,
    altezza: detto.altezza ?? delPiano.altezza ?? null,
  };
  return {
    ...delPiano,
    nome: io.nome || delPiano.nome,
    sesso: noti.sesso || 'm',
    eta: noti.eta ?? 30,
    altezza: noti.altezza ?? 170,
    noti,
    pesoIniziale: delPiano.pesoIniziale ?? peso,
    pesoObiettivo: detto.pesoObiettivo ?? delPiano.pesoObiettivo ?? peso,
    obiettivo: detto.obiettivo || delPiano.obiettivo || null,
    dataInizio: delPiano.pesoIniziale != null ? delPiano.dataInizio : (detto.dal || delPiano.dataInizio || oggi()),
  };
}

// ---------- le modifiche della persona al suo piano (S.mie) ----------
// Tutto quello che del piano si puo' cambiare senza toccare il catalogo sta in S.mie, con la stessa forma del piano:
//   cibi.<id>, ricette.<id>, schede.<lettera>     si aggiungono a quelli del piano; con un identificativo che c'e' gia'
//                                                 ne cambiano solo i pezzi scritti (il resto resta quello del piano)
//   obiettivi {train, rest, acqua, camminataMin}  calorie e grammi dei due tipi di giorno, acqua, minuti di movimento
//   settimana.<giorno 0-6> {tipo, scheda, pasti, ob}   che giorno e', quale scheda, quali piatti (null = quel pasto
//                                                 quel giorno non c'e'), e l'obiettivo di quel giorno
//   momenti.<pasto> {n, ora: {rest, train}, tipo} nome e ora di un pasto; con una chiave nuova, un pasto in piu'
//   profilo {pesoObiettivo, note, preferenze...}  quello che il piano dice della persona
// Le scrive soprattutto l'assistente (azioni.js). Ogni pezzo viene controllato prima di entrare: uno sbagliato resta
// fuori e l'app continua a funzionare con il piano com'era, invece di rompersi a ogni apertura.
const numero = (v) => typeof v === 'number' && Number.isFinite(v);
const MACRO = ['kcal', 'p', 'c', 'f'];
const ciboBuono = (c) => !!c && typeof c.n === 'string' && !!c.n && MACRO.every((k) => numero(c[k]) && c[k] >= 0)
  && (c.pz == null || (numero(c.pz) && c.pz > 0 && Array.isArray(c.pzn) && c.pzn.length === 2));
const ricettaBuona = (r, cibi) => !!r && typeof r.n === 'string' && !!r.n && typeof r.tipo === 'string' && Array.isArray(r.passi)
  && (r.libero ? !!r.stima && MACRO.every((k) => numero(r.stima[k])) && Array.isArray(r.ing)
    : Array.isArray(r.ing) && r.ing.length > 0 && r.ing.every((x) => Array.isArray(x) && !!cibi[x[0]] && numero(x[1]) && numero(x[2]) && x[1] >= 0 && x[2] >= 0));
const schedaBuona = (sc, esercizi) => !!sc && typeof sc.n === 'string' && !!sc.n && Array.isArray(sc.es) && sc.es.length > 0
  && sc.es.every((e) => Array.isArray(e) && !!esercizi[e[0]] && numero(e[1]) && e[1] >= 1 && e[1] <= 12 && (typeof e[2] === 'string' || numero(e[2])) && numero(e[3]) && e[3] >= 0);
const macroBuoni = (o) => !!o && MACRO.every((k) => numero(o[k]) && o[k] > 0);
const oraBuona = (t) => t == null || t === '' || /^\d{1,2}:\d{2}$/.test(t);

function conLeMie(P0) {
  const mie = S.mie || {};
  if (!['cibi', 'ricette', 'schede', 'obiettivi', 'settimana', 'momenti', 'profilo'].some((k) => mie[k] && typeof mie[k] === 'object' && Object.keys(mie[k]).length)) return P0;
  try {
    const cibi = { ...P0.cibi };
    for (const [id, c] of Object.entries(mie.cibi || {})) {
      const x = { rep: 'Dispensa', ...(P0.cibi[id] || {}), ...c };
      if (ciboBuono(x)) cibi[id] = x;
    }
    // niente senza foto: un piatto nuovo che non ne ha prende quella di uno dello stesso tipo
    const conFoto = (tipo) => Object.values(P0.ricette).find((x) => x.tipo === tipo && (x.img || x.foto)) || Object.values(P0.ricette).find((x) => x.img || x.foto);
    const ricette = { ...P0.ricette };
    for (const [id, r] of Object.entries(mie.ricette || {})) {
      const prima = P0.ricette[id];
      const x = { passi: [], come: 'Ricetta tua', min: 15, ...(prima || {}), ...r };
      if (!ricettaBuona(x, cibi)) continue;
      if (!x.img && !x.foto) { const f = conFoto(x.tipo); if (f?.img) x.img = f.img; else if (f?.foto) x.foto = f.foto; }
      ricette[id] = prima ? { ...x, modificata: true } : { ...x, mia: true };
    }
    const schede = { ...P0.schede };
    for (const [w, sc] of Object.entries(mie.schede || {})) {
      const x = { fuoco: '', durata: 60, ...(P0.schede[w] || {}), ...sc };
      if (schedaBuona(x, P0.esercizi)) schede[w] = x;
    }
    const om = mie.obiettivi || {};
    const obiettivi = { ...P0.obiettivi };
    for (const t of ['train', 'rest']) {
      const x = { ...P0.obiettivi[t], ...(om[t] || {}) };
      if (macroBuoni(x)) obiettivi[t] = x;
    }
    const acqua = { ...(P0.obiettivi.acqua || {}), ...(om.acqua || {}) };
    if (['rest', 'train'].every((k) => acqua[k] == null || (numero(acqua[k]) && acqua[k] >= 500 && acqua[k] <= 8000))) obiettivi.acqua = acqua;
    if (numero(om.camminataMin) && om.camminataMin >= 5 && om.camminataMin <= 240) obiettivi.camminataMin = om.camminataMin;
    // un pasto con una chiave nuova e' un pasto in piu': entra tra gli altri al posto giusto, in ordine di ora
    let momenti = { ...P0.momenti };
    let nuovi = false;
    for (const [mom, m] of Object.entries(mie.momenti || {})) {
      const prima = P0.momenti[mom];
      const x = { ...(prima || {}), ...m, ora: { ...(prima?.ora || {}), ...(m?.ora || {}) } };
      if (typeof x.n !== 'string' || !x.n || typeof x.tipo !== 'string' || !oraBuona(x.ora.rest) || !oraBuona(x.ora.train)) continue;
      if (x.ora.train === undefined) x.ora.train = x.ora.rest ?? null;
      if (x.ora.rest === undefined) x.ora.rest = x.ora.train ?? null;
      momenti[mom] = x;
      nuovi = nuovi || !prima;
    }
    if (nuovi) {
      // l'ora dei giorni di palestra per prima: e' li' che ci sono tutti i pasti, shake compreso, nell'ordine giusto
      const quando = (m) => { const t = m.ora.train || m.ora.rest; return t ? t.padStart(5, '0') : '99'; };
      momenti = Object.fromEntries(Object.entries(momenti).sort((a, b) => quando(a[1]).localeCompare(quando(b[1]))));
    }
    // se l'obiettivo di un tipo di giorno e' stato cambiato vale quello, non piu' quello scritto giorno per giorno
    const cambiati = ['train', 'rest'].filter((t) => om[t] && macroBuoni(obiettivi[t]));
    const settimana = P0.settimana.map((g, wd) => {
      const m = mie.settimana?.[wd] || {};
      const x = { ...g, pasti: { ...g.pasti } };
      if (m.tipo === 'train' || m.tipo === 'rest') x.tipo = m.tipo;
      if (typeof m.scheda === 'string' && schede[m.scheda] && !schede[m.scheda].casa) x.scheda = m.scheda;
      for (const [mom, rid] of Object.entries(m.pasti || {})) {
        if (rid === null) delete x.pasti[mom];
        else if (momenti[mom] && ricette[rid] && ricette[rid].tipo === momenti[mom].tipo) x.pasti[mom] = rid;
      }
      if (macroBuoni(m.ob)) x.ob = { ...m.ob }; else if (cambiati.includes(x.tipo)) delete x.ob;
      return x;
    });
    const profilo = { ...P0.profilo };
    for (const k of ['pesoObiettivo', 'pesoIniziale', 'dataInizio', 'note', 'preferenze', 'creatina', 'altezza', 'eta', 'lattosio']) {
      if (mie.profilo && mie.profilo[k] != null) profilo[k] = mie.profilo[k];
    }
    return { ...P0, cibi, ricette, schede, obiettivi, momenti, settimana, profilo };
  } catch {
    return P0;   // qualcosa li' dentro non torna: si usa il piano com'era
  }
}

// Chi ha un piano scritto a mano usa quello sopra al catalogo; gli altri ne hanno uno calcolato dalle loro risposte.
// Finche' le risposte non ci sono (account appena creato) il piano e' quello tipo, e l'app fa le domande.
function componi() {
  const detto = S.profilo || {};
  if (mio?.settimana) {
    const aCasa = Object.fromEntries(Object.entries(base.schede).filter(([, sc]) => sc.casa));
    // la dieta scritta in due forme (vedi menuDelPiano): vale quella scelta alla prima apertura, con i suoi obiettivi
    const fisso = !!mio.settimanaFissa && S.opzioni.menu === 'fisso';
    P = {
      ...base, ...mio,
      settimana: fisso ? mio.settimanaFissa : mio.settimana,
      obiettivi: fisso ? { ...mio.obiettivi, ...(mio.obiettiviFissi || {}) } : (mio.obiettivi || base.obiettivi),
      cibi: { ...base.cibi, ...(mio.cibi || {}) },
      // chi ha le sue ricette vede solo quelle: le alternative di un pasto devono venire dalla sua dieta, non dal catalogo
      ricette: mio.ricette ? { shake: base.ricette.shake, ...mio.ricette } : base.ricette,
      momenti: mio.momenti || base.momenti,
      // le schede: le sue se le ha, altrimenti quelle del catalogo. Il circuito a casa c'e' per tutti.
      schede: mio.schede ? { ...mio.schede, ...aCasa } : base.schede,
      profilo: profiloCon(mio.profilo, detto),
    };
  } else if (detto.fatto && detto.obiettivo) {
    P = personalizza(base, { ...detto, nome: io.nome, allena: S.opzioni.allena ?? detto.allena });
  } else {
    P = { ...base, puntiCarenti: [], guida: [], profilo: { nome: io.nome, sesso: 'm', eta: 30, altezza: 170, pesoIniziale: 70, pesoObiettivo: 70, dataInizio: oggi(), generato: true } };
  }
  // sopra al piano, qualunque sia, vanno le modifiche che la persona gli ha fatto (S.mie)
  P = conLeMie(P);
  // il sesso serve alla schermata di benvenuto ("Bentornata") prima ancora che l'app sia partita
  if (io.id != null && io.sesso !== P.profilo.sesso) { io.sesso = P.profilo.sesso; metti(CHIAVE_IO, io); }
}

// Il piano e' scritto a mano (dal capo, o da un nutrizionista) oppure calcolato dalle risposte?
export const pianoScritto = () => !!mio?.settimana;
// Certe diete sono scritte come un giorno solo con le alternative: il piano allora porta due settimane, quella che
// gira tra le alternative ("giro") e lo schema ripetuto cosi' com'e' ("fisso"), e i testi per chiedere quale si
// preferisce: {testo, giro: [titolo, sotto], fisso: [titolo, sotto]}. Null per chi ha una forma sola.
export const menuDelPiano = () => (mio?.settimanaFissa ? mio.menu || {} : null);
// An owner with an imported plan already has a profile.
export const serveProfilo = () => (!io.capo || !io.piano) && !S.profilo?.fatto;

// Salva le risposte del primo avvio (o di "Cambia i miei dati"). `casa` e `orari` finiscono nelle opzioni, dove si
// possono ritoccare una per una dalla scheda Piano.
export function salvaProfilo(pr, { casa = null, orari = null, menu = null } = {}) {
  aggiorna((s) => {
    const prima = s.profilo || {};
    s.profilo = { ...pr, fatto: true };
    s.opzioni.allena = pr.allena !== false;
    if (casa) s.opzioni.casa = { ...casa };
    if (orari) s.opzioni.orari = { ...orari };
    // passando dal menu che gira allo schema fisso (o viceversa) i piatti dei giorni cambiano: le sostituzioni fatte prima no
    if (menu && menu !== (s.opzioni.menu || 'giro')) s.cambi = {};
    if (menu) s.opzioni.menu = menu;
    // se cambiano obiettivo o cibi esclusi il piano calcolato cambia: le sostituzioni di prima non hanno piu' senso
    if (!mio?.settimana && (prima.obiettivo !== pr.obiettivo || String(prima.esclusi) !== String(pr.esclusi))) s.cambi = {};
  }, true);
  componi();
  avvisa();
}

// I pezzi della schermata Oggi che la persona puo' accendere e spegnere. Chi non ha mai scelto li vede tutti.
export const CASA = {
  numeri: ['Calorie e proteine', 'Il conto di quello che mangi, con l\'anello e le barre'],
  acqua: ['Acqua', 'Quanta ne hai bevuta e quanta te ne manca'],
  peso: ['Peso', 'L\'ultima pesata, e un promemoria quando è ora di rifarla'],
  movimento: ['Movimento', 'La seduta di oggi, le camminate, i minuti della settimana'],
  consiglio: ['Consiglio del giorno', 'Una riga al giorno presa dal tuo piano'],
};
// Cambia la forma della dieta (vedi menuDelPiano) senza rifare le domande. Le sostituzioni fatte nell'altra forma non valgono piu'.
export function scegliMenu(forma) {
  if ((S.opzioni.menu || 'giro') === forma) return;
  aggiorna((s) => { s.opzioni.menu = forma; s.cambi = {}; }, true);
  componi();
  avvisa();
}
export const vuole = (pezzo) => S.opzioni.casa?.[pezzo] !== false;
export function scegliCasa(pezzo, si) { aggiorna((s) => { s.opzioni.casa = { ...(s.opzioni.casa || {}), [pezzo]: !!si }; }); }

// Vai alla pagina che chiede il codice: il server non riconosce (piu') questo dispositivo.
function alCodice() {
  if (navigator.onLine === false || alCodice.fatto) return;
  alCodice.fatto = true;
  location.replace('accedi');
}

// Cancella dal dispositivo tutto quello che e' di un account: serve quando si esce o ne entra un altro.
function dimentica() {
  try { for (const k of [CHIAVE, CHIAVE_PIANO, 'fit.misure.v1']) localStorage.removeItem(k); } catch { /* niente da fare */ }
  mio = null;
}

async function chiSono() {
  const r = await fetch('api/io', { cache: 'no-store' });
  if (r.status === 401) { alCodice(); throw new Error('fuori'); }
  if (!r.ok) throw new Error(String(r.status));
  return r.json();
}

// Mette in `io` quello che dice il server. Restituisce true se sul dispositivo c'erano i dati di un altro account.
function riconosci(nuovoIo) {
  const cambiato = io.id != null && (io.id !== nuovoIo.id || (io.utente && io.utente !== nuovoIo.utente));
  // uno stato senza proprietario e' di prima degli account: era del capo, e a chiunque altro non va mostrato
  const orfano = io.id == null && nuovoIo.id !== 1 && (S.updatedAt || 0) > 0 && S.di == null;
  if (cambiato || orfano) { dimentica(); adotta({}); }
  Object.assign(io, nuovoIo);
  metti(CHIAVE_IO, io);
  S.di = io.id;
  return cambiato || orfano;
}

async function prendiPiano() {
  if (!io.piano) { mio = null; try { localStorage.removeItem(CHIAVE_PIANO); } catch { /* niente */ } return; }
  const r = await fetch('api/piano', { cache: 'no-store' });
  if (!r.ok) throw new Error(String(r.status));
  const j = await r.json();
  if (j?.settimana) { mio = j; metti(CHIAVE_PIANO, j); }
}

// Avvio. Se il dispositivo conosce gia' l'account parte subito da quello che ha in memoria e sente il server dopo,
// in sottofondo; la prima volta invece deve aspettarlo, perche' non sa ancora di chi e'.
export async function carica() {
  const r = await fetch('data/plan.json', { cache: 'no-cache' });
  if (!r.ok) throw new Error('piano non disponibile');
  base = await r.json();
  Object.assign(io, leggi(CHIAVE_IO) || {});
  mio = leggi(CHIAVE_PIANO);
  const salvato = leggi(CHIAVE);
  const pronto = io.id != null && (!io.piano || mio?.settimana);
  adotta(pronto && salvato && (salvato.di == null || salvato.di === io.id) ? salvato : {});
  // tiene solo gli ultimi sei mesi di spunte giornaliere
  const limite = piuGiorni(oggi(), -180);
  for (const d of Object.keys(S.giorni)) if (d < limite) delete S.giorni[d];

  const dalServer = async () => {
    const attese = io.attese || 0, bilancia = !!io.bilancia;
    const cambiato = riconosci(await chiSono());
    const versione = mio?.versione;
    await prendiPiano().catch(() => {});
    componi();
    if (!pronto || cambiato) {
      // quello che c'era sul dispositivo vale solo se e' di questo account (o e' di prima degli account, e questo e' il capo)
      const locale = !cambiato && salvato && (salvato.di === io.id || (salvato.di == null && io.id === 1)) ? salvato : null;
      const stato = await fetch('api/state', { cache: 'no-store' });
      const remoto = stato.ok ? await stato.json() : {};
      const vince = (locale?.updatedAt || 0) > (remoto.updatedAt || 0) ? locale : remoto;
      if (vince.updatedAt) { adotta(vince); scrivi(); }
    }
    // (se sul dispositivo mancava che la bilancia e' sua, Progressi va ridisegnato con il pallino e «Pesati ora»)
    return cambiato || mio?.versione !== versione || (io.attese || 0) !== attese || !!io.bilancia !== bilancia;
  };
  if (pronto) dalServer().then((daRidisegnare) => { if (daRidisegnare) avvisa(); }).catch(() => {});
  else await dalServer();
  return P;
}

// Esce da questo dispositivo: il server spegne il cookie e qui non resta niente dell'account.
export async function esci() {
  // senza la conferma del server il cookie resterebbe valido: meglio dirlo che far finta di essere usciti
  const r = await fetch('api/esci', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
  if (!r.ok) throw new Error('Il server non ha risposto bene');
  // entrati con EverID: il server dice dove chiudere anche quella sessione (poi EverID riporta alla pagina d'accesso)
  const j = await r.json().catch(() => ({}));
  dimentica();
  try { localStorage.removeItem(CHIAVE_IO); } catch { /* niente */ }
  location.replace(typeof j.dove === 'String' && j.dove.startsWith('https://') ? j.dove : 'accedi');
}

export async function rinomina(nome) {
  const r = await fetch('api/io', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ nome }) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.errore || 'Non riesco a cambiare il nome');
  io.nome = j.nome;
  metti(CHIAVE_IO, io);
  componi();
  avvisa();
}

// Dopo aver messo o tolto la chiave dell'AI: l'assistente e le foto si accendono o si spengono subito.
export function aggiornaIo(pezzi) {
  Object.assign(io, pezzi);
  metti(CHIAVE_IO, io);
  avvisa();
}

export function ascolta(fn) { ascoltatori.add(fn); return () => ascoltatori.delete(fn); }
function avvisa() { for (const fn of ascoltatori) fn(); }
// Lo stato della copia sul server cambia spesso: avvisa a parte, senza ridisegnare tutto (toglierebbe il fuoco ai campi).
export function ascoltaSync(fn) { ascoltatoriSync.add(fn); return () => ascoltatoriSync.delete(fn); }
function avvisaSync() { for (const fn of ascoltatoriSync) fn(); }

// Ogni modifica passa di qui. `zitto` salva senza ridisegnare (per i campi mentre si scrive).
export function aggiorna(fn, zitto = false) {
  const prima = tipiDeiGiorni();
  fn(S);
  fermaPasti(prima);   // i pasti gia' segnati tengono il tipo di giorno che avevano
  S.updatedAt = Date.now();
  scrivi();
  if (!zitto) avvisa();
  clearTimeout(attesa);
  attesa = setTimeout(spingi, 1500);
}

// ---------- sincronizzazione ----------
async function spingi() {
  try {
    const r = await fetch('api/state', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(S) });
    if (r.status === 409) {
      const j = await r.json();
      if (j.stato) { adotta(j.stato); scrivi(); avvisa(); }
    } else if (!r.ok) throw new Error(String(r.status));
    sync.stato = 'ok'; sync.quando = Date.now();
  } catch {
    sync.stato = navigator.onLine === false ? 'offline' : 'assente';
  }
  avvisaSync();
}

export async function allinea() {
  try {
    const r = await fetch('api/state', { cache: 'no-store' });
    // il server non riconosce piu' questo dispositivo: si va alla pagina che chiede il codice
    if (r.status === 401) { alCodice(); return; }
    if (!r.ok) throw new Error(String(r.status));
    const remoto = await r.json();
    if ((remoto.updatedAt || 0) > (S.updatedAt || 0)) { adotta(remoto); scrivi(); avvisa(); }
    // adesso questa copia e' la piu' fresca: se nel frattempo e' cambiato giorno, quelli passati si chiudono
    // (i giorni di palestra lasciati su "Gym" contano come fatti). E' una modifica come le altre: parte qui sotto.
    if (chiudiPresenze()) { S.updatedAt = Date.now(); scrivi(); avvisa(); }
    if ((S.updatedAt || 0) > (remoto.updatedAt || 0)) return spingi();
    sync.stato = 'ok'; sync.quando = Date.now();
  } catch {
    sync.stato = navigator.onLine === false ? 'offline' : 'assente';
  }
  avvisaSync();
}

// Telefono e PC lavorano sullo stesso stato: mentre l'app e' aperta si chiede ogni tanto al server se l'altro
// ha cambiato qualcosa, cosi' non si riparte da una copia vecchia (che al primo tocco coprirebbe quella nuova).
export async function controllaNovita() {
  try {
    const r = await fetch('api/state/versione', { cache: 'no-store' });
    if (r.ok && ((await r.json()).updatedAt || 0) > (S.updatedAt || 0)) await allinea();
  } catch { /* senza rete si riprova al giro dopo */ }
}

export const esporta = () => JSON.stringify(S, null, 1);
export function importa(obj) {
  if (!obj || typeof obj !== 'object' || !Array.isArray(obj.sedute) || typeof obj.giorni !== 'object') throw new Error('file non valido');
  adotta({ ...obj, di: io.id });
  aggiorna(() => {});
}
// Azzera spunte, diario e sedute; il profilo resta, altrimenti l'app richiederebbe tutto da capo.
export function azzera() { adotta({ profilo: S.profilo, opzioni: S.opzioni }); aggiorna(() => {}); }

// ---------- dieta ----------
// "Non mi alleno": ogni giorno e' di riposo, niente shake, e la sezione Gym diventa quella del movimento libero.
export const siAllena = () => (S.opzioni.allena ?? S.profilo?.allena ?? (P.profilo.allena !== false));
export function impostaAllena(si) {
  aggiorna((s) => { s.opzioni.allena = !!si; }, true);
  componi();
  avvisa();
}
// Di che tipo e' un giorno. Chi ha scelto i suoi giorni di allenamento vale quelli, anche sopra un piano scritto a mano
// (i pasti restano quelli del giorno, cambia solo quando cade la seduta).
export const tipoModello = (d) => {
  if (!siAllena()) return 'rest';
  const wd = giornoSett(daIso(d));
  const miei = mio?.settimana ? S.profilo?.giorni : null;
  return miei?.length ? (miei.includes(wd) ? 'train' : 'rest') : P.settimana[wd].tipo;
};
// Le calorie e i grammi di oggi: quelli scritti per quel giorno della settimana se il piano li ha, altrimenti quelli del tipo di giorno.
export const obDelGiorno = (d) => P.settimana[giornoSett(daIso(d))].ob || P.obiettivi[tipoGiorno(d)];

// A che ora cade un pasto: quella del piano, oppure quella che la persona ha detto di tenere (colazione, pranzo e cena;
// gli spuntini finiscono a meta' strada).
const inMinuti = (t) => { const [h, m] = String(t).split(':').map(Number); return h * 60 + (m || 0); };
const inOra = (min) => `${String(Math.floor(min / 60) % 24).padStart(2, '0')}:${String(Math.round(min % 60)).padStart(2, '0')}`;
function oraDelPasto(mom, info, tipo) {
  const base = info.ora[tipo] ?? info.ora.train;
  const o = S.opzioni.orari;
  if (!o || base === '' || base == null) return base;
  const c = inMinuti(o.colazione || '08:00'), p = inMinuti(o.pranzo || '13:00'), e = inMinuti(o.cena || '20:30');
  const meta = (a, b) => inOra(Math.round((a + b) / 2 / 15) * 15);
  if (mom === 'colazione' || info.con === 'colazione') return inOra(c);
  if (mom === 'pranzo') return inOra(p);
  if (mom === 'cena') return inOra(e);
  if (mom === 'spuntino') return meta(c, p);
  if (mom === 'merenda') return tipo === 'train' && !mio?.settimana ? inOra(Math.max(p + 120, e - 225)) : meta(p, e);
  if (mom === 'post') return inOra(e - 45);
  if (mom === 'sera') return inOra(e + 90);
  return base;
}
export const tipoGiorno = (d) => (siAllena() && S.giorni[d]?.tipo) || tipoModello(d);

export function giorno(d) {
  if (!S.giorni[d]) S.giorni[d] = { pasti: {} };
  if (!S.giorni[d].pasti) S.giorni[d].pasti = {};
  return S.giorni[d];
}

// `tolti` = ingredienti che quel giorno non hai mangiato (sostituiti con altro nel diario, o lasciati nel piatto).
// `dosi` = i grammi veri di quel giorno, ingrediente per ingrediente, al posto di quelli del piano (giorni[d].dosi).
export function macro(rid, tipo, tolti = null, dosi = null) {
  const r = P.ricette[rid];
  if (r.libero) return { ...r.stima };
  const i = tipo === 'train' ? 2 : 1;
  const t = { kcal: 0, p: 0, c: 0, f: 0 };
  for (const ing of r.ing) {
    if (tolti?.has(ing[0])) continue;
    const cibo = P.cibi[ing[0]];
    const g = dosi?.[ing[0]] ?? ing[i];
    for (const k in t) t[k] += cibo[k] * g / 100;
  }
  return t;
}

export function quantita(cibo, g) {
  if (cibo.pz) {
    const n = Math.round((g / cibo.pz) * 2) / 2;
    return `${dec(n)} ${cibo.pzn[n === 1 ? 0 : 1]}`;
  }
  return `${intero(g)} g`;
}

// `g` sono i grammi di quel giorno, `piano` quelli del piano: diversi quando quel giorno li hai cambiati (dosi).
export function ingredienti(rid, tipo, dosi = null) {
  const i = tipo === 'train' ? 2 : 1;
  return P.ricette[rid].ing.filter((x) => x[i] > 0 || dosi?.[x[0]] > 0).map((x) => {
    const cibo = P.cibi[x[0]];
    const g = dosi?.[x[0]] ?? x[i];
    return { id: x[0], n: cibo.n, g, piano: x[i], cambiato: g !== x[i], q: quantita(cibo, g), nota: cibo.nota, pz: !!cibo.pz, kcal: cibo.kcal * g / 100 };
  });
}

function ricettaDi(wd, mom, tipo) {
  // lo shake dopo l'allenamento c'e' solo per chi usa le proteine in polvere
  if (mom === 'post') return tipo === 'train' && P.profilo.shake !== false ? 'shake' : null;
  const scelta = S.cambi[wd]?.[mom];
  return (scelta && P.ricette[scelta] ? scelta : P.settimana[wd].pasti[mom]) || null;
}
// Il piatto cambiato solo per quel giorno (giorni[d].ricette), se c'e' ancora: vince sul cambio della settimana e sul piano.
const soloQuelGiorno = (d, mom) => {
  const rid = mom !== 'post' ? S.giorni[d]?.ricette?.[mom] : null;
  return rid && P.ricette[rid] ? rid : null;
};

export const FUORI_PASTO = 'fuori';
export const sommaVoci = (voci) => voci.reduce((t, e) => { for (const k in t) t[k] += e[k] || 0; return t; }, { kcal: 0, p: 0, c: 0, f: 0 });

// ---------- un pasto segnato non cambia piu' ----------
// Palestra o riposo decide i grammi di un piatto (le due colonne della ricetta) e se c'e' lo shake. Un pasto gia'
// segnato tiene il tipo di giorno di quando l'hai segnato (giorni[d].tipi[pasto]): se poi metti Riposo, o cambiano i
// giorni di allenamento, cambiano l'obiettivo e i pasti ancora da fare, non quello che hai gia' mangiato ("ho segnato
// il pranzo, poi ho messo Riposo e il riso e' sceso da 85 a 75 g").
// Toccato = spuntato, oppure con una voce del diario al posto di tutto il pasto o di una parte.
const toccato = (g, mom) => !!g?.pasti?.[mom] || (g?.extra || []).some((e) => e?.mom === mom && e.via?.length > 0);
const tipoBuono = (t) => t === 'train' || t === 'rest';
const tipoDelPasto = (g, mom, delGiorno) => (toccato(g, mom) && tipoBuono(g.tipi?.[mom]) ? g.tipi[mom] : delGiorno);
const tipiDeiGiorni = () => (P?.settimana ? Object.fromEntries(Object.keys(S.giorni || {}).map((d) => [d, tipoGiorno(d)])) : null);
// Scrive il tipo nei pasti toccati che non l'hanno ancora e lo toglie a quelli tornati da fare. Gira dopo ogni modifica
// (aggiorna, modificaStato) e quando arrivano dati da fuori (adotta). `prima` = il tipo dei giorni prima della modifica:
// un pasto segnato senza tipo (da un'app vecchia, o scritto da fuori) prende quello di prima.
function fermaPasti(prima = null) {
  if (!P?.momenti || !P?.settimana) return;
  for (const [d, g] of Object.entries(S.giorni || {})) {
    if (!g || typeof g !== 'object') continue;
    const allora = prima?.[d] || tipoGiorno(d);
    const tipi = {};
    for (const mom of Object.keys(P.momenti)) if (toccato(g, mom)) tipi[mom] = tipoBuono(g.tipi?.[mom]) ? g.tipi[mom] : allora;
    if (Object.keys(tipi).length) g.tipi = tipi; else delete g.tipi;
  }
}

export function pastiDelGiorno(d) {
  const wd = giornoSett(daIso(d));
  const delGiorno = tipoGiorno(d);
  const g = S.giorni[d] || {};
  const fatti = g.pasti || {};
  const lista = [];
  for (const [mom, info] of Object.entries(P.momenti)) {
    // il tipo di giorno di questo pasto: quello di quando l'hai segnato, se e' gia' segnato (vedi fermaPasti)
    const tipo = tipoDelPasto(g, mom, delGiorno);
    const solo = ricettaDi(wd, mom, tipo) ? soloQuelGiorno(d, mom) : null;
    const rid = solo || ricettaDi(wd, mom, tipo);
    if (!rid || !P.ricette[rid]) continue;
    const extra = (g.extra || []).filter((e) => e.mom === mom);
    // ogni voce del diario dice cosa ha sostituito: '*' = tutto il pasto, altrimenti gli ingredienti
    const tolti = new Set(extra.flatMap((e) => e.via || []));
    // i grammi di quel giorno (dosi) e gli ingredienti lasciati nel piatto (saltati, solo per un pasto fatto)
    const dosi = g.dosi?.[mom] || null;
    const saltati = new Set(fatti[mom] ? (g.saltati?.[mom] || []).filter((id) => !tolti.has(id)) : []);
    const previsti = ingredienti(rid, tipo, dosi);
    const alPosto = tolti.has('*') || (previsti.length > 0 && previsti.every((x) => tolti.has(x.id)));
    lista.push({
      mom, rid, tipo, r: P.ricette[rid], nome: info.n, ora: oraDelPasto(mom, info, tipo), con: info.con || null,
      fatto: !!fatti[mom], cambiato: !!solo || !!S.cambi[wd]?.[mom], soloOggi: !!solo,
      m: macro(rid, tipo, new Set([...tolti, ...saltati]), dosi), intero: macro(rid, tipo, null, dosi),
      extra, alPosto, tolti, senza: alPosto ? [] : previsti.filter((x) => tolti.has(x.id)),
      dosi, saltati, lasciati: alPosto ? [] : previsti.filter((x) => saltati.has(x.id)),
      presi: alPosto || !fatti[mom] ? [] : previsti.filter((x) => !tolti.has(x.id) && !saltati.has(x.id)),
      ritoccati: previsti.filter((x) => x.cambiato && !tolti.has(x.id)),
    });
  }
  return lista;
}

// Quello che hai mangiato senza un pasto a cui attaccarlo (o in un momento che oggi non c'e').
export function fuoriPasto(d) {
  const presenti = new Set(pastiDelGiorno(d).map((x) => x.mom));
  return (S.giorni[d]?.extra || []).filter((e) => !presenti.has(e.mom));
}

export function totali(d) {
  const tipo = tipoGiorno(d);
  const piano = { kcal: 0, p: 0, c: 0, f: 0 };
  const fatto = { kcal: 0, p: 0, c: 0, f: 0 };
  let n = 0, nFatti = 0;
  for (const x of pastiDelGiorno(d)) {
    n++;
    for (const k in piano) piano[k] += x.intero[k];
    // un pasto sostituito conta come fatto, ma i suoi numeri sono quelli di cio' che hai mangiato davvero
    if (x.alPosto) nFatti++;
    else if (x.fatto) { nFatti++; for (const k in fatto) fatto[k] += x.m[k]; }
  }
  const extra = sommaVoci(S.giorni[d]?.extra || []);
  for (const k in fatto) fatto[k] += extra[k];
  return { tipo, ob: obDelGiorno(d), piano, fatto, n, nFatti, extra };
}

// ---------- diario: quello che mangi fuori dal piano ----------
// `via` = cosa del pasto previsto non hai mangiato per far posto a questa voce:
// [] niente (e' in piu'), ['*'] tutto il pasto, oppure gli ingredienti, per esempio ['riso', 'pomodorini'].
export function aggiungiExtra(d, mom, voce, via = []) {
  const id = Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
  aggiorna(() => {
    const g = giorno(d);
    g.extra = g.extra || [];
    const nuova = { id, mom, ...voce };
    if (mom !== FUORI_PASTO && via.length) {
      nuova.via = [...via];
      // hai cambiato solo una parte del pasto: il resto lo stai mangiando, quindi il pasto risulta fatto
      if (!via.includes('*')) g.pasti[mom] = true;
    }
    g.extra.push(nuova);
  });
  return id;   // serve a chi poi la vuole togliere (l'assistente, quando si annulla)
}

// Togliendo una voce torna nel piano quello che aveva sostituito.
export function togliExtra(d, id) {
  aggiorna(() => {
    const g = giorno(d);
    g.extra = (g.extra || []).filter((e) => e.id !== id);
  });
}

// Cambia una voce del diario dov'e' (stessa voce, non una nuova): `campi` sono quelli che cambiano. Restituisce com'era.
export function cambiaVoce(d, id, campi) {
  const prima = (S.giorni[d]?.extra || []).find((e) => e.id === id);
  if (!prima) return null;
  const copia = { ...prima };
  aggiorna(() => { Object.assign(giorno(d).extra.find((e) => e.id === id), campi); });
  return copia;
}
export function rimettiVoce(d, prima) {
  aggiorna(() => {
    const g = giorno(d);
    const i = (g.extra || []).findIndex((e) => e.id === prima.id);
    if (i >= 0) g.extra[i] = { ...prima };
  });
}

// La quantita' di una voce come numero e unita': "17 g" -> {n: 17, u: 'g'}, "2 gallette" -> {n: 2, u: 'gallette'}.
// Senza numero (una voce scritta a mano senza quantita') vale come una porzione.
export function quantitaVoce(e) {
  if (numero(e?.g) && e.g > 0) return { n: e.g, u: 'g' };
  const m = String(e?.q || '').trim().match(/^(\d+(?:[.,]\d+)?)\s*(.*)$/);
  const n = m ? parseFloat(m[1].replace(',', '.')) : 0;
  return n > 0 ? { n, u: m[2].trim() || 'porzione' } : { n: 1, u: 'porzione' };
}
// "1 galletta" e "2 gallette": la parola dell'unita' segue il numero (le forme piu' comuni; le altre restano come sono)
function unitaPer(n, u) {
  if (u === 'g' || u === 'ml') return u;
  const [prima, ...resto] = u.split(' ');
  const uno = n === 1;
  let p = prima;
  if (uno) p = p === 'uova' ? 'uovo' : p.replace(/e$/, 'a').replace(/i$/, 'o');
  else p = p === 'uovo' ? 'uova' : p.replace(/a$/, 'e').replace(/o$/, 'i');
  return [p, ...resto].join(' ');
}
// I campi di una voce portata a `n` (nella sua unita'): i valori crescono o calano in proporzione.
export function vocePer(e, n) {
  const base = quantitaVoce(e);
  const k = n / base.n;
  const una = (v) => Math.round((v || 0) * k * 10) / 10;
  const q = base.u === 'g' ? `${dec(n)} g` : `${dec(n)} ${unitaPer(n, base.u)}`;
  return { q, g: base.u === 'g' ? n : (numero(e.g) ? Math.round(e.g * k) : e.g ?? null), kcal: Math.round((e.kcal || 0) * k), p: una(e.p), c: una(e.c), f: una(e.f) };
}

// ---------- un pasto, ingrediente per ingrediente ----------
// giorni[d].dosi[pasto][cibo] = i grammi veri di quel giorno ("oggi di pollo ne ho messi 137"): l'ingrediente resta nel
// piatto, cambiano solo i suoi grammi. giorni[d].saltati[pasto] = gli ingredienti che hai lasciato nel piatto: il pasto
// e' fatto, ma conta solo il resto ("ho mangiato solo la pasta").
// `nuove` = {cibo: grammi, oppure null per tornare a quelli del piano}. Restituisce le dosi di prima di quel pasto.
export function impostaDosi(d, mom, nuove) {
  const prima = { ...(S.giorni[d]?.dosi?.[mom] || {}) };
  aggiorna(() => {
    const g = giorno(d);
    const qui = { ...(g.dosi?.[mom] || {}) };
    for (const [cibo, grammi] of Object.entries(nuove)) {
      if (grammi == null) delete qui[cibo]; else qui[cibo] = grammi;
    }
    mettiPerPasto(g, 'dosi', mom, Object.keys(qui).length ? qui : null);
  });
  return prima;
}
export function rimettiDosi(d, mom, prima) {
  aggiorna(() => { mettiPerPasto(giorno(d), 'dosi', mom, prima && Object.keys(prima).length ? { ...prima } : null); });
}
// Segna un pasto: fatto (con `saltati` gli ingredienti lasciati, vuoto = mangiato tutto) o non fatto. Restituisce com'era.
export function mangiatiSolo(d, mom, saltati = null, fatto = true) {
  const g0 = S.giorni[d] || {};
  const prima = { fatto: !!g0.pasti?.[mom], saltati: [...(g0.saltati?.[mom] || [])] };
  aggiorna(() => {
    const g = giorno(d);
    g.pasti[mom] = !!fatto;
    const lista = fatto ? [...new Set(saltati || [])] : [];
    mettiPerPasto(g, 'saltati', mom, lista.length ? lista : null);
  });
  return prima;
}
// giorni[d][chiave][pasto] = valore, senza lasciare in giro oggetti vuoti
function mettiPerPasto(g, chiave, mom, valore) {
  const tutti = { ...(g[chiave] || {}) };
  if (valore == null) delete tutti[mom]; else tutti[mom] = valore;
  if (Object.keys(tutti).length) g[chiave] = tutti; else delete g[chiave];
}

// ---------- acqua ----------
// Si conta in millilitri (giorni[d].ml) con l'elenco delle bevute; i primi giorni dell'app contavano i bicchieri (acqua).
export const obiettivoAcqua = (d) => P.obiettivi.acqua?.[tipoGiorno(d)] || 2500;
export const acquaBevuta = (d) => { const g = S.giorni[d] || {}; return g.ml ?? (g.acqua || 0) * 250; };

export function bevi(d, ml) {
  aggiorna(() => {
    const g = giorno(d);
    const ora = new Date();
    g.ml = acquaBevuta(d) + ml;
    delete g.acqua;
    g.bevute = [...(g.bevute || []), { t: `${String(ora.getHours()).padStart(2, '0')}:${String(ora.getMinutes()).padStart(2, '0')}`, ml }];
  });
}

export function togliBevuta(d, i) {
  aggiorna(() => {
    const g = giorno(d);
    const [tolta] = (g.bevute || []).splice(i, 1);
    if (tolta) g.ml = Math.max(0, acquaBevuta(d) - tolta.ml);
  });
}

export function azzeraAcqua(d) {
  aggiorna(() => { const g = giorno(d); g.ml = 0; g.bevute = []; delete g.acqua; });
}

const chiaveProdotto = (a) => a.ean || `mio:${a.n.toLowerCase()}`;

// Tiene da parte un cibo usato nel diario. Ne restano 120, i piu' recenti.
export function ricordaProdotto(a, zitto = true) {
  aggiorna((s) => {
    s.prodotti = s.prodotti || {};
    const k = chiaveProdotto(a);
    const prima = s.prodotti[k] || {};
    s.prodotti[k] = {
      n: a.n, marca: a.marca || null, ean: a.ean || null, per: a.per, kcal: a.kcal, p: a.p, c: a.c, f: a.f,
      pz: a.pz || null, pzn: a.pzn || null, conf: a.conf || null, img: a.img || null, fonte: a.fonte || 'mio',
      usato: Date.now(), volte: (prima.volte || 0) + 1,
    };
    const tutti = Object.entries(s.prodotti).sort((x, y) => y[1].usato - x[1].usato);
    for (const [vecchio] of tutti.slice(120)) delete s.prodotti[vecchio];
  }, zitto);
}

export const prodottiRecenti = () => Object.values(S.prodotti || {}).sort((a, b) => b.usato - a.usato);

export function alternative(mom, rid) {
  const tipo = P.momenti[mom].tipo;
  // le ricette "personali" (la colazione di una persona sola) si propongono solo a chi ha il piano scritto a mano;
  // quelle con `per` solo nei pasti indicati (in certe diete il pranzo e la cena hanno schemi diversi e non si scambiano)
  return Object.entries(P.ricette).filter(([id, r]) => r.tipo === tipo && id !== rid && !(r.personale && P.profilo.generato)
    && (!r.per || r.per.includes(mom))).map(([id]) => id);
}

// ---------- cambiare il piano: un altro piatto al posto di quello previsto, e i piatti creati dalla persona ----------
// Le usa l'assistente (azioni.js): ognuna restituisce quello che serve per tornare indietro.

// Quella ricetta puo' stare in quel pasto? Stesso tipo, e (se la ricetta lo dice) solo nei pasti indicati.
export const vaNelPasto = (rid, mom) => {
  const r = P.ricette[rid], m = P.momenti[mom];
  return !!r && !!m && mom !== 'post' && r.tipo === m.tipo && (!r.per || r.per.includes(mom));
};

// Spunta o toglie la spunta a un pasto. Restituisce com'era.
export function segnaFatto(d, mom, si) {
  const era = !!S.giorni[d]?.pasti?.[mom];
  // spuntato o tolto per intero: gli ingredienti lasciati nel piatto non valgono piu'
  aggiorna(() => { const g = giorno(d); g.pasti[mom] = !!si; mettiPerPasto(g, 'saltati', mom, null); });
  return era;
}

// Mette `rid` in quel pasto nei giorni della settimana indicati (rid nullo = torna il piatto del piano).
// Restituisce com'era prima, giorno per giorno: {giorno: ricetta messa prima, o null}.
export function cambiaPasti(giorni, mom, rid) {
  const prima = {};
  aggiorna((s) => {
    for (const wd of giorni) {
      if (!P.settimana[wd]?.pasti?.[mom]) continue;   // quel giorno quel pasto non c'e'
      prima[wd] = s.cambi[wd]?.[mom] || null;
      s.cambi[wd] = s.cambi[wd] || {};
      if (!rid || rid === P.settimana[wd].pasti[mom]) delete s.cambi[wd][mom]; else s.cambi[wd][mom] = rid;
    }
  });
  return prima;
}
// Mette `rid` in quel pasto solo nel giorno `d` (rid nullo = torna il piatto della settimana). Restituisce com'era.
export function cambiaPastoDelGiorno(d, mom, rid) {
  const prima = S.giorni[d]?.ricette?.[mom] || null;
  aggiorna(() => {
    const g = giorno(d);
    g.ricette = { ...(g.ricette || {}) };
    if (rid) g.ricette[mom] = rid; else delete g.ricette[mom];
    if (!Object.keys(g.ricette).length) delete g.ricette;
  });
  return prima;
}
export function rimettiPasti(mom, prima) {
  aggiorna((s) => {
    for (const [wd, rid] of Object.entries(prima || {})) {
      s.cambi[wd] = s.cambi[wd] || {};
      if (rid) s.cambi[wd][mom] = rid; else delete s.cambi[wd][mom];
    }
  });
}

// Un identificativo "mio-..." che non c'e' ancora, ricavato da un nome.
export function nuovoId(nome, preso) {
  const radice = `mio-${String(nome).toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 28) || 'piatto'}`;
  let id = radice;
  for (let n = 2; preso(id); n++) id = `${radice}-${n}`;
  return id;
}

// Aggiunge un piatto della persona, con i cibi nuovi che gli servono ({id: cibo}). Restituisce il suo identificativo.
export function aggiungiPiatto(ricetta, cibiNuovi = {}) {
  const rid = nuovoId(ricetta.n, (id) => !!P.ricette[id] || !!S.mie.ricette[id]);
  aggiorna((s) => { Object.assign(s.mie.cibi, cibiNuovi); s.mie.ricette[rid] = { ...ricetta, mia: true }; }, true);
  componi();
  avvisa();
  return rid;
}

// Toglie un piatto della persona e i cibi rimasti senza piatti; dove era nel piano torna quello originale.
// Restituisce quello che serve a rimetterlo, oppure null se non era un piatto suo.
export function togliPiatto(rid) {
  const ricetta = S.mie.ricette[rid];
  if (!ricetta) return null;
  const tolto = { rid, ricetta, cibi: {}, cambi: [] };
  // un piatto tutto suo sparisce; la versione ritoccata di un piatto del piano torna quella originale, che resta dov'e'
  const tuttoSuo = !!P.ricette[rid]?.mia;
  aggiorna((s) => {
    delete s.mie.ricette[rid];
    if (!tuttoSuo) return;
    for (const [wd, g] of Object.entries(s.cambi)) {
      for (const [mom, r] of Object.entries(g || {})) if (r === rid) { tolto.cambi.push([wd, mom]); delete g[mom]; }
    }
    const usati = new Set(Object.values(s.mie.ricette).flatMap((r) => (r.ing || []).map((x) => x[0])));
    for (const id of Object.keys(s.mie.cibi)) if (id.startsWith('mio-') && !usati.has(id)) { tolto.cibi[id] = s.mie.cibi[id]; delete s.mie.cibi[id]; }
  }, true);
  componi();
  avvisa();
  return tolto;
}
export function rimettiPiatto(tolto) {
  aggiorna((s) => {
    Object.assign(s.mie.cibi, tolto.cibi || {});
    s.mie.ricette[tolto.rid] = tolto.ricetta;
    for (const [wd, mom] of tolto.cambi || []) { s.cambi[wd] = s.cambi[wd] || {}; s.cambi[wd][mom] = tolto.rid; }
  }, true);
  componi();
  avvisa();
}

// ---------- modifica generica dei dati della persona ----------
// La usa l'assistente per tutto quello che non ha una funzione sua: cambia direttamente lo stato, un'operazione alla volta.
//   {op: 'metti', percorso, valore}      scrive un valore (creando gli oggetti che mancano lungo la strada)
//   {op: 'togli', percorso}              toglie una chiave, o l'elemento di un elenco in quella posizione
//   {op: 'togli', percorso, dove}        toglie da un elenco gli elementi che hanno quei valori ({id: ...})
//   {op: 'aggiungi', percorso, valore}   aggiunge in fondo a un elenco
// Il percorso e' un elenco di chiavi che parte dallo stato e comincia con una delle RADICI: il resto (l'account, la
// conversazione, la seduta in corso) non si tocca. Dopo le modifiche si ricompone il piano e lo si prova (sano): se
// qualcosa non sta in piedi si rimette tutto com'era. Restituisce {ok: true, disfa} oppure {ok: false, errore}.
const RADICI = ['giorni', 'cambi', 'spesa', 'sedute', 'attivita', 'opzioni', 'profilo', 'mie'];
const VIETATE = new Set(['__proto__', 'prototype', 'constructor']);
const copia = (v) => (v === undefined ? undefined : JSON.parse(JSON.stringify(v)));
const sbagliato = (perche) => { throw new Error(perche); };

function ultimoPasso(p, crea) {
  let dove = S;
  for (let i = 0; i < p.length - 1; i++) {
    if (dove[p[i]] == null) { if (!crea) sbagliato('quel dato non c\'è'); dove[p[i]] = {}; }
    if (typeof dove[p[i]] !== 'object') sbagliato('quel percorso non porta a niente');
    dove = dove[p[i]];
  }
  return [dove, p[p.length - 1]];
}

function applica(o, disfa) {
  const p = o?.percorso;
  if (!Array.isArray(p) || !p.length || p.length > 9 || !RADICI.includes(p[0])) sbagliato('quella parte dei dati non si può toccare');
  for (const k of p) if (!(typeof k === 'string' || Number.isInteger(k)) || VIETATE.has(String(k)) || String(k).length > 60) sbagliato('percorso non valido');
  const valore = copia(o.valore);
  if (o.op === 'aggiungi') {
    const [dove, k] = ultimoPasso(p, true);
    if (dove[k] === undefined) dove[k] = [];
    if (!Array.isArray(dove[k]) || valore === undefined) sbagliato('lì non c\'è un elenco a cui aggiungere');
    // una seduta nuova deve avere la forma di quelle che scrive l'app (concludiSeduta), con scheda ed esercizi veri
    if (p.length === 1 && p[0] === 'sedute') {
      if (!valore || typeof valore.d !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(valore.d) || !P.schede[valore.w] || !Array.isArray(valore.voci) || !valore.voci.length
        || valore.voci.some((v) => !P.esercizi[v?.es] || !Array.isArray(v.serie) || !v.serie.length || v.serie.some((q) => !numero(q?.rip)))) sbagliato('la seduta non è scritta bene: giorno, scheda che esiste, esercizi che esistono con le loro serie');
      const allaSera = daIso(valore.d);
      allaSera.setHours(18, 0, 0, 0);   // se non si sa a che ora, le sei di sera di quel giorno
      valore.inizio = numero(valore.inizio) ? valore.inizio : allaSera.getTime();
      valore.fine = numero(valore.fine) && valore.fine > valore.inizio ? valore.fine : valore.inizio + (P.schede[valore.w].durata || 60) * 60000;
      valore.id = valore.inizio;
      valore.voci = valore.voci.map((v) => ({ es: v.es, rip: v.rip ?? null, serie: v.serie.map((q) => ({ kg: numero(q.kg) ? q.kg : null, rip: Math.round(q.rip), ok: true })) }));
    }
    // attivita' e voci del diario hanno un identificativo: se manca lo si mette
    if (valore && typeof valore === 'object' && !Array.isArray(valore) && valore.id == null) valore.id = Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
    dove[k].push(valore);
    disfa.push({ k: 'leva', p, id: valore?.id ?? null });
  } else if (o.op === 'togli' && o.dove && typeof o.dove === 'object') {
    const [dove, k] = ultimoPasso(p, false);
    if (!Array.isArray(dove[k])) sbagliato('lì non c\'è un elenco');
    const uguale = (x) => x && typeof x === 'object' && Object.entries(o.dove).every(([c, v]) => x[c] === v);
    const tolti = dove[k].map((x, i) => [i, x]).filter(([, x]) => uguale(x));
    if (!tolti.length) sbagliato('non trovo quello che c\'era da togliere');
    dove[k] = dove[k].filter((x) => !uguale(x));
    disfa.push({ k: 'rimetti', p, tolti: copia(tolti) });
  } else if (o.op === 'togli' || o.op === 'metti') {
    if (p.length < 2) sbagliato('una parte intera dei dati non si sostituisce');
    const [dove, k] = ultimoPasso(p, o.op === 'metti');
    if (Array.isArray(dove) && !(Number.isInteger(Number(k)) && Number(k) >= 0 && Number(k) < dove.length)) sbagliato('quella posizione nell\'elenco non c\'è');
    const cera = Object.prototype.hasOwnProperty.call(dove, k);
    if (o.op === 'togli' && !cera) sbagliato('quel dato non c\'è');
    if (o.op === 'metti' && valore === undefined) sbagliato('manca il valore da scrivere');
    disfa.push({ k: 'prima', p, cera, prima: copia(dove[k]), elenco: Array.isArray(dove) && o.op === 'togli' });
    if (o.op === 'metti') dove[k] = valore;
    else if (Array.isArray(dove)) dove.splice(Number(k), 1);
    else delete dove[k];
  } else sbagliato('operazione che non conosco');
}

// Rimette com'era quello che una `applica` ha cambiato.
function disfaUna(u) {
  const [dove, k] = ultimoPasso(u.p, true);
  if (u.k === 'leva') {
    const i = Array.isArray(dove[k]) ? (u.id != null ? dove[k].map((x) => x?.id).lastIndexOf(u.id) : dove[k].length - 1) : -1;
    if (i >= 0) dove[k].splice(i, 1);
  } else if (u.k === 'rimetti') {
    if (!Array.isArray(dove[k])) dove[k] = [];
    for (const [i, x] of u.tolti) dove[k].splice(Math.min(i, dove[k].length), 0, x);
  } else if (u.elenco) dove.splice(Math.min(Number(k), dove.length), 0, u.prima);
  else if (u.cera) dove[k] = u.prima;
  else delete dove[k];
}

// Il piano e i dati reggono? Si prova a fare i conti che fanno le schermate, per i giorni attorno a oggi.
function sano() {
  const o = oggi();
  for (let i = -2; i <= 8; i++) {
    const d = piuGiorni(o, i);
    const t = totali(d);
    for (const gruppo of [t.piano, t.fatto, t.ob]) for (const k of MACRO) if (!numero(gruppo?.[k])) sbagliato('i conti di un giorno non tornano più');
    for (const x of pastiDelGiorno(d)) ingredienti(x.rid, x.tipo);
    if (!numero(obiettivoAcqua(d))) sbagliato('l\'obiettivo dell\'acqua non è un numero');
    const w = schedaDelGiorno(d);
    if (w && !P.schede[w]) sbagliato('la scheda di un giorno non esiste');
  }
  listaSpesa();
  for (const sc of Object.values(P.schede)) if (!schedaBuona(sc, P.esercizi)) sbagliato('una scheda non sta in piedi');
  if (!Array.isArray(S.sedute) || !Array.isArray(S.attivita) || !S.opzioni || typeof S.opzioni !== 'object') sbagliato('manca un pezzo dei dati');
  for (const x of S.sedute) {
    if (!x || typeof x.d !== 'string' || typeof x.w !== 'string' || !numero(x.inizio) || !Array.isArray(x.voci)
      || x.voci.some((v) => typeof v?.es !== 'string' || !Array.isArray(v.serie) || v.serie.some((q) => !numero(q?.rip) || !(q.kg == null || numero(q.kg))))) sbagliato('una seduta non sta in piedi');
  }
  for (const a of S.attivita) {
    if (!a || typeof a.d !== 'string' || !numero(a.min) || !ATTIVITA[a.tipo]
      || (a.kcal != null && (!numero(a.kcal) || a.kcal < 0 || a.kcal > 10000))) sbagliato('un\'attività non sta in piedi');
  }
  for (const g of Object.values(S.giorni)) {
    if (!g || typeof g !== 'object' || (g.pasti != null && typeof g.pasti !== 'object') || (g.ml != null && !numero(g.ml))
      || (g.tipi != null && (typeof g.tipi !== 'object' || Object.values(g.tipi).some((t) => !tipoBuono(t))))
      || (g.bruciate != null && (!numero(g.bruciate) || g.bruciate < 0 || g.bruciate > 20000))
      || (g.ricette != null && (typeof g.ricette !== 'object' || Object.values(g.ricette).some((r) => typeof r !== 'string')))
      || (g.dosi != null && (typeof g.dosi !== 'object' || Object.values(g.dosi).some((m) => !m || typeof m !== 'object' || Object.values(m).some((x) => !numero(x) || x < 0 || x > 5000))))
      || (g.saltati != null && (typeof g.saltati !== 'object' || Object.values(g.saltati).some((m) => !Array.isArray(m) || m.some((x) => typeof x !== 'string'))))
      || (g.extra != null && (!Array.isArray(g.extra) || g.extra.some((e) => !e || typeof e.n !== 'string' || typeof e.mom !== 'string' || e.id == null || !numero(e.kcal) || !MACRO.every((k) => e[k] == null || numero(e[k])))))) sbagliato('il diario di un giorno non sta in piedi');
  }
  const orari = S.opzioni.orari || {};
  if (['colazione', 'pranzo', 'cena'].some((k) => orari[k] != null && !/^\d{1,2}:\d{2}$/.test(orari[k]))) sbagliato('un orario non è scritto bene');
  const pr = S.profilo;
  if (pr && pr.giorni != null && (!Array.isArray(pr.giorni) || pr.giorni.some((x) => !Number.isInteger(x) || x < 0 || x > 6))) sbagliato('i giorni di allenamento non sono scritti bene');
  // quello che sta in "mie" dev'essere entrato davvero nel piano: un pezzo scartato vuol dire una modifica scritta male
  const mie = S.mie || {};
  for (const id of Object.keys(mie.ricette || {})) if (!(P.ricette[id]?.mia || P.ricette[id]?.modificata)) sbagliato(`il piatto "${id}" non sta in piedi (nome, tipo, ingredienti con cibi che esistono)`);
  for (const [id, c] of Object.entries(mie.cibi || {})) {
    if (!P.cibi[id] || Object.entries(c || {}).some(([k, v]) => JSON.stringify(P.cibi[id][k]) !== JSON.stringify(v))) sbagliato(`il cibo "${id}" non sta in piedi (nome e kcal, p, c, f per 100 g)`);
  }
  for (const w of Object.keys(mie.schede || {})) if (!P.schede[w] || !schedaBuona({ fuoco: '', durata: 60, ...P.schede[w], ...mie.schede[w] }, P.esercizi)) sbagliato(`la scheda "${w}" non sta in piedi (esercizi che esistono, serie, ripetizioni, recupero)`);
  for (const t of ['train', 'rest']) if (mie.obiettivi?.[t] && !Object.entries(mie.obiettivi[t]).every(([k, v]) => MACRO.includes(k) && numero(v) && v > 0)) sbagliato('gli obiettivi devono essere numeri: kcal, p, c, f');
  for (const [wd, g] of Object.entries(mie.settimana || {})) {
    if (!/^[0-6]$/.test(wd) || !g || typeof g !== 'object' || (g.tipo != null && g.tipo !== 'train' && g.tipo !== 'rest')
      || (g.scheda != null && (!P.schede[g.scheda] || P.schede[g.scheda].casa)) || (g.ob != null && !macroBuoni(g.ob))
      || Object.entries(g.pasti || {}).some(([mom, rid]) => !P.momenti[mom] || (rid !== null && P.ricette[rid]?.tipo !== P.momenti[mom].tipo))) sbagliato(`il giorno ${wd} della settimana non è scritto bene`);
  }
  for (const [mom, m] of Object.entries(mie.momenti || {})) {
    const c = P.momenti[mom];
    if (!c || (m?.n != null && c.n !== m.n) || (m?.ora?.rest !== undefined && c.ora.rest !== m.ora.rest) || (m?.ora?.train !== undefined && c.ora.train !== m.ora.train)) sbagliato(`il pasto "${mom}" non è scritto bene (nome, tipo, ora come 13:00)`);
  }
}

export function modificaStato(operazioni) {
  const disfa = [];
  const prima = tipiDeiGiorni();
  let reggeva = true;
  try { sano(); } catch { reggeva = false; }
  try {
    for (const o of operazioni) applica(o, disfa);
    if (!S.mie || typeof S.mie !== 'object') S.mie = {};
    S.sedute.sort((a, b) => (a?.inizio || 0) - (b?.inizio || 0));
    S.attivita.sort((a, b) => String(a?.d).localeCompare(String(b?.d)));
    componi();
    // se qualcosa non tornava gia' prima non lo si fa pagare a questa modifica: basta che i conti di oggi reggano
    if (reggeva) sano(); else { totali(oggi()); listaSpesa(); }
    // dopo il controllo: un tipo di pasto scritto male va rifiutato, non aggiustato in silenzio
    fermaPasti(prima);
  } catch (e) {
    for (const u of disfa.reverse()) { try { disfaUna(u); } catch { /* si prosegue con le altre */ } }
    componi();
    return { ok: false, errore: e?.message || 'modifica non valida' };
  }
  aggiorna(() => {});   // salva, manda al server e ridisegna
  return { ok: true, disfa };
}

// Annulla una modificaStato andata a buon fine (le sue `disfa`), con lo stesso controllo.
export function annullaModifica(disfa) {
  try {
    for (const u of [...disfa].reverse()) disfaUna(u);
    componi();
  } catch {
    componi();
    return false;
  }
  aggiorna(() => {});
  return true;
}

export function listaSpesa() {
  const somma = {};
  for (let wd = 0; wd < 7; wd++) {
    const tipo = P.settimana[wd].tipo;
    const i = tipo === 'train' ? 2 : 1;
    for (const mom of Object.keys(P.momenti)) {
      const rid = ricettaDi(wd, mom, tipo);
      if (!rid) continue;
      for (const ing of P.ricette[rid].ing) if (ing[i] > 0 && P.cibi[ing[0]].spesa !== false) somma[ing[0]] = (somma[ing[0]] || 0) + ing[i];
    }
  }
  const gruppi = REPARTI.map((rep) => ({ rep, voci: [] }));
  for (const [id, g] of Object.entries(somma)) {
    const cibo = P.cibi[id];
    let q;
    if (cibo.pz && id !== 'olio') {
      const n = Math.ceil(g / cibo.pz - 0.01);
      q = `${n} ${cibo.pzn[n === 1 ? 0 : 1]}`;
    } else if (g >= 1000) q = `${dec(Math.ceil(g / 100) / 10)} kg`;
    else q = `${intero(Math.ceil(g / 10) * 10)} g`;
    (gruppi.find((x) => x.rep === cibo.rep) || gruppi[gruppi.length - 1]).voci.push({ id, n: cibo.n, q, nota: cibo.nota, presa: !!S.spesa[id] });
  }
  for (const gr of gruppi) gr.voci.sort((a, b) => a.n.localeCompare(b.n, 'it'));
  return gruppi.filter((x) => x.voci.length);
}

// ---------- allenamento ----------
export const sedutaDel = (d) => S.sedute.find((x) => x.d === d) || null;

// Le schede di palestra, in ordine. Il circuito a casa non entra nella rotazione.
export const schedePalestra = () => Object.keys(P.schede).filter((k) => !P.schede[k].casa);

export function prossimaLettera() {
  const ordine = schedePalestra();
  const ultima = [...S.sedute].reverse().find((x) => ordine.includes(x.w));
  if (!ultima) return ordine[0];
  return ordine[(ordine.indexOf(ultima.w) + 1) % ordine.length];
}

export function schedaDelGiorno(d) {
  // se quel giorno ti sei gia' allenato, la scheda e' quella fatta, non la prossima in rotazione
  const fatta = sedutaDel(d);
  if (fatta && P.schede[fatta.w]) return fatta.w;
  if (tipoGiorno(d) !== 'train') return null;
  return P.settimana[giornoSett(daIso(d))].scheda || prossimaLettera();
}

// Prossima seduta da fare: oggi se e' giorno di palestra e non l'hai fatta, altrimenti il primo giorno utile.
export function prossimaSeduta() {
  const o = oggi();
  for (let i = 0; i < 8; i++) {
    const d = piuGiorni(o, i);
    const w = schedaDelGiorno(d);
    if (w && !sedutaDel(d)) return { d, w, oggi: i === 0 };
  }
  return { d: o, w: prossimaLettera(), oggi: true };
}

export function ultimaVolta(es) {
  for (let i = S.sedute.length - 1; i >= 0; i--) {
    const v = S.sedute[i].voci.find((x) => x.es === es && x.serie.some((q) => q.ok));
    if (v) return { d: S.sedute[i].d, serie: v.serie.filter((q) => q.ok) };
  }
  return null;
}

// "8-12" -> [8, 12]; "30-60 s" -> [30, 60]; "10" -> [10, 10]
export function intervallo(rip) {
  const n = String(rip).match(/\d+/g)?.map(Number) || [];
  return n.length ? [n[0], n[n.length - 1]] : [0, 0];
}
// di quanto si sale: i carichi piccoli (manubri leggeri) vanno a chili, gli altri a due e mezzo
export const passoCarico = (kg) => (kg >= 20 ? 2.5 : 1);

// Cosa fare oggi, serie per serie, partendo dall'ultima volta (doppia progressione):
//   tutte le serie al massimo delle ripetizioni -> si sale di carico e si riparte dal minimo;
//   altrimenti stesso carico e una ripetizione in piu' dove non eri al massimo.
// mossa = 'prima' (mai fatto), 'sali', 'rip' (una ripetizione in piu'), 'uguale' (gia' al massimo, a corpo libero), 'tempo'.
// kgScheda = il carico di riferimento scritto nella scheda (chi arriva con una scheda sua non parte da zero).
// Con le ripetizioni fisse ("5 x 5") non si sale da soli: mossa 'fisso', e a decidere se aumentare e' chi si allena.
export function proposte(es, rip, nSerie, kgScheda = null) {
  const e = P.esercizi[es] || {};
  const [min, max] = intervallo(rip);
  const u = ultimaVolta(es);
  // mai fatto in una seduta conclusa: se pero' i chili per questo esercizio sono gia' stati scritti una volta
  // (S.carichi, li tiene da parte la seduta a ogni serie fatta) si riparte da quelli
  if (!u) return { ultima: null, mossa: 'prima', serie: Array.from({ length: nSerie }, () => ({ kg: e.tempo || e.corpo ? null : (S.carichi?.[es]?.kg ?? kgScheda), rip: min || null })) };
  const era = (k) => u.serie[k] || u.serie[u.serie.length - 1];
  if (!max && !e.tempo) {   // "max": quante ne vengono. Si prova a farne una in piu' dell'altra volta
    return { ultima: u, mossa: 'rip', serie: Array.from({ length: nSerie }, (_, k) => ({ kg: era(k).kg ?? null, rip: (era(k).rip || 0) + 1 })) };
  }
  if (e.tempo) {
    return { ultima: u, mossa: 'tempo', serie: Array.from({ length: nSerie }, (_, k) => ({ kg: null, rip: Math.min(max || 600, (era(k).rip || min) + 5) })) };
  }
  const piene = max > 0 && u.serie.length >= nSerie && u.serie.every((q) => (q.rip || 0) >= max);
  const conCarico = u.serie.some((q) => q.kg > 0);
  if (piene && min === max) {
    return { ultima: u, mossa: conCarico ? 'fisso' : 'uguale', serie: Array.from({ length: nSerie }, (_, k) => ({ kg: era(k).kg ?? null, rip: max })) };
  }
  if (piene && conCarico) {
    return { ultima: u, mossa: 'sali', serie: Array.from({ length: nSerie }, (_, k) => ({ kg: (era(k).kg || 0) + passoCarico(era(k).kg || 0), rip: min })) };
  }
  return {
    ultima: u, mossa: piene ? 'uguale' : 'rip',
    serie: Array.from({ length: nSerie }, (_, k) => ({ kg: era(k).kg ?? null, rip: max ? Math.min(max, (era(k).rip || min) + (era(k).rip < max ? 1 : 0)) : era(k).rip })),
  };
}

// Le serie di una voce con dentro gia' i numeri proposti: a chi li ha fatti basta una spunta.
export const serieProposte = (es, rip, nSerie, kgScheda = null) => proposte(es, rip, nSerie, kgScheda).serie.map((q) => ({ kg: q.kg, rip: q.rip, ok: false }));

export function iniziaSeduta(w, d = oggi()) {
  aggiorna((s) => {
    s.attiva = {
      w, d, inizio: Date.now(), i: 0, riposo: null,
      // il quinto pezzo di una riga della scheda, quando c'e': {nota, kg} (una nota e il carico di riferimento)
      voci: P.schede[w].es.map(([es, serie, rip, rec, piu]) => ({ es, base: es, rip, rec, nota: piu?.nota || null, kgScheda: piu?.kg ?? null, serie: serieProposte(es, rip, serie, piu?.kg ?? null) })),
    };
    // il circuito a casa non fa diventare la giornata "di palestra": niente carboidrati in piu'
    if (!P.schede[w].casa && siAllena() && tipoGiorno(d) !== 'train') giorno(d).tipo = 'train';
  });
}

export function volume(voci) {
  let v = 0;
  for (const x of voci) if (!P.esercizi[x.es]?.tempo) for (const q of x.serie) if (q.ok) v += (q.kg || 0) * (q.rip || 0);
  return v;
}

export function migliore(es, finoA = S.sedute.length) {
  let top = null;
  for (let i = 0; i < finoA; i++) {
    for (const x of S.sedute[i].voci) {
      if (x.es !== es) continue;
      for (const q of x.serie) {
        if (!q.ok || !q.rip) continue;
        if (!top || (q.kg || 0) > top.kg || ((q.kg || 0) === top.kg && q.rip > top.rip)) top = { kg: q.kg || 0, rip: q.rip };
      }
    }
  }
  return top;
}

export function concludiSeduta() {
  const a = S.attiva;
  if (!a) return null;
  const voci = a.voci.map((x) => ({ es: x.es, rip: x.rip, serie: x.serie.filter((q) => q.ok).map((q) => ({ kg: q.kg, rip: q.rip, ok: true })) })).filter((x) => x.serie.length);
  if (!voci.length) { aggiorna((s) => { s.attiva = null; }); return null; }
  const record = [];
  for (const x of voci) {
    if (P.esercizi[x.es]?.tempo) continue;
    const prima = migliore(x.es);
    const ora = x.serie.reduce((m, q) => (!m || (q.kg || 0) > m.kg || ((q.kg || 0) === m.kg && q.rip > m.rip) ? { kg: q.kg || 0, rip: q.rip } : m), null);
    if (prima && ora && (ora.kg > prima.kg || (ora.kg === prima.kg && ora.rip > prima.rip))) record.push({ es: x.es, ...ora });
  }
  const seduta = { id: a.inizio, d: a.d, w: a.w, inizio: a.inizio, fine: Date.now(), voci };
  aggiorna((s) => { s.sedute.push(seduta); s.sedute.sort((p, q) => p.inizio - q.inizio); s.attiva = null; });
  return { seduta, record, volume: volume(voci), serie: voci.reduce((n, x) => n + x.serie.length, 0) };
}

export function sedutaSettimana(lun) {
  const fine = piuGiorni(lun, 6);
  return S.sedute.filter((x) => x.d >= lun && x.d <= fine);
}

// ---------- in palestra senza segnare gli esercizi ----------
// Chi va in palestra e non segna la seduta non deve risultare assente: un giorno lasciato su "Gym" nella Home vale come
// allenamento fatto. Oggi vale dall'ora dello shake dopo l'allenamento (prima la giornata e' ancora da fare); quando il
// giorno e' passato resta scritto nel giorno stesso (`gym`), cosi' non cambia se poi si spostano i giorni di
// allenamento. Per dire "oggi non ci vado" c'e' l'interruttore su Riposo; un giorno passato si corregge dallo storico.
// E' una scelta di ciascuno (Gym, in fondo): chi gestisce l'app l'ha chiesta e la trova accesa, gli altri spenta.
export const contaPresenze = () => siAllena() && (S.opzioni.presenze ?? !!io.capo);
export function impostaPresenze(si) { aggiorna((s) => { s.opzioni.presenze = !!si; }); }
// Chiude i giorni passati: lo chiama `allinea` quando la copia sul telefono e' la piu' fresca. Dice se ha cambiato qualcosa.
function chiudiPresenze() {
  if (!contaPresenze() || !S.giorni || typeof S.giorni !== 'object') return false;
  const ieri = piuGiorni(oggi(), -1);
  const fino = S.presenze?.fino;
  if (fino && fino >= ieri) return false;
  // la prima volta non si torna indietro (si comincia da oggi); dopo un'assenza lunga, al massimo due settimane
  let d = fino ? piuGiorni(fino, 1) : null;
  if (d && d < piuGiorni(ieri, -13)) d = piuGiorni(ieri, -13);
  for (; d && d <= ieri; d = piuGiorni(d, 1)) {
    if (tipoGiorno(d) === 'train' && !sedutaDel(d) && S.giorni[d]?.gym == null) giorno(d).gym = true;
  }
  S.presenze = { fino: ieri };
  return true;
}
// Quel giorno si e' allenato? C'e' la seduta segnata, oppure era un giorno di palestra lasciato su "Gym".
export function allenato(d) {
  if (sedutaDel(d)) return true;
  if (!siAllena()) return false;
  if (d !== oggi()) return S.giorni[d]?.gym === true;
  if (!contaPresenze() || !S.presenze || tipoGiorno(d) !== 'train') return false;
  const adesso = new Date(), post = pastiDelGiorno(d).find((x) => x.mom === 'post')?.ora;
  return adesso.getHours() * 60 + adesso.getMinutes() >= (post ? inMinuti(post) : 21 * 60);
}
// I giorni di palestra contati senza una seduta segnata, dal piu' recente.
export function presenze() {
  const giorni = Object.keys(S.giorni).filter((d) => S.giorni[d]?.gym === true && !sedutaDel(d));
  const o = oggi();
  if (allenato(o) && !sedutaDel(o)) giorni.push(o);
  return [...new Set(giorni)].sort().reverse();
}
// Tutti i giorni in cui si e' allenato (sedute segnate e giorni contati), come insieme di date.
export const giorniAllenati = () => new Set([...S.sedute.map((x) => x.d), ...presenze()]);
// "Quel giorno non ci sono andato": il giorno passato non conta piu' (e non viene ricontato); per oggi e' come mettere
// su Riposo l'interruttore della Home.
export function togliPresenza(d) {
  aggiorna(() => {
    const g = giorno(d);
    if (d !== oggi()) g.gym = false;
    else if (tipoModello(d) === 'rest') delete g.tipo;
    else g.tipo = 'rest';
  });
}

// ---------- movimento libero: camminate, corse, esercizi a casa ----------
// met = quanto costa rispetto allo stare fermi: kcal = met x chili x ore. km = ha senso chiedere la distanza.
export const ATTIVITA = {
  camminata: { n: 'Camminata', icona: 'walk', met: 3.8, km: true, minuti: [20, 30, 45, 60] },
  corsa: { n: 'Corsa', icona: 'run', met: 9, km: true, minuti: [20, 30, 45, 60] },
  // i pesi segnati a mano, con le calorie dell'orologio se le hai (per chi va in palestra; la seduta resta a parte)
  palestra: { n: 'Palestra', icona: 'dumbbell', met: 5, minuti: [45, 60, 75, 90], palestra: true },
  bici: { n: 'Bici', icona: 'bike', met: 6.8, km: true, minuti: [30, 45, 60, 90] },
  casa: { n: 'Esercizi a casa', icona: 'home', met: 4.5, minuti: [10, 20, 30, 45] },
  nuoto: { n: 'Nuoto', icona: 'wave', met: 7, minuti: [20, 30, 45, 60] },
  altro: { n: 'Altro', icona: 'bolt', met: 4.5, minuti: [15, 30, 45, 60] },
};
export const OBIETTIVO_MINUTI = 150;   // minuti di movimento a settimana (per chi non va in palestra)

// `kcal` = le calorie bruciate che scrivi tu (dall'orologio, dal tapis roulant); senza, vale la stima dell'app.
export function aggiungiAttivita({ tipo, min, km = null, d = oggi(), nota = null, kcal = null }) {
  const id = Date.now().toString(36) + Math.random().toString(36).slice(2, 5);
  aggiorna((s) => {
    s.attivita.push({ id, d, tipo, min: Math.round(min), km: km || null, nota: nota || null, ...(numero(kcal) ? { kcal: Math.round(kcal) } : {}) });
    s.attivita.sort((a, b) => a.d.localeCompare(b.d));
    if (s.attivita.length > 1500) s.attivita.splice(0, s.attivita.length - 1500);
  });
  return id;
}
export function togliAttivita(id) { aggiorna((s) => { s.attivita = s.attivita.filter((a) => a.id !== id); }); }
export const attivitaDel = (d) => S.attivita.filter((a) => a.d === d);
// i minuti di movimento di un giorno: attivita' libere piu' le sedute (palestra o circuito a casa)
export function minutiAttivi(d) {
  // una seduta lasciata aperta per ore non sono ore di allenamento: conta al massimo due ore
  const sedute = S.sedute.filter((x) => x.d === d).reduce((n, x) => n + Math.min(120, Math.max(0, Math.round((x.fine - x.inizio) / 60000))), 0);
  return attivitaDel(d).reduce((n, a) => n + (a.min || 0), 0) + sedute;
}
export function minutiSettimana(lun) {
  let n = 0;
  for (let i = 0; i < 7; i++) n += minutiAttivi(piuGiorni(lun, i));
  return n;
}
// ---------- calorie bruciate: la stima dell'app oppure le tue ----------
// La stima viene dai MET (quanto costa il movimento rispetto allo stare fermi) e dal peso: e' una media, l'orologio
// spesso ne sa di piu'. Per questo ogni attivita' puo' avere le calorie scritte da te (`kcal`), e ogni giorno un totale
// tuo (giorni[d].bruciate) che vale al posto della somma delle attivita'. Non cambiano l'obiettivo del giorno: le
// calorie di un giorno di palestra contano gia' l'allenamento.
export const kcalStimate = (a, chili) => Math.round((ATTIVITA[a.tipo] || ATTIVITA.altro).met * chili * (a.min || 0) / 60);
export const kcalTue = (a) => (numero(a?.kcal) ? Math.round(a.kcal) : null);
export const kcalAttivita = (a, chili) => kcalTue(a) ?? kcalStimate(a, chili);
// Le calorie di un'attivita' gia' segnata: un numero tuo, oppure null per tornare alla stima.
export function impostaKcalAttivita(id, kcal) {
  aggiorna((s) => {
    const a = s.attivita.find((x) => x.id === id);
    if (!a) return;
    if (numero(kcal)) a.kcal = Math.round(kcal); else delete a.kcal;
  });
}
// Le calorie bruciate in un giorno: il totale tuo se l'hai scritto, altrimenti la somma delle attivita'.
export function bruciateDel(d, chili) {
  const att = attivitaDel(d);
  const somma = att.reduce((n, a) => n + kcalAttivita(a, chili), 0);
  const tuo = S.giorni[d]?.bruciate;
  return { kcal: numero(tuo) ? Math.round(tuo) : somma, tuo: numero(tuo), somma, n: att.length, stimate: att.filter((a) => kcalTue(a) == null).length };
}
export function impostaBruciate(d, kcal) {
  aggiorna(() => { const g = giorno(d); if (numero(kcal)) g.bruciate = Math.round(kcal); else delete g.bruciate; });
}

export { iso };
