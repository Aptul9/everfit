// La seduta guidata, un esercizio per volta. I numeri sono gia' scritti: l'app propone carico e ripetizioni
// partendo dall'ultima volta (store.js, proposte), e a chi li ha fatti basta toccare "Serie fatta".

import { h, s, icona, minSec, numero, intero, dec, durata, dataCorta, inCima, colpetto } from '../dom.js';
// (la modalita' a tutto schermo e' in fondo al file: apriImmersione)
import { P, S, aggiorna, proposte, serieProposte, intervallo, passoCarico, concludiSeduta } from '../store.js';
import { animazione, filmato, vuoleVideo, levaVideo, foglio, conferma, avviso, coriandoli, sbloccaAudio, bip } from '../ui.js';
import { apriEsercizio } from './allenamento.js';

let orologio = null;
let blocco = null;
let rifai = () => {};
const crono = { k: null, es: null, t0: 0 };
const GIRO = 2 * Math.PI * 21;

const tempoRec = (sec) => (sec >= 60 ? `${minSec(sec)}` : `${sec} s`);

async function tieniSveglio() {
  try { if (!blocco && navigator.wakeLock) blocco = await navigator.wakeLock.request('screen'); } catch { blocco = null; }
}

function battito() {
  const a = S.attiva;
  if (!a) return;
  const el = document.querySelector('[data-tempo]');
  if (el) el.textContent = minSec((Date.now() - a.inizio) / 1000);
  if (crono.k != null) {
    const campo = document.querySelector('[data-rip]');
    if (campo) campo.value = Math.floor((Date.now() - crono.t0) / 1000);
  }
  const r = a.riposo;
  const barra = document.querySelector('.recupero');
  if (!r || !barra) return;
  const resta = (r.fine - Date.now()) / 1000;
  const t = barra.querySelector('[data-resta]');
  const c = barra.querySelector('[data-cerchio]');
  if (resta > 0) {
    t.textContent = minSec(Math.ceil(resta));
    c.setAttribute('stroke-dashoffset', GIRO * (1 - resta / r.tot));
  } else {
    t.textContent = 'Via';
    c.setAttribute('stroke-dashoffset', 0);
    if (!r.suonato) {
      r.suonato = true;
      barra.classList.add('fine');
      barra.querySelector('[data-titolo]').textContent = 'Recupero finito';
      if (S.opzioni.suono !== false) bip();
    }
    if (resta < -6) { aggiorna((st) => { if (st.attiva) st.attiva.riposo = null; }, true); barra.remove(); }
  }
}

// Segna fatta la serie k dell'esercizio v con quei numeri: le serie che restano prendono lo stesso carico, parte il
// recupero, e i chili restano scritti per quell'esercizio (S.carichi): la prossima volta sono gia' li', anche se la
// seduta di oggi non viene conclusa.
function serieFatta(v, k, kg, rip) {
  const a = S.attiva, e = P.esercizi[v.es];
  const ultimo = a.i === a.voci.length - 1;
  aggiorna((st) => {
    const q = v.serie[k];
    q.kg = kg; q.rip = Math.round(rip); q.ok = true;
    for (let j = k + 1; j < v.serie.length; j++) {
      const dopo = v.serie[j];
      if (dopo.ok) continue;
      if (kg != null) dopo.kg = kg;                                        // stesso carico per le serie che restano
      if (!e.tempo && (dopo.rip == null || q.rip < dopo.rip)) dopo.rip = q.rip;   // se ne hai fatte meno, dopo non ne farai di piu'
    }
    if (kg != null && !e.tempo && !e.corpo) { st.carichi = st.carichi || {}; st.carichi[v.es] = { kg, rip: q.rip, d: a.d }; }
    const finito = v.serie.every((x) => x.ok) && ultimo;
    st.attiva.riposo = finito || !v.rec ? null : { fine: Date.now() + v.rec * 1000, tot: v.rec, suonato: false };
  });
}

export function lasciaSeduta() {
  chiudiImmersione();
  clearInterval(orologio); orologio = null;
  crono.k = null;
  blocco?.release?.().catch(() => {});
  blocco = null;
}

