// Prova js/apk.js in Chromium: l'avviso del guscio Android nuovo compare solo con ?apk, solo se il versionCode e'
// piu' alto, sparisce con "Non ora" e per quella versione non torna, e il JSON si chiede al massimo una volta al giorno.
//
//     node tools/prove/prova_apk.mjs <cartella app/public>        (serve il pacchetto playwright)
import { chromium } from 'playwright';
import { readFile } from 'node:fs/promises';
import path from 'node:path';

const PUBBLICA = path.resolve(process.argv[2] || 'public');
const SITO = 'https://fit.example';
const INDICE = 'https://servizi.everbright.it/download/EverFit-Android.json';
const sbagli = [];
const controlla = (nome, vero, dettaglio = '') => {
  console.log((vero ? 'ok   ' : 'ERRORE ') + nome + (!vero && dettaglio ? ' -> ' + dettaglio : ''));
  if (!vero) sbagli.push(nome);
};

const browser = await chromium.launch();
const ctx = await browser.newContext();
let pubblicato = { version: '1.2.0', versionCode: 5, file: 'EverFit-Android.apk', sha256: 'a'.repeat(64), bytes: 500000 };
let richieste = 0;
await ctx.route(INDICE, (r) => {
  richieste += 1;
  r.fulfill({ json: pubblicato, headers: { 'Access-Control-Allow-Origin': '*' } });
});
// la pagina di prova importa solo il modulo, con i file veri di app/public
await ctx.route(`${SITO}/**`, async (r) => {
  const u = new URL(r.request().url());
  if (u.pathname === '/') {
    return r.fulfill({ contentType: 'text/html', body: '<!doctype html><script type="module">import { controllaApk } from "/js/apk.js"; controllaApk(); window.pronto = true;</script>' });
  }
  try {
    const body = await readFile(path.join(PUBBLICA, ...u.pathname.split('/').filter(Boolean)));
    return r.fulfill({ body, contentType: u.pathname.endsWith('.js') ? 'text/javascript' : 'application/octet-stream' });
  } catch {
    return r.fulfill({ status: 404 });
  }
});

const page = await ctx.newPage();
const errori = [];
page.on('pageerror', (e) => errori.push(String(e)));
async function apri(query) {
  await page.goto(`${SITO}/${query}`);
  await page.waitForFunction(() => window.pronto);
  await page.waitForTimeout(300);
  return page.locator('.apk-nuova');
}

let avviso = await apri('');
controlla('senza ?apk: nessuna richiesta', richieste === 0, richieste);
controlla('senza ?apk: nessun avviso', (await avviso.count()) === 0);

avviso = await apri('?apk=3');
controlla('?apk=3, pubblicato 5: avviso', (await avviso.count()) === 1);
controlla('avviso: testo', (await avviso.innerText()).includes("Nuova versione dell'app"));
controlla('avviso: link all\'APK', (await avviso.locator('a').getAttribute('href')) === 'https://servizi.everbright.it/download/EverFit-Android.apk');
controlla('una richiesta sola', richieste === 1, richieste);

avviso = await apri('?apk=3');
controlla('riaperta nello stesso giorno: niente rete', richieste === 1, richieste);
controlla('riaperta: avviso ancora li\'', (await avviso.count()) === 1);
await avviso.locator('button').click();
controlla('"Non ora": sparisce', (await page.locator('.apk-nuova').count()) === 0);
avviso = await apri('?apk=3');
controlla('"Non ora" sulla 5: non torna', (await avviso.count()) === 0);

// passa un giorno e ne esce un'altra: la 6 si propone di nuovo
await page.evaluate(() => { const u = JSON.parse(localStorage.getItem('fit.apk.ultimo')); u.ora -= 86400001; localStorage.setItem('fit.apk.ultimo', JSON.stringify(u)); });
pubblicato = { ...pubblicato, version: '1.3.0', versionCode: 6 };
avviso = await apri('?apk=3');
controlla('dopo un giorno: una richiesta in piu\'', richieste === 2, richieste);
controlla('versione 6: avviso di nuovo', (await avviso.count()) === 1);

avviso = await apri('?apk=6');
controlla('guscio gia\' alla 6: nessun avviso', (await avviso.count()) === 0);

await page.evaluate(() => localStorage.clear());
pubblicato = { ...pubblicato, file: '../altro.apk' };
avviso = await apri('?apk=3');
controlla('JSON con un file strano: ignorato', (await avviso.count()) === 0);
controlla('nessun errore nella pagina', errori.length === 0, errori.join(' | '));

await browser.close();
console.log(sbagli.length ? `\nERRORI: ${sbagli.join(', ')}` : '\nTUTTO BENE');
process.exit(sbagli.length ? 1 : 0);
