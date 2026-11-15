// La sezione dell'allenamento. Per chi va in palestra: la prossima seduta, le schede, lo storico. Per chi ha detto
// "non mi alleno" diventa la sezione del movimento: minuti della settimana, camminate, corse, circuito a casa.

import { h, icona, intero, durata, dataCorta, minSec, oggi, maiuscola, daIso, lunedi, colpetto } from '../dom.js';
import { P, S, prossimaSeduta, iniziaSeduta, volume, aggiorna, siAllena, impostaAllena, schedePalestra, minutiSettimana, presenze, togliPresenza, contaPresenze, impostaPresenze, ATTIVITA } from '../store.js';
import { animazione, mostraEsercizio, levaVideo, vuoleVideo, sfondoEsercizi, mappaCorpo, foglio, conferma, avviso } from '../ui.js';
import { cartaSettimanaMovimento, tastiMovimento, rigaAttivita, minutiInParole, cartaBruciate } from './attivita.js';

const tempoRec = (sec) => (sec >= 60 ? `${minSec(sec)} min` : `${sec} s`);

// Scheda di un esercizio: animazione o video, muscoli, tecnica, alternative.
export function apriEsercizio(es, contesto) {
  let ora = es;
  return foglio((api) => {
    const e = P.esercizi[ora];
    return [
      h('div', { class: `copertina${vuoleVideo(ora) ? ' con-video' : ''}`, style: { aspectRatio: vuoleVideo(ora) ? '16 / 9' : '3 / 2' } }, mostraEsercizio(ora)),
      h('div', { class: 'sotto-figura' }, levaVideo(ora, () => api.ridisegna())),
      h('div', null,
        h('div', { class: 'chips', style: { marginBottom: '10px' } }, h('span', { class: 'chip acc' }, icona(e.corpo ? 'body' : 'dumbbell'), e.att)),
        h('h2', null, e.n)),
      contesto && ora === es ? h('div', { class: 'obiettivo' },
        h('div', null, h('b', null, contesto.serie), h('span', null, 'serie')),
        h('div', null, h('b', null, contesto.rip), h('span', null, e.tempo ? 'durata' : 'ripetizioni')),
        h('div', null, h('b', null, contesto.rec ? tempoRec(contesto.rec) : '–'), h('span', null, 'recupero'))) : null,
      contesto?.nota && ora === es ? h('div', { class: 'nota' }, icona('info'), h('span', null, contesto.nota)) : null,
      h('h4', null, 'Muscoli al lavoro'),
      mappaCorpo(e.m1, e.m2),
      h('div', { class: 'legenda' },
        h('span', null, h('i'), e.m1.map((m) => P.muscoli[m]).join(', ')),
        e.m2.length ? h('span', null, h('i', { class: 'due' }), 'In aiuto') : null),
      h('h4', null, 'Come si fa'),
      h('ol', { class: 'passi' }, e.come.map((p) => h('li', null, p))),
      h('h4', null, 'Da evitare'),
      h('ol', { class: 'passi no' }, e.no.map((p) => h('li', null, p))),
      e.alt.length ? h('h4', null, e.corpo ? 'Al suo posto' : 'Se la macchina è occupata') : null,
      e.alt.map((a) => h('button', { class: 'card es tocco', onclick: () => { ora = a; api.ridisegna(); api.el.querySelector('.corpo').scrollTop = 0; } },
        animazione(a), h('div', { class: 'cresce' }, h('h3', null, P.esercizi[a].n), h('div', { class: 'piccolo' }, P.esercizi[a].att)), icona('chev', 'freccia'))),
      ora !== es ? h('button', { class: 'btn', onclick: () => { ora = es; api.ridisegna(); } }, icona('back'), `Torna a ${P.esercizi[es].n.toLowerCase()}`) : null,
    ];
  }, { copertina: true });
}