function festa(esito) {
  const casa = !!P.schede[esito.seduta.w]?.casa;
  coriandoli();
  foglio(() => [
    h('div', { class: 'festa' },
      h('div', { class: 'coppa' }, icona('trophy')),
      h('h2', { style: { marginTop: '8px' } }, casa ? 'Circuito completato' : 'Seduta completata'),
      h('p', { class: 'muto' }, `${P.schede[esito.seduta.w]?.n || ''} · ${dataCorta(esito.seduta.d)}`)),
    h('div', { class: 'tre-col' },
      h('div', { class: 'stat' }, h('b', null, durata(esito.seduta.fine - esito.seduta.inizio)), h('span', null, 'durata')),
      h('div', { class: 'stat' }, h('b', null, esito.serie), h('span', null, 'serie')),
      esito.volume ? h('div', { class: 'stat' }, h('b', null, intero(esito.volume)), h('span', null, 'kg totali'))
        : h('div', { class: 'stat' }, h('b', null, esito.seduta.voci.length), h('span', null, 'esercizi'))),
    esito.record.length ? h('h4', null, 'Nuovi record') : null,
    esito.record.map((r) => h('div', { class: 'ultima su' }, icona('trend'), h('span', null, `${P.esercizi[r.es].n}: `, h('b', null, `${dec(r.kg)} kg × ${r.rip}`)))),
    h('div', { class: 'nota' }, icona('bolt'), h('span', null, P.profilo.shake !== false && !casa
      ? 'Adesso lo shake con la creatina, poi la cena del piano entro un\'ora.'
      : 'Bevi un bicchiere d\'acqua. Il prossimo pasto del piano fa già il suo lavoro.')),
  ]);
}

function chiudi() {
  const fatte = S.attiva.voci.reduce((n, x) => n + x.serie.filter((q) => q.ok).length, 0);
  conferma({
    titolo: 'Seduta in pausa?',
    testo: fatte ? `Hai fatto ${fatte} serie. Puoi riprendere più tardi da dove sei rimasto.` : 'Non hai ancora segnato nessuna serie.',
    azioni: [
      { t: 'Continua dopo', tipo: 'primo', fai: () => { location.hash = '#/allenamento'; } },
      fatte ? { t: 'Concludi e salva', fai: concludi } : null,
      { t: 'Elimina la seduta', tipo: 'rosso', fai: () => { aggiorna((st) => { st.attiva = null; }); location.hash = '#/allenamento'; } },
    ].filter(Boolean),
  });
}

function concludi() {
  const esito = concludiSeduta();
  location.hash = '#/oggi';
  if (esito) setTimeout(() => festa(esito), 380);
  else avviso('Nessuna serie segnata', 'info');
}

function cambiaEsercizio(v) {
  const base = P.esercizi[v.base];
  const scelte = [v.base, ...base.alt].filter((id) => id !== v.es);
  if (!scelte.length) { avviso('Nessuna alternativa per questo esercizio', 'info'); return; }
  const f = foglio(() => [
    h('h2', null, 'Cambia esercizio'),
    h('p', { class: 'muto' }, 'Stesso muscolo, attrezzo diverso. Vale solo per oggi.'),
    scelte.map((id) => h('button', { class: 'card es tocco', onclick: () => {
      aggiorna(() => {
        // i numeri proposti sono quelli dell'esercizio nuovo: le serie gia' fatte restano com'erano
        const nuove = serieProposte(id, v.rip, v.serie.length);
        v.es = id;
        v.serie.forEach((q, k) => { if (!q.ok) { q.kg = nuove[k].kg; q.rip = nuove[k].rip; } });
      });
      f.chiudi();
    } }, animazione(id), h('div', { class: 'cresce' }, h('h3', null, P.esercizi[id].n), h('div', { class: 'piccolo' }, P.esercizi[id].att)), id === v.base ? h('span', { class: 'chip' }, 'Originale') : null)),
  ]);
}

// Come si scrive una serie: "22,5 kg × 10", "12 ripetizioni", "45 s".
function inParole(e, q, lungo = false) {
  if (e.tempo) return q.rip ? `${q.rip} s` : '–';
  if (e.corpo || q.kg == null) return q.rip ? `${q.rip}${lungo ? ' ripetizioni' : ' rip.'}` : '–';
  return `${dec(q.kg, 2)} kg × ${q.rip ?? '–'}`;
}

// Tutte le serie dell'ultima volta in poche parole: "4 serie da 20 kg × 10", "40 kg × 10, 9, 8, 8", "3 × 40 s".
function riassunto(e, serie) {
  const rip = serie.map((x) => x.rip);
  const uguali = (lista) => lista.every((x) => x === lista[0]);
  const n = serie.length;
  if (e.tempo) return uguali(rip) && n > 1 ? `${n} × ${rip[0]} s` : `${rip.join(', ')} s`;
  const kg = serie.map((x) => x.kg);
  if (e.corpo || kg.every((x) => x == null)) return uguali(rip) && n > 1 ? `${n} serie da ${rip[0]}` : `${rip.join(', ')} ripetizioni`;
  if (!uguali(kg)) return serie.map((x) => inParole(e, x)).join(' · ');
  return uguali(rip) && n > 1 ? `${n} serie da ${dec(kg[0], 2)} kg × ${rip[0]}` : `${dec(kg[0], 2)} kg × ${rip.join(', ')}`;
}

