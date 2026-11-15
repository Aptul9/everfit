// Le domande del primo avvio (e, piu' avanti, "Personalizza" nella scheda Piano). Servono a cucire l'app addosso a chi
// la usa: cosa vuole ottenere, cosa vuole vedere ogni giorno, i suoi numeri, come si muove, a che ora mangia.
// Chi ha gia' la dieta scritta da qualcuno (pianoScritto) alla fine se lo sente dire; a chi non ce l'ha, dalle stesse
// risposte piu' qualcuna sul cibo, l'app calcola un piano (personale.js).

import { h, icona, numero, oggi, dec, intero, inCima, colpetto } from '../dom.js';
import { P, S, io, salvaProfilo, serveProfilo, pianoScritto, menuDelPiano, CASA, siAllena } from '../store.js';
import { M, ultimaPesata, salvaPesata, nuovaPesata } from '../misure.js';
import { avviso } from '../ui.js';
import { SCOPI, LAVORI, calorie, giorniPer, pesoObiettivo } from '../personale.js';

const GIORNI = ['L', 'M', 'M', 'G', 'V', 'S', 'D'];
const LIVELLI = {
  nuovo: ['Da poco', 'Ti spiego ogni esercizio, passo per passo'],
  medio: ['Da un po\'', 'I consigli restano, ma senza insistere'],
  esperto: ['Da anni', 'Solo numeri e cronometro: la tecnica la sai'],
};
const PESATE = { giorno: ['Ogni giorno', 1], settimana: ['Una volta a settimana', 7], tanto: ['Ogni tanto', 30] };
let bozza = null;
let passo = 0;

const oraDelPiano = (mom, riserva) => P.momenti[mom]?.ora?.rest || riserva;

function nuovaBozza() {
  const p = S.profilo || {};
  const piano = P.profilo || {};
  const scritto = pianoScritto();
  // dal piano scritto si propone solo quello che c'e' davvero (vedi profiloCon): il resto si chiede
  const noti = (scritto && piano.noti) || {};
  return {
    sesso: p.sesso || noti.sesso || null,
    eta: p.eta ?? noti.eta ?? null,
    altezza: p.altezza ?? noti.altezza ?? null,
    peso: ultimaPesata()?.peso || p.peso || null,
    obiettivo: p.obiettivo || null, pesoObiettivo: p.pesoObiettivo || null,
    menu: S.opzioni.menu || null,   // solo per chi ha la dieta in due forme: finche' non sceglie resta da chiedere
    casa: Object.fromEntries(Object.keys(CASA).map((k) => [k, S.opzioni.casa?.[k] !== false])),
    allena: S.opzioni.allena ?? p.allena ?? (scritto && piano.conScheda ? true : null),
    giorni: p.giorni?.length ? [...p.giorni] : (scritto && piano.giorni?.length ? [...piano.giorni] : giorniPer(3)),
    livello: p.livello || 'medio', lavoro: p.lavoro || 'seduto', shake: !!p.shake,
    lattosio: !!p.lattosio, esclusi: [...(p.esclusi || [])],
    orari: { colazione: S.opzioni.orari?.colazione || oraDelPiano('colazione', '07:30'), pranzo: S.opzioni.orari?.pranzo || oraDelPiano('pranzo', '13:00'), cena: S.opzioni.orari?.cena || oraDelPiano('cena', '20:30') },
    pesate: p.pesate || 'settimana', dal: p.dal || oggi(),
  };
}

const campoNumero = (chiave, etichetta, unita, decimali) => h('div', { class: 'campo' },
  h('label', null, etichetta),
  h('div', { class: 'con-unita' },
    h('input', {
      type: 'text', inputmode: decimali ? 'decimal' : 'numeric', autocomplete: 'off', enterkeyhint: 'next',
      value: bozza[chiave] != null ? dec(bozza[chiave], 1) : '', 'aria-label': etichetta,
      oninput: (e) => { bozza[chiave] = numero(e.target.value); },
    }), h('span', null, unita)));

