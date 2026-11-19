import { h, icona, foto, oggi, intero, giornoSett, daIso, iso, lunedi, piuGiorni, colpetto, maiuscola, dataLunga, dataCorta } from '../dom.js';
import { P, S, aggiorna, pastiDelGiorno, tipoGiorno, giorno, ingredienti, alternative, macro, listaSpesa, siAllena, cambiaPastoDelGiorno,
  segnaFatto, mangiatiSolo, impostaDosi, modificaStato } from '../store.js';
import { spunta, foglio, avviso, barra, ICONA_COTTURA } from '../ui.js';
import { apriDiario, cartaAlPosto, rigaSottoIlPasto, fuoriPianoDelGiorno } from './diario.js';
import { giornata, apriGiorno, fascia, ESITI } from './rapporto.js';

const ui = { sel: null, scheda: 'piano', arrivo: false };
const INIZIALI = ['L', 'M', 'M', 'G', 'V', 'S', 'D'];

// Dalla Home, toccando un giorno della settimana: la sezione si apre su quel giorno.
export function mostraGiorno(d) { ui.sel = d === oggi() ? null : d; ui.scheda = 'piano'; ui.arrivo = true; }

export function segnaPasto(d, mom) {
  const era = !!S.giorni[d]?.pasti?.[mom];
  colpetto();
  segnaFatto(d, mom, !era);   // spuntato o tolto per intero: anche gli ingredienti lasciati nel piatto ripartono da zero
  if (!era) avviso(P.momenti[mom]?.con ? 'Segnato' : 'Pasto segnato');
  return !era;
}

const elenca = (nomi) => (nomi.length > 1 ? `${nomi.slice(0, -1).join(', ')} e ${nomi[nomi.length - 1]}` : nomi[0] || '');
// "solo pasta" o "senza pomodorini" per un pasto mangiato in parte; null se l'hai mangiato tutto (o non ancora).
export function parteMangiata(x) {
  if (!x.fatto || !x.lasciati?.length) return null;
  const nomi = (l) => elenca(l.map((i) => i.n.toLowerCase()));
  return x.presi.length <= x.lasciati.length ? `solo ${nomi(x.presi)}` : `senza ${nomi(x.lasciati)}`;
}
// "pollo 137 g": gli ingredienti che quel giorno hanno grammi diversi dal piano
export const grammiDelGiorno = (x) => (x.ritoccati?.length ? x.ritoccati.map((i) => `${i.n.toLowerCase()} ${intero(i.g)} g`).join(', ') : null);

// Il riquadro di un pasto: la foto del piatto, la stella del pasto libero, o un'icona (il caffe' non ha una foto).
// La foto di un piatto: quelle di tutti i giorni stanno nell'app (img), le altre arrivano dal sito delle foto (foto).
export const indirizzoFoto = (r) => r.foto || (r.img ? `img/food/${r.img}.jpg` : null);
// Ogni piatto ha la sua foto, anche il pasto libero; la stella e il segnaposto restano solo per un piano che ne fosse senza.
export function fotoPasto(r) {
  const dove = indirizzoFoto(r);
  if (dove) return foto(dove, r.n);
  if (r.libero) return h('div', { class: 'stella' }, icona('star'));
  return h('div', { class: 'senza-foto' }, icona(r.icona || 'fork'));
}

function copertina(r) {
  const dove = indirizzoFoto(r);
  if (dove) return h('div', { class: 'copertina' }, foto(dove, r.n));
  if (!r.libero) return h('div', { style: { height: '34px' } });
  return h('div', { class: 'copertina', style: { background: 'radial-gradient(120% 120% at 20% 0%, #5b3df5, #c13cff 45%, #ff5d8f 100%)' } }, h('div', { style: { position: 'absolute', inset: '0', display: 'grid', placeItems: 'center', color: '#fff' } }, icona('star', 'stellona')));
}