export function vistaSeduta(_, ridisegna) {
  rifai = ridisegna;
  const a = S.attiva;
  if (!a) { setTimeout(() => { if (location.hash.startsWith('#/seduta')) location.hash = '#/allenamento'; }); return []; }
  if (!orologio) orologio = setInterval(battito, 250);
  tieniSveglio();

  const v = a.voci[a.i];
  const e = P.esercizi[v.es];
  const [minRip, maxRip] = intervallo(v.rip);
  const idea = proposte(v.es, v.rip, v.serie.length, v.kgScheda ?? null);
  const esperto = S.profilo?.livello === 'esperto';
  const prima = a.i === 0, ultimo = a.i === a.voci.length - 1;
  const tutteFatte = v.serie.every((q) => q.ok);
  const k = v.serie.findIndex((q) => !q.ok);     // la serie su cui si sta lavorando
  const q = k >= 0 ? v.serie[k] : null;
  if (crono.es !== v.es) crono.k = null;

  const vai = (i) => { aggiorna((st) => { st.attiva.i = i; }); crono.k = null; inCima(); rifai(true); };

  // ---- la serie di adesso: due numeri gia' scritti, da ritoccare con + e - o scrivendoci sopra
  const campoKg = q && !e.tempo && !e.corpo ? h('input', {
    'data-kg': '', type: 'text', inputmode: 'decimal', autocomplete: 'off', enterkeyhint: 'done',
    value: q.kg != null ? dec(q.kg, 2) : '', placeholder: '–', 'aria-label': 'Chili',
    oninput: (ev) => aggiorna(() => { q.kg = numero(ev.target.value); }, true),
  }) : null;
  const campoRip = q ? h('input', {
    'data-rip': '', type: 'text', inputmode: 'numeric', autocomplete: 'off', enterkeyhint: 'done',
    value: q.rip ?? '', placeholder: minRip || '–', 'aria-label': e.tempo ? 'Secondi' : 'Ripetizioni',
    oninput: (ev) => aggiorna(() => { q.rip = numero(ev.target.value); }, true),
  }) : null;
  const sposta = (campo, chiave, passo, minimo = 0) => () => {
    colpetto();
    const ora = numero(campo.value);
    // dal vuoto il primo tocco porta a un valore sensato, non a 1
    const nuovo = ora == null ? (chiave === 'rip' ? (minRip || 10) : Math.max(passo, 0)) : Math.max(minimo, Math.round((ora + passo) * 100) / 100);
    campo.value = chiave === 'kg' ? dec(nuovo, 2) : nuovo;
    aggiorna(() => { q[chiave] = nuovo; }, true);
  };
  // il passo si calcola al tocco, non prima: quello dei chili dipende da quanti ce ne sono scritti in quel momento
  const regolo = (campo, chiave, etichetta, passo) => h('div', { class: 'regolo' },
    h('span', null, etichetta),
    h('div', null,
      h('button', { 'aria-label': `Meno ${etichetta}`, onclick: () => sposta(campo, chiave, -passo(), chiave === 'rip' ? 1 : 0)() }, icona('minus')),
      campo,
      h('button', { 'aria-label': `Più ${etichetta}`, onclick: () => sposta(campo, chiave, passo())() }, icona('plus'))));

  const segna = () => {
    sbloccaAudio();
    const kg = campoKg ? numero(campoKg.value) : null;
    const rip = numero(campoRip.value) ?? numero(campoRip.placeholder);
    if (!rip) { campoRip.focus(); avviso(e.tempo ? 'Scrivi i secondi' : 'Scrivi le ripetizioni', 'info'); return; }
    if (campoKg && kg == null) { campoKg.focus(); avviso('Scrivi i chili', 'info'); return; }
    colpetto();
    crono.k = null;
    serieFatta(v, k, kg, rip);
  };

  const cronometro = e.tempo && q ? h('button', { class: `btn basso crono${crono.k === k ? ' va' : ''}`, onclick: () => {
    sbloccaAudio();
    if (crono.k === k) { crono.k = null; aggiorna(() => { q.rip = numero(campoRip.value); }, true); } else { crono.k = k; crono.es = v.es; crono.t0 = Date.now(); }
    rifai();
  } }, icona(crono.k === k ? 'pause' : 'timer'), crono.k === k ? 'Ferma il cronometro' : 'Cronometro') : null;

  const eraCosi = idea.ultima ? (idea.ultima.serie[k] || idea.ultima.serie[idea.ultima.serie.length - 1]) : null;
  const serieOra = q ? h('div', { class: 'card serie-ora' },
    h('div', { class: 'fra' },
      h('b', null, `Serie ${k + 1} di ${v.serie.length}`),
      eraCosi ? h('span', { class: 'piccolo' }, `l'altra volta ${inParole(e, eraCosi)}`) : h('span', { class: 'piccolo' }, `obiettivo ${v.rip}`)),
    h('div', { class: `regoli${campoKg ? '' : ' uno'}` },
      campoKg ? regolo(campoKg, 'kg', 'kg', () => passoCarico(numero(campoKg.value) || 0)) : null,
      regolo(campoRip, 'rip', e.tempo ? 'secondi' : 'ripetizioni', () => (e.tempo ? 5 : 1))),
    cronometro,
    // a tutto schermo: il righello dei chili, il tempo e un solo tasto (vedi apriImmersione)
    h('button', { class: 'btn primo', onclick: () => { sbloccaAudio(); colpetto(); apriImmersione(); } }, icona('play'), 'Inizia la serie'),
    h('button', { class: 'btn basso', onclick: segna }, icona('check'), 'Già fatta: segnala e basta')) : null;

  // ---- tutte le serie, in piccolo: quelle fatte, quella di adesso, quelle che aspettano con i numeri proposti
  const elenco = h('div', { class: 'serie-lista' }, v.serie.map((x, i) =>
    h('button', { class: `serie-riga${x.ok ? ' fatta' : i === k ? ' ora' : ''}`, 'aria-label': x.ok ? `Serie ${i + 1} fatta: tocca per correggerla` : `Serie ${i + 1}`,
      onclick: () => { if (x.ok) { colpetto(); aggiorna((st) => { x.ok = false; st.attiva.riposo = null; }); } } },
      h('span', { class: 'n' }, i + 1),
      h('span', { class: 'cosa' }, inParole(e, x, true)),
      x.ok ? s('svg', { viewBox: '0 0 24 24', class: 'fatto' }, s('path', { d: 'M5 12.500l4.500 4.500L19 7.500' })) : h('small', null, i === k ? 'adesso' : 'dopo'))));

  // ---- scorciatoie: rifare l'ultima volta, segnarle tutte, una serie in piu' o in meno
  const restano = v.serie.filter((x) => !x.ok).length;
  const comeAllora = () => {
    aggiorna(() => {
      v.serie.forEach((x, i) => { if (x.ok) return; const u = idea.ultima.serie[i] || idea.ultima.serie[idea.ultima.serie.length - 1]; x.kg = u.kg ?? null; x.rip = u.rip; });
    });
    avviso('Numeri dell\'ultima volta', 'copy');
  };
  const tutte = () => {
    if (v.serie.some((x) => !x.ok && (!x.rip || (!e.tempo && !e.corpo && x.kg == null)))) { avviso('Mancano dei numeri: scrivili nella serie di adesso', 'info'); return; }
    colpetto();
    aggiorna((st) => { v.serie.forEach((x) => { x.ok = true; }); st.attiva.riposo = null; });
  };
  const sali = () => {
    aggiorna(() => { v.serie.forEach((x) => { if (!x.ok && x.kg != null) x.kg = Math.round((x.kg + passoCarico(x.kg)) * 100) / 100; }); });
    avviso('Carico aumentato', 'trend');
  };
  const scorciatoie = h('div', { class: 'scorri' },
    idea.mossa === 'fisso' && restano ? h('button', { class: 'scelta on', onclick: sali }, `Sali di ${dec(passoCarico(q?.kg || 0), 1)} kg`) : null,
    idea.ultima && restano && idea.mossa !== 'uguale' && idea.mossa !== 'fisso' ? h('button', { class: 'scelta', onclick: comeAllora }, 'Come l\'ultima volta') : null,
    restano > 1 ? h('button', { class: 'scelta', onclick: tutte }, 'Segna tutte fatte') : null,
    h('button', { class: 'scelta', onclick: () => aggiorna(() => { const u = v.serie[v.serie.length - 1]; v.serie.push({ kg: u?.kg ?? null, rip: u?.rip ?? minRip ?? null, ok: false }); }) }, '+ Una serie'),
    restano && v.serie.length > 1 ? h('button', { class: 'scelta', onclick: () => aggiorna(() => { const i = v.serie.map((x) => x.ok).lastIndexOf(false); v.serie.splice(i, 1); }) }, '− Una serie') : null);

  // ---- cosa propone l'app oggi, e perche'
  const allora = idea.ultima ? riassunto(e, idea.ultima.serie) : '';
  const frase = {
    prima: e.tempo ? 'Prima volta: tieni la posizione finché la schiena resta ferma.'
      : e.corpo ? (maxRip ? `Prima volta: punta a ${v.rip} ripetizioni fatte bene.` : 'Prima volta: fanne quante ne vengono, pulite.')
        : v.kgScheda ? `Parti dal carico della tua scheda: ${dec(v.kgScheda, 2)} kg.` : 'Prima volta: scegli un carico con cui te ne restano due in canna.',
    fisso: 'Le hai chiuse tutte. Se erano pulite fino alla fine, è il momento di salire.',
    sali: `L'altra volta le hai chiuse tutte a ${maxRip}: oggi sali di carico e riparti da ${minRip}.`,
    rip: 'Oggi stesso carico, una ripetizione in più.',
    uguale: 'Sei al massimo delle ripetizioni: rallenta la discesa o aggiungi una serie.',
    tempo: 'Oggi prova a tenere 5 secondi in più.',
  }[idea.mossa];
  const consiglio = h('div', { class: `ultima${idea.mossa === 'sali' || idea.mossa === 'fisso' ? ' su' : ''}` }, icona(idea.mossa === 'sali' || idea.mossa === 'fisso' ? 'trend' : idea.ultima ? 'clock' : 'info'),
    h('span', null, idea.ultima ? [`${dataCorta(idea.ultima.d)}: `, h('b', null, allora), '. '] : null, frase));

  const r = a.riposo;
  const restaOra = r ? (r.fine - Date.now()) / 1000 : 0;
  const barraRecupero = r ? h('div', { class: `recupero${restaOra <= 0 ? ' fine' : ''}` },
    h('div', { class: 'anello', style: { width: '50px', height: '50px' } },
      s('svg', { width: 50, height: 50, viewBox: '0 0 50 50' },
        s('circle', { class: 'traccia', cx: 25, cy: 25, r: 21, 'stroke-width': 5 }),
        s('circle', { 'data-cerchio': '', class: 'giro-recupero', cx: 25, cy: 25, r: 21, 'stroke-width': 5, 'stroke-dasharray': GIRO, 'stroke-dashoffset': GIRO * (1 - Math.max(0, restaOra) / r.tot), style: { transition: 'stroke-dashoffset .25s linear' } }))),
    h('div', { class: 't cresce' }, h('b', { class: 'num', 'data-resta': '' }, restaOra > 0 ? minSec(Math.ceil(restaOra)) : 'Via'), h('small', { 'data-titolo': '' }, restaOra > 0 ? 'Recupero' : 'Recupero finito')),
    h('button', { class: 'piu', onclick: () => aggiorna((st) => { const x = st.attiva.riposo; if (!x) return; const base = Math.max(x.fine, Date.now()); x.fine = base + 15000; x.tot = Math.max(x.tot, (x.fine - Date.now()) / 1000); x.suonato = false; }) }, '+15 s'),
    h('button', { class: 'piu', onclick: () => aggiorna((st) => { st.attiva.riposo = null; }) }, 'Salta')) : null;

  // ---- in cima: l'animazione con il titolo sopra, oppure il video (che resta fermo mentre il resto si ridisegna)
  const tasti = [
    h('button', { class: 'tondo vetro', 'aria-label': 'Cambia esercizio', onclick: () => cambiaEsercizio(v) }, icona('swap')),
    h('button', { class: 'tondo vetro', 'aria-label': 'Tecnica', onclick: () => apriEsercizio(v.es, { serie: v.serie.length, rip: v.rip, rec: v.rec }) }, icona('info')),
  ];
  const posto = `Esercizio ${a.i + 1} di ${a.voci.length}`;
  const video = levaVideo(v.es, () => rifai(true));   // rifai(true): la figura va sostituita, non tenuta ferma
  const cima = vuoleVideo(v.es)
    ? [h('div', { class: 'es-media video', 'data-tieni': `video:${v.es}` }, filmato(v.es)),
      h('div', { class: 'es-titolo' }, h('div', { class: 'cresce' }, h('small', null, posto), h('h2', null, e.n), h('div', { class: 'att' }, e.att)), h('div', { class: 'riga', style: { gap: '8px' } }, tasti)),
      h('div', { class: 'sotto-figura' }, video)]
    : [h('div', { class: 'es-media' },
      animazione(v.es),
      h('div', { class: 'ombra' }),
      h('div', { class: 'su' }, h('span', { class: 'chip vetro' }, posto), h('div', { class: 'riga', style: { gap: '8px' } }, tasti)),
      h('div', { class: 'giu' }, h('h2', null, e.n), h('div', { class: 'att' }, e.att))),
    h('div', { class: 'sotto-figura' }, video)];

  const fatteQui = v.serie.filter((x) => x.ok).length;

  return [
    h('div', { class: 'seduta-top' },
      h('button', { class: 'tondo', 'aria-label': 'Chiudi la seduta', onclick: chiudi }, icona('x')),
      h('div', { class: 'tacche' }, a.voci.map((x, i) => h('i', { class: x.serie.every((y) => y.ok) ? 'fatta' : i === a.i ? 'ora' : '' }))),
      h('span', { class: 'tempo-tot', 'data-tempo': '' }, minSec((Date.now() - a.inizio) / 1000))),
    ...cima,
    h('div', { class: 'chips centro' },
      h('span', { class: 'chip' }, `${v.serie.length} serie`),
      h('span', { class: 'chip acc' }, e.tempo ? v.rip : `${v.rip} ripetizioni`),
      v.rec ? h('span', { class: 'chip' }, icona('clock'), `recupero ${tempoRec(v.rec)}`) : null),
    v.nota ? h('div', { class: 'ultima' }, icona('info'), h('span', null, v.nota)) : null,
    consiglio,
    serieOra || h('div', { class: 'card serie-ora finita' }, icona('check'), h('b', null, 'Esercizio fatto'), h('span', { class: 'piccolo' }, ultimo ? 'Era l\'ultimo: concludi la seduta.' : 'Vai al prossimo quando vuoi.')),
    elenco,
    scorciatoie,
    esperto ? null : h('div', { class: 'nota' }, icona('bolt'), h('span', null, e.come[Math.min(fatteQui, e.come.length - 1)])),
    barraRecupero ? h('div', { style: { height: '84px' } }) : null,
    barraRecupero,
    h('div', { class: 'barra-giu' }, h('div', null,
      prima ? null : h('button', { class: 'btn stretto', 'aria-label': 'Esercizio precedente', onclick: () => vai(a.i - 1) }, icona('back')),
      ultimo
        ? h('button', { class: `btn ${tutteFatte ? 'primo' : ''}`, onclick: () => (tutteFatte ? concludi() : conferma({ titolo: 'Concludere la seduta?', testo: 'Ci sono ancora serie non segnate.', azioni: [{ t: 'Concludi e salva', tipo: 'primo', fai: concludi }, { t: 'Continua ad allenarti' }] })) }, icona('trophy'), 'Concludi la seduta')
        : h('button', { class: `btn ${tutteFatte ? 'primo' : ''}`, onclick: () => vai(a.i + 1) }, 'Prossimo esercizio', icona('chev')))),
  ];
}


