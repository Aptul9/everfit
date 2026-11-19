import { h, s, icona, oggi, dataLunga, intero, lunedi, piuGiorni, daIso, durata } from '../dom.js';
import { P, S, io, aggiorna, totali, pastiDelGiorno, tipoModello, schedaDelGiorno, sedutaDel, allenato, giorno, volume, iniziaSeduta, siAllena, minutiAttivi, attivitaDel, ATTIVITA, vuole } from '../store.js';
import { ultimaPesata, passiDel } from '../misure.js';
import { anello, macroRiga, spunta, sfondoEsercizi } from '../ui.js';
import { apriPasto, segnaPasto, mostraGiorno, fotoPasto, parteMangiata, grammiDelGiorno } from './dieta.js';
import { apriAttivita, minutiInParole } from './attivita.js';
import { tema, cambiaTema } from '../tema.js';
import { cartaAlPosto, rigaSottoIlPasto, fuoriPianoDelGiorno } from './diario.js';
import { cartaAcqua } from './acqua.js';
import { mostraScheda } from './progressi.js';

const INIZIALI = ['L', 'M', 'M', 'G', 'V', 'S', 'D'];

function cartaGiorno(d, t) {
  const train = t.tipo === 'train';
  const w = schedaDelGiorno(d);
  const cambia = (tipo) => aggiorna(() => {
    const g = giorno(d);
    if (tipo === tipoModello(d)) delete g.tipo; else g.tipo = tipo;
  });
  const mancano = Math.max(0, t.ob.kcal - t.fatto.kcal);
  const oltre = Math.round(t.fatto.kcal - t.ob.kcal);
  const dentro = oltre > 30 ? [h('b', null, `+${intero(oltre)}`), h('span', null, 'kcal oltre')]
    : [h('b', null, intero(mancano)), h('span', null, mancano ? 'kcal rimaste' : 'obiettivo fatto')];
  // non solo quanto resta: anche il tetto del giorno ("937 kcal rimaste su 1.900")
  dentro.push(h('small', { class: 'tetto' }, `su ${intero(t.ob.kcal)}`));
  const mossi = minutiAttivi(d);
  // chi non va in palestra non ha giorni "di palestra" e "di riposo": in cima c'e' il movimento di oggi
  const testa = siAllena()
    ? h('div', { class: 'giorno-tipo' },
      h('div', { class: 'et' }, h('i', { class: train ? '' : 'riposo' }, icona(train ? 'dumbbell' : 'moon')),
        h('div', null, train ? 'Oggi palestra' : 'Oggi riposo',
          h('small', null, train ? (P.schede[w]?.n || 'Allenamento') : 'Recupero attivo'))),
      h('div', { class: 'seg mini', style: { width: '124px', flex: 'none' } },
        h('button', { class: train ? 'on' : '', 'aria-label': 'Giorno di palestra', onclick: () => cambia('train') }, 'Gym'),
        h('button', { class: train ? '' : 'on', 'aria-label': 'Giorno di riposo', onclick: () => cambia('rest') }, 'Riposo')))
    : h('div', { class: 'giorno-tipo' },
      h('div', { class: 'et' }, h('i', { class: 'riposo' }, icona('walk')),
        h('div', null, mossi ? `${minutiInParole(mossi)} di movimento` : 'Oggi zero minuti',
          h('small', null, mossi >= P.obiettivi.camminataMin ? 'Per oggi ci siamo' : `Punta a ${P.obiettivi.camminataMin} minuti`))),
      h('button', { class: 'btn basso', style: { width: 'auto', padding: '0 14px', flex: 'none' }, onclick: () => apriAttivita('camminata') }, icona('plus'), 'Segna'));
  // chi non vuole i numeri vede solo a che punto e' con i pasti di oggi
  if (!vuole('numeri')) {
    const prossimo = pastiDelGiorno(d).find((x) => !x.fatto && !x.alPosto);
    return h('div', { class: 'card' },
      testa,
      h('div', { class: 'eroe' },
        anello({ id: 'pasti', val: t.nFatti, max: t.n, dentro: [h('b', null, `${t.nFatti}/${t.n}`), h('span', null, t.nFatti === t.n ? 'giornata fatta' : 'pasti fatti')] }),
        h('div', { class: 'macro-col' },
          h('b', { style: { fontSize: '17px', letterSpacing: '-.01em' } }, prossimo ? `Adesso: ${prossimo.nome.toLowerCase()}` : 'Hai mangiato tutto'),
          h('span', { class: 'muto', style: { fontSize: '14.5px', lineHeight: 1.35 } }, prossimo ? `${prossimo.r.n}${prossimo.ora ? `, alle ${prossimo.ora}` : ''}` : 'Per oggi il piano è chiuso. A domani.'))));
  }
  return h('div', { class: 'card' },
    testa,
    h('div', { class: 'eroe' },
      anello({ id: 'kcal', val: t.fatto.kcal, max: t.ob.kcal, dentro }),
      h('div', { class: 'macro-col' },
        macroRiga({ id: 'mp', nome: 'Proteine', val: t.fatto.p, max: t.ob.p, colore: 'var(--p)' }),
        macroRiga({ id: 'mc', nome: 'Carboidrati', val: t.fatto.c, max: t.ob.c, colore: 'var(--c)' }),
        macroRiga({ id: 'mf', nome: 'Grassi', val: t.fatto.f, max: t.ob.f, colore: 'var(--f)' }))));
}