export function apriPasto(d, mom) {
  let modo = 'dettaglio';
  // il cambio vale solo per quel giorno ("stasera non mi va") oppure per tutti quei giorni della settimana
  let soloOggi = true;
  // i grammi: solo per quel giorno (dosi) oppure per sempre (la ricetta); `scritti` e' quello che si sta scrivendo
  let perSempre = false;
  let scritti = {};
  const wd = giornoSett(daIso(d));
  const ogni = `ogni ${P.giorni[wd].toLowerCase()}`;
  const quelGiorno = d === oggi() ? 'oggi' : `${dataLunga(d)}`;
  const f = foglio((api) => {
    const x = pastiDelGiorno(d).find((p) => p.mom === mom);
    if (!x) { setTimeout(() => api.chiudi()); return []; }
    const tipo = x.tipo;   // un pasto gia' segnato tiene il tipo di giorno di quando l'hai segnato
    if (modo === 'cambia') {
      const lato = (si, nome) => h('button', { class: soloOggi === si ? 'on' : '', 'aria-pressed': soloOggi === si,
        onclick: () => { if (soloOggi !== si) { soloOggi = si; api.ridisegna(); } } }, nome);
      return [
        h('div', { style: { height: '34px' } }),
        h('h2', null, `Sostituisci ${x.nome.toLowerCase()}`),
        h('div', { class: 'seg mini', role: 'group', 'aria-label': 'Per quanto tempo' },
          lato(true, d === oggi() ? 'Solo oggi' : `Solo ${dataCorta(d)}`), lato(false, maiuscola(ogni))),
        h('p', { class: 'muto' }, soloOggi ? `Vale solo ${d === oggi() ? 'per oggi' : `per ${quelGiorno}`}: gli altri giorni resta il piano.` : `Vale per ${ogni}, finché non torni al piano.`),
        h('div', { style: { display: 'flex', flexDirection: 'column', gap: '10px' } },
          alternative(mom, x.rid).map((rid) => {
            const r = P.ricette[rid], m = macro(rid, tipo);
            return h('button', { class: `pasto piccola tocco${r.libero ? ' libera' : ''}`, onclick: () => {
              if (soloOggi) {
                // se e' il piatto che quel giorno ci sarebbe comunque, basta togliere il cambio del giorno
                const diSempre = S.cambi[wd]?.[mom] && P.ricette[S.cambi[wd][mom]] ? S.cambi[wd][mom] : P.settimana[wd].pasti[mom];
                cambiaPastoDelGiorno(d, mom, rid === diSempre ? null : rid);
              } else {
                aggiorna((s) => {
                  s.cambi[wd] = s.cambi[wd] || {};
                  if (rid === P.settimana[wd].pasti[mom]) delete s.cambi[wd][mom]; else s.cambi[wd][mom] = rid;
                  // un cambio solo per questo giorno coprirebbe quello appena scelto per tutta la settimana
                  if (s.giorni[d]?.ricette?.[mom]) { delete s.giorni[d].ricette[mom]; if (!Object.keys(s.giorni[d].ricette).length) delete s.giorni[d].ricette; }
                });
              }
              modo = 'dettaglio'; api.ridisegna(); avviso('Pasto sostituito', 'swap');
            } },
              h('div', { class: 'foto' }, fotoPasto(r)),
              h('div', { class: 'cresce' }, h('h3', null, r.n),
                h('div', { class: 'chips' }, h('span', { class: 'chip' }, `${r.libero ? 'circa ' : ''}${intero(m.kcal)} kcal`), h('span', { class: 'chip p' }, `${intero(m.p)} g proteine`))));
          })),
        h('button', { class: 'btn', onclick: () => { modo = 'dettaglio'; api.ridisegna(); } }, 'Annulla'),
      ];
    }
    const previsti = ingredienti(x.rid, tipo, x.dosi);
    const mangiabili = previsti.filter((i) => !x.tolti.has(i.id));   // quelli non gia' sostituiti con altro nel diario
    const quando = d === oggi() ? 'oggi' : 'quel giorno';
    if (modo === 'grammi') {
      const lato = (si, nome) => h('button', { class: perSempre === si ? 'on' : '', 'aria-pressed': perSempre === si,
        onclick: () => { if (perSempre !== si) { perSempre = si; document.activeElement?.blur?.(); api.ridisegna(); } } }, nome);
      return [
        h('div', { style: { height: '34px' } }),
        h('h2', null, `I grammi: ${x.r.n}`),
        h('div', { class: 'seg mini', role: 'group', 'aria-label': 'Per quanto tempo' },
          lato(false, d === oggi() ? 'Solo oggi' : `Solo ${dataCorta(d)}`), lato(true, 'Sempre')),
        h('p', { class: 'muto' }, perSempre ? `Cambia il piatto in tutti i giorni in cui c'è.` : `Vale solo per ${d === oggi() ? 'oggi' : quelGiorno}: il piano resta com'è.`),
        h('div', { class: 'card elenco' }, mangiabili.map((i) => h('label', { class: 'voce' },
          h('div', { class: 'cresce' }, h('b', null, i.n),
            h('small', null, `nel piano ${intero(i.piano)} g${i.pz ? ` · un pezzo ${intero(P.cibi[i.id].pz)} g` : ''}`)),
          h('span', { class: 'grammi' },
            h('input', { type: 'number', inputmode: 'decimal', min: '0', max: '2000', step: '1', 'aria-label': `Grammi di ${i.n}`,
              value: scritti[i.id] ?? String(Math.round(i.g * 10) / 10), oninput: (e) => { scritti[i.id] = e.target.value; } }),
            h('span', null, 'g'))))),
        h('p', { class: 'piccolo' }, 'Pesi a crudo.'),
        h('button', { class: 'btn primo', onclick: () => salvaGrammi() }, icona('check'), 'Salva'),
        h('button', { class: 'btn', onclick: () => { scritti = {}; modo = 'dettaglio'; document.activeElement?.blur?.(); api.ridisegna(); } }, 'Annulla'),
      ];
    }
    const r = x.r, m = x.m;
    const piuDiUno = mangiabili.length > 1;
    const parte = parteMangiata(x);
    return [
      copertina(r),
      h('div', null,
        h('div', { class: 'chips', style: { marginBottom: '10px' } },
          h('span', { class: 'chip acc' }, `${x.nome} · ${x.ora}`),
          parte ? h('span', { class: 'chip p' }, maiuscola(parte)) : null,
          h('span', { class: 'chip' }, icona(ICONA_COTTURA[r.come] || 'pot'), r.come),
          r.min ? h('span', { class: 'chip' }, icona('clock'), `${r.min} min tuoi`) : null),
        h('h2', null, r.n)),
      h('div', { class: 'quattro' },
        h('div', { class: 'k' }, h('b', null, intero(m.kcal)), h('span', null, 'kcal')),
        h('div', { class: 'p' }, h('b', null, intero(m.p)), h('span', null, 'proteine')),
        h('div', { class: 'c' }, h('b', null, intero(m.c)), h('span', null, 'carbo')),
        h('div', { class: 'f' }, h('b', null, intero(m.f)), h('span', null, 'grassi'))),
      r.libero ? h('p', { class: 'piccolo', style: { textAlign: 'center' } }, 'Valori stimati: una cena fuori non si pesa.') : null,
      r.ing.length ? h('div', { class: 'fra testa-ingr' },
        h('h4', null, siAllena() ? `Ingredienti · ${tipo === 'train' ? 'giorno di palestra' : 'giorno di riposo'}` : 'Ingredienti'),
        mangiabili.length ? h('button', { class: 'testo-link', onclick: () => { scritti = {}; perSempre = false; modo = 'grammi'; api.ridisegna(); f.el.querySelector('.corpo').scrollTop = 0; } }, icona('edit'), 'Cambia i grammi') : null) : null,
      piuDiUno ? h('p', { class: 'piccolo', style: { marginTop: '-4px' } }, 'Ne hai mangiato solo una parte? Spunta quello che hai mangiato.') : null,
      // quello che hai sostituito con altro (dal diario) resta in elenco, barrato; il resto si spunta uno per uno
      r.ing.length ? h('div', { class: 'ingredienti' }, previsti.map((i) => {
        if (x.tolti.has(i.id)) {
          return h('div', { class: 'voce presa' }, h('div', { class: 'cresce' }, h('b', null, i.n), h('small', null, `${quando} sostituito con altro`)), h('span', { class: 'q' }, '–'));
        }
        const preso = x.fatto && !x.saltati.has(i.id);
        return h('div', { class: `voce${piuDiUno ? ' con-spunta' : ''}${x.fatto && !preso ? ' lasciato' : ''}` },
          piuDiUno ? h('button', { class: 'spunta-ingr', 'aria-pressed': String(preso), 'aria-label': `${preso ? 'Non ho mangiato' : 'Ho mangiato'} ${i.n.toLowerCase()}`,
            onclick: () => toccaIngrediente(i.id) }, spunta(preso)) : null,
          h('div', { class: 'cresce' }, h('b', null, i.n),
            i.cambiato ? h('small', { class: 'oggi' }, `${quando} ${intero(i.g)} g · nel piano ${intero(i.piano)} g`)
              : x.fatto && !preso ? h('small', null, 'non mangiato') : i.nota ? h('small', null, i.nota) : null),
          h('span', { class: 'q' }, i.pz ? `${i.q} · ${intero(i.g)} g` : i.q));
      })) : null,
      r.ing.length ? h('p', { class: 'piccolo' }, 'Pesi a crudo.') : null,
      // le alternative scritte da chi ha fatto la dieta: cosa si puo' mettere al posto di cosa, e quanto
      r.scambi?.length ? [h('h4', null, 'Puoi scambiare'),
        h('div', { class: 'scambi' }, r.scambi.map(([cosa, con]) => h('div', null, icona('swap'), h('span', null, h('b', null, cosa), ` con ${con}`))))] : null,
      h('h4', null, r.libero ? 'Come funziona' : 'Preparazione'),
      h('ol', { class: 'passi' }, r.passi.map((p) => h('li', null, p))),
      r.nota ? h('div', { class: 'nota' }, icona('info'), h('span', null, r.nota)) : null,
      h('div', { class: 'azioni' },
        mom !== 'post' && alternative(mom, x.rid).length ? h('button', { class: 'btn', onclick: () => { modo = 'cambia'; api.ridisegna(); f.el.querySelector('.corpo').scrollTop = 0; } }, icona('swap'), 'Sostituisci') : null,
        // mangiato in parte: il tasto grande rimette "tutto", il "non fatto" scende sotto
        parte ? h('button', { class: 'btn primo', onclick: () => { colpetto(); mangiatiSolo(d, mom, null, true); avviso('Segnato tutto il pasto'); } }, icona('check'), 'Mangiato tutto')
          : h('button', { class: `btn ${x.fatto ? '' : 'primo'}`, onclick: () => { const ora = segnaPasto(d, mom); if (ora) api.chiudi(); } }, icona(x.fatto ? 'x' : 'check'),
            x.fatto ? 'Non fatto' : x.con ? 'Preso' : piuDiUno ? 'Mangiato tutto' : 'Mangiato')),
      parte ? h('button', { class: 'btn basso', onclick: () => segnaPasto(d, mom) }, icona('x'), 'Non l\'ho mangiato') : null,
      x.soloOggi ? h('button', { class: 'btn basso', onclick: () => { cambiaPastoDelGiorno(d, mom, null); avviso('Rimesso il piatto previsto'); } }, d === oggi() ? 'Oggi rimetti il piatto previsto' : 'Rimetti il piatto previsto')
        : x.cambiato ? h('button', { class: 'btn basso', onclick: () => { aggiorna((s) => { delete s.cambi[wd][mom]; }); avviso('Tornato al piano'); } }, 'Torna al piano originale') : null,
      h('button', { class: 'btn basso', onclick: () => { api.chiudi(); apriDiario(d, x.con || mom); } }, icona('plus'), 'Ho mangiato altro'),
    ];
  }, { copertina: true });

  // Il cerchio di un ingrediente: se il pasto non era segnato, conta solo quello; poi si aggiungono o si tolgono gli
  // altri. Tolto anche l'ultimo, il pasto torna non fatto.
  function toccaIngrediente(id) {
    const x = pastiDelGiorno(d).find((p) => p.mom === mom);
    if (!x) return;
    const ids = ingredienti(x.rid, x.tipo, x.dosi).filter((i) => !x.tolti.has(i.id)).map((i) => i.id);
    const lasciati = new Set(x.fatto ? x.saltati : ids);
    if (lasciati.has(id)) lasciati.delete(id); else lasciati.add(id);
    colpetto();
    if (ids.every((i) => lasciati.has(i))) mangiatiSolo(d, mom, null, false);
    else mangiatiSolo(d, mom, [...lasciati], true);
  }

  // I grammi scritti: solo per quel giorno diventano le dosi del giorno (uguali al piano = via la dose), per sempre
  // cambiano la ricetta. Nella ricetta ci sono due colonne, riposo e palestra: quella di oggi prende il numero nuovo,
  // l'altra si adegua (uguale se erano uguali, in proporzione se erano diverse).
  function salvaGrammi() {
    document.activeElement?.blur?.();
    const x = pastiDelGiorno(d).find((p) => p.mom === mom);
    if (!x) return;
    const tipo = x.tipo;
    const previsti = ingredienti(x.rid, tipo, x.dosi).filter((i) => !x.tolti.has(i.id));
    const nuove = {};
    for (const i of previsti) {
      const v = scritti[i.id];
      if (v == null || String(v).trim() === '') continue;
      const g = Math.round(Number(String(v).replace(',', '.')) * 10) / 10;
      if (!Number.isFinite(g) || g < 0 || g > 2000) { avviso(`${i.n}: scrivi i grammi, da 0 a 2000`, 'info'); return; }
      if (g !== i.g) nuove[i.id] = g;
    }
    const fine = (testo) => { scritti = {}; modo = 'dettaglio'; f.ridisegna(); if (testo) avviso(testo, 'check'); };
    if (!Object.keys(nuove).length) return fine(null);
    if (perSempre) {
      const col = tipo === 'train' ? 2 : 1, altra = col === 2 ? 1 : 2;
      const ing = P.ricette[x.rid].ing.map((riga) => {
        if (!(riga[0] in nuove)) return [...riga];
        const g = nuove[riga[0]], nuova = [...riga];
        nuova[altra] = riga[1] === riga[2] ? g : riga[col] > 0 ? Math.round(riga[altra] * g / riga[col] / 5) * 5 : riga[altra];
        nuova[col] = g;
        return nuova;
      });
      const esito = modificaStato([{ op: 'metti', percorso: ['mie', 'ricette', x.rid, 'ing'], valore: ing }]);
      if (!esito.ok) { avviso(esito.errore, 'info'); return; }
      // ora e' la ricetta a dirlo: le dosi del giorno per quegli ingredienti non servono piu'
      impostaDosi(d, mom, Object.fromEntries(Object.keys(nuove).map((id) => [id, null])));
      return fine('Piatto cambiato per sempre');
    }
    impostaDosi(d, mom, Object.fromEntries(Object.entries(nuove).map(([id, g]) => [id, g === previsti.find((i) => i.id === id).piano ? null : g])));
    return fine(d === oggi() ? 'Grammi cambiati per oggi' : 'Grammi cambiati per quel giorno');
  }
  return f;
}

