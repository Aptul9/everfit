// Il rapporto sulla dieta (Progressi → Dieta): giorno per giorno quanto si e' mangiato rispetto all'obiettivo, i giorni
// in linea e gli sgarri, un grafico delle ultime due settimane, il dettaglio di ogni giorno, e due righe su come sta
// andando. I conti si fanno con il piano di adesso: se nel frattempo e' cambiato, i giorni vecchi risultano misurati
// con gli obiettivi e le quantita' nuove (nel diario resta scritto quali pasti sono stati spuntati, non i loro numeri).

import { h, s, oggi, piuGiorni, daIso, giornoSett, dataCorta, dataLunga, intero, dec, maiuscola } from '../dom.js';
import { S, P, totali, pastiDelGiorno, siAllena, FUORI_PASTO } from '../store.js';
import { M } from '../misure.js';
import { foglio } from '../ui.js';
import { modificaVoce } from './diario.js';

// Dentro questa fascia dell'obiettivo di calorie il giorno e' "in linea"; sopra e' uno sgarro, sotto si e' mangiato poco
// (o non si e' segnato tutto).
const SOPRA = 1.08, SOTTO = 0.85;
export const ESITI = {
  linea: { n: 'In linea', c: 'ok' },
  sgarro: { n: 'Sgarro', c: 'no' },
  poco: { n: 'Sotto', c: 'occhio' },
  corso: { n: 'In corso', c: 'info' },
  vuoto: { n: 'Non segnato', c: 'grigio' },
};
const INIZIALI = ['L', 'M', 'M', 'G', 'V', 'S', 'D'];

// Dove cadono tante calorie rispetto all'obiettivo: 'sopra' (uno sgarro), 'sotto' oppure 'linea'.
export function fascia(kcal, ob) {
  const quota = ob ? kcal / ob : 0;
  return quota > SOPRA && kcal - ob > 120 ? 'sopra' : quota < SOTTO ? 'sotto' : 'linea';
}

export function giornata(d) {
  const t = totali(d);
  const segnato = t.nFatti > 0 || (S.giorni[d]?.extra || []).length > 0;
  const quota = t.ob.kcal ? t.fatto.kcal / t.ob.kcal : 0;
  const dove = fascia(t.fatto.kcal, t.ob.kcal);
  let esito = 'vuoto';
  if (segnato) esito = dove === 'sopra' ? 'sgarro' : d === oggi() && t.nFatti < t.n ? 'corso' : dove === 'sotto' ? 'poco' : 'linea';
  return { d, t, segnato, quota, esito, delta: t.fatto.kcal - t.ob.kcal };
}

const periodo = (n) => Array.from({ length: n }, (_, i) => giornata(piuGiorni(oggi(), i - n + 1)));
const media = (lista, f) => (lista.length ? lista.reduce((a, x) => a + f(x), 0) / lista.length : 0);
const conSegno = (x) => `${x > 0 ? '+' : x < 0 ? '−' : ''}${intero(Math.abs(x))}`;