function inCorso() {
  const sc = P.schede[S.attiva.w];
  return h('div', { class: 'card piena scheda-eroe tocco', role: 'button', onclick: () => { location.hash = '#/seduta'; } },
    h('div', { class: 'sfondo' }, sfondoEsercizi([S.attiva.voci[S.attiva.i].es, ...S.attiva.voci.map((x) => x.es)])),
    h('div', { class: 'chips' }, h('span', { class: 'chip acc' }, icona('timer'), 'Seduta in corso')),
    h('h3', { style: { marginTop: '8px' } }, sc?.n || 'Seduta'),
    h('span', { class: 'btn primo' }, icona('play'), 'Riprendi'));
}

function avviaScheda(w) {
  const vai = () => { location.hash = '#/seduta'; };
  if (S.attiva?.w === w) return vai();
  if (S.attiva) {
    return conferma({
      titolo: 'Hai già una seduta in corso', testo: `Stai facendo ${P.schede[S.attiva.w]?.n || 'un\'altra seduta'}. Se inizi questa, quella viene scartata.`,
      azioni: [{ t: 'Riprendi quella in corso', tipo: 'primo', fai: vai }, { t: 'Scarta e inizia questa', tipo: 'rosso', fai: () => { iniziaSeduta(w, oggi()); vai(); } }, { t: 'Annulla' }],
    });
  }
  iniziaSeduta(w, oggi());
  return vai();
}

function cartaProssima() {
  if (S.attiva) return inCorso();
  const pr = prossimaSeduta();
  const sc = P.schede[pr.w];
  const quando = pr.oggi ? 'oggi' : daIso(pr.d).toLocaleDateString('it-IT', { weekday: 'long' });
  return h('div', { class: 'card piena scheda-eroe' },
    h('div', { class: 'sfondo' }, sfondoEsercizi(sc.es.map((x) => x[0]))),
    h('div', { class: 'chips' },
      h('span', { class: 'chip acc' }, icona('cal'), `Prossima: ${quando}`),
      h('span', { class: 'chip vetro' }, icona('clock'), `${sc.durata} min`)),
    h('h3', { style: { marginTop: '8px' } }, sc.n),
    h('div', { class: 'muto', style: { fontSize: '14.5px' } }, sc.fuoco),
    h('button', { class: 'btn primo', onclick: () => avviaScheda(pr.w) }, icona('play'), 'Inizia la seduta'));
}

// Il circuito senza attrezzi: si apre come una scheda e si fa con la stessa seduta guidata.
function carteCasa() {
  return Object.entries(P.schede).filter(([, sc]) => sc.casa).map(([w, sc]) =>
    h('button', { class: 'card scheda casa tocco', onclick: () => { location.hash = `#/allenamento/${w}`; } },
      h('div', { class: 'riga' },
        h('span', { class: 'lettera' }, icona('home')),
        h('div', { class: 'cresce' }, h('h3', null, sc.n), h('div', { class: 'piccolo' }, `${sc.fuoco} · ${sc.es.length} esercizi · ${sc.durata} min`)),
        icona('chev', 'freccia'))));
}

// Un giorno di palestra contato senza la seduta segnata (store.js, allenato): si puo' dire che non ci si e' andati.
function rigaPresenza(d) {
  const apri = () => conferma({
    titolo: 'Palestra contata', testo: `${maiuscola(daIso(d).toLocaleDateString('it-IT', { weekday: 'long', day: 'numeric', month: 'long' }))} era su Gym e non hai segnato gli esercizi: l'ho contata come allenamento fatto.`,
    azioni: [{ t: 'Non ci sono andato', tipo: 'rosso', fai: () => { togliPresenza(d); avviso('Tolta dagli allenamenti', 'trash'); } }, { t: 'Va bene così' }],
  });
  return h('button', { class: 'voce', onclick: apri },
    h('span', { class: 'ic-att acc' }, icona('dumbbell')),
    h('div', { class: 'cresce' }, h('b', null, 'Palestra'), h('small', null, `${dataCorta(d)} · esercizi non segnati`)),
    icona('chev', 'freccia'));
}