function cartaSeduta(d) {
  const w = schedaDelGiorno(d);
  const fatta = sedutaDel(d);
  if (S.attiva && P.schede[S.attiva.w]) {
    const sc = P.schede[S.attiva.w];
    const fatte = S.attiva.voci.reduce((n, x) => n + x.serie.filter((q) => q.ok).length, 0);
    const tot = S.attiva.voci.reduce((n, x) => n + x.serie.length, 0);
    return h('div', { class: 'card piena scheda-eroe tocco', role: 'button', onclick: () => { location.hash = '#/seduta'; } },
      h('div', { class: 'sfondo' }, sfondoEsercizi([S.attiva.voci[S.attiva.i].es, ...S.attiva.voci.map((x) => x.es)])),
      h('div', { class: 'chips' }, h('span', { class: 'chip acc' }, icona('timer'), 'Seduta in corso')),
      h('h3', { style: { marginTop: '8px' } }, sc.n),
      h('div', { class: 'muto', style: { fontSize: '14.5px' } }, `${fatte} serie su ${tot}`),
      h('span', { class: 'btn primo' }, icona('play'), 'Riprendi'));
  }
  if (fatta) {
    const chili = volume(fatta.voci);
    return h('div', { class: 'card tocco', role: 'button', onclick: () => { mostraScheda('allenamenti'); location.hash = '#/progressi'; } },
      h('div', { class: 'riga' },
        spunta(true),
        h('div', { class: 'cresce' }, h('b', { style: { fontSize: '17px' } }, `${P.schede[fatta.w]?.n || 'Seduta'}: fatta`),
          h('div', { class: 'piccolo' }, `${durata(fatta.fine - fatta.inizio)}${chili ? ` · ${intero(chili)} kg sollevati` : ''}`)),
        icona('chev', 'freccia')));
  }
  if (!w || !siAllena()) return null;
  const sc = P.schede[w];
  return h('div', { class: 'card piena scheda-eroe' },
    h('div', { class: 'sfondo' }, sfondoEsercizi(sc.es.map((x) => x[0]))),
    h('div', { class: 'chips' },
      h('span', { class: 'chip vetro' }, icona('dumbbell'), `${sc.es.length} esercizi`),
      h('span', { class: 'chip vetro' }, icona('clock'), `${sc.durata} min`)),
    h('h3', { style: { marginTop: '8px' } }, sc.n),
    h('div', { class: 'muto', style: { fontSize: '14.5px' } }, sc.fuoco),
    h('div', { class: 'riga', style: { marginTop: '14px' } },
      h('button', { class: 'btn', style: { width: 'auto', padding: '0 18px', marginTop: 0 }, onclick: () => { location.hash = `#/allenamento/${w}`; } }, 'Vedi'),
      h('button', { class: 'btn primo', style: { marginTop: 0 }, onclick: () => { iniziaSeduta(w, d); location.hash = '#/seduta'; } }, icona('play'), 'Inizia la seduta')));
}

