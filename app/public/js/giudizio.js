// Giudizio su un prodotto confezionato rispetto agli obiettivi di chi usa l'app. Regole fisse, niente AI:
// - grassi, saturi, zuccheri e sale con le soglie "a semaforo" dell'etichettatura britannica (FSA);
// - proteine e fibre con le soglie delle indicazioni nutrizionali europee ("fonte di", "ricco di");
// - piu' quello che conta per questa persona: lattosio, alcol, quanto e' lavorato.
// I valori sono per 100 g (o 100 ml); `a.x` e' il resto dell'etichetta come lo manda il server (vedi server/cibo.py).

import { dec, intero } from './dom.js';

const SOGLIE = {
  solido: { f: [3, 17.5], sat: [1.5, 5], zuc: [5, 22.5], sale: [0.3, 1.5] },
  bevanda: { f: [1.5, 8.75], sat: [0.75, 2.5], zuc: [2.5, 11.25], sale: [0.3, 0.75] },
};
const POLIOLI = ['E420', 'E421', 'E953', 'E965', 'E966', 'E967', 'E968'];
const ESITI = {
  ok: { titolo: 'Va bene per la tua dieta', colore: '#c8ff4d' },
  cosi: { titolo: 'Ogni tanto, con misura', colore: '#ffc34d' },
  no: { titolo: 'Meglio di no', colore: '#ff7a7a' },
};

export const livello = (v, [basso, alto]) => (v == null ? null : v <= basso ? 'basso' : v > alto ? 'alto' : 'medio');

