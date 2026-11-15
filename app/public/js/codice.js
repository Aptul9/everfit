// Lettura dei codici a barre dei prodotti (EAN-13, UPC-A, EAN-8) dalla fotocamera.
// Dove il browser lo sa fare da solo (BarcodeDetector) lascia fare a lui; sull'iPhone legge le righe dell'immagine:
// trova i passaggi chiaro/scuro, cerca le tre barre di guardia e confronta ogni cifra con le larghezze previste.

// larghezze dei quattro tratti di ogni cifra (in moduli, somma 7): serie L; la serie G e' la stessa al contrario
const L = [[3, 2, 1, 1], [2, 2, 2, 1], [2, 1, 2, 2], [1, 4, 1, 1], [1, 1, 3, 2], [1, 2, 3, 1], [1, 1, 1, 4], [1, 3, 1, 2], [1, 2, 1, 3], [3, 1, 1, 2]];
const LG = L.concat(L.map((w) => [...w].reverse()));
// la prima cifra dell'EAN-13 non ha barre: si ricava da quali delle sei cifre di sinistra sono in serie G
const PARITA = ['LLLLLL', 'LLGLGG', 'LLGGLG', 'LLGGGL', 'LGLLGG', 'LGGLLG', 'LGGGLL', 'LGLGLG', 'LGLGGL', 'LGGLGL'];
const CONTRASTO = 36;     // sotto questa differenza tra chiaro e scuro la zona e' considerata vuota
const TOLLERANZA = 1.7;   // scarto massimo (in moduli, sui quattro tratti) per accettare una cifra
const RIGHE = 24;

export function codiceValido(c) {
  if (!/^(\d{8}|\d{12,13})$/.test(c)) return false;
  const cifre = [...c].map(Number);
  const controllo = cifre.pop();
  const somma = cifre.reverse().reduce((t, v, i) => t + v * (i % 2 ? 1 : 3), 0);
  return (10 - (somma % 10)) % 10 === controllo;
}

// Passaggi chiaro/scuro di una riga di luminosita'. La soglia e' locale (meta' tra minimo e massimo dei dintorni),
// cosi' ombre e riflessi non contano; la posizione del passaggio e' interpolata tra due pixel.
function tratti(lum) {
  const n = lum.length;
  const B = Math.max(6, n >> 6);
  const nb = Math.ceil(n / B);
  const lo = new Float32Array(nb), hi = new Float32Array(nb);
  for (let b = 0; b < nb; b++) {
    let a = 255, z = 0;
    for (let x = b * B, fine = Math.min(n, x + B); x < fine; x++) { const v = lum[x]; if (v < a) a = v; if (v > z) z = v; }
    lo[b] = a; hi[b] = z;
  }
  const d = new Float32Array(n);
  for (let b = 0; b < nb; b++) {
    let a = 255, z = 0;
    for (let k = Math.max(0, b - 3); k <= Math.min(nb - 1, b + 3); k++) { if (lo[k] < a) a = lo[k]; if (hi[k] > z) z = hi[k]; }
    const soglia = (a + z) / 2, vuoto = z - a < CONTRASTO;
    for (let x = b * B, fine = Math.min(n, x + B); x < fine; x++) d[x] = vuoto ? 1 : lum[x] - soglia;
  }
  const pos = [];
  let primoScuro = false;
  for (let x = 1; x < n; x++) {
    const a = d[x - 1], b = d[x];
    if ((a > 0) !== (b > 0)) {
      if (!pos.length) primoScuro = b <= 0;
      pos.push(x - 1 + a / (a - b));
    }
  }
  return larghezze(pos, primoScuro, n);
}

function larghezze(pos, primoScuro, n) {
  const w = new Float32Array(Math.max(0, pos.length - 1));
  for (let i = 0; i < w.length; i++) w[i] = pos[i + 1] - pos[i];
  return { w, primoScuro, prima: pos.length ? pos[0] : n, dopo: pos.length ? n - pos[pos.length - 1] : n };
}