// ---------- a tutto schermo ----------
// Mentre ci si allena lo schermo deve dire poco e chiedere ancora meno: in alto i chili, su un righello che si scorre
// (se non lo si tocca restano quelli), in mezzo il tempo, sotto un tasto solo. STOP segna la serie con i chili del
// righello e le ripetizioni previste e fa partire il recupero; quando il recupero finisce suona e riparte da sola la
// serie dopo, o il primo giro dell'esercizio successivo. Le ripetizioni si ritoccano durante il recupero, se non erano
// quelle. Per gli esercizi a tempo (plank) il via lo da' chi si allena, e a contare e' il cronometro.
const PASSO = 0.5, TACCA = 14, MASSIMO = 300;   // il righello: da 0 a 300 kg, mezzo chilo per tacca, 14 px a tacca
let imm = null;   // { el, fase: 'serie' | 'recupero' | 'pronto', t0, kg, tic, fatta: {v, k}, provato }

function chiudiImmersione() {
  if (!imm) return;
  clearInterval(imm.tic);
  imm.el.remove();
  document.documentElement.classList.remove('immersa');
  imm = null;
}

// dove si e' arrivati: l'esercizio di adesso e la sua prima serie da fare (null se la seduta e' finita)
function puntoSeduta() {
  const a = S.attiva;
  if (!a) return null;
  for (let i = a.i; i < a.voci.length; i++) {
    const k = a.voci[i].serie.findIndex((q) => !q.ok);
    if (k >= 0) return { a, i, v: a.voci[i], k, q: a.voci[i].serie[k], e: P.esercizi[a.voci[i].es] };
  }
  return null;
}