function rigaPasto(d, x, prossimo) {
  return h('div', { class: `card pasto-riga tocco${x.fatto ? ' fatto' : ''}`, role: 'button', tabindex: 0, onclick: () => apriPasto(d, x.mom) },
    h('div', { class: 'foto' }, fotoPasto(x.r)),
    h('div', { class: 'cresce' },
      h('div', { class: 'ora', style: prossimo ? null : { color: 'var(--tx3)' } }, `${prossimo ? 'Adesso · ' : ''}${x.nome} ${x.ora}`),
      h('h3', null, x.r.n),
      h('div', { class: 'piccolo', style: { marginTop: '3px' } }, [
        vuole('numeri') ? `${intero(x.m.kcal)} kcal · ${intero(x.m.p)} g proteine` : (x.r.min ? `${x.r.come} · ${x.r.min} min` : x.r.come || ''),
        x.senza.length ? `senza ${x.senza.map((i) => i.n.toLowerCase()).join(', ')}` : null,
        parteMangiata(x), grammiDelGiorno(x)].filter(Boolean).join(' · '))),
    h('button', { 'aria-label': 'Segna come mangiato', onclick: (e) => { e.stopPropagation(); segnaPasto(d, x.mom); } }, spunta(x.fatto)));
}

// Il movimento di oggi (camminate e simili) e, per chi la prende, la creatina.
function abitudini(d) {
  const g = S.giorni[d] || {};
  const mossi = attivitaDel(d).reduce((n, a) => n + a.min, 0);
  const cosa = attivitaDel(d).map((a) => (ATTIVITA[a.tipo] || ATTIVITA.altro).n.toLowerCase());
  const fatto = mossi >= P.obiettivi.camminataMin;
  const tessere = [
    vuole('movimento') ? h('button', { class: `card abit tocco${fatto ? ' on' : ''}`, onclick: () => apriAttivita('camminata', d) },
      h('span', { class: 'ic' }, icona(fatto ? 'check' : 'walk')),
      h('div', null, h('b', null, mossi ? minutiInParole(mossi) : 'Camminata'),
        // i passi arrivano dall'app Salute dell'iPhone (il comando di Comandi, vedi Piano)
        h('small', null, [passiDel(d) != null ? `${passiDel(d).toLocaleString('it-IT')} passi` : null,
          mossi ? [...new Set(cosa)].join(', ') : passiDel(d) != null ? null : `${P.obiettivi.camminataMin} minuti`].filter(Boolean).join(' · ')))) : null,
    P.profilo.creatina !== false ? h('button', { class: `card abit tocco${g.creatina ? ' on' : ''}`, onclick: () => aggiorna(() => { const x = giorno(d); x.creatina = !x.creatina; }) },
      h('span', { class: 'ic' }, icona(g.creatina ? 'check' : 'bolt')),
      h('div', null, h('b', null, 'Creatina'), h('small', null, '3-5 grammi'))) : null,
  ].filter(Boolean);
  return tessere.length ? h('div', { class: `abitudini due${tessere.length === 1 ? ' una' : ''}` }, tessere) : null;
}

