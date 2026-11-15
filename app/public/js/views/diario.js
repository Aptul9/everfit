// Diario: quello che hai mangiato fuori dal piano. Il foglio fa tre domande in fila:
//   1. quando (a quale pasto, o fuori pasto)
//   2. in piu' o al posto di qualcosa, e di cosa (uno o piu' ingredienti del pasto previsto, o tutto)
//   3. cosa: cercandolo, dal codice a barre, da una foto o scrivendolo a mano, e quanto
//
// Un cibo, qui dentro, e' { n, marca, ean, per, kcal, p, c, f, pz, pzn, conf, img, stima, fonte }:
// i valori valgono per 100 grammi (per: 100) oppure per un pezzo o una porzione (per: 'pz').

import { h, icona, intero, dec, numero, oggi } from '../dom.js';
import {
  P, S, io, pastiDelGiorno, tipoGiorno, macro, ingredienti, aggiungiExtra, togliExtra, ricordaProdotto,
  prodottiRecenti, fuoriPasto, sommaVoci, FUORI_PASTO, cambiaVoce, quantitaVoce, vocePer,
} from '../store.js';
import { foglio, avviso, spunta } from '../ui.js';
import { avviaLettore, fotocameraDisponibile, codiceValido } from '../codice.js';
import { conLaFoto, ricordaScanner, tastoFoto, notaPermesso, TESTO_FOTO, TESTO_VIVO, PASSA_ALLA_FOTO, PASSA_AL_VIVO } from '../scatto.js';

const CRUDI = new Set(['riso', 'pasta', 'patate', 'pollo', 'tacchino', 'hamburger', 'salmone', 'merluzzo', 'gamberi', 'spinaci', 'piselli']);
const liscio = (t) => String(t || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
const una = (v) => Math.round(v * 10) / 10;
const elenca = (nomi) => (nomi.length > 1 ? `${nomi.slice(0, -1).join(', ')} e ${nomi[nomi.length - 1]}` : nomi[0] || '');
const PEZZO = ['pezzo', 'pezzi'];
let conFoto = null;   // questo account ha una chiave per riconoscere le foto? Lo dice io.ai.

// La foto della confezione sta sul sito di Open Food Facts, in piu' misure: per le righe basta la piccola.
const mini = (url) => String(url).replace(/\.400\.jpg$/, '.200.jpg');
function fotoProdotto(url, classe) {
  if (!url) return null;
  const img = h('img', { src: url, alt: '', loading: 'lazy', decoding: 'async', referrerpolicy: 'no-referrer' });
  const scatola = h('div', { class: classe }, img);
  img.addEventListener('error', () => scatola.remove(), { once: true });   // senza rete, o foto tolta dal catalogo
  return scatola;
}

function catalogo(d) {
  const tipo = tipoGiorno(d);
  return [
    ...prodottiRecenti().map((a) => ({ ...a, per: a.per || 100, gruppo: 'I tuoi' })),
    ...(P.fuori || []).map((a) => ({ n: a.n, per: 'pz', kcal: a.kcal, p: a.p, c: a.c, f: a.f, pzn: a.u, stima: true, gruppo: a.gr, fonte: 'fuori' })),
    ...(P.comuni || []).map((a) => ({ n: a.n, per: 100, kcal: a.kcal, p: a.p, c: a.c, f: a.f, pz: a.pz || null, pzn: a.pzn || null, gruppo: 'Cibi comuni', fonte: 'comune' })),
    ...Object.entries(P.cibi).map(([id, a]) => ({
      n: a.n, per: 100, kcal: a.kcal, p: a.p, c: a.c, f: a.f, pz: a.pz || null, pzn: a.pzn || null,
      gruppo: 'Dal piano', fonte: 'piano', nota: CRUDI.has(id) ? 'peso a crudo' : null,
    })),
    ...Object.entries(P.ricette).filter(([, r]) => !r.libero).map(([id, r]) => ({
      n: r.n, per: 'pz', ...macro(id, tipo), pzn: ['porzione', 'porzioni'], gruppo: 'Ricette del piano', fonte: 'ricetta',
    })),
  ];
}

const perUnita = (a) => (a.per === 'pz' ? `${intero(a.kcal)} kcal a ${a.pzn?.[0] || 'porzione'}` : `${intero(a.kcal)} kcal per 100 g`);

// Come una voce sta rispetto al pasto previsto: "in piu'", "al posto di tutto il pasto", "al posto di riso e pomodorini".
export function viaTesto(via) {
  if (!via?.length) return 'in più';
  if (via.includes('*')) return 'al posto di tutto il pasto';
  return `al posto di ${elenca(via.map((id) => (P.cibi[id]?.n || id).toLowerCase()))}`;
}

// Il pasto piu' vicino all'ora di adesso: e' quasi sempre quello che si sta segnando.
function momentoVicino(d) {
  const pasti = pastiDelGiorno(d).filter((x) => !x.con);
  if (!pasti.length || d !== oggi()) return null;
  const ora = new Date();
  const adesso = ora.getHours() * 60 + ora.getMinutes();
  let meglio = pasti[0], distanza = Infinity;
  for (const x of pasti) {
    const [hh, mm] = x.ora.split(':').map(Number);
    const dist = Math.abs(hh * 60 + mm - adesso);
    if (dist < distanza) { distanza = dist; meglio = x; }
  }
  return meglio.mom;
}

async function prodottoDaEan(ean) {
  const mio = S.prodotti?.[ean];
  if (mio) return { ...mio, per: mio.per || 100 };
  let r;
  try { r = await fetch(`api/cibo/ean/${ean}`); } catch { throw new Error('Sei senza rete: scrivi i valori a mano o riprova dopo.'); }
  if (r.status === 404) return null;
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.errore || 'Il catalogo dei prodotti non risponde.');
  return { ...j, per: 100 };
}