function righello(kg, alCambio) {
  const valore = h('b', { class: 'num' }, `${dec(kg || 0, 1)} kg`);
  const striscia = h('div', { class: 'striscia' }, Array.from({ length: MASSIMO / PASSO + 1 }, (_, i) => {
    const x = i * PASSO;
    return h('i', { class: x % 5 === 0 ? 'cinque' : Number.isInteger(x) ? 'uno' : '' }, x % 5 === 0 ? h('span', null, x) : null);
  }));
  const scorre = h('div', { class: 'scorre' }, striscia);
  scorre.addEventListener('scroll', () => {
    const ora = Math.max(0, Math.min(MASSIMO, Math.round(scorre.scrollLeft / TACCA) * PASSO));
    valore.textContent = `${dec(ora, 1)} kg`;
    alCambio(ora);
  }, { passive: true });
  // la posizione di partenza si puo' dare solo quando il righello e' in pagina (due volte: con l'app in secondo piano
  // il primo dei due non parte)
  const alPosto = () => { scorre.scrollLeft = Math.round((kg || 0) / PASSO) * TACCA; };
  requestAnimationFrame(alPosto);
  setTimeout(alPosto, 80);
  return h('div', { class: 'righello' }, valore, h('div', { class: 'finestra' }, scorre, h('div', { class: 'ago' })), h('small', null, 'scorri per cambiare i chili'));
}