// Seconda lettura, per le immagini sfocate: le barre sottili restano "annegate" nel grigio e una soglia fissa
// non le vede. Qui si cercano cime e valli della luminosita' e il passaggio sta a meta' altezza tra l'una e l'altra.
function trattiSfocati(lum) {
  const n = lum.length;
  const v = new Float32Array(n);
  v[0] = lum[0]; v[n - 1] = lum[n - 1];
  for (let x = 1; x < n - 1; x++) v[x] = (lum[x - 1] + 2 * lum[x] + lum[x + 1]) / 4;
  let lo = 255, hi = 0;
  for (let x = 0; x < n; x++) { if (v[x] < lo) lo = v[x]; if (v[x] > hi) hi = v[x]; }
  const passo = Math.max(5, (hi - lo) * 0.09);   // di quanto deve scendere o risalire perche' sia una cima o una valle vera
  const estremi = [];
  let maxV = -1, maxX = 0, minV = 256, minX = 0, cercaCima = true;
  for (let x = 0; x < n; x++) {
    const a = v[x];
    if (a > maxV) { maxV = a; maxX = x; }
    if (a < minV) { minV = a; minX = x; }
    if (cercaCima && a < maxV - passo) { estremi.push([maxX, maxV]); minV = a; minX = x; cercaCima = false; }
    else if (!cercaCima && a > minV + passo) { estremi.push([minX, minV]); maxV = a; maxX = x; cercaCima = true; }
  }
  const pos = [];
  for (let k = 0; k + 1 < estremi.length; k++) {
    const [x1, v1] = estremi[k], [x2, v2] = estremi[k + 1];
    const meta = (v1 + v2) / 2;
    for (let x = x1 + 1; x <= x2; x++) {
      if ((v[x - 1] > meta) !== (v[x] > meta)) { pos.push(x - 1 + (v[x - 1] - meta) / (v[x - 1] - v[x])); break; }
    }
  }
  return larghezze(pos, true, n);   // il primo estremo e' sempre una cima: il primo tratto e' scuro
}

function cifra(w, j, scuro, delta, tabella) {
  let somma = 0;
  const t = [0, 0, 0, 0];
  for (let k = 0; k < 4; k++) { t[k] = w[j + k] + ((k % 2 === 0) === scuro ? -delta : delta); somma += t[k]; }
  const unita = somma / 7;
  let meglio = -1, errore = Infinity;
  for (let c = 0; c < tabella.length; c++) {
    let e = 0;
    for (let k = 0; k < 4; k++) e += Math.abs(t[k] / unita - tabella[c][k]);
    if (e < errore) { errore = e; meglio = c; }
  }
  return errore <= TOLLERANZA ? meglio : -1;
}

// Prova a leggere un codice le cui barre di guardia cominciano al tratto i. `meta` = cifre per parte (6 o 4).
function leggiDa(w, i, meta) {
  const perParte = meta * 4;
  const centro = i + 3 + perParte, destra = centro + 5, fine = destra + perParte;
  if (fine + 3 > w.length) return null;
  let tot = 0;
  for (let k = i; k < fine + 3; k++) tot += w[k];
  const mod = tot / (meta === 6 ? 95 : 67);
  const barre = [i, i + 2, centro + 1, centro + 3, fine, fine + 2];
  const spazi = [i + 1, centro, centro + 2, centro + 4, fine + 1];
  const media = (ix) => ix.reduce((s, k) => s + w[k], 0) / ix.length;
  // stampa e messa a fuoco ingrassano o smagriscono le barre: le guardie, che valgono tutte un modulo, dicono di quanto
  const delta = (media(barre) - media(spazi)) / 2;
  for (const k of barre) if (w[k] - delta < 0.4 * mod || w[k] - delta > 1.8 * mod) return null;
  for (const k of spazi) if (w[k] + delta < 0.4 * mod || w[k] + delta > 1.8 * mod) return null;
  if (fine + 3 < w.length && w[fine + 3] < 2.5 * mod) return null;   // dopo l'ultima barra serve un margine bianco
  let codice = '', parita = '';
  for (let k = 0; k < meta; k++) {
    const c = cifra(w, i + 3 + k * 4, false, delta, meta === 6 ? LG : L);
    if (c < 0) return null;
    codice += c % 10; parita += c < 10 ? 'L' : 'G';
  }
  if (meta === 6) {
    const prima = PARITA.indexOf(parita);
    if (prima < 0) return null;
    codice = prima + codice;
  }
  for (let k = 0; k < meta; k++) {
    const c = cifra(w, destra + k * 4, true, delta, L);
    if (c < 0) return null;
    codice += c;
  }
  return codiceValido(codice) ? codice : null;
}

