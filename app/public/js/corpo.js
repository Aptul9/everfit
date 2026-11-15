// Composizione corporea da peso e impedenza, con le stesse formule dell'app Starfit.
//
// La bilancia (Runstar R5, FG2431WB) manda solo peso e impedenza: tutto il resto lo calcola il telefono.
// Queste sono le formule della famiglia "Inter" della libreria iComon, riscritte leggendo il codice
// dell'app (analisi statica, per usare la propria bilancia con un altro programma). Controllate su una pesata
// vera: con lo stesso peso e la stessa impedenza danno gli stessi numeri dell'app sul telefono (IMC, grasso,
// muscolo, sottocutaneo, viscerale, ossa, acqua, proteine, scheletrico, metabolismo, eta' corporea).
//
// La libreria mescola numeri a 32 e a 64 bit e arrotonda in un modo tutto suo: per avere gli stessi
// decimali va rifatta ogni operazione con la stessa precisione. `f` e' un numero a 32 bit.

const f = Math.fround;

// Arrotonda a un decimale come fa la libreria: la seconda cifra decimale sale solo se supera 5.
function r1(x) {
  x = f(x);
  const intero = Math.trunc(x);
  let dec = f(f(x % 1) * 10);
  if (f(dec % 1) > 0.5) dec = f(dec + 1);
  let r = f(Math.trunc(dec) / 10);
  if (r === 0 && f(x - intero) > 0.99) r = 1;
  return f(r + intero);
}

// Grasso corporeo in millesimi. p100 = peso in kg x 100, sesso 1 = uomo, tipo 1 = atleta.
function grassoMillesimi(p100, h, eta, imp, sesso, tipo) {
  if (eta < 7) return 0;
  const h2 = h * h;
  const imc = r1(f(((p100 * 10000) / h2) / 10));
  const z = f(imp);
  const adulto = eta > 15 && tipo === 0;
  const atleta = eta >= 16 && tipo === 1;
  let v;
  if (sesso === 1) {
    if (adulto) v = (f(120090 / z) + eta * 0.676 + 376) + -50679100 / (z * imc);
    else if (atleta) v = ((f(314700 / z) + 240.4) + -1222000000 / (z * p100)) + (h2 * -6.5038) / z;
    else v = (f(f(120090 / z) + 566) + eta * -11.21) + -50679100 / (z * imc);
  } else if (adulto) v = (f(173870 / z) + eta * 0.467 + 430) + -55642100 / (z * imc);
  else if (atleta) v = ((f(424500 / z) + 535) + -1593166000 / (z * p100)) + (h2 * -11.38) / z;
  else v = f(f(173870 / z) + 442) + -55642100 / (z * imc);
  let s = f(v);
  if (s <= 40) s = 40;
  if (s >= 600) s = 600;
  return r1(s);
}

function viscerale(p100, h, eta, imp, sesso) {
  const z = f(imp);
  let v;
  if (sesso === 1) {
    let a = f(6096.2998046875 / z) + (f(f(0.77216) / z) + 0.000678) * p100;
    a += eta * 0.1668;
    a -= (h * (f(f(0.5489) / z) + -0.00028)) * h;
    v = a + -1.2000000476837158;
  } else {
    let a = eta * 0.068 + (f(f(0.7192) / z) + 0.000876) * p100;
    a += 5.9;
    a -= (h * (0.12617 / z + 0.000288)) * h;
    v = a + -1545.6 / z;
  }
  if (v < 1) v = 1;
  return r1(f(v));
}

const ACQUA = {
  '1a': [696819008, 37053, 299430, -107700, 296],   // uomo adulto
  '1s': [702739968, 37074, 280000, -108220, 298],   // uomo atleta
  '2a': [556707008, 37524, 444930, -102760, 243],   // donna adulta
  '2s': [527425984, 36977, 502010, -95828, 233],    // donna atleta
};

function acquaMillesimi(p100, h, eta, imp, sesso, tipo) {
  const grasso = grassoMillesimi(p100, h, eta, imp, sesso, tipo);
  const z = f(imp);
  const chiave = (sesso === 1 ? '1' : '2') + (eta > 15 && tipo === 0 ? 'a' : eta >= 16 && tipo === 1 ? 's' : '');
  const k = ACQUA[chiave];
  if (!k) return r1(f((1000 - grasso) * 0.6875));
  const [a, m, c, d, base] = k;
  const quota = Math.trunc(Math.imul(h * h, m) / 10000);
  let v = f(f(a / z) + c) / p100;
  v += f(quota / z);
  v += base;
  v += f(d / z);
  return r1(f(v));
}

const OSSA = [0.061000000685453415, 0.052000001072883606];   // donna, uomo

function proteineMillesimi(p100, h, eta, imp, sesso, tipo) {
  const grasso = grassoMillesimi(p100, h, eta, imp, sesso, tipo);
  const ossa = r1(f(OSSA[sesso === 1 ? 1 : 0] * (1000 - grasso)));
  const acqua = acquaMillesimi(p100, h, eta, imp, sesso, tipo);
  return r1(f(1000 - (acqua + (grasso + ossa))));
}

// Fasce di grasso (in %) e anni da aggiungere o togliere: [uomo, donna] per chi ha meno o piu' di 30 anni.
const ETA = {
  giovane: [[[14, -3], [18, -2], [22, -1], [24, 1], [27, 2], [30, 3], [33, 4]], [[18, -3], [20, -2], [24, -1], [28, 1], [32, 2], [36, 3], [40, 4]]],
  adulto: [[[14, -3], [18, -2], [22, -1], [26, 1], [30, 2], [34, 3], [36, 4]], [[21, -3], [24, -2], [27, -1], [30, 1], [34, 2], [38, 3], [39, 4]]],
};

