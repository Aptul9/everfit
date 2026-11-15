// Aspetto scuro (com'e' nata l'app) o chiaro. Vale per il dispositivo, non per l'account: sta nella memoria del
// browser e index.html lo applica prima ancora di disegnare qualcosa, cosi' non c'e' il lampo del colore sbagliato.
// I colori dei due aspetti stanno in css/app.css (:root e :root[data-tema="chiaro"]).

const CHIAVE = 'fit.tema';

export const tema = () => (document.documentElement.dataset.tema === 'chiaro' ? 'chiaro' : 'scuro');

export function cambiaTema(nuovo = tema() === 'chiaro' ? 'scuro' : 'chiaro') {
  const radice = document.documentElement;
  // un attimo senza transizioni: altrimenti ogni scheda sfuma per conto suo e l'app sembra andare a pezzi
  radice.classList.add('cambio-tema');
  if (nuovo === 'chiaro') radice.dataset.tema = 'chiaro'; else delete radice.dataset.tema;
  try { localStorage.setItem(CHIAVE, nuovo); } catch { /* resta cosi' fino alla chiusura */ }
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', nuovo === 'chiaro' ? '#f2f3f6' : '#090a0d');
  document.querySelector('meta[name="color-scheme"]')?.setAttribute('content', nuovo === 'chiaro' ? 'light' : 'dark');
  setTimeout(() => radice.classList.remove('cambio-tema'), 80);
  return nuovo;
}