function disegnaImmersione() {
  if (!imm) return;
  const p = puntoSeduta();
  if (!p) { chiudiImmersione(); concludi(); return; }
  const { a, i, v, k, q, e } = p;
  if (a.i !== i) aggiorna((st) => { st.attiva.i = i; }, true);
  const conChili = !e.tempo && !e.corpo;
  if (imm.per !== `${i}:${k}`) { imm.per = `${i}:${k}`; imm.kg = q.kg ?? 0; imm.provato = false; }
  const cima = h('div', { class: 'imm-cima' },
    h('button', { class: 'tondo', 'aria-label': 'Esci dalla modalità a tutto schermo', onclick: () => { chiudiImmersione(); rifai(true); } }, icona('x')),
    h('span', null, `Esercizio ${i + 1} di ${a.voci.length}`),
    h('span', { class: 'num', 'data-imm-totale': '' }, minSec((Date.now() - a.inizio) / 1000)));
  const chili = conChili ? righello(imm.kg, (kg) => { imm.kg = kg; }) : h('div', { class: 'righello vuoto' }, h('b', null, e.tempo ? 'A tempo' : 'A corpo libero'));
  const titolo = [h('h2', null, e.n), h('div', { class: 'imm-serie' }, `Serie ${k + 1} di ${v.serie.length}`, h('span', null, e.tempo ? ` · tieni ${v.rip}` : ` · ${v.rip} ripetizioni`))];

  let centro, sotto;
  if (imm.fase === 'recupero' && a.riposo) {
    const f = imm.fatta;
    const ritocca = (di) => () => { colpetto(); aggiorna(() => { const x = f.v.serie[f.k]; x.rip = Math.max(1, (x.rip || 0) + di); }, true); disegnaImmersione(); };
    centro = h('div', { class: 'imm-centro' },
      h('small', null, 'Recupero'),
      h('b', { class: 'imm-tempo num', 'data-imm-resta': '' }, minSec(Math.max(0, Math.ceil((a.riposo.fine - Date.now()) / 1000)))),
      f && !P.esercizi[f.v.es].tempo ? h('div', { class: 'imm-fatta' },
        h('span', null, 'Appena fatta: ', h('b', null, `${f.v.serie[f.k].kg != null ? `${dec(f.v.serie[f.k].kg, 1)} kg × ` : ''}${f.v.serie[f.k].rip} ripetizioni`)),
        h('div', null, h('button', { 'aria-label': 'Una ripetizione in meno', onclick: ritocca(-1) }, icona('minus')), h('button', { 'aria-label': 'Una ripetizione in più', onclick: ritocca(1) }, icona('plus')))) : null,
      h('div', { class: 'imm-poi' }, f && f.v !== v ? `Poi: ${e.n}` : `Poi: serie ${k + 1} di ${v.serie.length}`));
    sotto = h('div', { class: 'imm-sotto due' },
      h('button', { class: 'btn', onclick: () => aggiorna((st) => { const x = st.attiva.riposo; if (!x) return; const base = Math.max(x.fine, Date.now()); x.fine = base + 15000; x.tot = Math.max(x.tot, (x.fine - Date.now()) / 1000); x.suonato = false; }, true) }, '+15 s'),
      h('button', { class: 'btn primo', onclick: () => { colpetto(); dopoIlRecupero(); } }, icona('play'), 'Salta il recupero'));
  } else if (imm.fase === 'pronto') {
    centro = h('div', { class: 'imm-centro' }, h('small', null, e.tempo ? 'Mettiti in posizione' : 'Prepara il peso, poi via'), h('b', { class: 'imm-tempo num' }, '0:00'));
    sotto = h('div', { class: 'imm-sotto' }, h('button', { class: 'imm-tasto via', onclick: () => { sbloccaAudio(); colpetto(); imm.fase = 'serie'; imm.t0 = Date.now(); disegnaImmersione(); } }, 'VIA'));
  } else {
    imm.fase = 'serie';
    centro = h('div', { class: 'imm-centro' }, h('small', null, e.tempo ? 'Tieni la posizione' : 'Serie in corso'), h('b', { class: 'imm-tempo num', 'data-imm-serie': '' }, minSec((Date.now() - imm.t0) / 1000)));
    sotto = h('div', { class: 'imm-sotto' }, h('button', { class: 'imm-tasto', onclick: stop }, 'STOP'), h('small', null, 'toccalo quando hai finito la serie'));
  }
  imm.el.replaceChildren(cima, chili, ...titolo, centro, sotto);
}

