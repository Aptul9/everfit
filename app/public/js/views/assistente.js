// L'assistente: una chat a cui chiedere della propria dieta e del proprio allenamento, e a cui far fare le cose
// (segnare quello che si mangia, cambiare un piatto del piano). Si apre dal tondo che galleggia in basso a destra.
// Le risposte le scrive il servizio di AI dell'account (server/assistente.py); l'app gli manda, con ogni domanda, un
// riassunto di quello che sa (obiettivi, pasti di oggi, menu, schede, carichi, pesate) e il catalogo di quello che si
// puo' toccare. Se la risposta porta delle azioni, le esegue azioni.js e sotto la risposta resta scritto cosa e'
// stato fatto, con il tasto per annullarlo.

import { h, icona, oggi, daIso, giornoSett, dec, intero, dataLunga, dataCorta, lunedi, piuGiorni, colpetto } from '../dom.js';
import {
  P, S, io, aggiorna, totali, pastiDelGiorno, ingredienti, tipoGiorno, tipoModello, siAllena, schedePalestra,
  acquaBevuta, obiettivoAcqua, minutiSettimana, attivitaDel, ATTIVITA, presenze, kcalTue,
} from '../store.js';
import { kcalDi } from './attivita.js';
import { M, ultimaPesata, passiDel } from '../misure.js';
import { foglio, avviso, conferma } from '../ui.js';
import { catalogo, settimanaPiano, vociDiario, idsAssistente, mondo, esegui, annulla } from '../azioni.js';
import { leggiFoto } from '../codice.js';
import { rimpicciolisci } from './diario.js';