function cartaPasto(d, x) {
  const grande = x.r.tipo === 'pasto';
  const r = x.r;
  const tocca = (e) => { e.stopPropagation(); segnaPasto(d, x.mom); };
  const parte = parteMangiata(x), grammi = grammiDelGiorno(x);
  const chips = h('div', { class: 'chips' },
    h('span', { class: `chip ${grande ? 'vetro' : ''}` }, icona('flame'), `${r.libero ? 'circa ' : ''}${intero(x.m.kcal)} kcal`),
    h('span', { class: `chip ${grande ? 'vetro' : 'p'}` }, `${intero(x.m.p)} g proteine`),
    grande && parte ? h('span', { class: 'chip vetro' }, maiuscola(parte)) : null,
    grande && grammi ? h('span', { class: 'chip vetro' }, icona('edit'), x.ritoccati.length > 1 ? (d === oggi() ? 'Grammi di oggi' : 'Grammi cambiati') : maiuscola(grammi)) : null,
    grande && !r.libero && !parte && !grammi ? h('span', { class: 'chip vetro' }, icona(ICONA_COTTURA[r.come] || 'pot'), r.come) : null);
  if (!grande) {
    return h('div', { class: `pasto piccola tocco${x.fatto ? ' fatto' : ''}`, role: 'button', tabindex: 0, onclick: () => apriPasto(d, x.mom) },
      h('div', { class: 'foto' }, fotoPasto(r)),
      h('div', { class: 'cresce' }, h('h3', null, r.n), h('div', { class: 'piccolo', style: { marginTop: '4px' } },
        [`${intero(x.m.kcal)} kcal · ${intero(x.m.p)} g proteine`, parte, grammi].filter(Boolean).join(' · '))),
      h('button', { 'aria-label': 'Segna come mangiato', onclick: tocca }, spunta(x.fatto)));
  }
  return h('div', { class: `pasto tocco${x.fatto ? ' fatto' : ''}${r.libero ? ' libera' : ''}`, role: 'button', tabindex: 0, onclick: () => apriPasto(d, x.mom) },
    h('div', { class: 'foto' }, fotoPasto(r)),
    h('div', { class: 'sopra' },
      x.cambiato ? h('span', { class: 'chip vetro' }, icona('swap'), x.soloOggi ? (d === oggi() ? 'Solo oggi' : 'Solo questo giorno') : 'Sostituito') : h('span'),
      h('button', { 'aria-label': 'Segna come mangiato', onclick: tocca }, spunta(x.fatto, 'vetro'))),
    h('div', { class: 'sotto' }, h('h3', null, r.n), chips));
}