function etaCorporea(p100, h, eta, imp, sesso, tipo) {
  if (eta < 16) return eta;
  const grasso = grassoMillesimi(p100, h, eta, imp, sesso, tipo) / 10;
  if (sesso !== 1 && sesso !== 2) return eta;
  const fasce = ETA[eta > 29 ? 'adulto' : 'giovane'][sesso === 1 ? 0 : 1];
  for (const [soglia, anni] of fasce) if (grasso < soglia) return eta + anni;
  return eta + 5;
}

// [divisore del termine a/z, termine b, costante, numeratore della parte di altezza, costante dell'altezza, numeratore /eta', termine /z]
function metabolismo(p100, h, eta, imp, sesso, tipo) {
  const z = f(imp);
  let perPeso, base, daZ, numH, costH, numEta;
  if (sesso === 1 && tipo !== 0) { perPeso = -27.047 / z + 0.22576; base = -146; daZ = 64132; numH = 118380; costH = f(-8.561); numEta = 3086; }
  else if (sesso === 1) { perPeso = f(f(f(-26.475) / z) + f(0.1764)); base = -133; daZ = 45378; numH = 137877; costH = f(-9.3522); numEta = 4095; }
  else if (tipo !== 0) { perPeso = f(f(f(-25.81) / z) + f(0.15016)); base = -21; daZ = 42482; numH = 147997; costH = f(-15.777); numEta = 3112; }
  else { perPeso = f(f(f(-36.424) / z) + f(0.1739)); base = -49; daZ = 32682; numH = 132178; costH = f(-19.79); numEta = 3758; }
  const hf = f(h);
  const altezza = f(f(f(f(f(numH / z) + costH) * hf) * hf) / 10000);
  let v = altezza + perPeso * p100;
  v += Math.trunc(numEta / eta);
  v -= f(daZ / z);
  return r1(f(base + v));
}

// Tutti i valori che mostra Starfit. sesso: 'm' o 'f'. Senza impedenza valida torna solo peso e IMC.
export function composizione({ peso, impedenza, altezza, eta, sesso, atleta = false }) {
  const s = sesso === 'f' ? 2 : 1;
  const tipo = atleta ? 1 : 0;
  const p100 = peso * 100;
  const imc10 = r1(f(((p100 * 10000) / (altezza * altezza)) / 10));
  const imc = r1(f(imc10 / 10));
  const pesoForma = Math.round(22 * altezza * altezza / 1000) / 10;
  if (!impedenza || impedenza < 10) return { peso, imc: Math.round(imc * 10) / 10, pesoForma, soloPeso: true };

  const grasso = grassoMillesimi(p100, altezza, eta, impedenza, s, tipo);
  const magra = 1000 - grasso;
  const sottocutaneo = r1(f(r1(f(grasso * (0.72 + grasso * -0.0002))) / 10));
  const muscolo = r1(f(r1(f(magra * 0.9375)) / 10));
  const ossaPerc = r1(f(r1(f(OSSA[s === 1 ? 1 : 0] * magra)) / 10));
  const grassoPerc = r1(f(grasso / 10));
  const acqua = r1(f(acquaMillesimi(p100, altezza, eta, impedenza, s, tipo) / 10));
  const proteine = r1(f(proteineMillesimi(p100, altezza, eta, impedenza, s, tipo) / 10));
  const pulito = (x, n = 1) => Math.round(x * 10 ** n) / 10 ** n;
  // tre decimali: chi li mostra arrotonda a uno, e arrotondare due volte sposterebbe l'ultima cifra
  const kg = (perc) => pulito(peso * perc / 100, 3);

  return {
    peso, impedenza, imc: pulito(imc), pesoForma,
    grasso: pulito(grassoPerc), grassoKg: kg(grassoPerc), magraKg: pulito(peso - peso * grassoPerc / 100, 3),
    muscolo: pulito(muscolo), muscoloKg: kg(muscolo),
    scheletrico: pulito(r1(f((magra * 0.6875) / 10))),
    acqua: pulito(acqua), acquaKg: kg(acqua),
    proteine: pulito(proteine), proteineKg: kg(proteine),
    ossaKg: pulito((p100 * ossaPerc) / 10000, 3),
    sottocutaneo: pulito(sottocutaneo),
    viscerale: pulito(r1(f(viscerale(p100, altezza, eta, impedenza, s)))),
    bmr: Math.trunc(metabolismo(p100, altezza, eta, impedenza, s, tipo)),
    etaCorporea: etaCorporea(p100, altezza, eta, impedenza, s, tipo),
    algoritmo: 'icomon-inter',
  };
}

// ---------- dal metro da sarta ----------

// Grasso corporeo stimato dalle circonferenze (formula della Marina americana), in cm.
export function grassoMarina({ sesso, altezza, collo, vita, fianchi }) {
  if (!altezza || !collo || !vita) return null;
  let v;
  if (sesso === 'f') {
    if (!fianchi) return null;
    v = 495 / (1.29579 - 0.35004 * Math.log10(vita + fianchi - collo) + 0.221 * Math.log10(altezza)) - 450;
  } else {
    if (vita <= collo) return null;
    v = 495 / (1.0324 - 0.19077 * Math.log10(vita - collo) + 0.15456 * Math.log10(altezza)) - 450;
  }
  return Number.isFinite(v) && v > 2 && v < 60 ? Math.round(v * 10) / 10 : null;
}

export const rapporto = (a, b) => (a && b ? Math.round((a / b) * 100) / 100 : null);