// Il peso: l'ultima pesata e, quando e' passato il tempo che la persona si e' data, il promemoria per rifarla.
const OGNI = { giorno: 1, settimana: 7, tanto: 30 };
function cartaPeso() {
  const u = ultimaPesata();
  const ogni = OGNI[S.profilo?.pesate] || 7;
  const giorni = u ? Math.round((daIso(oggi()) - daIso(u.giorno)) / 86400000) : null;
  const ora = giorni == null || giorni >= ogni;
  const quando = giorni == null ? 'Ancora nessuna pesata' : giorni === 0 ? 'Pesata di oggi' : giorni === 1 ? 'Pesata di ieri' : `Pesata di ${giorni} giorni fa`;
  return h('button', { class: `card peso-carta tocco${ora ? ' ora' : ''}`, onclick: () => { mostraScheda('corpo'); location.hash = '#/progressi'; } },
    h('span', { class: 'ic' }, icona('scale')),
    h('div', { class: 'cresce' },
      h('b', null, u ? `${String(u.peso).replace('.', ',')} kg` : 'Peso'),
      h('small', null, ora && u ? `${quando}: è ora di rifarla` : quando)),
    ora ? h('span', { class: 'chip acc' }, 'Pesati') : icona('chev', 'freccia'));
}

// Una riga al giorno dalla guida del piano: sempre la stessa per tutta la giornata, diversa domani.
function cartaConsiglio(d) {
  const righe = (P.guida || []).flatMap((g) => g.p.map((t) => [g.t, t]));
  if (!righe.length) return null;
  const [da, testo] = righe[Math.floor(daIso(d).getTime() / 86400000) % righe.length];
  return h('div', { class: 'card consiglio' }, h('span', { class: 'ic' }, icona('bolt')), h('div', null, h('small', null, da), h('p', null, testo)));
}

function settimana(o) {
  const lun = lunedi(o);
  return h('div', { class: 'card', style: { padding: '10px 8px' } },
    h('div', { class: 'settimana' }, INIZIALI.map((l, i) => {
      const d = piuGiorni(lun, i);
      const t = totali(d);
      const quota = t.n ? t.nFatti / t.n : 0;
      const giro = 2 * Math.PI * 13.500;
      const fatta = allenato(d);   // la seduta segnata, oppure un giorno di palestra lasciato su "Gym"
      const train = t.tipo === 'train' || fatta;
      return h('button', { class: d === o ? 'oggi' : '', onclick: () => { mostraGiorno(d); location.hash = '#/dieta'; } },
        h('small', null, l),
        h('span', { class: 'pall' },
          s('svg', { class: 'g', viewBox: '0 0 30 30' },
            s('circle', { class: 'traccia', cx: 15, cy: 15, r: 13.500 }),
            quota ? s('circle', { class: 'fatto', cx: 15, cy: 15, r: 13.500, 'stroke-dasharray': giro, 'stroke-dashoffset': giro * (1 - quota) }) : null),
          train ? icona(fatta ? 'check' : 'dumbbell', `ic${fatta ? ' acc' : ''}`) : h('b', null, daIso(d).getDate())));
    })));
}

// Dentro Safari l'app ha le barre del browser attorno e sembra un sito: sull'iPhone va messa sulla Home.
// L'invito compare solo li', e se lo si rimanda torna dopo dieci giorni.
function invitoHome() {
  const iphone = /iPhone|iPad|iPod/.test(navigator.userAgent);
  if (!iphone || document.documentElement.classList.contains('installata')) return null;
  let rimandato = 0;
  try { rimandato = Number(localStorage.getItem('fit.invito') || 0); } catch { /* senza memoria si mostra sempre */ }
  if (Date.now() - rimandato < 10 * 86400000) return null;
  return h('div', { class: 'card installa' },
    h('span', { class: 'ic' }, icona('phone')),
    h('div', { class: 'cresce' },
      h('b', null, 'Mettila sulla schermata Home'),
      h('p', null, 'Si apre a tutto schermo, senza le barre di Safari, come un\'app vera. Tocca ', h('b', null, 'Condividi'), ' qui sotto e poi ', h('b', null, 'Aggiungi alla schermata Home'), '.'),
      h('button', { class: 'chiudi-invito', onclick: (e) => {
        try { localStorage.setItem('fit.invito', String(Date.now())); } catch { /* pazienza */ }
        e.currentTarget.closest('.installa').remove();
      } }, 'Non ora')));
}