// ---------- muoversi tra i giorni ----------
// La striscia mostra la settimana del giorno scelto, che non e' per forza quella di adesso: le frecce (o un dito
// trascinato di lato sulla striscia) portano avanti e indietro di una settimana, "Oggi" riporta a oggi e il calendario
// apre un mese intero da cui scegliere. `ui.sel` vuoto vuol dire oggi: a mezzanotte la sezione passa da sola al giorno nuovo.
let verso = null;   // da che parte entra la striscia al prossimo disegno: 'avanti' o 'indietro'
const scelto = () => ui.sel || oggi();

function vaiA(d) {
  const prima = scelto();
  if (d === prima) return;
  colpetto();
  verso = lunedi(d) === lunedi(prima) ? null : d > prima ? 'avanti' : 'indietro';
  ui.sel = d === oggi() ? null : d;
  ridisegna();
}

// "12 – 18 ottobre", a cavallo di due mesi "28 set – 4 ott"; l'anno solo se non e' questo
function settimanaInParole(lun) {
  const a = daIso(lun), b = daIso(piuGiorni(lun, 6));
  const mese = (x, forma) => x.toLocaleDateString('it-IT', { month: forma });
  const anno = b.getFullYear() !== new Date().getFullYear() ? ` ${b.getFullYear()}` : '';
  return (a.getMonth() === b.getMonth() ? `${a.getDate()} – ${b.getDate()} ${mese(b, 'long')}` : `${a.getDate()} ${mese(a, 'short')} – ${b.getDate()} ${mese(b, 'short')}`) + anno;
}
function quantoDista(lun) {
  const n = Math.round((daIso(lun) - daIso(lunedi(oggi()))) / (7 * 86400000));
  return n === 0 ? 'Questa settimana' : n === -1 ? 'Settimana scorsa' : n === 1 ? 'Settimana prossima' : n < 0 ? `${-n} settimane fa` : `Tra ${n} settimane`;
}