const DA_TENERE = 60;      // messaggi che restano nella conversazione salvata
const DA_MANDARE = 8;      // messaggi che si rimandano ogni volta al servizio
let occupato = false;
// Lo stato della domanda in corso sta qui fuori, non dentro il foglio: una risposta lenta (l'AI che gira sulla VM) puo'
// arrivare dopo che il foglio e' stato chiuso e riaperto, e deve ridisegnare quello che c'e' adesso.
// chi: chi sta rispondendo; nota: perche' si e' passati a lui, o da quanto lavora; aspetto: il conto alla rovescia.
const corsa = { chi: null, nota: null, aspetto: null, errore: null };
let ridisegna = () => {};
// Il numero della risposta lenta che si sta aspettando: resta sul telefono, cosi' se l'app viene chiusa nel frattempo
// alla riapertura si riprende ad aspettare.
const LAVORO = 'fit-lavoro';
const ricorda = (v) => { try { localStorage.setItem(LAVORO, JSON.stringify(v)); } catch { /* pazienza */ } };
const dimentica = () => { try { localStorage.removeItem(LAVORO); } catch { /* pazienza */ } };
const tempo = (s) => (s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${s % 60} s`);

// Chi risponde: il nome che si vede sopra ogni risposta, e sopra i puntini mentre si aspetta.
const NOMI = { gemini: 'Gemini', mistral: 'Mistral', anthropic: 'Claude', locale: 'AI sulla VM' };
const nomeDi = (chi, leggero) => (chi ? `${NOMI[chi] || chi}${leggero ? ' · modello leggero' : ''}` : '');

// ---------- quello che l'assistente deve sapere ----------
// Di norma parte un riassunto asciutto (livello "base"), in tre pezzi dal piu' fermo al piu' mosso:
//   DATI                     chi e', i cibi, le ricette con gli ingredienti, le schede, i pasti
//   PIANO DI QUESTI GIORNI   la settimana con i cambi, gli obiettivi, il peso, le ultime sedute
//   ADESSO                   i pasti di oggi, il diario, quanto ha mangiato, che ore sono
// L'ordine conta per l'AI che gira sulla VM: leggere le costa caro ma si ricorda quello che ha gia' letto, quindi a ogni
// domanda rilegge solo da dove il testo cambia in poi (il server divide proprio su questi titoli: assistente.py).
// Lo stato e il piano interi, in JSON, si aggiungono solo quando la domanda li richiede (livello "tutto").
function contesto(livello) {
  const p = P.profilo, o = P.obiettivi, d = oggi();
  const t = totali(d);
  const peso = ultimaPesata();
  const ora = new Date();
  const f = [];
  f.push(`Persona: ${io.nome || p.nome}, ${p.sesso === 'f' ? 'donna' : 'uomo'}, ${p.eta} anni, ${p.altezza} cm. Vuole arrivare a ${dec(p.pesoObiettivo)} kg.`);
  if (p.note) f.push(`Note: ${p.note}`);
  if (p.preferenze) f.push(`Gusti e regole: ${p.preferenze}`);
  f.push(catalogo());
  if (siAllena()) {
    f.push('Schede (lettera: esercizi, serie x ripetizioni):');
    for (const w of schedePalestra()) {
      const sc = P.schede[w];
      f.push(`- ${w} ${sc.n}: ${sc.es.map(([es, n, rip]) => `${P.esercizi[es].n} ${n}x${rip}`).join(', ')}`);
    }
  }

  const w = [];
  w.push(settimanaPiano());
  const ob = (x) => `${x.kcal} kcal, proteine ${x.p} g, carboidrati ${x.c} g, grassi ${x.f} g`;
  w.push(siAllena() ? `Obiettivi: nei giorni di palestra ${ob(o.train)}; nei giorni di riposo ${ob(o.rest)}.`
    : `Obiettivi di ogni giorno: ${ob(o.rest)}. Non va in palestra.`);
  w.push(`Peso: ${peso ? `${dec(peso.peso)} kg (pesata del ${dataCorta(peso.giorno)})` : `${dec(p.pesoIniziale)} kg`}.`
    + (peso?.grasso ? ` Grasso corporeo ${dec(peso.grasso)}%, muscolo ${dec(peso.muscolo)}%.` : ''));
  const pesate = M.pesate.slice(-5);
  if (pesate.length > 1) w.push(`Pesate: ${pesate.map((x) => `${dataCorta(x.giorno)} ${dec(x.peso)} kg${x.grasso ? ` (grasso ${dec(x.grasso)}%)` : ''}`).join(', ')}.`);
  const ultime = S.sedute.slice(-2);
  if (ultime.length) {
    w.push('Ultime sedute:');
    for (const x of ultime) {
      w.push(`- ${x.d}, scheda ${x.w}: ${x.voci.map((y) => `${P.esercizi[y.es]?.n || y.es} ${y.serie.map((q) => (q.kg ? `${dec(q.kg, 2)}x${q.rip}` : `${q.rip}`)).join('/')}`).join('; ')}`);
    }
  }
  // i giorni di palestra contati senza una seduta segnata (store.js, allenato): c'e' andato, ma i carichi non ci sono
  const senzaCarichi = presenze().slice(0, 5);
  if (senzaCarichi.length) w.push(`In palestra senza segnare gli esercizi: ${senzaCarichi.map(dataCorta).join(', ')}.`);

  const r = [];
  r.push('Pasti di oggi (identificativo e ora: ricetta "nome", stato):');
  const voce = (e) => `${e.n}${e.q ? ` ${e.q}` : ''} (${intero(e.kcal || 0)} kcal, proteine ${intero(e.p || 0)} g)`;
  for (const x of pastiDelGiorno(d)) {
    // scritto per esteso: i modelli piccoli leggevano "da mangiare" come gia' mangiato e rifacevano i conti a modo loro
    const stato = x.alPosto ? `sostituito con: ${x.extra.map(voce).join('; ')}`
      : x.fatto ? (x.lasciati.length ? `già mangiato, ma senza ${x.lasciati.map((i) => i.id).join(', ')}` : 'già mangiato') : 'NON ancora mangiato';
    r.push(`- ${x.mom} ${x.ora || ''}: ${x.rid} "${x.r.n}" (${intero(x.intero.kcal)} kcal, proteine ${intero(x.intero.p)} g), ${stato}`
      // i grammi cambiati solo per oggi (azione dose): nel piatto restano, con un altro peso
      + (x.ritoccati.length ? `; oggi con ${x.ritoccati.map((i) => `${i.id} ${intero(i.g)} g invece di ${intero(i.piano)}`).join(', ')}` : '')
      + (!x.alPosto && x.extra.length ? `; in più: ${x.extra.map(voce).join('; ')}` : ''));
  }
  const fuori = (S.giorni[d]?.extra || []).filter((e) => e.mom === 'fuori');
  if (fuori.length) r.push(`- fuori pasto: ${fuori.map(voce).join('; ')}`);
  const diario = vociDiario();
  if (diario) r.push(diario);
  const mossi = minutiSettimana(lunedi(d));
  const oggiFatto = attivitaDel(d).map((x) => `${(ATTIVITA[x.tipo] || ATTIVITA.altro).n.toLowerCase()} ${x.min} min `
    + `(${intero(kcalDi(x))} kcal${kcalTue(x) != null ? ' scritte a mano' : ', stima dell\'app'})`).join(', ');
  const bruciate = S.giorni[d]?.bruciate;
  r.push(`Movimento: ${mossi} minuti questa settimana${oggiFatto ? `; oggi ${oggiFatto}` : ''}`
    + `${typeof bruciate === 'number' ? `; calorie bruciate oggi, totale scritto a mano: ${intero(bruciate)}` : ''}. `
    + 'Le calorie bruciate non cambiano l\'obiettivo del giorno.');
  // i passi dall'app Salute dell'iPhone, se il comando li manda
  const passiOggi = passiDel(d), passiIeri = passiDel(piuGiorni(d, -1));
  if (passiOggi != null || passiIeri != null) r.push(`Passi (dall'iPhone): ${[passiOggi != null ? `oggi ${passiOggi}` : null, passiIeri != null ? `ieri ${passiIeri}` : null].filter(Boolean).join(', ')}.`);
  r.push(`Conti di oggi, già fatti dall'app (usa questi numeri, non rifarli): mangiato finora ${intero(t.fatto.kcal)} kcal, proteine ${intero(t.fatto.p)} g, `
    + `carboidrati ${intero(t.fatto.c)} g, grassi ${intero(t.fatto.f)} g; mancano ancora ${intero(Math.max(0, t.ob.kcal - t.fatto.kcal))} kcal e `
    + `${intero(Math.max(0, t.ob.p - t.fatto.p))} g di proteine per arrivare all'obiettivo di oggi (${intero(t.ob.kcal)} kcal, proteine ${intero(t.ob.p)} g). `
    + `Acqua: ${acquaBevuta(d)} ml su ${obiettivoAcqua(d)}.`);
  // l'ora per ultima: e' la riga che cambia sempre
  r.push(`Oggi e' ${dataLunga(d)}, ${d} (giorno ${giornoSett(daIso(d))} della settimana)` + (siAllena() ? `, ${t.tipo === 'train' ? 'giorno di palestra' : 'giorno di riposo'}` : '')
    + `. Ieri era ${piuGiorni(d, -1)}. Sono le ${String(ora.getHours()).padStart(2, '0')}:${String(ora.getMinutes()).padStart(2, '0')}.`);
  const base = `DATI (cambiano di rado)\n${f.join('\n')}\n\nPIANO DI QUESTI GIORNI\n${w.join('\n')}\n\nADESSO\n${r.join('\n')}`.slice(0, 16000);
  return livello === 'tutto' ? `${base}\n\n${mondo()}`.slice(0, 58000) : base;
}

// La domanda chiede di cambiare qualcosa che sta solo nei dati completi (obiettivi, quantita', schede, orari, sezioni
// dell'app) o di registrare una seduta? Allora partono subito, senza far fare all'assistente un giro a vuoto per
// chiederli. Deve essere una scelta sicura, non larga: se qui sfugge qualcosa li chiede lui ({"serve": "tutto"}), e
// costa solo una domanda leggera in piu'; mandarli quando non servono costa il triplo ogni volta.
const VERBI = /(cambia|modific|sostitu|togli|aggiung|porta|aument|diminu|riduc|abbass|alza|sposta|elimin|rimuov|imposta|nascond|\bcrea|inventa)/i;
const COSE = /(calori|kcal|obiettiv|grammi|quantit|porzion|ingredient|sched[ae]|eserciz|\bserie\b|ripetizion|allenament|orari|\bora\b|spuntin|schermata|sezion|impostazion|sedut|spesa)/i;
const SEDUTA = /(ho fatto|segna)\w*\b.{0,40}(sched[ae]|sedut|allenament)/i;
const serveTutto = (testo) => (VERBI.test(testo) && COSE.test(testo)) || SEDUTA.test(testo);

// Quello che si rimanda al servizio di un messaggio gia' scritto: le parole e, per le risposte, cosa e' stato fatto
// davvero nell'app. Cosi' sa se un'azione e' andata a buon fine o e' stata annullata, e non la ripete.
// `conLaFoto`: questa richiesta porta davvero la sua foto (solo la domanda appena fatta).
function perIlServizio(m, conLaFoto = false) {
  const fatti = (m.az || []).map((x) => `${x.t}${!x.ok ? ' (non riuscito)' : x.annullata ? ' (poi annullato dalla persona)' : ''}`);
  // Le foto dei messaggi passati non si rimandano (pesano): resta scritto che c'erano, e che FitAI adesso non le vede.
  // Il 26/10/2026, sentendosi dire "non e' una barretta", ha risposto "la foto mostra una barretta" senza averla davanti.
  const foto = !m.img ? '' : conLaFoto ? '\n[con una foto allegata]' : '\n[qui c\'era una foto: adesso non la vedi più, non dire cosa mostrava]';
  // il codice a barre della foto l'ha letto il telefono: il server ci mette accanto il prodotto (assistente.con_i_codici)
  const codice = m.ean ? `\n[codice a barre nella foto: ${m.ean}]` : '';
  return { r: m.r, t: `${m.t}${foto}${codice}${fatti.length ? `\n[Nell'app: ${fatti.join('; ')}]` : ''}` };
}

// ---------- il testo delle risposte: grassetto ed elenchi, senza mai passare da HTML scritto da altri ----------
function conGrassetto(testo) {
  return testo.split(/(\*\*[^*]+\*\*)/g).filter(Boolean).map((pezzo) => (/^\*\*[^*]+\*\*$/.test(pezzo) ? h('b', null, pezzo.slice(2, -2)) : pezzo.replace(/\*\*/g, '')));
}
function inPagina(testo) {
  const nodi = [];
  let lista = null;
  for (const riga of String(testo).split('\n').map((x) => x.trim())) {
    const punto = /^(?:[-*•]|\d+[.)])\s+(.*)$/.exec(riga);
    if (punto) {
      if (!lista) { lista = h('ul'); nodi.push(lista); }
      lista.append(h('li', null, conGrassetto(punto[1])));
    } else {
      lista = null;
      if (riga) nodi.push(h('p', null, conGrassetto(riga.replace(/^#+\s*/, ''))));
    }
  }
  return nodi;
}

function suggerimenti() {
  const ora = new Date().getHours();
  return [
    ora < 15 ? 'Cosa mangio stasera?' : 'Com\'è andata oggi con le calorie?',
    'Ho mangiato una pizza margherita a cena: segnala',
    'Quante proteine mi mancano oggi?',
    'Domani a cena metti un altro piatto con il salmone',
    siAllena() ? 'Come sto andando con i carichi?' : 'Come faccio a muovermi di più?',
  ];
}

// ---------- chiedere ----------
// Una domanda e' un lavoro del server (POST api/chat con "lavoro"): lui prova chi deve rispondere, uno dopo l'altro
// (io.fila: i servizi con la chiave e, in fondo, l'AI che gira sulla VM), e intanto dice chi sta rispondendo e perche'
// si e' passati a lui; qui si passa a chiedere a che punto e' e poi a prendere la risposta. Tutto questo sta fuori dal
// foglio della chat: se la chat viene chiusa la risposta arriva lo stesso (numeretto sull'icona e avviso), e se viene
// chiusa l'app il numero del lavoro resta sul telefono e alla riapertura si riprende (riprendiAssistente).
let aperto = false;      // il foglio della chat e' in vista
let daLeggere = 0;       // risposte arrivate a chat chiusa
const pausa = (ms) => new Promise((ok) => setTimeout(ok, ms));
const sbagliato = (e) => (navigator.onLine === false && !e.nonPartita ? 'Sei senza rete: riprova quando torna.' : e.message);

// La domanda in corso non resta mai appesa: ogni richiesta al server ha un tempo massimo, e una domanda nuova fa
// lasciar perdere quella di prima (il server la ferma, e la nuova la comprende, perche' parte con la conversazione).
// Il 28/10/2026, in un supermercato con poca rete, una domanda con la foto e' rimasta appesa senza mai arrivare al
// server: l'app aspettava una risposta che non poteva arrivare e non lasciava mandare altro finche' non la si chiudeva.
let incorso = null;      // {ferma: AbortController} della domanda che si sta aspettando

// Una richiesta con un tempo massimo, letta fino in fondo; si interrompe subito se `ferma` dice di lasciar perdere.
async function chiamaConLimite(url, opzioni, ms, ferma) {
  const ac = new AbortController();
  const via = () => ac.abort();
  const sveglia = setTimeout(via, ms);
  ferma?.signal.addEventListener('abort', via);
  try {
    const r = await fetch(url, { ...opzioni, signal: ac.signal });
    return { status: r.status, j: await r.json().catch(() => null) };
  } finally {
    clearTimeout(sveglia);
    ferma?.signal.removeEventListener('abort', via);
  }
}

// Una domanda che non e' partita (niente rete, o una rete cosi' lenta che dopo un minuto non era arrivata) parte da
// sola appena si puo': quando torna la rete, quando si riapre l'app, o al giro dopo mentre e' aperta. Parte con lo
// stesso segno (`q`, l'ora della domanda): se in realta' era arrivata il server riprende lo stesso lavoro invece di
// eseguirla due volte. Dopo RIMANDA_PER, o se nel frattempo e' arrivato altro, si lascia stare.
const DA_RIMANDARE = 'fit-da-mandare';
const RIMANDA_PER = 2 * 3600000;
let fotoDaRimandare = null;   // {q, immagine}: la foto, se nella memoria del telefono non ci stava
function daRimandare(q, immagine) {
  fotoDaRimandare = immagine ? { q, immagine } : null;
  try { localStorage.setItem(DA_RIMANDARE, JSON.stringify({ q, foto: !!immagine, immagine })); } catch {
    try { localStorage.setItem(DA_RIMANDARE, JSON.stringify({ q, foto: !!immagine })); } catch { /* pazienza */ }
  }
}
function giaPartita() {
  fotoDaRimandare = null;
  try { localStorage.removeItem(DA_RIMANDARE); } catch { /* pazienza */ }
}
async function rimandaSeServe() {
  if (occupato || navigator.onLine === false || document.visibilityState === 'hidden') return;
  let v = null;
  try { v = JSON.parse(localStorage.getItem(DA_RIMANDARE) || 'null'); } catch { v = null; }
  if (!v?.q) return;
  const ultima = S.chat[S.chat.length - 1];
  if (ultima?.r !== 'io' || ultima.q !== v.q || Date.now() - v.q > RIMANDA_PER) { giaPartita(); return; }
  const immagine = v.foto ? v.immagine || (fotoDaRimandare?.q === v.q ? fotoDaRimandare.immagine : null) : null;
  if (v.foto && !immagine) return;   // la foto non c'e' piu' (app chiusa): resta il tasto Riprova
  await chiedi(immagine, null, { zitto: true });
}
addEventListener('online', () => { rimandaSeServe(); });
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') rimandaSeServe(); });
setInterval(() => { rimandaSeServe(); }, 20000);

function segnaNonLetti() {
  const bolla = document.getElementById('bolla');
  if (bolla) { if (daLeggere) bolla.dataset.nuovi = String(daLeggere); else delete bolla.dataset.nuovi; }
  try { if (daLeggere) navigator.setAppBadge?.(daLeggere); else navigator.clearAppBadge?.(); } catch { /* non tutti i telefoni lo sanno fare */ }
}
function arrivata(testo, ic) {
  if (aperto) return;
  daLeggere += 1;
  segnaNonLetti();
  avviso(testo, ic, () => apriAssistente());
}

// Aspetta la risposta di un lavoro: lo si chiede ogni secondo e poco piu', aggiornando chi sta rispondendo.
// `ferma`: chi aspetta puo' lasciar perdere (e' arrivata una domanda nuova).
async function ritira(lavoro, inizio, ferma = null) {
  for (let buchi = 0; ;) {
    await pausa(1200);
    if (ferma?.signal.aborted) return { codice: 0, j: {} };
    let q = null, perso = false;
    try {
      const rr = await chiamaConLimite(`api/chat/lavoro/${lavoro}`, { cache: 'no-store' }, 15000, ferma);
      perso = rr.status === 404;
      q = rr.j;
    } catch { q = null; }
    if (ferma?.signal.aborted) return { codice: 0, j: {} };
    if (perso) { dimentica(); return { codice: 404, j: { errore: 'La risposta è andata persa: rifai la domanda.' } }; }
    if (!q) {   // un momento senza rete: il lavoro intanto va avanti sul server, si riprova
      if (++buchi > 50) return { codice: 0, j: { errore: 'Sei senza rete: riapri FitAI quando torna, la risposta ti aspetta.' } };
      continue;
    }
    buchi = 0;
    if (!q.in_corso) { dimentica(); return { codice: q.codice || 200, j: q }; }
    const secondi = Math.round((Date.now() - inizio) / 1000);
    corsa.chi = q.chi || null;
    corsa.aspetto = q.aspetto ? `Hanno tutti troppe richieste: riprovo tra ${q.aspetto} secondi…` : null;
    corsa.nota = [q.nota, q.chi === 'locale' ? `è più lenta: ${secondi < 80 ? 'può volerci un minuto' : 'sta rileggendo i tuoi dati, ci vuole ancora un po\''} · ${tempo(secondi)}` : null].filter(Boolean).join(' · ') || null;
    ridisegna();
  }
}

// La risposta e' arrivata: prima si fa quello che ha chiesto di fare, poi la si scrive con accanto com'e' andata.
// `giorno` e' il giorno in cui e' stata fatta la domanda: se la risposta si ritira il giorno dopo, quello che c'era
// da segnare va segnato li'. `per` e' l'ora della domanda: la stessa risposta due volte (domanda rimandata che il
// server aveva gia' finito) non rifa' le azioni.
function concludi(j, giorno, per = null) {
  if (per != null && S.chat.some((m) => m.r === 'ai' && m.per === per)) return;
  const allora = giorno && giorno !== oggi() ? giorno : null;
  const delGiorno = ['mangiato', 'pasto_fatto', 'togli_voce', 'acqua', 'movimento'];
  const az = (Array.isArray(j.azioni) ? j.azioni : []).map((a) => esegui(allora && !a.giorno && delGiorno.includes(a.tipo) ? { ...a, giorno: allora } : a));
  // quello che ha detto di fare ma non e' arrivato in una forma eseguibile: va detto, altrimenti resta un "fatto" falso
  if (j.scartate) az.push({ ok: false, t: j.scartate > 1 ? `${j.scartate} cose che voleva fare erano scritte male: non le ho eseguite` : 'Una cosa che voleva fare era scritta male: non l\'ho eseguita', u: null });
  if (j.vuoto) az.push({ ok: false, t: 'Dice di averlo fatto, ma non ha mandato niente da eseguire: non è cambiato niente', u: null });
  // La frase l'ha scritta prima che si provasse a fare le cose: il 28/10/2026 diceva "Tolta la barretta" sopra l'avviso
  // "Non trovo quella voce". Se non e' riuscito niente la frase la scrive l'app, se e' riuscito solo un pezzo lo dice.
  const riuscite = az.filter((x) => x.ok).length;
  const testo = az.length && !riuscite ? `Non ho cambiato niente: ${az.map((x) => x.t).join('; ')}.`
    : riuscite < az.length ? `${j.testo}\n\nNon è riuscito tutto: guarda qui sotto.` : j.testo;
  if (riuscite) colpetto();
  const leggero = /lite|small|ministral/i.test(j.modello || '') && j.motore !== 'locale';   // ("mini" no: c'e' in "gemini")
  aggiorna((s) => {
    s.chat.push({ r: 'ai', t: testo, q: Date.now(), ...(per != null ? { per } : {}), ...(j.motore ? { chi: j.motore } : {}), ...(leggero ? { mod: 'leggero' } : {}), ...(az.length ? { az } : {}) });
    if (s.chat.length > DA_TENERE) s.chat.splice(0, s.chat.length - DA_TENERE);
  }, true);
  arrivata('FitAI ti ha risposto', 'sparkle');
}

// Fa la domanda che sta in fondo alla conversazione. `immagine` e' la foto che l'accompagna, se c'e'. Se ce n'era
// gia' una in corso la si lascia perdere: risponde a questa, che porta con se' anche quella. `zitto`: nessun avviso se
// non va (la rimanda l'app da sola, vedi rimandaSeServe).
async function chiedi(immagine = null, alFatto = null, { zitto = false } = {}) {
  incorso?.ferma.abort();
  const mia = { ferma: new AbortController() };
  incorso = mia;
  occupato = true; Object.assign(corsa, { chi: null, nota: null, aspetto: null, errore: null }); ridisegna();
  const ultima = [...S.chat].reverse().find((m) => m.r === 'io');
  try {
    // lo stato e il piano interi partono sempre (mondo): il server li usa solo se la domanda li richiede
    const corpo = JSON.stringify({ lavoro: true, id: ultima?.q ? String(ultima.q) : undefined,
      livello: serveTutto(ultima?.t || '') ? 'tutto' : 'base', contesto: contesto('base'), mondo: mondo(), ids: idsAssistente(),
      messaggi: S.chat.slice(-DA_MANDARE).map((m, i, tutti) => perIlServizio(m, !!immagine && i === tutti.length - 1)), ...(immagine ? { immagine } : {}) });
    let r;
    try {
      // con una foto, su una rete lenta, la domanda pesa: le si lascia un minuto per arrivare
      r = await chiamaConLimite('api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: corpo }, immagine ? 60000 : 30000, mia.ferma);
    } catch {
      if (mia.ferma.signal.aborted) return;
      if (ultima?.q) daRimandare(ultima.q, immagine);
      throw Object.assign(new Error('Non è partita: c\'è poca rete. La mando da sola appena si può.'), { nonPartita: true });
    }
    if (r.status !== 202 || !r.j?.lavoro) throw new Error(r.j?.errore || 'Non sono riuscito a rispondere.');
    giaPartita();
    const inizio = Date.now();
    ricorda({ n: r.j.lavoro, da: inizio, q: ultima?.q, g: oggi() });
    corsa.chi = (r.j.fila || io.fila || [])[0] || null; ridisegna();
    const esito = await ritira(r.j.lavoro, inizio, mia.ferma);
    if (mia.ferma.signal.aborted) return;
    if (esito.codice !== 200) throw new Error(esito.j.errore || 'Non sono riuscito a rispondere.');
    concludi(esito.j, null, ultima?.q ?? null);
    alFatto?.();
  } catch (e) {
    if (mia.ferma.signal.aborted) return;
    corsa.errore = sbagliato(e);
    if (!zitto) arrivata('FitAI non è riuscito a rispondere', 'info');
  } finally {
    if (incorso === mia) {
      incorso = null;
      occupato = false; Object.assign(corsa, { chi: null, nota: null, aspetto: null });
      ridisegna();
    }
  }
}

// All'avvio dell'app e all'apertura della chat: c'e' una risposta ancora da ritirare per l'ultima domanda (l'app era
// stata chiusa mentre FitAI lavorava)? Allora si riprende ad aspettarla, o la si prende se e' gia' pronta. Se invece
// la domanda non era partita, parte adesso.
export async function riprendiAssistente() {
  let v = null;
  try { v = JSON.parse(localStorage.getItem(LAVORO) || 'null'); } catch { v = null; }
  if (occupato) return;
  const ultimo = S.chat[S.chat.length - 1];
  if (!v?.n || Date.now() - v.da > 6 * 3600000 || ultimo?.r !== 'io' || ultimo.q !== v.q) {
    if (v?.n) dimentica();
    rimandaSeServe();
    return;
  }
  const mia = { ferma: new AbortController() };
  incorso = mia;
  occupato = true; Object.assign(corsa, { chi: null, nota: null, aspetto: null, errore: null }); ridisegna();
  try {
    const esito = await ritira(v.n, v.da, mia.ferma);
    if (mia.ferma.signal.aborted) return;
    if (esito.codice !== 200) throw new Error(esito.j.errore || 'Non sono riuscito a rispondere.');
    concludi(esito.j, v.g, v.q);
  } catch (e) {
    if (mia.ferma.signal.aborted) return;
    corsa.errore = sbagliato(e);
  } finally {
    if (incorso === mia) {
      incorso = null;
      occupato = false; Object.assign(corsa, { chi: null, nota: null, aspetto: null });
      ridisegna();
    }
  }
}

export function apriAssistente() {
  aperto = true; daLeggere = 0; segnaNonLetti();
  // Questi tre pezzi si creano una volta e restano gli stessi a ogni ridisegno del foglio: la conversazione si aggiorna
  // toccando solo l'elenco, cosi' il campo non perde il fuoco e la tastiera non si chiude mentre arriva la risposta.
  const elenco = h('div', { class: 'chat-elenco' });
  const campo = h('textarea', { rows: 1, placeholder: 'Scrivi una domanda', 'aria-label': 'La tua domanda', enterkeyhint: 'send', maxlength: 1500 });
  const tasto = h('button', { class: 'manda', 'aria-label': 'Manda' }, icona('send'));
  const nuovaChat = h('button', { class: 'nuova-chat', 'aria-label': 'Cancella la conversazione e ricomincia da capo' }, icona('trash'), 'Nuova');
  // un tocco sul vuoto della conversazione chiude la tastiera
  elenco.addEventListener('click', (e) => { if (!e.target.closest('button, a')) campo.blur(); });
  // La foto da mandare con il prossimo messaggio: un piatto, un'etichetta, uno scontrino, una schermata. `dati` e' il
  // JPEG rimpicciolito che va al servizio una volta sola; `mini` la miniatura che resta nella conversazione.
  const scatto = h('input', { type: 'file', accept: 'image/*', hidden: true });
  const allega = h('button', { class: 'allega', 'aria-label': 'Aggiungi una foto' }, icona('camera'));
  const anteprima = h('div', { class: 'chat-foto' });
  let foto = null;        // {dati, mini}
  let daMandare = null;   // la foto del messaggio appena mandato, finche' il servizio non ha risposto
  const mostraFoto = () => {
    anteprima.replaceChildren(...(foto ? [
      h('img', { src: `data:image/jpeg;base64,${foto.mini}`, alt: 'La foto che stai per mandare' }),
      h('span', null, foto.ean ? `Codice a barre ${foto.ean}: FitAI prende il prodotto dal catalogo` : 'Foto pronta: scrivi cosa vuoi sapere, o manda così'),
      h('button', { 'aria-label': 'Togli la foto', onclick: () => { foto = null; mostraFoto(); } }, icona('x')),
    ] : []));
    anteprima.hidden = !foto;
    campo.placeholder = foto ? 'Cosa vuoi sapere di questa foto?' : 'Scrivi una domanda';
  };
  allega.addEventListener('click', () => scatto.click());
  scatto.addEventListener('change', async () => {
    const file = scatto.files?.[0];
    scatto.value = '';
    if (!file) return;
    try {
      const questa = { dati: await rimpicciolisci(file, 1280, 0.8), mini: await rimpicciolisci(file, 220, 0.6) };
      // Il codice a barre, se nella foto c'e', lo legge il telefono (come lo scanner del diario): le cifre FitAI non
      // le sa leggere, e il 28/10/2026 ha preso una barretta Nesquik per quella del piano. Il server cerca il prodotto.
      questa.codice = leggiFoto(file).catch(() => null);
      questa.codice.then((c) => { questa.ean = c || null; if (foto === questa) mostraFoto(); });
      foto = questa;
      mostraFoto();
      campo.focus();
    } catch (e) { avviso(e.message || 'Non riesco a leggere questa foto', 'info'); }
  });

  const inFondo = () => { const c = elenco.closest('.corpo'); if (c) c.scrollTop = c.scrollHeight; };
  const disegnaElenco = () => {
    // sotto ogni risposta, quello che l'assistente ha fatto nell'app: una riga per cosa, con il tasto per annullarla
    const fatto = (m, i) => {
      const x = m.az[i];
      return h('div', { class: `fatto-ai${x.ok ? '' : ' no'}${x.annullata ? ' annullata' : ''}` },
        h('span', { class: 'ic' }, icona(x.ok ? (x.annullata ? 'x' : 'check') : 'info')),
        h('span', { class: 'cresce' }, x.t),
        x.ok && x.u && !x.annullata ? h('button', { onclick: () => {
          colpetto();
          if (!annulla(x.u)) { avviso('Non riesco ad annullarlo: guarda nel diario', 'info'); return; }
          // la conversazione puo' essere stata ricaricata dal server nel frattempo: il messaggio si ritrova dall'ora
          aggiorna((s) => { const vero = s.chat.find((y) => y.r === 'ai' && y.q === m.q)?.az?.[i]; if (vero) vero.annullata = true; }, true);
          avviso('Annullato', 'check');
          disegnaElenco();
        } }, 'Annulla') : null);
    };
    const voci = S.chat.flatMap((m) => [
      ...(m.r === 'ai' && m.chi ? [h('div', { class: 'chi-risponde' }, nomeDi(m.chi, m.mod === 'leggero'))] : []),
      h('div', { class: `fumetto ${m.r}${m.img ? ' con-foto' : ''}` },
        m.img ? h('img', { src: `data:image/jpeg;base64,${m.img}`, alt: 'Foto allegata' }) : null,
        m.r === 'ai' ? inPagina(m.t) : m.t),
      ...(m.az || []).map((_, i) => fatto(m, i)),
    ]);
    if (!S.chat.length) {
      voci.push(h('div', { class: 'chat-vuota' },
        h('span', { class: 'bolla-grande' }, icona('sparkle')),
        h('b', null, `Ciao ${io.nome}, chiedimi quello che vuoi`),
        h('p', null, 'Conosco il tuo piano, cosa hai mangiato oggi, i tuoi allenamenti e le tue pesate. E le cose le faccio io: dimmi cosa hai mangiato e lo segno, chiedimi di cambiare un piatto, le quantità, gli obiettivi, la scheda. Puoi anche mandarmi una foto.'),
        h('div', { class: 'chat-idee' }, suggerimenti().map((t) => h('button', { class: 'scelta', onclick: () => manda(t) }, t)))));
    }
    if (occupato) {
      // sopra i puntini: chi sta rispondendo adesso e, se si e' passati da uno all'altro, perche'
      if (corsa.chi) voci.push(h('div', { class: 'chi-risponde' }, nomeDi(corsa.chi), corsa.nota ? h('small', null, corsa.nota) : null));
      voci.push(corsa.aspetto ? h('div', { class: 'fumetto ai attesa' }, corsa.aspetto) : h('div', { class: 'fumetto ai scrive', 'aria-label': 'Sta scrivendo' }, h('i'), h('i'), h('i')));
    }
    if (corsa.errore && !occupato) voci.push(h('div', { class: 'fumetto errore' }, corsa.errore, h('button', { onclick: () => { corsa.errore = null; chiediQui(); } }, 'Riprova')));
    elenco.replaceChildren(...voci);
    inFondo();
  };
  ridisegna = disegnaElenco;   // da adesso chi sta aspettando una risposta ridisegna questo foglio

  // la domanda parte da qui con la foto di questo foglio, se c'e' (con "Riprova" la foto si rimanda)
  const chiediQui = () => chiedi(daMandare, () => { daMandare = null; });

  // Si puo' scrivere anche mentre FitAI sta rispondendo: la domanda nuova parte subito con tutta la conversazione, e
  // quella di prima non la si aspetta piu' (prima il tasto restava spento, e con una domanda appesa restava spento).
  async function manda(testo) {
    const conFoto = testo == null ? foto : null;   // i suggerimenti gia' pronti partono senza foto
    const t = String(testo ?? campo.value).trim() || (conFoto ? 'Guarda questa foto.' : '');
    if (!t) return;
    colpetto();
    campo.value = ''; campo.style.height = '';
    const q = Date.now();
    aggiorna((s) => { s.chat.push({ r: 'io', t, q, ...(conFoto ? { img: conFoto.mini } : {}) }); }, true);
    if (conFoto) { foto = null; mostraFoto(); }
    disegnaElenco();
    // il codice a barre della foto: se il telefono lo sta ancora leggendo lo si aspetta un momento
    const ean = conFoto ? conFoto.ean ?? await Promise.race([conFoto.codice, pausa(2500).then(() => null)]) : null;
    if (ean) aggiorna((s) => { const m = s.chat.find((x) => x.r === 'io' && x.q === q); if (m) m.ean = ean; }, true);
    daMandare = conFoto ? conFoto.dati : null;
    chiediQui();
  }
  campo.addEventListener('input', () => { campo.style.height = ''; campo.style.height = `${Math.min(120, campo.scrollHeight)}px`; });
  campo.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); manda(); } });
  tasto.addEventListener('click', () => { manda(); campo.focus(); });
  // sempre in vista: cancella la conversazione e si riparte da capo (quello che FitAI ha gia' segnato nel diario resta)
  nuovaChat.addEventListener('click', () => {
    if (!S.chat.length && !corsa.errore) { avviso('La conversazione è già vuota', 'info'); return; }
    conferma({
      titolo: 'Ricominciare da capo?', testo: 'La conversazione viene cancellata. Quello che FitAI ha già segnato o cambiato resta com\'è.',
      azioni: [{ t: 'Cancella la conversazione', tipo: 'rosso', fai: () => {
        // anche a meta' di una risposta: quella non la si aspetta piu'
        incorso?.ferma.abort(); incorso = null;
        occupato = false; Object.assign(corsa, { chi: null, nota: null, aspetto: null, errore: null });
        aggiorna((s) => { s.chat = []; }, true); daMandare = null; dimentica(); giaPartita(); disegnaElenco();
      } }, { t: 'Annulla' }],
    });
  });
  mostraFoto();

  const f = foglio((api) => {
    if (!io.ai) {
      return [
        h('div', { class: 'chat-vuota', style: { padding: '26px 6px 10px' } },
          h('span', { class: 'bolla-grande' }, icona('sparkle')),
          h('b', null, 'FitAI è spento'),
          h('p', null, 'È l\'assistente dell\'app: risponde alle tue domande su dieta e allenamento conoscendo il tuo piano. Per accenderlo serve una chiave gratuita di Google, da incollare una volta sola.')),
        h('button', { class: 'btn primo', onclick: () => {
          api.chiudi();
          location.hash = '#/altro';
          setTimeout(() => document.getElementById('carta-ai')?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 450);
        } }, icona('key'), 'Accendilo adesso'),
      ];
    }
    return [
      h('div', { class: 'chat-testa' },
        h('span', { class: 'bolla-piccola' }, icona('sparkle')),
        h('div', { class: 'cresce' }, h('b', null, 'FitAI'), h('small', null, 'Risponde e segna per te')),
        nuovaChat),
      elenco,
      h('div', { class: 'chat-scrivi' }, anteprima, scatto, allega, campo, tasto),
    ];
  }, { classe: 'chat', alChiudere: () => { aperto = false; } });
  disegnaElenco();
  setTimeout(inFondo, 60);
  riprendiAssistente();
  // Se in fondo alla fila c'e' l'AI che gira sulla VM, intanto le si fa leggere la parte ferma del contesto: le ci
  // vuole qualche minuto, e cosi' se poi tocca a lei non parte da capo. Se non e' cambiato niente non costa niente.
  if (io.fila?.includes('locale') && !occupato) {
    fetch('api/chat/scalda', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ contesto: contesto('base') }) }).catch(() => {});
  }
  return f;
}