function stop() {
  const p = puntoSeduta();
  if (!imm || !p) return;
  const { v, k, q, e } = p;
  sbloccaAudio();
  const conChili = !e.tempo && !e.corpo;
  // zero chili su un esercizio con i pesi quasi sempre vuol dire che il righello non e' stato toccato: lo si dice una volta
  if (conChili && !imm.kg && !imm.provato) { imm.provato = true; avviso('Scorri il righello in alto per mettere i chili, poi STOP', 'info'); return; }
  colpetto();
  const [minRip] = intervallo(v.rip);
  const rip = e.tempo ? Math.max(1, Math.round((Date.now() - imm.t0) / 1000)) : (q.rip ?? (minRip || 10));
  serieFatta(v, k, conChili ? imm.kg : null, rip);
  imm.fatta = { v, k };
  if (!puntoSeduta()) { chiudiImmersione(); concludi(); return; }
  if (S.attiva.riposo) { imm.fase = 'recupero'; disegnaImmersione(); } else dopoIlRecupero();
}

// finito (o saltato) il recupero: la serie dopo parte da sola; per gli esercizi a tempo il via lo da' chi si allena
function dopoIlRecupero() {
  if (!imm) return;
  aggiorna((st) => { if (st.attiva) st.attiva.riposo = null; }, true);
  const p = puntoSeduta();
  if (!p) { chiudiImmersione(); concludi(); return; }
  // stesso esercizio: si riparte subito. Esercizio nuovo (c'e' da spostarsi e da mettere il peso) o a tempo: aspetta il VIA
  imm.fase = p.e.tempo || (imm.fatta && imm.fatta.v !== p.v) ? 'pronto' : 'serie';
  imm.t0 = Date.now();
  disegnaImmersione();
}