function naviga(d) {
  const o = oggi(), lun = lunedi(d);
  return h('div', { class: 'naviga' },
    h('button', { class: 'fr', 'aria-label': 'Settimana precedente', onclick: () => vaiA(piuGiorni(d, -7)) }, icona('back')),
    h('button', { class: 'dove', 'aria-label': 'Apri il calendario', onclick: apriCalendario }, h('b', null, settimanaInParole(lun)), h('small', null, quantoDista(lun))),
    h('button', { class: 'fr', 'aria-label': 'Settimana successiva', onclick: () => vaiA(piuGiorni(d, 7)) }, icona('chev')),
    h('button', { class: 'oggi-tasto', disabled: d === o, onclick: () => vaiA(o) }, 'Oggi'),
    h('button', { class: 'fr', 'aria-label': 'Scegli una data dal calendario', onclick: apriCalendario }, icona('cal')));
}

function striscia(d) {
  const o = oggi(), lun = lunedi(d);
  const el = h('div', { class: `giorni${verso ? ` da-${verso}` : ''}` }, INIZIALI.map((l, i) => {
    const g = piuGiorni(lun, i);
    return h('button', { class: `${g === d ? 'on' : ''} ${g === o ? 'oggi' : ''} ${tipoGiorno(g) === 'train' ? 'all' : ''}`, 'aria-label': dataLunga(g), onclick: () => vaiA(g) },
      h('small', null, l), h('b', null, daIso(g).getDate()), h('i'));
  }));
  verso = null;
  // un dito trascinato di lato cambia settimana (in verticale la pagina scorre come sempre)
  let x0 = null, y0 = 0;
  el.addEventListener('touchstart', (e) => { x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; }, { passive: true });
  el.addEventListener('touchend', (e) => {
    if (x0 == null) return;
    const dx = e.changedTouches[0].clientX - x0, dy = e.changedTouches[0].clientY - y0;
    x0 = null;
    if (Math.abs(dx) > 48 && Math.abs(dx) > Math.abs(dy) * 1.5) vaiA(piuGiorni(d, dx < 0 ? 7 : -7));
  }, { passive: true });
  return el;
}