function cercaIn(w, primoScuro, margine) {
  for (let i = primoScuro ? 0 : 1; i + 43 <= w.length; i += 2) {
    // guardia: due barre uguali con in mezzo uno spazio dello stesso ordine (la stampa puo' ingrassarle o smagrirle)
    const barra = (w[i] + w[i + 2]) / 2, m = (w[i] + w[i + 1] + w[i + 2]) / 3;
    if (Math.abs(w[i] - w[i + 2]) > 0.5 * barra || w[i + 1] < 0.3 * barra || w[i + 1] > 3.3 * barra) continue;
    if ((i === 0 ? margine : w[i - 1]) < 4 * m) continue;          // prima delle guardie serve un margine bianco
    const codice = leggiDa(w, i, 6) || leggiDa(w, i, 4);
    if (codice) return codice;
  }
  return null;
}

export function leggiRiga(lum) {
  for (const modo of [tratti, trattiSfocati]) {
    const { w, primoScuro, prima, dopo } = modo(lum);
    if (w.length < 43) continue;
    // l'ultimo tratto e' scuro se il loro numero e' dispari e il primo e' scuro, o pari e il primo e' chiaro
    const ultimoScuro = (w.length % 2 === 1) === primoScuro;
    const codice = cercaIn(w, primoScuro, prima) || cercaIn(Float32Array.from(w).reverse(), ultimoScuro, dopo);
    if (codice) return codice;
  }
  return null;
}

// Legge un'immagine (ImageData) su piu' righe. Restituisce quante righe hanno dato ogni codice.
export function leggiImmagine({ data, width: W, height: H }) {
  const voti = new Map();
  const lum = new Float32Array(W);
  for (let r = 0; r < RIGHE; r++) {
    const y = Math.min(H - 2, Math.max(1, Math.round((r + 0.5) * H / RIGHE)));
    for (let x = 0; x < W; x++) {
      let s = 0;
      for (let dy = -1; dy <= 1; dy++) { const o = ((y + dy) * W + x) * 4; s += data[o] * 0.3 + data[o + 1] * 0.59 + data[o + 2] * 0.11; }
      lum[x] = s / 3;
    }
    const c = leggiRiga(lum);
    if (c) voti.set(c, (voti.get(c) || 0) + 1);
  }
  return voti;
}

export const fotocameraDisponibile = () => !!navigator.mediaDevices?.getUserMedia;

// ---------- il codice letto da una foto ----------
// Sull'iPhone, nell'app aperta dalla schermata Home, il permesso della fotocamera viene richiesto a ogni apertura: lo
// decide iOS e un'app web non puo' farci niente. Il campo "file" con capture, invece, apre la fotocamera di sistema senza
// chiedere niente: si scatta, e il codice si legge dalla foto (vedi scatto.js).
async function immagineDi(file) {
  if (window.createImageBitmap) { try { return await createImageBitmap(file, { imageOrientation: 'from-image' }); } catch { /* si prova con <img> */ } }
  return new Promise((ok, no) => {
    const img = new Image(), url = URL.createObjectURL(file);
    img.onload = () => { URL.revokeObjectURL(url); ok(img); };
    img.onerror = () => { URL.revokeObjectURL(url); no(new Error('foto illeggibile')); };
    img.src = url;
  });
}