// La foto viene rimpicciolita sul telefono: al server bastano 1280 pixel di lato. Restituisce il JPEG in base64.
export async function rimpicciolisci(file, lato = 1280, qualita = 0.82) {
  const url = URL.createObjectURL(file);
  try {
    const img = await new Promise((ok, no) => {
      const i = new Image();
      i.onload = () => ok(i);
      i.onerror = () => no(new Error('Non riesco a leggere questa foto.'));
      i.src = url;
    });
    const k = Math.min(1, lato / Math.max(img.naturalWidth, img.naturalHeight));
    const tela = document.createElement('canvas');
    tela.width = Math.round(img.naturalWidth * k);
    tela.height = Math.round(img.naturalHeight * k);
    tela.getContext('2d').drawImage(img, 0, 0, tela.width, tela.height);
    return tela.toDataURL('image/jpeg', qualita).split(',')[1];
  } finally {
    URL.revokeObjectURL(url);
  }
}

function quattro(t) {
  return [
    h('div', { class: 'k' }, h('b', null, intero(t.kcal)), h('span', null, 'kcal')),
    h('div', { class: 'p' }, h('b', null, dec(t.p)), h('span', null, 'proteine')),
    h('div', { class: 'c' }, h('b', null, dec(t.c)), h('span', null, 'carbo')),
    h('div', { class: 'f' }, h('b', null, dec(t.f)), h('span', null, 'grassi')),
  ];
}