function storico() {
  // un giorno di palestra segnato a mano tra le attivita' (con le sue calorie) non si ripete come "esercizi non segnati"
  const conPalestra = new Set(S.attivita.filter((a) => ATTIVITA[a.tipo]?.palestra).map((a) => a.d));
  const contati = presenze().filter((d) => !conPalestra.has(d));
  const voci = [
    ...S.sedute.map((x) => ({ d: x.d, t: x.inizio, seduta: x })),
    ...contati.map((d) => ({ d, t: daIso(d).getTime() + 1, presenza: true })),
    ...S.attivita.map((a) => ({ d: a.d, t: daIso(a.d).getTime(), attivita: a })),
  ].sort((a, b) => (b.d === a.d ? b.t - a.t : b.d.localeCompare(a.d))).slice(0, 12);
  const quante = S.sedute.length + S.attivita.length + contati.length;
  return [
    h('div', { class: 'sez' }, h('h2', null, 'Storico'), quante ? h('span', null, quante === 1 ? '1 volta' : `${quante} volte`) : null),
    voci.length
      ? h('div', { class: 'card elenco' }, voci.map((v) => (v.attivita ? rigaAttivita(v.attivita) : v.presenza ? rigaPresenza(v.d)
        : h('button', { class: 'voce', onclick: () => apriSeduta(v.seduta) },
          h('span', { class: 'ic-att acc' }, P.schede[v.seduta.w]?.casa ? icona('home') : h('b', null, v.seduta.w)),
          h('div', { class: 'cresce' }, h('b', null, P.schede[v.seduta.w]?.casa ? P.schede[v.seduta.w].n : (P.schede[v.seduta.w]?.fuoco || v.seduta.w)), h('small', null, `${dataCorta(v.seduta.d)} · ${durata(v.seduta.fine - v.seduta.inizio)}`)),
          h('span', { class: 'q' }, volume(v.seduta.voci) ? `${intero(volume(v.seduta.voci))} kg` : `${v.seduta.voci.reduce((n, x) => n + x.serie.length, 0)} serie`)))))
      : h('div', { class: 'card vuoto' }, h('b', null, siAllena() ? 'La prima seduta ti aspetta' : 'Qui vedrai quello che fai'),
        siAllena() ? 'Segna i carichi mentre ti alleni: qui trovi tutto lo storico.' : 'Camminate, corse, allenamenti a casa: ogni cosa che segni finisce qui.'),
  ];
}

// In fondo alla sezione: chi non va in palestra lo dice qui, e l'app si adatta.
function levaAllena() {
  const si = siAllena();
  const cambia = (nuovo) => {
    if (nuovo === si) return;
    colpetto();
    if (!nuovo && S.attiva) aggiorna((st) => { st.attiva = null; }, true);
    impostaAllena(nuovo);
    avviso(nuovo ? 'Palestra riattivata' : 'Ok, niente palestra', nuovo ? 'dumbbell' : 'walk');
  };
  return h('div', { class: 'card' },
    h('div', { class: 'fra' },
      h('div', null, h('b', null, 'Vado in palestra'),
        h('div', { class: 'piccolo', style: { lineHeight: 1.4, marginTop: '2px' } }, si
          ? 'Se non ti alleni spegnilo: spariscono schede e shake, e le calorie diventano quelle di chi non fa pesi.'
          : 'Spento: ogni giorno ha le calorie di un giorno senza pesi, niente shake, e qui segni il movimento che fai.')),
      h('div', { class: 'seg mini', style: { width: '112px', flex: 'none' } },
        h('button', { class: si ? 'on' : '', onclick: () => cambia(true) }, 'Sì'),
        h('button', { class: si ? '' : 'on', onclick: () => cambia(false) }, 'No'))));
}

// Per chi va in palestra ma non sempre segna gli esercizi: un giorno lasciato su "Gym" conta lo stesso.
function levaPresenze() {
  const si = contaPresenze();
  const cambia = (nuovo) => { if (nuovo !== si) { colpetto(); impostaPresenze(nuovo); } };
  return h('div', { class: 'card' },
    h('div', { class: 'fra' },
      h('div', null, h('b', null, 'Conta anche senza esercizi'),
        h('div', { class: 'piccolo', style: { lineHeight: 1.4, marginTop: '2px' } }, si
          ? 'Un giorno lasciato su Gym nella Home vale come allenamento fatto anche se non segni la seduta. Se non ci vai, mettilo su Riposo.'
          : 'Spento: un allenamento conta solo se segni la seduta.')),
      h('div', { class: 'seg mini', style: { width: '112px', flex: 'none' } },
        h('button', { class: si ? 'on' : '', onclick: () => cambia(true) }, 'Sì'),
        h('button', { class: si ? '' : 'on', onclick: () => cambia(false) }, 'No'))));
}