// Il calendario: un mese alla volta, con un segno sui giorni in cui e' stato segnato qualcosa (com'e' andata, con le
// stesse parole e gli stessi colori del rapporto in Progressi; la forma del segno cambia insieme al colore).
function apriCalendario() {
  const o = oggi();
  const parte = daIso(scelto());
  let mese = new Date(parte.getFullYear(), parte.getMonth(), 1, 12);
  foglio((api) => {
    const m = mese.getMonth(), d = scelto();
    const inizio = lunedi(iso(mese));
    const righe = Math.ceil((giornoSett(mese) + new Date(mese.getFullYear(), m + 1, 0).getDate()) / 7);
    const cambia = (n) => { colpetto(); mese = new Date(mese.getFullYear(), m + n, 1, 12); api.ridisegna(); };
    const celle = Array.from({ length: righe * 7 }, (_, i) => {
      const g = piuGiorni(inizio, i), data = daIso(g);
      // i giorni senza niente di segnato non si calcolano nemmeno
      const esito = S.giorni[g] ? giornata(g).esito : 'vuoto';
      const segno = esito === 'vuoto' ? null : ESITI[esito];
      return h('button', {
        class: `${data.getMonth() === m ? '' : 'fuori'} ${g === o ? 'oggi' : ''} ${g === d ? 'on' : ''}`,
        'aria-label': `${dataLunga(g)}${segno ? `, ${segno.n.toLowerCase()}` : ''}`,
        onclick: () => { api.chiudi(); vaiA(g); },
      }, h('b', null, data.getDate()), h('i', { class: segno ? `segno ${segno.c}` : 'segno' }));
    });
    return [
      h('h2', null, 'Vai a un giorno'),
      h('div', { class: 'cal-testa' },
        h('button', { class: 'tondo', 'aria-label': 'Mese precedente', onclick: () => cambia(-1) }, icona('back')),
        h('b', null, maiuscola(mese.toLocaleDateString('it-IT', { month: 'long', year: 'numeric' }))),
        h('button', { class: 'tondo', 'aria-label': 'Mese successivo', onclick: () => cambia(1) }, icona('chev'))),
      h('div', { class: 'cal' }, INIZIALI.map((l) => h('small', null, l)), celle),
      h('div', { class: 'rap-legenda' }, ['linea', 'sgarro', 'poco', 'corso'].map((e) => h('span', null, h('i', { class: `segno ${ESITI[e].c}` }), ESITI[e].n))),
      h('button', { class: 'btn', onclick: () => { api.chiudi(); vaiA(o); } }, icona('target'), 'Torna a oggi'),
    ];
  });
}

// ---------- il resoconto del giorno: quanto si e' mangiato rispetto all'obiettivo ----------
// Le misure si muovono da dov'erano all'ultimo disegno (non da zero), anche passando da un giorno all'altro.
const dovErano = new Map();

// Una misura: il pieno e' quanto si e' fatto, la fine della traccia e' l'obiettivo. Andando oltre, la traccia si accorcia
// per far posto al di piu', staccato da un filo del colore del fondo che resta dov'era l'obiettivo. `sgarro` lo colora
// d'avviso (lo decide chi chiama: per le proteine andare oltre non e' un male).
function misura({ id, classe, val, ob, sgarro = false }) {
  const scala = Math.max(ob, val, 1);
  const pieno = (Math.min(val, ob) / scala) * 100, oltre = (Math.max(0, val - ob) / scala) * 100;
  const [p0, o0] = dovErano.get(id) || [0, 0];
  dovErano.set(id, [pieno, oltre]);
  const a = h('i', { class: 'pieno', style: { width: `${p0 + o0}%` } });
  const b = h('i', { class: 'oltre', style: { left: `${p0}%`, width: `${o0}%` } });
  setTimeout(() => {
    if (a.isConnected) void a.getBoundingClientRect();
    a.style.width = `${pieno + oltre}%`; b.style.left = `${pieno}%`; b.style.width = `${oltre}%`;
  }, 0);
  return h('div', { class: `misura ${classe}${sgarro ? ' sgarro' : ''}`, role: 'img', 'aria-label': `${intero(val)} su ${intero(ob)}` }, a, b);
}

// Come si dice un pasto in una frase ("c'e' ancora la merenda"): articolo e nome dei momenti del catalogo. Un momento
// che non e' qui (un pasto aggiunto da chi ha scritto il piano) si dice con il suo nome, senza articolo.
const IN_FRASE = {
  colazione: ['la', 'colazione'], caffe: ['il', 'caffè'], spuntino: ['lo', 'spuntino'], pranzo: ['il', 'pranzo'],
  merenda: ['la', 'merenda'], cena: ['la', 'cena'], sera: ['il', 'dopo cena'], post: ['lo', 'shake'],
};