// Due righe su come sta andando l'ultima settimana: {titolo, tono, frasi}.
function nota(giorni) {
  const chiusi = giorni.filter((g) => g.esito === 'linea' || g.esito === 'sgarro' || g.esito === 'poco');
  if (!chiusi.length) {
    return { titolo: 'Ancora niente da leggere', tono: 'info', frasi: ['Spunta i pasti che mangi e segna quello che è in più: da domani qui vedi se stai andando in linea con il piano.'] };
  }
  const conta = (e) => giorni.filter((g) => g.esito === e).length;
  const li = conta('linea'), sg = conta('sgarro'), po = conta('poco'), vu = conta('vuoto');
  const kcal = media(chiusi, (g) => g.t.fatto.kcal), ob = media(chiusi, (g) => g.t.ob.kcal), scarto = kcal - ob;
  const prot = media(chiusi, (g) => g.t.fatto.p), obProt = media(chiusi, (g) => g.t.ob.p);
  let titolo = 'Quasi in linea', tono = 'occhio';
  if (sg === 0 && Math.abs(scarto) <= ob * 0.08) { titolo = 'Sei in linea'; tono = 'ok'; }
  else if (scarto > ob * 0.08 || sg >= 2) { titolo = 'Stai sforando'; tono = 'no'; }
  else if (scarto < -ob * 0.15) { titolo = 'Stai mangiando troppo poco'; tono = 'occhio'; }
  const pezzi = [li ? `${li} in linea` : null, sg ? `${sg} ${sg === 1 ? 'sgarro' : 'sgarri'}` : null, po ? `${po} sotto` : null, vu ? `${vu} non ${vu === 1 ? 'segnato' : 'segnati'}` : null].filter(Boolean);
  const frasi = [`Negli ultimi 7 giorni: ${pezzi.join(', ')}.`,
    `In media ${intero(kcal)} kcal al giorno su ${intero(ob)} di obiettivo (${conSegno(scarto)}).`];
  const saldo = chiusi.reduce((a, g) => a + g.delta, 0);
  if (sg && saldo > 500) frasi.push(`Gli sgarri pesano: in tutto sei sopra di ${intero(saldo)} kcal, cioè ${dec(saldo / 7700, 2)} kg di grasso che il piano contava di togliere.`);
  if (obProt && prot < obProt * 0.85) frasi.push(`Proteine basse: in media ${intero(prot)} g su ${intero(obProt)}. Sono quelle che tengono il muscolo mentre scendi.`);
  if (po >= 2 && tono !== 'no') frasi.push('Nei giorni «sotto» o hai mangiato poco o non hai segnato tutto: se è la seconda, i conti qui sopra valgono meno.');
  // il peso, se nelle ultime due settimane ci sono almeno due pesate
  const da = piuGiorni(oggi(), -14);
  const pesate = M.pesate.filter((x) => x.giorno >= da);
  if (pesate.length >= 2) {
    const a = pesate[0], b = pesate[pesate.length - 1], d = b.peso - a.peso;
    const giu = P.profilo.pesoObiettivo < a.peso;
    const bene = Math.abs(d) < 0.15 ? null : (d < 0) === giu;
    frasi.push(`Peso: da ${dec(a.peso)} a ${dec(b.peso)} kg (${d > 0 ? '+' : d < 0 ? '−' : ''}${dec(Math.abs(d))}) dal ${dataCorta(a.giorno)}${bene == null ? ': fermo.' : bene ? ': nella direzione giusta.' : ': nella direzione sbagliata.'}`);
  }
  return { titolo, tono, frasi };
}

// Le colonne delle ultime due settimane: alta quanto si e' mangiato, la tacca e' l'obiettivo, il colore dice com'e' andata.
function colonne(giorni, alTocco) {
  const W = 320, H = 150, giu = 26, su = 8, n = giorni.length;
  const tetto = Math.max(1, ...giorni.map((g) => Math.max(g.t.fatto.kcal, g.t.ob.kcal))) * 1.08;
  const passo = W / n, larga = Math.min(16, passo - 6);
  const Y = (kcal) => su + (1 - kcal / tetto) * (H - su - giu);
  return s('svg', { class: 'colonne', viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'Calorie mangiate negli ultimi giorni' },
    giorni.map((g, i) => {
      const x = i * passo + (passo - larga) / 2, alta = Math.max(2, H - giu - Y(g.t.fatto.kcal));
      const data = daIso(g.d);
      return s('g', { class: `col ${ESITI[g.esito].c}${g.d === oggi() ? ' oggi' : ''}`, onclick: () => alTocco(g.d) },
        s('rect', { class: 'tocco', x: i * passo, y: 0, width: passo, height: H }),
        g.segnato ? s('rect', { class: 'pieno', x, y: H - giu - alta, width: larga, height: alta, rx: 4 }) : s('rect', { class: 'pieno', x, y: H - giu - 3, width: larga, height: 3, rx: 1.5 }),
        s('line', { class: 'meta', x1: x - 2, x2: x + larga + 2, y1: Y(g.t.ob.kcal), y2: Y(g.t.ob.kcal) }),
        s('text', { x: i * passo + passo / 2, y: H - 12, 'text-anchor': 'middle' }, INIZIALI[giornoSett(data)]),
        s('text', { class: 'num', x: i * passo + passo / 2, y: H - 1, 'text-anchor': 'middle' }, data.getDate()));
    }));
}