// `pronto` = un cibo gia' scelto (per esempio dallo scanner): si chiede solo quando e come, poi si va dritti alla quantita'.
export function apriDiario(d, momIniziale = null, pronto = null) {
  // modo: quando -> come -> cosa -> (quantita | codice | etichetta | mano | foto) -> riepilogo
  const st = { modo: 'quando', vista: [], mom: null, via: [], scelti: new Set(), sostituisco: false, gruppo: null, online: null };
  let spegni = null;   // la fotocamera accesa, se c'e'
  let giro = 0;        // cambia a ogni cambio di schermata: chi arriva in ritardo se ne accorge
  let f = null;

  const vai = (modo, vista = []) => {
    document.activeElement?.blur?.();   // su iPhone un bottone non toglie il fuoco al campo, e il foglio non si ridisegnerebbe
    giro++;
    if (spegni) { spegni(); spegni = null; }
    st.modo = modo; st.vista = vista;
    f.ridisegna();
    f.el.querySelector('.corpo').scrollTop = 0;
  };
  const indietro = (dove = 'cosa') => h('button', { class: 'indietro', onclick: () => vai(dove) }, icona('back'), 'Indietro');
  const pasto = () => pastiDelGiorno(d).find((x) => x.mom === st.mom) || null;
  const voci = () => (pasto() ? pasto().extra : fuoriPasto(d));

  function scegliMomento(mom) {
    st.mom = mom;
    st.via = []; st.scelti = new Set(); st.sostituisco = false;
    const x = pasto();
    if (!x) { st.mom = FUORI_PASTO; if (voci().length && !daUsare) vai('riepilogo'); else versoCosa(); return; }
    if (x.extra.length && !daUsare) vai('riepilogo'); else vai('come');
  }

  // Salva una voce; la prima porta con se' cio' che sostituisce, le eventuali altre dello stesso giro sono "in piu'".
  function segna(voce) {
    aggiungiExtra(d, st.mom, voce, st.via);
    st.via = [];
  }
  const fatto = () => { campo.value = ''; st.online = null; st.gruppo = null; avviso('Aggiunto al diario'); vai('riepilogo'); };

  // ---------- 1. quando ----------
  function vistaQuando() {
    // il caffe' della colazione ha la sua spunta ma non e' un pasto a cui attaccare altro
    const pasti = pastiDelGiorno(d).filter((x) => !x.con);
    const vicino = momentoVicino(d);
    return [
      h('div', null, h('h2', null, 'Quando l\'hai mangiato?'), h('p', { class: 'muto', style: { marginTop: '4px' } }, pronto ? `${pronto.n}: scegli il pasto a cui attaccarlo.` : 'Fuori dal piano, a casa o in giro: scegli il pasto a cui attaccarlo.')),
      h('div', { class: 'card elenco' }, pasti.map((x) => h('button', { class: 'voce', onclick: () => scegliMomento(x.mom) },
        h('div', { class: 'cresce' },
          h('b', null, x.nome, x.mom === vicino ? h('span', { class: 'chip acc', style: { marginLeft: '8px' } }, 'adesso') : null),
          h('small', null, `${x.ora} · ${x.alPosto ? `hai segnato ${nomiVoci(x.extra)}` : `previsto ${x.r.n}`}`)),
        icona('chev', 'piu')))),
      h('button', { class: 'card in-piu tocco', style: { marginTop: 0 }, onclick: () => scegliMomento(FUORI_PASTO) },
        icona('star'),
        h('div', { class: 'cresce' }, h('b', null, 'Fuori pasto'), h('small', null, 'Uno sfizio lontano dai pasti: si somma al resto della giornata.')),
        icona('chev', 'piu')),
      h('button', { class: 'btn', onclick: () => f.chiudi() }, 'Annulla'),
    ];
  }

  // ---------- 2. in piu' o al posto di qualcosa ----------
  function vistaCome() {
    const x = pasto();
    if (!x) return vistaQuando();
    const previsti = ingredienti(x.rid, x.tipo);
    const liberi = previsti.filter((i) => !x.tolti.has(i.id));
    const avanti = (via) => { st.via = via; versoCosa(); };
    // niente da scegliere: pasto libero, un ingrediente solo, oppure gia' tutto sostituito
    const tuttoInsieme = x.r.libero || previsti.length <= 1;
    const tutti = liberi.length > 0 && liberi.every((i) => st.scelti.has(i.id));
    const alterna = (id) => { if (st.scelti.has(id)) st.scelti.delete(id); else st.scelti.add(id); f.ridisegna(); };
    return [
      momIniziale ? null : indietro('quando'),
      h('div', null,
        h('h2', null, `${x.nome}: in più o al posto di qualcosa?`),
        h('p', { class: 'muto', style: { marginTop: '4px' } }, x.alPosto ? `Hai già segnato ${nomiVoci(x.extra)} al posto del pasto previsto.` : `Era previsto: ${x.r.n}.`)),
      h('button', { class: 'card in-piu tocco', style: { marginTop: 0 }, onclick: () => avanti([]) },
        icona('plus'),
        h('div', { class: 'cresce' }, h('b', null, 'In più'), h('small', null, x.alPosto ? 'Si aggiunge a quello che hai già segnato.' : 'Mangio anche il pasto previsto, questo si aggiunge.')),
        icona('chev', 'piu')),
      x.alPosto ? null : h('button', { class: `card in-piu tocco${st.sostituisco ? ' scelta-on' : ''}`, style: { marginTop: 0 }, onclick: () => {
        if (tuttoInsieme) { avanti(['*']); return; }
        st.sostituisco = !st.sostituisco; f.ridisegna();
      } },
        icona('swap'),
        h('div', { class: 'cresce' }, h('b', null, tuttoInsieme ? 'Al posto del pasto' : 'Al posto di qualcosa'),
          h('small', null, tuttoInsieme ? `Non conto «${x.r.n}».` : 'Scegli cosa non hai mangiato: una cosa sola, più di una o tutto.')),
        icona('chev', 'piu')),
      st.sostituisco && !tuttoInsieme ? h('div', { class: 'card elenco' },
        h('button', { class: 'voce', onclick: () => { if (tutti) st.scelti.clear(); else liberi.forEach((i) => st.scelti.add(i.id)); f.ridisegna(); } },
          spunta(tutti), h('div', { class: 'cresce' }, h('b', null, 'Tutto il pasto'), h('small', null, `${intero(x.m.kcal)} kcal`))),
        previsti.map((i) => (x.tolti.has(i.id)
          ? h('div', { class: 'voce presa' }, spunta(true), h('div', { class: 'cresce' }, h('b', null, i.n), h('small', null, 'già sostituito')))
          : h('button', { class: 'voce', onclick: () => alterna(i.id) },
            spunta(st.scelti.has(i.id)), h('div', { class: 'cresce' }, h('b', null, i.n), h('small', null, `${i.q} · ${intero(i.kcal)} kcal`)))))) : null,
      st.sostituisco && !tuttoInsieme ? h('button', { class: 'btn primo', onclick: () => {
        if (!st.scelti.size) { avviso('Scegli almeno una cosa', 'info'); return; }
        avanti(tutti && !x.tolti.size ? ['*'] : [...st.scelti]);
      } }, 'Avanti', icona('chev')) : null,
    ];
  }

  // ---------- quanto ne hai mangiato ----------
  function editor(a) {
    const nomi = a.pzn || PEZZO;
    const soloPezzi = a.per === 'pz';
    const passo = soloPezzi && a.kcal < 150 ? 1 : 0.5;
    const q = { n: 1, g: soloPezzi ? null : (a.pz || (a.conf && a.conf <= 250 ? a.conf : 100)) };
    const fattore = () => (soloPezzi ? q.n : (q.g || 0) / 100);
    const quanti = h('b', null);
    const come = h('span', null);
    const grammi = h('input', { type: 'text', inputmode: 'decimal', autocomplete: 'off', 'aria-label': 'Grammi' });
    const esito = h('div', { class: 'quattro' });

    const mostra = (daGrammi = false) => {
      if (!soloPezzi && a.pz) { if (daGrammi) q.n = (q.g || 0) / a.pz; else q.g = una(q.n * a.pz); }
      quanti.textContent = dec(q.n, 1);
      come.textContent = nomi[Math.abs(q.n - 1) < 0.01 ? 0 : 1];
      if (!daGrammi && !soloPezzi) grammi.value = dec(q.g, 1);
      const k = fattore();
      esito.replaceChildren(...quattro({ kcal: a.kcal * k, p: a.p * k, c: a.c * k, f: a.f * k }));
    };
    const muovi = (verso) => { q.n = Math.max(passo, Math.round((q.n + verso * passo) / passo) * passo); mostra(); };
    grammi.addEventListener('input', () => { q.g = Math.max(0, numero(grammi.value) || 0); mostra(true); });
    const svelta = (testo, g) => h('button', { class: 'scelta', onclick: () => { q.g = una(g); if (a.pz) q.n = q.g / a.pz; mostra(); grammi.value = dec(q.g, 1); } }, testo);

    const aggiungi = () => {
      const k = fattore();
      if (!(k > 0)) { avviso('Scrivi quanto ne hai mangiato', 'info'); return; }
      const tondo = Math.abs(q.n * 2 - Math.round(q.n * 2)) < 0.02;
      const testo = soloPezzi ? `${dec(q.n, 1)} ${nomi[q.n === 1 ? 0 : 1]}`
        : (a.pz && tondo ? `${dec(q.n, 1)} ${nomi[q.n === 1 ? 0 : 1]} · ${intero(q.g)} g` : `${intero(q.g)} g`);
      segna({
        n: a.n, marca: a.marca || null, ean: a.ean || null, img: a.img || null, q: testo, g: soloPezzi ? null : Math.round(q.g),
        kcal: Math.round(a.kcal * k), p: una(a.p * k), c: una(a.c * k), f: una(a.f * k),
        fonte: a.fonte || 'mio', stima: !!a.stima,
      });
      if (a.ean || a.fonte === 'mio' || a.fonte === 'off') ricordaProdotto(a);
      fatto();
    };

    mostra();
    return [
      indietro(),
      h('div', { class: 'riga', style: { alignItems: 'flex-start' } },
        fotoProdotto(a.img, 'prodotto-foto'),
        h('div', { class: 'cresce' },
          h('h2', null, a.n),
          h('p', { class: 'muto', style: { marginTop: '4px' } }, [a.marca, perUnita(a), soloPezzi ? null : `P ${dec(a.p)} · C ${dec(a.c)} · G ${dec(a.f)}`, a.nota, a.stima ? 'valori medi, è una stima' : null].filter(Boolean).join(' · ')))),
      soloPezzi || a.pz ? h('div', { class: 'quanti' },
        h('button', { class: 'tondo', 'aria-label': 'Meno', onclick: () => muovi(-1) }, icona('minus')),
        h('div', null, quanti, come),
        h('button', { class: 'tondo', 'aria-label': 'Più', onclick: () => muovi(1) }, icona('plus'))) : null,
      soloPezzi ? null : h('div', { class: 'campo' }, h('label', null, 'Grammi'), grammi),
      soloPezzi ? null : h('div', { class: 'scorri' },
        a.conf ? [svelta('¼ di confezione', a.conf / 4), svelta('Metà', a.conf / 2), svelta(`Tutta · ${intero(a.conf)} g`, a.conf)]
          : [50, 100, 150, 200, 300].map((g) => svelta(`${g} g`, g))),
      soloPezzi ? null : h('button', { class: 'collega', onclick: () => vai('quantita', editorPezzo(a)) },
        a.pz ? `1 ${nomi[0]} = ${dec(a.pz, 1)} g · cambia` : 'Si conta a pezzi? Dimmi quanto pesa un pezzo'),
      esito,
      h('button', { class: 'btn primo', onclick: aggiungi }, icona('plus'), 'Aggiungi'),
    ];
  }

  // Quanto pesa un pezzo: si scrive il peso, oppure quanti ce ne sono nella confezione.
  function editorPezzo(a) {
    const peso = h('input', { type: 'text', inputmode: 'decimal', autocomplete: 'off', placeholder: a.pz ? dec(a.pz, 1) : '110' });
    const quanti = h('input', { type: 'text', inputmode: 'numeric', autocomplete: 'off', placeholder: '3' });
    const pronto = () => {
      const n = numero(quanti.value);
      const g = numero(peso.value) || (a.conf && n > 0 ? a.conf / n : null);
      if (!(g >= 1 && g <= 2000)) { avviso('Scrivi il peso di un pezzo in grammi', 'info'); return; }
      a.pz = una(g);
      if (!a.pzn || a.pzn[0] === 'porzione') a.pzn = PEZZO;
      if (a.ean || a.fonte === 'mio' || a.fonte === 'off') ricordaProdotto(a);
      vai('quantita', editor(a));
    };
    return [
      h('button', { class: 'indietro', onclick: () => vai('quantita', editor(a)) }, icona('back'), 'Indietro'),
      h('div', null, h('h2', null, 'Quanto pesa un pezzo?'), h('p', { class: 'muto', style: { marginTop: '4px' } }, `${a.n}: me lo ricordo per le prossime volte.`)),
      h('div', { class: 'campo' }, h('label', null, 'Un pezzo pesa, in grammi'), peso),
      a.conf ? h('div', { class: 'campo' }, h('label', null, `Oppure: quanti pezzi nella confezione da ${intero(a.conf)} g`), quanti) : null,
      h('button', { class: 'btn primo', onclick: pronto }, icona('check'), 'Fatto'),
    ];
  }

  const scegli = (a) => vai('quantita', editor({ ...a }));
  // con un cibo gia' scelto si salta la ricerca (una volta sola: da li' in poi il foglio torna quello di sempre)
  let daUsare = pronto;
  function versoCosa() {
    if (daUsare) { const a = daUsare; daUsare = null; scegli(a); } else vai('cosa');
  }

  // Un prodotto trovato nella ricerca in rete ha solo i valori: la scheda intera dice anche quanto pesa un pezzo.
  async function scegliInRete(a) {
    const mio = ++giro;
    avviso('Apro la scheda…', 'search');
    let pieno = null;
    try { pieno = await prodottoDaEan(a.ean); } catch { /* ci si accontenta di quello che c'e' */ }
    if (mio !== giro) return;
    scegli(pieno && pieno.kcal != null ? pieno : a);
  }

  // ---------- etichetta scritta a mano (prodotto che il catalogo non conosce) ----------
  function vistaEtichetta(base) {
    const campi = {
      n: h('input', { type: 'text', autocomplete: 'off', placeholder: 'Piadina sfogliata', value: base.n && base.n !== 'Prodotto senza nome' ? base.n : '' }),
      kcal: h('input', { type: 'text', inputmode: 'decimal', autocomplete: 'off', placeholder: '310' }),
      p: h('input', { type: 'text', inputmode: 'decimal', autocomplete: 'off', placeholder: '8' }),
      c: h('input', { type: 'text', inputmode: 'decimal', autocomplete: 'off', placeholder: '50' }),
      f: h('input', { type: 'text', inputmode: 'decimal', autocomplete: 'off', placeholder: '9' }),
      pz: h('input', { type: 'text', inputmode: 'decimal', autocomplete: 'off', placeholder: 'facoltativo', value: base.pz ? dec(base.pz, 1) : '' }),
    };
    const salva = () => {
      const nome = campi.n.value.trim();
      const kcal = numero(campi.kcal.value);
      if (!nome) { campi.n.focus(); avviso('Dagli un nome', 'info'); return; }
      if (kcal == null || kcal < 0 || kcal > 950) { campi.kcal.focus(); avviso('Scrivi le calorie per 100 grammi', 'info'); return; }
      const g = (x) => Math.min(100, Math.max(0, numero(x.value) || 0));
      const pz = numero(campi.pz.value);
      const a = {
        n: nome.slice(0, 80), marca: base.marca || null, ean: base.ean || null, img: base.img || null, per: 100, kcal: Math.round(kcal),
        p: g(campi.p), c: g(campi.c), f: g(campi.f), pz: pz >= 1 ? una(pz) : null, pzn: pz >= 1 ? PEZZO : null,
        conf: base.conf || null, fonte: 'mio',
      };
      ricordaProdotto(a);
      scegli(a);
    };
    return [
      indietro(),
      h('div', { class: 'riga', style: { alignItems: 'flex-start' } },
        fotoProdotto(base.img, 'prodotto-foto'),
        h('div', { class: 'cresce' },
          h('h2', null, base.ean ? 'Questo non lo conosco' : 'Prodotto nuovo'),
          h('p', { class: 'muto', style: { marginTop: '4px' } }, `${base.ean ? `Il codice ${base.ean} non ha i valori nel catalogo. ` : ''}Copiali dall'etichetta, colonna «per 100 g»: li scrivi una volta e me lo ricordo.`))),
      h('div', { class: 'campo' }, h('label', null, 'Nome'), campi.n),
      h('div', { class: 'due-col' },
        h('div', { class: 'campo' }, h('label', null, 'Calorie (kcal)'), campi.kcal),
        h('div', { class: 'campo' }, h('label', null, 'Proteine (g)'), campi.p)),
      h('div', { class: 'due-col' },
        h('div', { class: 'campo' }, h('label', null, 'Carboidrati (g)'), campi.c),
        h('div', { class: 'campo' }, h('label', null, 'Grassi (g)'), campi.f)),
      h('div', { class: 'campo' }, h('label', null, 'Peso di un pezzo, in grammi'), campi.pz),
      h('button', { class: 'btn primo', onclick: salva }, icona('check'), 'Salva e continua'),
    ];
  }

  // ---------- scritto a mano, senza grammi: "una roba da 400 calorie" ----------
  function vistaMano() {
    const campi = {
      n: h('input', { type: 'text', autocomplete: 'off', placeholder: 'Aperitivo con gli amici' }),
      kcal: h('input', { type: 'text', inputmode: 'decimal', autocomplete: 'off', placeholder: '400' }),
      p: h('input', { type: 'text', inputmode: 'decimal', autocomplete: 'off', placeholder: '0' }),
      c: h('input', { type: 'text', inputmode: 'decimal', autocomplete: 'off', placeholder: '0' }),
      f: h('input', { type: 'text', inputmode: 'decimal', autocomplete: 'off', placeholder: '0' }),
    };
    const salva = () => {
      const nome = campi.n.value.trim();
      const kcal = numero(campi.kcal.value);
      if (!nome) { campi.n.focus(); avviso('Scrivi cosa hai mangiato', 'info'); return; }
      if (!(kcal > 0 && kcal < 6000)) { campi.kcal.focus(); avviso('Scrivi le calorie, anche a occhio', 'info'); return; }
      const g = (x) => Math.min(600, Math.max(0, numero(x.value) || 0));
      const valori = { kcal: Math.round(kcal), p: una(g(campi.p)), c: una(g(campi.c)), f: una(g(campi.f)) };
      segna({ n: nome.slice(0, 80), q: '', g: null, ...valori, fonte: 'mano', stima: true });
      ricordaProdotto({ n: nome.slice(0, 80), per: 'pz', ...valori, pzn: ['porzione', 'porzioni'], fonte: 'mio' });
      fatto();
    };
    return [
      indietro(),
      h('div', null, h('h2', null, 'Scrivilo tu'), h('p', { class: 'muto', style: { marginTop: '4px' } }, 'Per quello che non trovi. Bastano il nome e le calorie, anche stimate; il resto se lo sai.')),
      h('div', { class: 'campo' }, h('label', null, 'Cosa'), campi.n),
      h('div', { class: 'due-col' },
        h('div', { class: 'campo' }, h('label', null, 'Calorie (kcal)'), campi.kcal),
        h('div', { class: 'campo' }, h('label', null, 'Proteine (g)'), campi.p)),
      h('div', { class: 'due-col' },
        h('div', { class: 'campo' }, h('label', null, 'Carboidrati (g)'), campi.c),
        h('div', { class: 'campo' }, h('label', null, 'Grassi (g)'), campi.f)),
      h('button', { class: 'btn primo', onclick: salva }, icona('plus'), 'Aggiungi'),
    ];
  }

  // ---------- codice a barre ----------
  function vistaCodice() {
    const video = h('video', { playsinline: true, muted: true, autoplay: true });
    const lettore = h('div', { class: 'lettore' }, video, h('div', { class: 'mira' }));
    const conFoto_ = conLaFoto();   // dal vivo, a meno che la persona non abbia scelto di scattare una foto: vedi scatto.js
    let conNota = !conFoto_;
    const stato = h('p', { class: 'piccolo', style: { textAlign: 'center' } }, conFoto_ ? TESTO_FOTO : TESTO_VIVO);
    const cifre = h('input', { type: 'text', inputmode: 'numeric', autocomplete: 'off', maxlength: 14, placeholder: '8001234567890' });

    const trova = async (codice) => {
      const ean = codice.replace(/\D/g, '');
      if (!codiceValido(ean)) { avviso('Il codice non torna: ricontrolla le cifre', 'info'); return; }
      const mio = giro;
      stato.textContent = `Cerco ${ean}…`;
      try {
        const a = await prodottoDaEan(ean.length === 12 ? `0${ean}` : ean);
        if (mio !== giro) return;
        if (!a || a.kcal == null) vai('etichetta', vistaEtichetta(a || { ean }));
        else scegli(a);
      } catch (e) {
        if (mio !== giro) return;
        // la fotocamera a questo punto e' spenta: il codice resta nel campo, basta ripremere Cerca
        stato.textContent = e.message;
        cifre.value = ean;
      }
    };
    const cerca = () => trova(cifre.value);
    cifre.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); cerca(); } });

    const scattoCodice = tastoFoto(stato, (c) => trova(c));
    const altroModo = h('button', { class: 'testo-link', style: { marginTop: 0 }, onclick: () => { ricordaScanner(conFoto_ ? 'vivo' : 'foto'); spegni?.(); vai('codice', vistaCodice()); } },
      conFoto_ ? PASSA_AL_VIVO : PASSA_ALLA_FOTO);
    if (conFoto_) {
      lettore.replaceChildren(scattoCodice.campo, scattoCodice.tasto);
      lettore.className = '';
    } else if (fotocameraDisponibile()) {
      const mio = giro + 1;   // il giro che `vai` sta per aprire
      avviaLettore(video, trova).then((ferma) => { if (mio === giro) spegni = ferma; else ferma(); }).catch(() => {
        lettore.remove();
        stato.textContent = 'La fotocamera non parte (serve il permesso). Scrivi i numeri che trovi sotto le barre.';
      });
    } else {
      lettore.remove();
      conNota = false;
      stato.textContent = 'Scrivi i numeri che trovi sotto le barre.';
    }
    return [
      indietro(),
      h('h2', null, 'Codice a barre'),
      lettore, stato, conNota ? notaPermesso() : null, altroModo,
      h('div', { class: 'campo' }, h('label', null, 'Oppure scrivi i numeri'), cifre),
      h('button', { class: 'btn primo', onclick: cerca }, icona('search'), 'Cerca'),
    ];
  }

  // ---------- foto del piatto ----------
  const scatto = h('input', { type: 'file', accept: 'image/*', hidden: true });
  scatto.addEventListener('change', () => { const file = scatto.files?.[0]; scatto.value = ''; if (file) guarda(file); });

  function apriFoto() {
    if (conFoto) { scatto.click(); return; }
    vai('foto', [
      indietro(),
      h('div', { class: 'festa' }, h('div', { class: 'bilancia-onda' }, icona('camera')), h('h2', null, 'Foto del piatto: da accendere')),
      h('p', { class: 'muto' }, 'Fotografi il piatto e l\'app stima cosa c\'è e quanto pesa. Per farlo serve la chiave di un servizio che sa guardare le immagini, messa sul server: quella gratuita di Google (Gemini) va benissimo.'),
      h('div', { class: 'nota' }, icona('info'), h('span', null, 'Come si accende è scritto nel README del progetto, alla voce «Foto del piatto». Intanto codice a barre e ricerca funzionano già.')),
    ]);
  }

  async function guarda(file) {
    vai('foto', [
      indietro(),
      h('div', { class: 'festa' }, h('div', { class: 'bilancia-onda viva' }, icona('camera')), h('h2', null, 'Guardo la foto'),
        h('p', { class: 'muto' }, 'Qualche secondo: riconosco il piatto e stimo le quantità.')),
    ]);
    const mio = giro;
    const errore = (testo) => vai('foto', [
      indietro(), h('h2', null, 'Non ci sono riuscito'), h('p', { class: 'muto' }, testo),
      h('button', { class: 'btn primo', onclick: () => scatto.click() }, icona('camera'), 'Riprova con un\'altra foto'),
    ]);
    try {
      const immagine = await rimpicciolisci(file);
      let r;
      try { r = await fetch('api/foto', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ immagine }) }); } catch { throw new Error('Sei senza rete.'); }
      const j = await r.json().catch(() => ({}));
      if (mio !== giro) return;
      if (!r.ok) throw new Error(j.errore || 'Il riconoscimento non ha risposto.');
      if (j.ean && codiceValido(j.ean)) {   // nella foto c'era una confezione: vale il suo codice a barre
        const a = await prodottoDaEan(j.ean).catch(() => null);
        if (mio !== giro) return;
        if (a && a.kcal != null) { scegli(a); return; }
        if (!j.voci?.length) { vai('etichetta', vistaEtichetta(a || { ean: j.ean })); return; }
      }
      if (!j.voci?.length) throw new Error(j.nota || 'Nella foto non ho riconosciuto niente da mangiare.');
      vai('foto', vistaFoto(j));
    } catch (e) {
      if (mio === giro) errore(e.message);
    }
  }

  function vistaFoto(j) {
    const trovate = j.voci.map((v) => ({ ...v, dentro: true }));
    let quota = 1;
    const lista = h('div', { class: 'card elenco' });
    const porzione = h('div', { class: 'seg mini' });
    const totale = h('div', { class: 'quattro' });
    const mostra = () => {
      lista.replaceChildren(...trovate.map((v) => h('button', { class: `voce${v.dentro ? '' : ' presa'}`, onclick: () => { v.dentro = !v.dentro; mostra(); } },
        spunta(v.dentro), h('div', { class: 'cresce' }, h('b', null, v.n), h('small', null, `circa ${intero(v.g * quota)} g`)),
        h('span', { class: 'q' }, `${intero(v.kcal * quota)} kcal`))));
      porzione.replaceChildren(...[[0.5, 'Metà'], [1, 'Tutto'], [1.5, 'Una e mezza']].map(([k, t]) =>
        h('button', { class: quota === k ? 'on' : '', onclick: () => { quota = k; mostra(); } }, t)));
      const t = sommaVoci(trovate.filter((v) => v.dentro));
      totale.replaceChildren(...quattro({ kcal: t.kcal * quota, p: t.p * quota, c: t.c * quota, f: t.f * quota }));
    };
    const aggiungi = () => {
      const scelte = trovate.filter((v) => v.dentro);
      if (!scelte.length) { avviso('Lascia almeno una voce', 'info'); return; }
      for (const v of scelte) {
        segna({ n: v.n, q: `circa ${intero(v.g * quota)} g`, g: Math.round(v.g * quota), kcal: Math.round(v.kcal * quota),
          p: una(v.p * quota), c: una(v.c * quota), f: una(v.f * quota), fonte: 'foto', stima: true });
      }
      fatto();
    };
    mostra();
    const testoSicurezza = { alta: 'stima affidabile', media: 'stima discreta', bassa: 'stima incerta' }[j.sicurezza] || 'stima';
    return [
      indietro(),
      h('div', null, h('div', { class: 'chips', style: { marginBottom: '10px' } }, h('span', { class: 'chip acc' }, icona('camera'), testoSicurezza)), h('h2', null, j.piatto)),
      j.nota ? h('div', { class: 'nota' }, icona('info'), h('span', null, j.nota)) : null,
      h('p', { class: 'piccolo' }, 'Togli la spunta a quello che non c\'era. Sono stime a occhio: buone per non lasciare il buco, non per il grammo.'),
      lista, porzione, totale,
      h('button', { class: 'btn primo', onclick: aggiungi }, icona('plus'), 'Aggiungi al diario'),
    ];
  }

  // ---------- 3. cosa: ricerca, codice a barre, foto, a mano ----------
  const campo = h('input', { type: 'search', placeholder: 'Cerca: piadina, pizza, mela…', autocomplete: 'off', autocapitalize: 'off', spellcheck: 'false', enterkeyhint: 'search', 'aria-label': 'Cerca un cibo' });
  const risultati = h('div', { class: 'risultati' });
  const testoCercato = () => campo.value.trim();
  campo.addEventListener('input', () => { st.online = null; st.gruppo = null; mostraRisultati(); });
  campo.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); campo.blur(); if (testoCercato().length >= 2) cercaInRete(); } });

  const rigaCibo = (a, alTocco = scegli) => h('button', { class: 'voce', onclick: () => alTocco(a) },
    fotoProdotto(a.img && mini(a.img), 'prodotto-mini'),
    h('div', { class: 'cresce' }, h('b', null, a.n), h('small', null, [a.marca, perUnita(a), a.nota].filter(Boolean).join(' · '))),
    icona('plus', 'piu'));
  const titolo = (t) => h('div', { class: 'momento' }, t);

  async function cercaInRete() {
    const q = testoCercato();
    st.online = { q, stato: 'attesa' };
    mostraRisultati();
    try {
      let r;
      try { r = await fetch(`api/cibo/cerca?q=${encodeURIComponent(q)}`); } catch { throw new Error('Sei senza rete.'); }
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.errore || 'La ricerca non ha risposto.');
      st.online = { q, stato: 'ok', voci: j.risultati.map((a) => ({ ...a, per: 100 })) };
    } catch (e) {
      st.online = { q, stato: 'errore', errore: e.message };
    }
    if (testoCercato() === q && st.modo === 'cosa') mostraRisultati();
  }

  function mostraRisultati() {
    const q = liscio(testoCercato());
    const tutto = catalogo(d);
    const nodi = [];
    if (q.length >= 2) {
      const parole = q.split(/\s+/);
      const inizia = (a) => (liscio(a.n).startsWith(parole[0]) ? 1 : 0);
      const trovati = tutto.filter((a) => { const t = liscio(`${a.n} ${a.marca || ''} ${a.gruppo}`); return parole.every((p) => t.includes(p)); })
        .sort((a, b) => inizia(b) - inizia(a)).slice(0, 30);
      if (trovati.length) nodi.push(h('div', { class: 'card elenco' }, trovati.map((a) => rigaCibo(a))));
      const o = st.online;
      if (!o) {
        nodi.push(h('button', { class: 'btn', onclick: cercaInRete }, icona('search'), `Cerca «${testoCercato()}» tra i prodotti in commercio`));
      } else if (o.stato === 'attesa') {
        nodi.push(h('p', { class: 'piccolo', style: { textAlign: 'center', padding: '10px' } }, 'Cerco tra i prodotti in commercio…'));
      } else if (o.stato === 'errore') {
        nodi.push(h('div', { class: 'nota' }, icona('info'), h('span', null, o.errore)));
      } else {
        nodi.push(titolo('Prodotti in commercio'));
        nodi.push(o.voci.length ? h('div', { class: 'card elenco' }, o.voci.map((a) => rigaCibo(a, scegliInRete)))
          : h('p', { class: 'piccolo', style: { padding: '4px' } }, 'Niente con questo nome. Prova il codice a barre, oppure scrivilo a mano.'));
      }
    } else {
      const gruppi = [...new Set(tutto.filter((a) => a.gruppo !== 'I tuoi').map((a) => a.gruppo))];
      nodi.push(h('div', { class: 'scorri' }, gruppi.map((g) =>
        h('button', { class: `scelta${st.gruppo === g ? ' on' : ''}`, onclick: () => { st.gruppo = st.gruppo === g ? null : g; mostraRisultati(); } }, g))));
      const mostrati = st.gruppo ? tutto.filter((a) => a.gruppo === st.gruppo) : tutto.filter((a) => a.gruppo === 'I tuoi').slice(0, 8);
      if (!st.gruppo && mostrati.length) nodi.push(titolo('Usati di recente'));
      if (mostrati.length) nodi.push(h('div', { class: 'card elenco' }, mostrati.map((a) => rigaCibo(a))));
      else if (!st.gruppo) nodi.push(h('p', { class: 'piccolo', style: { padding: '2px 4px' } }, 'Cerca per nome, scegli un tipo di locale qui sopra, oppure usa il codice a barre della confezione.'));
    }
    risultati.replaceChildren(...nodi);
  }

  function vistaCosa() {
    const x = pasto();
    mostraRisultati();
    return [
      h('button', { class: 'indietro', onclick: () => vai(x ? 'come' : (voci().length ? 'riepilogo' : 'quando')) }, icona('back'), 'Indietro'),
      h('div', null,
        h('div', { class: 'chips', style: { marginBottom: '10px' } },
          h('span', { class: 'chip acc' }, x ? x.nome : 'Fuori pasto'),
          x ? h('span', { class: 'chip' }, viaTesto(st.via)) : null),
        h('h2', null, 'Cosa hai mangiato?')),
      h('div', { class: 'campo' }, campo),
      h('div', { class: 'tre-azioni' },
        h('button', { onclick: () => vai('codice', vistaCodice()) }, icona('barcode'), 'Codice a barre'),
        h('button', { onclick: apriFoto }, icona('camera'), 'Foto del piatto'),
        h('button', { onclick: () => vai('mano', vistaMano()) }, icona('edit'), 'Scrivilo tu')),
      risultati,
    ];
  }

  // ---------- quello che hai gia' segnato in quel pasto ----------
  function vistaRiepilogo() {
    const x = pasto();
    const segnate = voci();
    if (!segnate.length) {   // tolta l'ultima voce: si torna a chiedere
      st.modo = x ? 'come' : 'cosa';
      return DINAMICHE[st.modo]();
    }
    const t = sommaVoci(segnate);
    return [
      momIniziale ? null : indietro('quando'),
      h('div', null,
        h('h2', null, x ? `${x.nome}: fuori piano` : 'Fuori pasto'),
        h('p', { class: 'muto', style: { marginTop: '4px' } }, x
          ? (x.alPosto ? `Al posto di «${x.r.n}».` : x.senza.length ? `«${x.r.n}» resta, senza ${elenca(x.senza.map((i) => i.n.toLowerCase()))}.` : `In più rispetto a «${x.r.n}».`)
          : 'Si somma al resto della giornata.')),
      // tocca una voce per cambiare quanto ne hai mangiato (resta la stessa voce, i valori seguono)
      h('div', { class: 'card elenco' }, segnate.map((e) => h('div', { class: 'voce tocco', role: 'button', tabindex: 0, onclick: () => modificaVoce(d, e.id) },
        fotoProdotto(e.img && mini(e.img), 'prodotto-mini'),
        h('div', { class: 'cresce' }, h('b', null, e.n),
          h('small', null, [e.q, e.marca, x ? viaTesto(e.via) : null, e.stima ? 'stima' : null].filter(Boolean).join(' · '))),
        h('span', { class: 'q' }, `${intero(e.kcal)} kcal`),
        h('button', { class: 'tondo mini', 'aria-label': `Togli ${e.n}`, onclick: (ev) => { ev.stopPropagation(); togliExtra(d, e.id); } }, icona('trash'))))),
      h('p', { class: 'piccolo', style: { marginTop: '-4px' } }, 'Tocca una voce per cambiare quanto ne hai mangiato.'),
      h('div', { class: 'quattro' }, quattro(t)),
      h('button', { class: 'btn', onclick: () => { st.via = []; st.scelti = new Set(); st.sostituisco = false; vai(x ? 'come' : 'cosa'); } }, icona('plus'), 'Aggiungi altro'),
      h('button', { class: 'btn primo', onclick: () => f.chiudi() }, icona('check'), 'Fatto'),
    ];
  }

  const DINAMICHE = { quando: vistaQuando, come: vistaCome, cosa: vistaCosa, riepilogo: vistaRiepilogo };
  if (momIniziale) {
    st.mom = momIniziale;
    st.modo = voci().length ? 'riepilogo' : (pasto() ? 'come' : 'cosa');
  }
  f = foglio(() => (DINAMICHE[st.modo] ? DINAMICHE[st.modo]() : st.vista), { alChiudere: () => { giro++; spegni?.(); } });
  f.el.append(scatto);
  conFoto = !!io.motore;   // serve un servizio con la chiave: l'AI che gira sulla VM fa solo l'assistente
  return f;
}