// `persona` = { obiettivi: {rest, train}, lattosio: true se intollerante }
export function valuta(a, persona) {
  if (a.kcal == null) return null;
  const x = a.x || {};
  const s = SOGLIE[x.bevanda ? 'bevanda' : 'solido'];
  const cento = x.bevanda ? '100 ml' : '100 g';
  const quota = a.kcal > 0 ? (a.p * 4) / a.kcal : 0;   // la parte delle calorie che viene dalle proteine
  const liv = { f: livello(a.f, s.f), sat: livello(x.sat, s.sat), zuc: livello(x.zuc, s.zuc), sale: livello(x.sale, s.sale) };
  const forti = [], deboli = [], consigli = [];
  let voto = 60, tetto = 100;

  // proteine: per chi vuole mettere muscolo sono la prima cosa da guardare
  if (quota >= 0.3 && a.p >= 10) { voto += 18; forti.push(`Ricco di proteine: ${dec(a.p)} g ogni ${cento}, il ${intero(quota * 100)}% delle calorie`); }
  else if (quota >= 0.2) { voto += 12; forti.push(`Buona quota di proteine: ${dec(a.p)} g ogni ${cento}`); }
  else if (quota >= 0.12) voto += 5;
  else if (a.kcal >= 150) { voto -= 6; deboli.push(`Poche proteine: ${dec(a.p)} g ogni ${cento}`); }
  if (/prote/i.test(a.n) && quota < 0.2) deboli.push(`Si chiama «protein» ma solo il ${intero(quota * 100)}% delle calorie viene dalle proteine`);

  if (x.fib >= 6) { voto += 8; forti.push(`Ricco di fibre: ${dec(x.fib)} g`); } else if (x.fib >= 3) { voto += 4; forti.push(`Buona quota di fibre: ${dec(x.fib)} g`); }

  if (liv.zuc === 'alto') { voto -= 18; deboli.push(`Tanto zucchero: ${dec(x.zuc)} g ogni ${cento}`); }
  else if (liv.zuc === 'medio') { voto -= x.zuc > 12 ? 10 : 5; if (x.zuc > 12) deboli.push(`Zuccheri non pochi: ${dec(x.zuc)} g ogni ${cento}`); }
  else if (liv.zuc === 'basso') { voto += 5; forti.push(`Pochi zuccheri: ${dec(x.zuc)} g`); }
  if (x.bevanda && liv.zuc === 'alto') { voto -= 8; deboli.push('Calorie da bere: non saziano e si sommano'); }

  if (liv.sat === 'alto') { voto -= 12; deboli.push(`Tanti grassi saturi: ${dec(x.sat)} g`); } else if (liv.sat === 'basso') { voto += 4; if (a.f <= s.f[0]) forti.push('Pochissimi grassi'); }
  if (liv.sale === 'alto') { voto -= 10; deboli.push(`Molto salato: ${dec(x.sale)} g di sale`); } else if (liv.sale === 'basso') voto += 2;

  if (!x.bevanda && a.kcal > 450 && quota < 0.2) { voto -= 6; deboli.push(`Molto calorico: ${intero(a.kcal)} kcal ogni 100 g, conta la porzione`); }

  if (x.nova === 4) { voto -= 6; deboli.push('Ultra-processato (gruppo NOVA 4)'); } else if (x.nova === 1 || x.nova === 2) { voto += 4; forti.push('Poco lavorato'); }
  if ((x.additivi || []).length >= 5) { voto -= 4; deboli.push(`${x.additivi.length} additivi in etichetta`); }
  voto += { a: 4, b: 2, d: -4, e: -8 }[x.nutri] || 0;

  if (x.alcol > 1) { voto -= 30; tetto = 35; deboli.push('Alcol: calorie vuote, e frena il recupero dopo l\'allenamento'); }
  const latte = (x.allergeni || []).some((t) => /milk|latte|lait|lactose/.test(t));
  if (persona?.lattosio && latte && !x.senza_lattosio) { voto -= 15; tetto = Math.min(tetto, 60); deboli.push('Contiene latte e non risulta «senza lattosio»: tu sei intollerante'); }
  else if (persona?.lattosio && x.senza_lattosio) forti.push('Senza lattosio');

  // consigli: come farlo stare nella giornata
  const ob = persona?.obiettivi?.rest;
  if (a.pz) {
    const k = a.pz / 100, nome = a.pzn?.[0] || 'porzione';
    consigli.push(`Un${nome === 'porzione' ? 'a' : ''} ${nome} da ${dec(a.pz, 1)} g: ${intero(a.kcal * k)} kcal e ${dec(a.p * k)} g di proteine${ob ? `, il ${intero(a.p * k / ob.p * 100)}% delle proteine di una giornata` : ''}.`);
  }
  if (quota >= 0.2) consigli.push('Va bene come merenda o subito dopo l\'allenamento.');
  else if (a.c >= 45 && a.f <= 6 && liv.zuc !== 'alto') consigli.push('Carboidrati con pochi grassi: adatto prima della palestra o nel pasto dopo.');
  if (liv.zuc === 'alto' && !(x.alcol > 1)) consigli.push('Se lo vuoi, tienilo per dopo l\'allenamento: è il momento in cui gli zuccheri servono.');
  if (a.f >= 20 && ob) consigli.push(`Hai ${ob.f} g di grassi al giorno: 100 g di questo ne valgono ${dec(a.f)}.`);
  // E965 ed E965II sono lo stesso dolcificante: conta il numero
  if ((x.additivi || []).some((e) => POLIOLI.includes((e.match(/^E\d+/) || [''])[0]))) consigli.push('Contiene polioli (dolcificanti): più di due o tre porzioni al giorno possono dare gonfiore.');
  if (quota < 0.12 && a.kcal >= 150 && ob) consigli.push('Non contarlo come fonte di proteine: quelle prendile dal resto della giornata.');
  const tracceDiLatte = (x.tracce || []).some((t) => /milk|latte|lait/.test(t));
  if (persona?.lattosio && tracceDiLatte && !latte) consigli.push('«Può contenere latte» vuol dire tracce: per l\'intolleranza al lattosio non sono un problema.');

  voto = Math.round(Math.max(5, Math.min(98, Math.min(voto, tetto))));
  const esito = voto >= 68 ? 'ok' : voto >= 45 ? 'cosi' : 'no';
  return { voto, esito, ...ESITI[esito], forti, deboli, consigli, liv, parziale: !a.x };
}

// Le righe della tabella nutrizionale: [nome, valore per 100, unita', livello a semaforo, rientrata]
export function tabella(a) {
  const x = a.x || {};
  const s = SOGLIE[x.bevanda ? 'bevanda' : 'solido'];
  return [
    ['Energia', a.kcal, 'kcal', null, false],
    ['Grassi', a.f, 'g', livello(a.f, s.f), false],
    ['di cui saturi', x.sat, 'g', livello(x.sat, s.sat), true],
    ['Carboidrati', a.c, 'g', null, false],
    ['di cui zuccheri', x.zuc, 'g', livello(x.zuc, s.zuc), true],
    ['Fibre', x.fib, 'g', null, false],
    ['Proteine', a.p, 'g', null, false],
    ['Sale', x.sale, 'g', livello(x.sale, s.sale), false],
  ].filter((r) => r[1] != null);
}