// Il dettaglio di un giorno: i numeri e, pasto per pasto, quello che e' stato mangiato. Lo apre anche la sezione Dieta.
export function apriGiorno(d) {
  const g = giornata(d), t = g.t;
  const numero_ = (nome, fatto, ob, unita) => h('div', { class: 'stat' }, h('b', null, intero(fatto), h('small', null, ` / ${intero(ob)}${unita}`)), h('span', null, nome));
  // una voce del diario si tocca per cambiare quanto ne hai mangiato
  const voce = (e) => h('button', { class: 'rap-riga dentro tocco', onclick: () => modificaVoce(d, e.id) },
    h('span', { class: 'cresce' }, `${e.n}${e.q ? ` · ${e.q}` : ''}`), h('b', null, `${intero(e.kcal || 0)} kcal`));
  const righe = [];
  for (const x of pastiDelGiorno(d)) {
    const nome = P.momenti[x.mom]?.n || x.mom;
    const stato = x.alPosto ? 'sostituito' : x.fatto ? `${intero(x.m.kcal)} kcal` : 'non segnato';
    righe.push(h('div', { class: `rap-riga${x.fatto || x.alPosto ? '' : ' spento'}` },
      h('div', { class: 'cresce' }, h('b', null, nome), h('small', null, x.r.n)), h('span', null, stato)));
    for (const e of x.extra || []) righe.push(voce(e));
  }
  const fuori = (S.giorni[d]?.extra || []).filter((e) => e.mom === FUORI_PASTO);
  if (fuori.length) { righe.push(h('div', { class: 'rap-riga' }, h('div', { class: 'cresce' }, h('b', null, 'Fuori pasto')), h('span', null, ''))); for (const e of fuori) righe.push(voce(e)); }
  foglio(() => [
    h('h2', null, maiuscola(dataLunga(d))),
    h('p', { class: 'muto' }, h('span', { class: `bollo ${ESITI[g.esito].c}` }), ` ${ESITI[g.esito].n}${siAllena() ? ` · ${t.tipo === 'train' ? 'giorno di palestra' : 'giorno di riposo'}` : ''}`
      + (g.segnato ? ` · ${g.delta > 0 ? `${intero(g.delta)} kcal sopra l'obiettivo` : `${intero(-g.delta)} kcal sotto l'obiettivo`}` : '')),
    h('div', { class: 'due-col' }, numero_('kcal', t.fatto.kcal, t.ob.kcal, ''), numero_('proteine', t.fatto.p, t.ob.p, ' g')),
    h('div', { class: 'due-col' }, numero_('carboidrati', t.fatto.c, t.ob.c, ' g'), numero_('grassi', t.fatto.f, t.ob.f, ' g')),
    h('h4', null, 'Cosa hai mangiato'),
    h('div', { class: 'card rap-elenco' }, righe),
  ]);
}

export function cartaRapporto() {
  const giorni = periodo(14);
  const sette = giorni.slice(-7);
  const n = nota(sette);
  const segnati = giorni.filter((g) => g.segnato).reverse();
  return [
    h('div', { class: `card rap-nota ${n.tono}` },
      h('div', { class: 'riga' }, h('span', { class: `bollo grande ${n.tono}` }), h('b', null, n.titolo)),
      n.frasi.map((f) => h('p', null, f))),
    h('div', { class: 'card' },
      h('div', { class: 'fra', style: { marginBottom: '8px' } }, h('b', null, 'Ultimi 14 giorni'), h('span', { class: 'piccolo' }, 'tocca un giorno')),
      colonne(giorni, apriGiorno),
      h('div', { class: 'rap-legenda' }, ['linea', 'sgarro', 'poco', 'vuoto'].map((e) => h('span', null, h('i', { class: `bollo ${ESITI[e].c}` }), ESITI[e].n)), h('span', null, h('i', { class: 'tacca' }), 'obiettivo'))),
    segnati.length ? h('div', { class: 'sez' }, h('h2', null, 'Giorno per giorno')) : null,
    segnati.length ? h('div', { class: 'card rap-elenco' }, segnati.map((g) => h('button', { class: 'rap-riga tocco', onclick: () => apriGiorno(g.d) },
      h('span', { class: `bollo ${ESITI[g.esito].c}` }),
      h('div', { class: 'cresce' }, h('b', null, maiuscola(daIso(g.d).toLocaleDateString('it-IT', { weekday: 'long', day: 'numeric', month: 'short' }))), h('small', null, ESITI[g.esito].n)),
      h('span', null, `${intero(g.t.fatto.kcal)} / ${intero(g.t.ob.kcal)}`)))) : null,
  ];
}