// ---------- cambiare una voce gia' segnata ----------
// Quanto ne hai mangiato davvero ("erano 35 grammi, non 17"): resta la stessa voce, calorie e grammi seguono la
// quantita' (vocePer in store.js). In grammi si scrive il numero; a pezzi ci sono il meno e il piu', di mezzo in mezzo.
export function modificaVoce(d, id) {
  const e0 = (S.giorni[d]?.extra || []).find((e) => e.id === id);
  if (!e0) return null;
  const base = quantitaVoce(e0);
  const inGrammi = base.u === 'g';
  let n = base.n;
  const tessere = h('div', { class: 'quattro' }, quattro(vocePer(e0, n)));
  const grande = h('b', null, dec(n, 1));
  const unita = h('span', null, base.u);
  const rinfresca = () => {
    tessere.replaceChildren(...quattro(vocePer(e0, n)));
    grande.textContent = dec(n, 1);
    unita.textContent = vocePer(e0, n).q.replace(/^[\d.,]+\s*/, '');
  };
  const campo = h('input', { type: 'text', inputmode: 'decimal', autocomplete: 'off', value: dec(n, 1), 'aria-label': 'Grammi' });
  campo.addEventListener('input', () => { const v = numero(campo.value); if (v > 0) { n = v; rinfresca(); } });
  const muovi = (k) => { n = Math.max(0.5, Math.round((n + k * 0.5) * 2) / 2); rinfresca(); };
  const f = foglio(() => [
    h('div', { style: { height: '34px' } }),
    h('div', null, h('h2', null, e0.n),
      h('p', { class: 'muto', style: { marginTop: '4px' } }, `Avevi segnato ${e0.q || '1 porzione'}, ${intero(e0.kcal)} kcal. Cambia quanto ne hai mangiato: i valori seguono.`)),
    inGrammi ? h('div', { class: 'campo' }, h('label', null, 'Grammi'), campo)
      : h('div', { class: 'quanti' },
        h('button', { class: 'tondo', 'aria-label': 'Meno', onclick: () => muovi(-1) }, icona('minus')),
        h('div', null, grande, unita),
        h('button', { class: 'tondo', 'aria-label': 'Più', onclick: () => muovi(1) }, icona('plus'))),
    tessere,
    h('button', { class: 'btn primo', onclick: () => {
      if (!(n > 0)) { avviso('Scrivi quanto ne hai mangiato', 'info'); return; }
      cambiaVoce(d, id, vocePer(e0, n));
      f.chiudi();
      avviso('Voce aggiornata');
    } }, icona('check'), 'Salva'),
    h('button', { class: 'btn basso', onclick: () => { togliExtra(d, id); f.chiudi(); avviso('Tolto dal diario'); } }, icona('trash'), 'Togli dal diario'),
  ]);
  return f;
}