function elenco() {
  if (!siAllena()) {
    return [
      h('div', { class: 'top' }, h('div', null, h('div', { class: 'sopra' }, 'Un po\' ogni giorno'), h('h1', null, 'Movimento'))),
      cartaSettimanaMovimento(),
      h('div', { class: 'sez' }, h('h2', null, 'Cosa hai fatto?')),
      tastiMovimento(),
      cartaBruciate(),
      h('div', { class: 'sez' }, h('h2', null, 'Allenati a casa'), h('span', null, 'Senza attrezzi')),
      S.attiva ? inCorso() : null,
      ...carteCasa(),
      ...storico(),
      levaAllena(),
    ];
  }
  const pr = S.attiva ? null : prossimaSeduta();
  const perSettimana = P.settimana.filter((g) => g.tipo === 'train').length;
  const liberi = minutiSettimana(lunedi(oggi()));
  return [
    h('div', { class: 'top' }, h('div', null, h('div', { class: 'sopra' }, perSettimana === 1 ? 'Una seduta a settimana' : `${perSettimana} sedute a settimana`), h('h1', null, 'Allenamento'))),
    cartaProssima(),
    h('div', { class: 'sez' }, h('h2', null, 'Le tue schede')),
    ...schedePalestra().map((w) => {
      const sc = P.schede[w];
      return h('button', { class: `card scheda tocco${pr?.w === w ? ' prossima' : ''}`, onclick: () => { location.hash = `#/allenamento/${w}`; } },
        h('div', { class: 'riga' },
          h('span', { class: 'lettera' }, w),
          h('div', { class: 'cresce' }, h('h3', null, sc.fuoco), h('div', { class: 'piccolo' }, `${sc.giorno != null ? `${P.giorni[sc.giorno]} · ` : ''}${sc.es.length} esercizi · ${sc.durata} min`)),
          icona('chev', 'freccia')),
        h('div', { class: 'miniature' }, sc.es.slice(0, 5).map(([es]) => h('div', { class: 'm' }, sfondoEsercizi([es])))));
    }),
    h('div', { class: 'sez' }, h('h2', null, 'Movimento e calorie'), liberi ? h('span', null, `${minutiInParole(liberi)} questa settimana`) : null),
    tastiMovimento(['camminata', 'corsa', 'palestra']),
    cartaBruciate(),
    ...carteCasa(),
    ...storico(),
    levaPresenze(),
    levaAllena(),
  ];
}

function apriSeduta(x) {
  const f = foglio(() => [
    h('h2', null, `${P.schede[x.w]?.n || x.w}`),
    h('p', { class: 'muto' }, `${maiuscola(daIso(x.d).toLocaleDateString('it-IT', { weekday: 'long', day: 'numeric', month: 'long' }))} · ${durata(x.fine - x.inizio)}`),
    h('div', { class: 'tre-col' },
      h('div', { class: 'stat' }, h('b', null, x.voci.reduce((n, v) => n + v.serie.length, 0)), h('span', null, 'serie')),
      h('div', { class: 'stat' }, h('b', null, intero(volume(x.voci))), h('span', null, 'kg totali')),
      h('div', { class: 'stat' }, h('b', null, x.voci.length), h('span', null, 'esercizi'))),
    h('div', null, x.voci.map((v) => h('div', { class: 'voce' },
      h('div', { class: 'cresce' }, h('b', null, P.esercizi[v.es]?.n || v.es),
        h('small', null, v.serie.map((q) => (P.esercizi[v.es]?.tempo ? `${q.rip} s` : q.kg ? `${intero(q.kg)} × ${q.rip}` : `${q.rip}`)).join('  ·  ')))))),
    h('button', { class: 'btn rosso', onclick: () => conferma({
      titolo: 'Eliminare questa seduta?', testo: 'I carichi segnati spariranno dallo storico.',
      azioni: [{ t: 'Elimina', tipo: 'rosso', fai: () => { f.chiudi(); aggiorna((st) => { st.sedute = st.sedute.filter((q) => q.id !== x.id); }); avviso('Seduta eliminata', 'trash'); } }, { t: 'Annulla' }],
    }) }, icona('trash'), 'Elimina seduta'),
  ]);
}