function ticImmersione() {
  const a = S.attiva;
  if (!imm || !a) { chiudiImmersione(); return; }
  const scrivi = (chiave, testo) => { const el = imm.el.querySelector(`[data-imm-${chiave}]`); if (el && el.textContent !== testo) el.textContent = testo; };
  scrivi('totale', minSec((Date.now() - a.inizio) / 1000));
  if (imm.fase === 'serie') scrivi('serie', minSec((Date.now() - imm.t0) / 1000));
  if (imm.fase === 'recupero') {
    const r = a.riposo;
    if (!r) { dopoIlRecupero(); return; }
    const resta = (r.fine - Date.now()) / 1000;
    scrivi('resta', minSec(Math.max(0, Math.ceil(resta))));
    if (resta <= 0) {
      if (!r.suonato) { r.suonato = true; if (S.opzioni.suono !== false) bip(); navigator.vibrate?.(200); }
      dopoIlRecupero();
    }
  }
}

function apriImmersione() {
  const p = puntoSeduta();
  if (!p || imm) return;
  const el = h('div', { class: 'immersione', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Serie in corso' });
  document.body.append(el);
  document.documentElement.classList.add('immersa');
  imm = { el, fase: p.e.tempo ? 'pronto' : 'serie', t0: Date.now(), kg: 0, per: null, fatta: null, provato: false };
  // se c'era un recupero in corso si riprende da li'
  if (S.attiva.riposo && S.attiva.riposo.fine > Date.now()) imm.fase = 'recupero';
  imm.tic = setInterval(ticImmersione, 200);
  tieniSveglio();
  disegnaImmersione();
}