// ---------- pezzi per le schermate Oggi e Dieta ----------
export function nomiVoci(voci) {
  const nomi = voci.map((e) => e.n);
  return nomi.length > 3 ? `${nomi.slice(0, 2).join(', ')} e altre ${nomi.length - 2} cose` : nomi.join(', ');
}

// Il pasto previsto e' stato sostituito per intero: al suo posto si vede quello che hai mangiato davvero.
export function cartaAlPosto(d, x, breve = false) {
  const t = sommaVoci(x.extra);
  const conFotografia = x.extra.find((e) => e.img);
  const scatola = h('div', { class: 'foto diario' }, icona('fork', 'ic28'));
  if (conFotografia) {
    const img = h('img', { src: mini(conFotografia.img), alt: '', loading: 'lazy', referrerpolicy: 'no-referrer' });
    img.addEventListener('load', () => scatola.replaceChildren(img), { once: true });   // finche' non arriva resta la forchetta
  }
  return h('div', { class: 'card pasto-riga tocco', role: 'button', tabindex: 0, onclick: () => apriDiario(d, x.mom) },
    scatola,
    h('div', { class: 'cresce' },
      h('div', { class: 'ora', style: { color: 'var(--tx3)' } }, breve ? 'Fuori piano' : `${x.nome} ${x.ora} · fuori piano`),
      h('h3', null, nomiVoci(x.extra)),
      h('div', { class: 'piccolo', style: { marginTop: '3px' } }, `${intero(t.kcal)} kcal · ${intero(t.p)} g proteine`)),
    spunta(true));
}