// Le cifre del codice a barre che c'e' nella foto, oppure null. Il codice puo' essere ovunque, piccolo, dritto o di
// lato: si provano l'immagine intera e i suoi ritagli, prima cosi' com'e' e poi girata di 90 gradi.
export async function leggiFoto(file) {
  const img = await immagineDi(file);
  const iw = img.width || img.naturalWidth, ih = img.height || img.naturalHeight;
  if (!iw || !ih) return null;
  const intero = (c) => (c.length === 12 ? `0${c}` : c);
  if ('BarcodeDetector' in window) {
    try {
      const trovati = await new window.BarcodeDetector({ formats: ['ean_13', 'ean_8', 'upc_a'] }).detect(img);
      const c = trovati.map((x) => x.rawValue).find(codiceValido);
      if (c) return intero(c);
    } catch { /* si legge a mano */ }
  }
  const tela = document.createElement('canvas');
  const ctx = tela.getContext('2d', { willReadFrequently: true });
  const voti = new Map();
  const prova = ([x, y, w, a], girata) => {
    const sx = x * iw, sy = y * ih, sw = w * iw, sh = a * ih;
    const W = Math.round(Math.min(1600, girata ? sh : sw)), H = Math.max(8, Math.round((girata ? sw : sh) * W / (girata ? sh : sw)));
    tela.width = W; tela.height = H;
    ctx.save();
    if (girata) { ctx.translate(W, 0); ctx.rotate(Math.PI / 2); ctx.drawImage(img, sx, sy, sw, sh, 0, 0, H, W); }
    else ctx.drawImage(img, sx, sy, sw, sh, 0, 0, W, H);
    ctx.restore();
    for (const [c, n] of leggiImmagine(ctx.getImageData(0, 0, W, H))) voti.set(c, (voti.get(c) || 0) + n);
    for (const [c, n] of voti) if (n >= (c.length === 8 ? 3 : 2)) return c;
    return null;
  };
  // [da sinistra, dall'alto, larghezza, altezza] in frazioni della foto
  const RITAGLI = [[0, 0, 1, 1], [0.15, 0.15, 0.7, 0.7], [0, 0.25, 1, 0.5], [0.25, 0, 0.5, 1], [0, 0, 0.6, 0.6], [0.4, 0, 0.6, 0.6], [0, 0.4, 0.6, 0.6], [0.4, 0.4, 0.6, 0.6]];
  for (const girata of [false, true]) {
    for (const ritaglio of RITAGLI) {
      const c = prova(ritaglio, girata);
      if (c) return intero(c);
    }
  }
  // letto una volta sola: meglio di niente (le cifre di controllo tornano), chi guarda vede subito se e' il prodotto giusto
  const meglio = [...voti].sort((a, b) => b[1] - a[1] || b[0].length - a[0].length)[0];
  return meglio ? intero(meglio[0]) : null;
}

// Accende la fotocamera sul <video> e chiama alCodice(cifre) al primo codice letto due volte uguale.
// Restituisce la funzione che spegne tutto. Se la fotocamera non parte, l'errore arriva a chi chiama.
export async function avviaLettore(video, alCodice) {
  const flusso = await navigator.mediaDevices.getUserMedia({
    audio: false, video: { facingMode: { ideal: 'environment' }, width: { ideal: 1920 }, height: { ideal: 1080 } },
  });
  let vivo = true, sveglia = null, giri = 0;
  const ferma = () => {
    vivo = false;
    clearTimeout(sveglia);
    flusso.getTracks().forEach((t) => t.stop());
    video.srcObject = null;
  };
  video.muted = true;
  video.setAttribute('playsinline', '');
  video.srcObject = flusso;
  await video.play().catch(() => {});
  let nativo = null;
  if ('BarcodeDetector' in window) { try { nativo = new window.BarcodeDetector({ formats: ['ean_13', 'ean_8', 'upc_a'] }); } catch { /* si legge a mano */ } }
  const tela = document.createElement('canvas');
  const ctx = tela.getContext('2d', { willReadFrequently: true });
  const voti = new Map();

  const giro = async () => {
    if (!vivo) return;
    try {
      const vw = video.videoWidth, vh = video.videoHeight;
      if (video.readyState >= 2 && vw && vh) {
        let trovato = null;
        if (nativo) trovato = (await nativo.detect(video).catch(() => [])).map((x) => x.rawValue).find(codiceValido) || null;
        if (!trovato) {
          // la fascia centrale del fotogramma, larga al massimo 1280 pixel
          const scala = Math.min(1, 1280 / vw), fascia = Math.round(vh * 0.44);
          const W = Math.round(vw * scala), H = Math.max(8, Math.round(fascia * scala));
          if (tela.width !== W || tela.height !== H) { tela.width = W; tela.height = H; }
          ctx.drawImage(video, 0, (vh - fascia) / 2, vw, fascia, 0, 0, W, H);
          if (++giri % 30 === 0) voti.clear();   // una lettura sbagliata e isolata non deve restare in conto per sempre
          for (const [c, n] of leggiImmagine(ctx.getImageData(0, 0, W, H))) voti.set(c, (voti.get(c) || 0) + n);
          for (const [c, n] of voti) if (n >= (c.length === 8 ? 3 : 2)) { trovato = c; break; }
        }
        if (trovato && vivo) {
          ferma();
          navigator.vibrate?.(60);
          alCodice(trovato.length === 12 ? `0${trovato}` : trovato);
          return;
        }
      }
    } catch { /* un fotogramma storto non ferma la lettura */ }
    sveglia = setTimeout(giro, 90);
  };
  giro();
  return ferma;
}