export const scelta = (acceso, titolo, sotto, tocca, quadro = false) => h('button', { class: `card in-piu tocco${acceso ? ' scelta-on' : ''}`, style: { marginTop: 0 }, 'aria-pressed': acceso, onclick: () => { colpetto(); tocca(); } },
  h('div', { class: 'cresce' }, h('b', null, titolo), sotto ? h('small', null, sotto) : null),
  h('span', { class: `pallino${quadro ? ' quadro' : ''}${acceso ? ' on' : ''}` }));

const siNo = (valore, cambia) => h('div', { class: 'seg mini', style: { width: '112px', flex: 'none' } },
  h('button', { class: valore ? 'on' : '', onclick: () => cambia(true) }, 'Sì'),
  h('button', { class: valore ? '' : 'on', onclick: () => cambia(false) }, 'No'));

function controlla(nome) {
  const b = bozza;
  if (nome === 'menu' && !b.menu) return 'Scegli come vuoi seguirla';
  if (nome === 'scopo' && !b.obiettivo) return 'Scegli quello che ti somiglia di più';
  if (nome === 'tu') {
    if (!b.sesso) return 'Uomo o donna? Serve per i conti';
    if (!(b.eta >= 14 && b.eta <= 90)) return 'Scrivi la tua età';
    if (!(b.altezza >= 130 && b.altezza <= 220)) return 'Scrivi l\'altezza in centimetri';
    if (!(b.peso >= 35 && b.peso <= 250)) return 'Scrivi quanto pesi';
  }
  if (nome === 'movimento') {
    if (b.allena == null) return 'Vai in palestra oppure no?';
    if (b.allena && !b.giorni.length) return 'Scegli almeno un giorno';
  }
  return null;
}

