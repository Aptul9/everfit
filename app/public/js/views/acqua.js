// Acqua: quanta ne hai bevuta oggi, i tasti per aggiungerla e l'andamento degli ultimi sette giorni.

import { h, icona, dec, intero, numero, piuGiorni, daIso } from '../dom.js';
import { S, acquaBevuta, obiettivoAcqua, bevi, togliBevuta, azzeraAcqua, tipoGiorno } from '../store.js';
import { foglio, barra, avviso } from '../ui.js';

const litri = (ml) => dec(ml / 1000, 2);
const TAGLI = [[250, 'Bicchiere'], [500, 'Bottiglietta'], [750, 'Borraccia']];
const INIZIALI = ['D', 'L', 'M', 'M', 'G', 'V', 'S'];

function aggiungi(d, ml) {
  const prima = acquaBevuta(d), ob = obiettivoAcqua(d);
  bevi(d, ml);
  if (prima < ob && prima + ml >= ob) avviso('Obiettivo d\'acqua raggiunto', 'drop');
}

const tasti = (d) => h('div', { class: 'tre-azioni acqua' }, TAGLI.map(([ml, nome]) =>
  h('button', { 'aria-label': `Aggiungi ${nome.toLowerCase()} da ${ml} millilitri`, onclick: () => aggiungi(d, ml) }, h('b', null, `+${ml} ml`), h('span', null, nome))));

export function cartaAcqua(d) {
  const ml = acquaBevuta(d), ob = obiettivoAcqua(d);
  const manca = Math.max(0, ob - ml);
  return h('div', { class: 'card acqua-carta' },
    h('div', { class: 'fra tocco', role: 'button', tabindex: 0, onclick: () => apriAcqua(d) },
      h('div', { class: 'riga' },
        h('span', { class: 'ic-acqua' }, icona('drop')),
        h('div', null,
          h('div', { class: 'acqua-litri' }, litri(ml), h('small', null, ` di ${litri(ob)} L`)),
          h('div', { class: 'piccolo' }, manca ? `Ne mancano ${litri(manca)} L: ${Math.ceil(manca / 250)} bicchieri` : 'Obiettivo raggiunto'))),
      icona('chev', 'freccia')),
    barra({ id: 'acqua', val: ml, max: ob, colore: 'linear-gradient(90deg,#5cc8ff,#8fe3ff)', alta: true }),
    tasti(d));
}

export function apriAcqua(d) {
  const altro = h('input', { type: 'text', inputmode: 'numeric', autocomplete: 'off', placeholder: '330', 'aria-label': 'Millilitri' });
  const metti = () => {
    const ml = Math.round(numero(altro.value) || 0);
    if (!(ml >= 30 && ml <= 2000)) { altro.focus(); avviso('Scrivi i millilitri, da 30 a 2000', 'info'); return; }
    altro.blur();
    altro.value = '';
    aggiungi(d, ml);
  };
  altro.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); metti(); } });

  const f = foglio(() => {
    const ml = acquaBevuta(d), ob = obiettivoAcqua(d);
    const bevute = (S.giorni[d] || {}).bevute || [];
    const giorni = Array.from({ length: 7 }, (_, i) => piuGiorni(d, i - 6));
    const centrati = giorni.filter((g) => acquaBevuta(g) >= obiettivoAcqua(g)).length;
    return [
      h('div', null,
        h('h2', null, 'Acqua'),
        h('p', { class: 'muto', style: { marginTop: '4px' } }, `Oggi ${litri(ml)} L su ${litri(ob)}${tipoGiorno(d) === 'train' ? ', giorno di palestra' : ''}.`)),
      h('div', { class: 'acqua-sett' }, giorni.map((g) => {
        const quota = acquaBevuta(g) / obiettivoAcqua(g);
        return h('div', { class: g === d ? 'oggi' : '' },
          h('span', null, acquaBevuta(g) ? dec(acquaBevuta(g) / 1000, 1) : ''),
          h('div', { class: 'colonna' }, h('i', { class: quota >= 1 ? 'pieno' : '', style: { height: `${Math.min(1, quota) * 100}%` } })),
          h('small', null, INIZIALI[daIso(g).getDay()]));
      })),
      h('p', { class: 'piccolo', style: { textAlign: 'center' } }, centrati ? `Obiettivo centrato ${centrati === 1 ? 'un giorno' : `${centrati} giorni`} su sette.` : 'Qui vedi gli ultimi sette giorni.'),
      h('h4', null, 'Aggiungi'),
      tasti(d),
      h('div', { class: 'riga' },
        h('div', { class: 'campo cresce' }, altro),
        h('button', { class: 'btn', style: { width: 'auto', padding: '0 20px', flex: 'none', marginTop: 0 }, onclick: metti }, icona('plus'), 'ml')),
      bevute.length ? h('h4', null, 'Bevute di oggi') : null,
      bevute.length ? h('div', { class: 'card', style: { paddingTop: '6px', paddingBottom: '6px' } }, bevute.map((b, i) =>
        h('div', { class: 'voce' },
          h('div', { class: 'cresce' }, h('b', null, `${intero(b.ml)} ml`), h('small', null, `alle ${b.t}`)),
          h('button', { class: 'tondo mini', 'aria-label': `Togli la bevuta delle ${b.t}`, onclick: () => togliBevuta(d, i) }, icona('trash')))).reverse()) : null,
      h('div', { class: 'nota' }, icona('info'), h('span', null, 'Nei giorni di palestra e con la creatina serve più acqua: per questo l\'obiettivo sale. Un bicchiere appena sveglio, uno a ogni pasto e la borraccia in palestra coprono quasi tutto.')),
      ml ? h('button', { class: 'btn basso', onclick: () => { azzeraAcqua(d); avviso('Acqua di oggi azzerata'); } }, 'Azzera oggi') : null,
    ];
  });
  return f;
}