function dettaglio(w) {
  const sc = P.schede[w];
  const m1 = new Set(), m2 = new Set();
  for (const [es] of sc.es) { P.esercizi[es].m1.forEach((m) => m1.add(m)); P.esercizi[es].m2.forEach((m) => m2.add(m)); }
  const serie = sc.es.reduce((n, e) => n + e[1], 0);
  const riscaldamento = sc.casa
    ? ['Due minuti di marcia sul posto, braccia che ruotano.', 'Il primo esercizio del circuito fa già da riscaldamento: parti piano.']
    : P.riscaldamento;
  return [
    h('button', { class: 'indietro', onclick: () => { location.hash = '#/allenamento'; } }, icona('back'), sc.casa ? 'Movimento' : 'Schede'),
    h('div', { class: 'top' }, h('div', null, h('div', { class: 'sopra' }, sc.casa ? 'A casa, quando vuoi' : `${sc.giorno != null ? `${P.giorni[sc.giorno]} · ` : ''}${sc.n}`), h('h1', null, sc.casa ? sc.n : sc.fuoco))),
    h('div', { class: 'chips' },
      h('span', { class: 'chip acc' }, icona(sc.casa ? 'body' : 'dumbbell'), `${sc.es.length} esercizi`),
      h('span', { class: 'chip' }, `${serie} serie`),
      h('span', { class: 'chip' }, icona('clock'), `${sc.durata} min`)),
    h('div', { class: 'card' },
      h('div', { class: 'fra', style: { marginBottom: '6px' } }, h('b', { style: { fontSize: '16.5px' } }, 'Cosa alleni'), h('div', { class: 'legenda' }, h('span', null, h('i'), 'Principale'), h('span', null, h('i', { class: 'due' }), 'In aiuto'))),
      mappaCorpo([...m1], [...m2].filter((m) => !m1.has(m)))),
    h('div', { class: 'card' },
      h('b', { style: { fontSize: '16.5px' } }, 'Riscaldamento'),
      h('ol', { class: 'passi', style: { marginTop: '12px' } }, riscaldamento.map((p) => h('li', null, p)))),
    h('div', { class: 'sez' }, h('h2', null, 'Esercizi'), h('span', null, 'Tocca per la tecnica')),
    ...sc.es.map(([es, ns, rip, rec, piu], i) => {
      const e = P.esercizi[es];
      // il carico di riferimento e la nota arrivano dalla scheda di chi si allena (quando ne ha una sua)
      const sotto = [piu?.nota, rec ? `recupero ${tempoRec(rec)}` : null].filter(Boolean).join(' · ');
      return h('button', { class: 'card es tocco', onclick: () => apriEsercizio(es, { serie: ns, rip, rec, nota: piu?.nota }) },
        animazione(es),
        h('div', { class: 'cresce' },
          h('h3', null, e.n),
          h('div', { class: 'serie' }, `${ns} × ${rip}${piu?.kg ? ` · ${String(piu.kg).replace('.', ',')} kg` : ''}`),
          sotto ? h('div', { class: 'piccolo' }, sotto.charAt(0).toUpperCase() + sotto.slice(1)) : null),
        h('span', { class: 'n' }, i + 1));
    }),
    h('div', { class: 'barra-giu' }, h('div', null,
      h('button', { class: 'btn primo', onclick: () => avviaScheda(w) }, icona('play'), S.attiva?.w === w ? 'Riprendi la seduta' : sc.casa ? 'Inizia il circuito' : 'Inizia la seduta'))),
  ];
}

export function vistaAllenamento(parti) {
  const w = parti[0];
  if (w && P.schede[w]) return dettaglio(w);
  return elenco();
}