// La riga di oggi sotto la barra. Dice due cose diverse, ognuna col suo nome: quanto manca all'obiettivo (lo stesso numero
// di "kcal rimaste" in Oggi) e cosa c'e' ancora nel piano, cioe' i pasti non spuntati (`ancora`), con dove si arriva se li
// mangi. Prima c'era solo il secondo ("Nel piano restano 223 kcal") e si leggeva come il primo.
export function fraseDelResto(t, ancora) {
  const resta = ancora.reduce((n, x) => n + x.m.kcal, 0);
  const delta = t.fatto.kcal - t.ob.kcal;
  const arrivo = t.fatto.kcal + resta, scarto = arrivo - t.ob.kcal;
  const intanto = delta > 30 ? `Sei già ${intero(delta)} kcal sopra l'obiettivo.` : Math.round(-delta) >= 1 ? `Ti restano ${intero(-delta)} kcal.` : 'Obiettivo raggiunto.';
  const uno = ancora.length === 1 ? IN_FRASE[ancora[0].mom] : null;
  const nomi = ancora.map((x) => IN_FRASE[x.mom]?.[1] || x.nome.toLowerCase());
  const kcal = `${intero(resta)} kcal`;
  const [cosa, lo] = uno ? [`c'è ancora ${uno[0]} ${uno[1]} (${kcal})`, uno[0] === 'la' ? 'la' : 'lo']
    : ancora.length === 1 ? [`c'è ancora un pasto: ${nomi[0]} (${kcal})`, 'lo']
      : [`ci sono ancora ${ancora.length} pasti${ancora.length <= 3 ? `: ${elenca(nomi)}` : ''} (${kcal})`, 'li'];
  // (stesso metro del rapporto in Progressi: dentro la fascia e' "in linea", e lo scarto si dice tra parentesi; ma se si
  // e' gia' detto "sopra l'obiettivo" non si dice anche "in linea": resta il numero)
  const fine = delta <= 30 && fascia(arrivo, t.ob.kcal) === 'linea'
    ? `in linea con l'obiettivo${Math.abs(scarto) > 30 ? ` (${scarto > 0 ? '+' : '−'}${intero(Math.abs(scarto))})` : ''}`
    : `${intero(Math.abs(scarto))} ${scarto > 0 ? 'sopra' : 'sotto'}`;
  // due punti una volta sola nella frase: se i pasti sono elencati, il "se li mangi" apre una frase nuova
  return `${intanto} Nel piano ${cosa}${cosa.includes(':') ? '. Se' : ': se'} ${lo} mangi arrivi a ${intero(arrivo)}, ${fine}.`;
}

function resoconto(d) {
  const o = oggi(), g = giornata(d), t = g.t;
  // quello che il piano prevede ancora per quel giorno: i pasti non spuntati
  const ancora = pastiDelGiorno(d).filter((x) => !x.fatto && !x.alPosto);
  const resta = ancora.reduce((n, x) => n + x.m.kcal, 0);
  const arrivo = t.fatto.kcal + resta;
  const sopraSotto = (x) => (x > 0 ? `${intero(x)} kcal sopra l'obiettivo` : `${intero(-x)} kcal sotto l'obiettivo`);
  const esito = g.esito === 'vuoto' && d >= o ? { n: d === o ? 'Da cominciare' : 'In programma', c: 'grigio' } : ESITI[g.esito];
  let frase;
  if (d > o) frase = g.segnato && resta > 0 ? `Con il resto del piano arrivi a ${intero(arrivo)} kcal.` : null;   // un giorno ancora da fare: basta la riga del piano, piu' sotto
  else if (d < o) frase = !g.segnato ? 'Quel giorno non hai segnato niente.' : Math.abs(g.delta) <= 30 ? 'Obiettivo centrato.' : `${maiuscola(sopraSotto(g.delta))}.`;
  else if (resta > 0) frase = fraseDelResto(t, ancora);
  else frase = Math.abs(g.delta) <= 30 ? 'Giornata chiusa, obiettivo centrato.' : `Giornata chiusa: ${sopraSotto(g.delta)}.`;
  const giorno_ = d === o ? 'Oggi' : d === piuGiorni(o, -1) ? 'Ieri' : d === piuGiorni(o, 1) ? 'Domani' : maiuscola(dataLunga(d));
  const sotto = [siAllena() ? (t.tipo === 'train' ? 'Giorno di palestra' : 'Giorno di riposo') : null, `${t.nFatti} di ${t.n} pasti`].filter(Boolean).join(' · ');
  const tessera = (classe, nome, val, max) => h('div', { class: 'res-m' },
    h('span', null, h('i', { class: `punto ${classe}` }), nome),
    h('b', null, intero(val), h('small', null, ` / ${intero(max)} g`)),
    misura({ id: `res-${classe}`, classe, val, ob: max }));
  return h('div', { class: 'card resoconto' },
    h('div', { class: 'fra' },
      h('div', { style: { minWidth: 0 } }, h('b', { class: 'res-giorno' }, giorno_), h('div', { class: 'piccolo' }, sotto)),
      h('span', { class: 'chip res-esito' }, h('i', { class: `segno ${esito.c}` }), esito.n)),
    h('div', { class: 'res-kcal' },
      h('div', { class: 'grande' }, intero(t.fatto.kcal), h('small', null, 'kcal mangiate')),
      h('div', { class: 'res-ob' }, h('span', null, 'obiettivo'), h('b', null, intero(t.ob.kcal)))),
    misura({ id: 'res-k', classe: 'k', val: t.fatto.kcal, ob: t.ob.kcal, sgarro: g.esito === 'sgarro' }),
    frase ? h('p', { class: 'res-frase' }, frase) : null,
    h('div', { class: 'res-macro' },
      tessera('p', 'Proteine', t.fatto.p, t.ob.p), tessera('c', 'Carbo', t.fatto.c, t.ob.c), tessera('f', 'Grassi', t.fatto.f, t.ob.f)),
    // quello che c'era prima in questa carta: i totali del piano per quel giorno
    h('p', { class: 'piccolo res-piano' }, `Nel piano: ${intero(t.piano.kcal)} kcal · P ${intero(t.piano.p)} g · C ${intero(t.piano.c)} g · G ${intero(t.piano.f)} g`),
    g.segnato ? h('button', { class: 'testo-link', style: { marginTop: 0 }, onclick: () => apriGiorno(d) }, 'Tutto quello che hai mangiato') : null);
}