// Solo per l'amministratore: i piani gia' scritti di chi non ha ancora l'account. Finche' non sceglie lui la password
// quelle persone non possono entrare, e senza questo avviso se ne accorgerebbe solo andando a cercare in fondo a Piano.
function cartaAttese() {
  if (!io.capo || !io.attese) return null;
  return h('button', { class: 'card peso-carta attese tocco ora', onclick: () => {
    location.hash = '#/altro';
    setTimeout(() => document.getElementById('carta-persone')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 450);
  } },
    h('span', { class: 'ic' }, icona('users')),
    h('div', { class: 'cresce' },
      h('b', null, io.attese === 1 ? 'Un account da attivare' : `${io.attese} account da attivare`),
      h('small', null, 'Il piano è pronto: scegli la password e possono entrare')),
    h('span', { class: 'chip acc' }, 'Attiva'));
}

export function vistaOggi(_, rifai) {
  const d = oggi();
  const t = totali(d);
  const pasti = pastiDelGiorno(d);
  const prossimo = pasti.find((x) => !x.fatto && !x.alPosto);
  return [
    h('div', { class: 'top' },
      h('div', { class: 'cresce' }, h('div', { class: 'sopra' }, dataLunga(d)), h('h1', { class: 'tronca' }, 'Ciao, ', h('em', null, io.nome || P.profilo.nome))),
      // il tastino dell'aspetto: dal buio (com'e' nata) al chiaro, e ritorno
      h('button', { id: 'cambia-tema', class: 'tondo', 'aria-label': tema() === 'chiaro' ? 'Passa all\'aspetto scuro' : 'Passa all\'aspetto chiaro', onclick: () => { cambiaTema(); rifai(); } }, icona(tema() === 'chiaro' ? 'moon' : 'sun')),
      h('button', { class: 'faccia', 'aria-label': 'Il tuo account', onclick: () => { location.hash = '#/altro'; } }, (io.nome || P.profilo.nome || '?').charAt(0).toUpperCase())),
    invitoHome(),
    cartaAttese(),
    h('div', { class: 'griglia-schede oggi-riepilogo' }, cartaGiorno(d, t), vuole('movimento') ? cartaSeduta(d) : null),
    h('div', { class: 'sez' }, h('h2', null, 'Pasti di oggi'), h('span', null, `${t.nFatti} di ${t.n}`)),
    // un pasto sostituito mostra quello che hai mangiato davvero; le aggiunte stanno sotto al loro pasto
    h('div', { class: 'griglia-schede' }, pasti.map((x) => h('div', { class: 'gruppo-view' },
      x.alPosto ? cartaAlPosto(d, x) : [rigaPasto(d, x, x === prossimo), rigaSottoIlPasto(d, x)]))),
    ...fuoriPianoDelGiorno(d),
    h('div', { class: 'griglia-schede' },
      vuole('acqua') ? h('section', { class: 'gruppo-view' }, h('div', { class: 'sez' }, h('h2', null, 'Acqua')), cartaAcqua(d)) : null,
      vuole('peso') ? h('section', { class: 'gruppo-view' }, h('div', { class: 'sez' }, h('h2', null, 'Peso')), cartaPeso()) : null,
      abitudini(d) ? h('section', { class: 'gruppo-view' }, h('div', { class: 'sez' }, h('h2', null, P.profilo.creatina !== false ? 'Abitudini' : 'Movimento')), abitudini(d)) : null,
      vuole('consiglio') && cartaConsiglio(d) ? h('section', { class: 'gruppo-view' }, h('div', { class: 'sez' }, h('h2', null, 'Consiglio del giorno')), cartaConsiglio(d)) : null),
    h('div', { class: 'sez' }, h('h2', null, 'Questa settimana')),
    settimana(d),
  ];
}