export function vistaProfilo(parti, rifai) {
  // l'account dell'amministratore non ha domande: l'app e' nata su di lui
  if (io.capo) { setTimeout(() => { if (location.hash.startsWith('#/profilo')) location.hash = '#/altro'; }); return []; }
  const primo = parti[0] === 'primo' || serveProfilo();
  const scritto = pianoScritto();
  // chi ha gia' la dieta non deve dire cosa non mangia: quelle domande servono solo a calcolare un piano.
  // Se la sua dieta esiste in due forme (menuDelPiano) la prima cosa che gli si chiede e' quale preferisce.
  const menu = menuDelPiano();
  const PASSI = ['ciao', ...(menu ? ['menu'] : []), 'scopo', 'serve', 'tu', 'movimento', ...(scritto ? [] : ['cibo']), 'giornata', 'fine'];
  if (!bozza) { bozza = nuovaBozza(); passo = primo ? 0 : 1; }
  const b = bozza;
  const nome = PASSI[passo];
  const chiudi = () => { bozza = null; location.hash = '#/altro'; };
  const vai = (n) => { passo = n; inCima(); rifai(true); };

  const salva = () => {
    const pr = {
      sesso: b.sesso, eta: Math.round(b.eta), altezza: Math.round(b.altezza), peso: b.peso,
      obiettivo: b.obiettivo, pesoObiettivo: b.pesoObiettivo || pesoObiettivo(b),
      allena: !!b.allena, giorni: b.allena ? [...b.giorni].sort() : [], livello: b.livello, pesate: b.pesate,
      lavoro: b.lavoro, shake: b.allena && b.shake, lattosio: b.lattosio, esclusi: [...b.esclusi], dal: b.dal,
    };
    const casa = { ...b.casa }, orari = { ...b.orari }, comeDieta = menu ? b.menu : null;
    bozza = null;
    salvaProfilo(pr, { casa, orari, menu: comeDieta });
    // la prima pesata: senza, i progressi non avrebbero un punto di partenza
    if (!M.pesate.length && pr.peso) salvaPesata(nuovaPesata({ peso: pr.peso, fonte: 'manuale', nota: 'Peso dichiarato al primo avvio' }));
    location.hash = '#/oggi';
    avviso(primo ? `${pr.sesso === 'f' ? 'Benvenuta' : 'Benvenuto'} in FitFuel` : 'Fatto: l\'app è aggiornata');
  };
  const avanti = () => {
    const errore = controlla(nome);
    if (errore) { avviso(errore, 'info'); return; }
    if (nome === 'fine') return salva();
    return vai(passo + 1);
  };
  const indietro = () => { if (passo > (primo ? 0 : 1)) vai(passo - 1); else if (!primo) chiudi(); };

  let corpo;
  if (nome === 'ciao') {
    corpo = [
      h('div', { class: 'top grande' }, h('div', null, h('div', { class: 'sopra' }, `${b.sesso === 'f' ? 'Benvenuta' : 'Benvenuto'} in FitFuel`), h('h1', null, 'Ciao, ', h('em', null, io.nome)))),
      h('p', { class: 'muto', style: { fontSize: '17px', lineHeight: 1.45 } }, scritto
        ? 'La tua dieta c\'è già. Prima di cominciare ti faccio qualche domanda: non tutti cerchiamo la stessa cosa, e l\'app si regola su di te.'
        : 'Qualche domanda su di te e ti preparo il piano: quanto mangiare ogni giorno, cosa, e come muoverti.'),
      h('div', { class: 'card' }, h('ol', { class: 'passi' },
        menu ? h('li', null, 'Come preferisci seguire la tua dieta.') : null,
        h('li', null, 'Cosa vuoi ottenere, e cosa vuoi avere sott\'occhio ogni giorno.'),
        h('li', null, 'I tuoi numeri: età, altezza, peso.'),
        h('li', null, 'Come ti muovi e a che ora mangi.'))),
      h('p', { class: 'piccolo', style: { textAlign: 'center' } }, 'Un minuto in tutto. Quello che scrivi lo vedi solo tu, e puoi cambiarlo quando vuoi.'),
    ];
  } else if (nome === 'menu') {
    // la dieta c'e' gia' ma si puo' vedere in due modi: lo decide chi la deve seguire, non chi l'ha caricata
    const da = P.profilo.da;
    corpo = [
      h('div', { class: 'top' }, h('div', null, h('div', { class: 'sopra' }, 'La tua dieta'), h('h1', null, 'Come vuoi seguirla?'))),
      h('p', { class: 'muto' }, `${da && !io.capo ? `${da} mi ha già dato la tua dieta. ` : ''}${menu.testo || ''}`),
      ...['giro', 'fisso'].map((id) => scelta(b.menu === id, menu[id]?.[0] || id, menu[id]?.[1], () => { b.menu = id; rifai(); })),
      h('p', { class: 'piccolo' }, 'Puoi cambiare idea quando vuoi, dalla scheda Piano.'),
    ];
  } else if (nome === 'scopo') {
    corpo = [
      h('div', { class: 'top' }, h('div', null, h('div', { class: 'sopra' }, 'L\'obiettivo'), h('h1', null, 'Cosa vuoi ottenere?'))),
      ...Object.entries(SCOPI).map(([id, [titolo, sotto]]) => scelta(b.obiettivo === id, titolo, scritto ? null : sotto, () => { b.obiettivo = id; b.pesoObiettivo = null; rifai(); })),
      scritto ? h('p', { class: 'piccolo' }, 'La dieta resta quella che hai: questo mi serve per dirti come stai andando.') : null,
    ];
  } else if (nome === 'serve') {
    corpo = [
      h('div', { class: 'top' }, h('div', null, h('div', { class: 'sopra' }, 'La tua schermata di ogni giorno'), h('h1', null, 'Cosa vuoi tenere d\'occhio?'))),
      h('p', { class: 'muto' }, 'I pasti di oggi ci sono sempre. Il resto lo scegli tu: spegni quello che non ti interessa.'),
      ...Object.entries(CASA).map(([id, [titolo, sotto]]) => scelta(b.casa[id], titolo, sotto, () => { b.casa[id] = !b.casa[id]; rifai(); }, true)),
    ];
  } else if (nome === 'tu') {
    corpo = [
      h('div', { class: 'top' }, h('div', null, h('div', { class: 'sopra' }, 'Su di te'), h('h1', null, 'I tuoi numeri'))),
      h('div', { class: 'seg' },
        h('button', { class: b.sesso === 'm' ? 'on' : '', onclick: () => { b.sesso = 'm'; rifai(); } }, 'Uomo'),
        h('button', { class: b.sesso === 'f' ? 'on' : '', onclick: () => { b.sesso = 'f'; rifai(); } }, 'Donna')),
      h('div', { class: 'due-col' }, campoNumero('eta', 'Età', 'anni'), campoNumero('altezza', 'Altezza', 'cm')),
      h('div', { class: b.obiettivo === 'dimagrire' || b.obiettivo === 'massa' ? 'due-col' : '' },
        campoNumero('peso', 'Quanto pesi oggi', 'kg', true),
        b.obiettivo === 'dimagrire' || b.obiettivo === 'massa' ? campoNumero('pesoObiettivo', 'Dove vuoi arrivare', 'kg', true) : null),
      h('p', { class: 'piccolo' }, 'Servono per i grafici, per l\'acqua da bere e per stimare quanto consumi. Il peso lo aggiornerai ogni volta che ti pesi.'),
    ];
  } else if (nome === 'movimento') {
    corpo = [
      h('div', { class: 'top' }, h('div', null, h('div', { class: 'sopra' }, 'Il movimento'), h('h1', null, 'Vai in palestra?'))),
      scelta(b.allena === true, 'Sì, mi alleno con i pesi', P.profilo.conScheda ? 'Trovi la tua scheda, con i carichi da cui ripartire' : 'Schede guidate, con i carichi da segnare', () => { b.allena = true; rifai(); }),
      scelta(b.allena === false, 'No, non mi alleno', 'Niente schede: segni camminate, corse e allenamenti a casa quando li fai', () => { b.allena = false; rifai(); }),
      b.allena ? [
        h('div', { class: 'sez' }, h('h2', null, 'In quali giorni?'), h('span', null, b.giorni.length === 1 ? '1 giorno' : `${b.giorni.length} giorni`)),
        h('div', { class: 'giorni scelta-giorni' }, GIORNI.map((l, i) =>
          h('button', { class: b.giorni.includes(i) ? 'on' : '', 'aria-label': P.giorni[i], onclick: () => { colpetto(); b.giorni = b.giorni.includes(i) ? b.giorni.filter((x) => x !== i) : [...b.giorni, i]; rifai(); } }, h('b', null, l)))),
        h('div', { class: 'sez' }, h('h2', null, 'Da quanto ti alleni?')),
        h('div', { class: 'tre-scelte' }, Object.entries(LIVELLI).map(([id, [titolo, sotto]]) =>
          h('button', { class: `card tocco${b.livello === id ? ' on' : ''}`, onclick: () => { colpetto(); b.livello = id; rifai(); } }, h('b', null, titolo), h('small', null, sotto)))),
        scritto ? null : h('div', { class: 'fra', style: { padding: '4px 4px 0' } },
          h('div', null, h('b', null, 'Proteine in polvere dopo l\'allenamento'), h('div', { class: 'piccolo' }, 'Se le usi, le metto nel piano.')),
          siNo(b.shake, (v) => { b.shake = v; rifai(); })),
      ] : null,
      scritto ? null : [
        h('div', { class: 'sez' }, h('h2', null, 'Come passi le giornate?')),
        h('div', { class: 'tre-scelte' }, Object.entries(LAVORI).map(([id, [titolo, sotto]]) =>
          h('button', { class: `card tocco${b.lavoro === id ? ' on' : ''}`, onclick: () => { colpetto(); b.lavoro = id; rifai(); } }, h('b', null, titolo), h('small', null, sotto)))),
      ],
    ];
  } else if (nome === 'cibo') {
    corpo = [
      h('div', { class: 'top' }, h('div', null, h('div', { class: 'sopra' }, 'A tavola'), h('h1', null, 'C\'è qualcosa che non mangi?'))),
      h('p', { class: 'muto' }, 'Tocca quello che vuoi fuori dal piano: scelgo altri piatti. Se mangi di tutto vai avanti.'),
      h('div', { class: 'chips grandi' }, Object.entries(P.gruppi || {}).map(([id, g]) =>
        h('button', { class: `scelta${b.esclusi.includes(id) ? ' on' : ''}`, onclick: () => { colpetto(); b.esclusi = b.esclusi.includes(id) ? b.esclusi.filter((x) => x !== id) : [...b.esclusi, id]; rifai(); } }, g.n))),
      h('div', { class: 'card' }, h('div', { class: 'fra' },
        h('div', null, h('b', null, 'Intollerante al lattosio'), h('div', { class: 'piccolo' }, 'Formaggi e latte del piano sono già senza lattosio; lo scanner ti avvisa sui prodotti che ne hanno.')),
        siNo(b.lattosio, (v) => { b.lattosio = v; rifai(); }))),
    ];
  } else if (nome === 'giornata') {
    const ora = (chiave, etichetta) => h('div', { class: 'campo' }, h('label', null, etichetta),
      h('input', { type: 'time', value: b.orari[chiave], 'aria-label': `Ora di ${etichetta.toLowerCase()}`, oninput: (e) => { if (e.target.value) b.orari[chiave] = e.target.value; } }));
    corpo = [
      h('div', { class: 'top' }, h('div', null, h('div', { class: 'sopra' }, 'Le tue giornate'), h('h1', null, 'A che ora mangi?'))),
      h('div', { class: 'tre-col orari' }, ora('colazione', 'Colazione'), ora('pranzo', 'Pranzo'), ora('cena', 'Cena')),
      h('p', { class: 'piccolo' }, 'Così in cima alla lista trovi sempre il pasto che viene adesso. Spuntini e merenda finiscono a metà strada.'),
      h('div', { class: 'sez' }, h('h2', null, 'Ogni quanto ti pesi?')),
      h('div', { class: 'chips grandi' }, Object.entries(PESATE).map(([id, [titolo]]) =>
        h('button', { class: `scelta${b.pesate === id ? ' on' : ''}`, onclick: () => { colpetto(); b.pesate = id; rifai(); } }, titolo))),
      h('p', { class: 'piccolo' }, 'Quando è ora, te lo ricordo nella schermata di oggi. Niente notifiche.'),
    ];
  } else if (scritto) {
    const da = P.profilo.da;
    const conScheda = P.profilo.conScheda && b.allena;
    const cosa = conScheda ? 'la tua dieta e la tua scheda di allenamento: le trovi' : 'la tua dieta: la trovi';
    corpo = [
      h('div', { class: 'fatto-grande' }, h('span', null, icona('check')), h('h1', null, 'È tutto pronto, ', h('em', null, io.nome))),
      h('div', { class: 'card messaggio' },
        h('p', null, primo && da && !io.capo ? `${da} mi ha già dato ${cosa} qui dentro, giorno per giorno, con le quantità giuste.` : 'Ho sistemato l\'app su quello che mi hai detto.'),
        h('p', null, primo ? 'Buon utilizzo.' : 'Puoi rifare queste domande quando vuoi.')),
      h('div', { class: 'card' }, h('ol', { class: 'passi' },
        menu ? h('li', null, `La dieta la vedi così: ${(menu[b.menu]?.[0] || '').toLowerCase()}.`) : null,
        h('li', null, `${SCOPI[b.obiettivo][0]}: è da qui che guardo come stai andando.`),
        h('li', null, b.allena ? `Ti alleni ${b.giorni.length === 1 ? 'un giorno' : `${b.giorni.length} giorni`} a settimana: ${b.giorni.slice().sort().map((i) => P.giorni[i].toLowerCase()).join(', ')}.` : 'Niente palestra: ti propongo mezz\'ora di movimento al giorno, e se vuoi c\'è un circuito da fare a casa.'),
        h('li', null, `Colazione alle ${b.orari.colazione}, pranzo alle ${b.orari.pranzo}, cena alle ${b.orari.cena}.`))),
    ];
  } else {
    const k = calorie(b);
    corpo = [
      h('div', { class: 'top' }, h('div', null, h('div', { class: 'sopra' }, 'Fatto'), h('h1', null, 'Ecco il tuo piano'))),
      h('div', { class: 'card' },
        h('div', { class: b.allena ? 'due-col' : '' },
          h('div', { class: 'stat' }, h('b', null, intero(k.rest), h('small', null, 'kcal')), h('span', null, b.allena ? 'Giorni di riposo' : 'Ogni giorno')),
          b.allena ? h('div', { class: 'stat' }, h('b', null, intero(k.train), h('small', null, 'kcal')), h('span', null, 'Giorni di palestra')) : null),
        h('ol', { class: 'passi', style: { marginTop: '16px' } },
          h('li', null, `${SCOPI[b.obiettivo][0]}: ${SCOPI[b.obiettivo][1].charAt(0).toLowerCase()}${SCOPI[b.obiettivo][1].slice(1)}.`),
          h('li', null, `A riposo il tuo corpo consuma circa ${intero(k.base)} kcal al giorno; con quello che fai diventano di più.`),
          h('li', null, b.allena ? `${b.giorni.length === 1 ? 'Un allenamento' : `${b.giorni.length} allenamenti`} a settimana, con le schede già pronte.` : 'Niente palestra: punta a mezz\'ora di movimento al giorno, e se vuoi c\'è il circuito a casa.'))),
      h('p', { class: 'piccolo', style: { textAlign: 'center', lineHeight: 1.45 } }, 'È una stima ragionata, non una prescrizione: se hai una malattia o prendi farmaci, senti prima il tuo medico.'),
    ];
  }

  const ultimo = nome === 'fine';
  const primoPasso = passo <= (primo ? 0 : 1);
  return [
    h('div', { class: 'profilo-su' },
      !primoPasso ? h('button', { class: 'tondo', 'aria-label': 'Indietro', onclick: indietro }, icona('back')) : h('span', { style: { width: '40px' } }),
      h('div', { class: 'tacche' }, PASSI.slice(1).map((_, i) => h('i', { class: i < passo ? 'fatta' : '' }))),
      !primo ? h('button', { class: 'tondo', 'aria-label': 'Chiudi', onclick: chiudi }, icona('x')) : h('span', { style: { width: '40px' } })),
    ...corpo.flat(Infinity).filter(Boolean),
    h('div', { class: 'barra-giu' }, h('div', null,
      h('button', { class: 'btn primo', onclick: avanti }, ultimo ? (primo ? 'Inizia' : 'Salva') : nome === 'ciao' ? 'Cominciamo' : 'Avanti', ultimo ? icona('check') : icona('chev')))),
  ];
}

// Usata dalla scheda Piano per dire com'e' impostata l'app.
export const riassuntoProfilo = () => {
  const p = S.profilo;
  if (!p?.fatto) return null;
  return `${SCOPI[p.obiettivo]?.[0] || ''}${siAllena() ? ` · ${p.giorni?.length || 0} allenamenti a settimana` : ' · senza palestra'}`;
};