function piano() {
  const d = scelto();
  const pasti = pastiDelGiorno(d);
  return [
    h('div', { class: 'diario-layout' },
      h('section', { class: 'gruppo-view', 'aria-label': 'Riepilogo giornaliero' }, naviga(d), striscia(d), resoconto(d)),
      h('section', { class: 'gruppo-view', 'aria-label': 'Pasti del giorno' },
        pasti.flatMap((x) => [
          // quello che fa parte di un altro pasto sta sotto lo stesso titolo
          x.con && pasti.some((y) => y.mom === x.con) ? null : h('div', { class: 'momento' }, h('b', null, x.ora), x.nome),
          x.alPosto ? cartaAlPosto(d, x, true) : cartaPasto(d, x),
          rigaSottoIlPasto(d, x),
        ]),
        fuoriPianoDelGiorno(d))),
  ];
}

function spesa() {
  const gruppi = listaSpesa();
  const tot = gruppi.reduce((n, g) => n + g.voci.length, 0);
  const prese = gruppi.reduce((n, g) => n + g.voci.filter((v) => v.presa).length, 0);
  return [
    h('div', { class: 'card' },
      h('div', { class: 'fra', style: { marginBottom: '12px' } },
        h('div', null, h('b', { style: { fontSize: '17px' } }, 'Spesa della settimana'), h('div', { class: 'piccolo' }, 'Calcolata sui pasti del piano, sostituzioni comprese.')),
        h('span', { class: 'num', style: { fontWeight: 800, fontSize: '19px', whiteSpace: 'nowrap' } }, `${prese}/${tot}`)),
      barra({ id: 'spesa', val: prese, max: tot, colore: 'var(--acc)', alta: true })),
    h('div', { class: 'griglia-schede' }, gruppi.map((g) => h('section', { class: 'gruppo-view' },
      h('div', { class: 'sez' }, h('h2', null, g.rep), h('span', null, g.voci.length === 1 ? '1 cosa' : `${g.voci.length} cose`)),
      h('div', { class: 'card', style: { paddingTop: '6px', paddingBottom: '6px' } }, g.voci.map((v) =>
        h('button', { class: `voce${v.presa ? ' presa' : ''}`, onclick: () => aggiorna((s) => { if (v.presa) delete s.spesa[v.id]; else s.spesa[v.id] = true; }) },
          spunta(v.presa), h('div', { class: 'cresce' }, h('b', null, v.n), v.nota ? h('small', null, v.nota) : null), h('span', { class: 'q' }, v.q)))),
    ))),
    prese ? h('button', { class: 'btn', onclick: () => { aggiorna((s) => { s.spesa = {}; }); avviso('Lista azzerata'); } }, 'Azzera le spunte') : null,
  ];
}

let ridisegna = () => {};
export function vistaDieta(_, rifai) {
  ridisegna = rifai;
  // Entrando nella sezione da un'altra si riparte da oggi, anche se l'ultima volta si era rimasti su un altro giorno
  // (a meno che non ci si arrivi dalla Home toccando proprio un giorno). Finche' si resta qui il giorno scelto non cambia.
  if (!document.getElementById('vista-dieta') && !ui.arrivo) ui.sel = null;
  ui.arrivo = false;
  return [
    h('div', { class: 'top', id: 'vista-dieta' }, h('div', null, h('div', { class: 'sopra' }, 'Alimentazione'), h('h1', null, 'Diario'))),
    h('div', { class: 'seg', role: 'group', 'aria-label': 'Viste del diario' },
      h('button', { id: 'diario-piano', class: ui.scheda === 'piano' ? 'on' : '', 'aria-pressed': String(ui.scheda === 'piano'), onclick: () => { ui.scheda = 'piano'; rifai(true); } }, 'Piano alimentare'),
      h('button', { id: 'diario-spesa', class: ui.scheda === 'spesa' ? 'on' : '', 'aria-pressed': String(ui.scheda === 'spesa'), onclick: () => { ui.scheda = 'spesa'; rifai(true); } }, 'Lista della spesa')),
    ...(ui.scheda === 'piano' ? piano() : spesa()),
  ];
}