// Qualcosa in piu' rispetto al pasto previsto, al posto di una sua parte, o lontano dai pasti.
export function rigaInPiu(d, mom, voci, etichetta) {
  const t = sommaVoci(voci);
  return h('button', { class: 'card in-piu tocco', onclick: () => apriDiario(d, mom) },
    icona('plus'),
    h('div', { class: 'cresce' }, h('b', null, nomiVoci(voci)), h('small', null, etichetta)),
    h('span', { class: 'q' }, `${intero(t.kcal)} kcal`));
}

// La riga sotto un pasto che resta nel piano: dice se le voci sono in piu' o al posto di una parte.
export function rigaSottoIlPasto(d, x) {
  if (x.alPosto || !x.extra.length) return null;
  const etichetta = x.senza.length ? `Al posto di ${elenca(x.senza.map((i) => i.n.toLowerCase()))}` : `In più a ${x.nome.toLowerCase()}`;
  return rigaInPiu(d, x.mom, x.extra, etichetta);
}

export function fuoriPianoDelGiorno(d) {
  const voci = fuoriPasto(d);
  return [
    voci.length ? rigaInPiu(d, FUORI_PASTO, voci, 'Fuori pasto') : null,
    h('button', { class: 'btn', onclick: () => apriDiario(d) }, icona('plus'), 'Ho mangiato altro'),
  ];
}
