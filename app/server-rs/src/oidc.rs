//! Sign-in through the central account service. An unauthenticated navigation tries silent authorization first;
//! when no central session exists it continues directly to the interactive authorization page.
//! Accounts are keyed by the service's `sub`, which for this provider equals `user.uid` of the flow login (checked on
//! the live service 2026-11-20); the first login creates the account, the owner gets the admin one, and the
//! `FIT_OIDC_GRUPPO` group is required. No page shows the service's name.

use crate::accesso;
use crate::conf::conf;
use crate::errore::{Esito, Problema};
use crate::py;
use crate::server::{Ctx, Risposta};
use base64::Engine;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::{HashMap, VecDeque};
use std::sync::{LazyLock, Mutex};
use std::time::{Duration, Instant};

/// how long the trip to the service and back may take
const VIAGGIO: f64 = 600.0;
const COOKIE: &str = "fito";
const SCOPE: &str = "openid email profile";
/// the service group whose members may take over the admin account with the owner's e-mail
const ADMIN: &str = "everid-admins";
const FLUSSO: &str = "default-authentication-flow";
const FLUSSO_USCITA: &str = "default-invalidation-flow";
/// failed form logins allowed per client address within FINESTRA seconds
const TENTATIVI: usize = 5;
const FINESTRA: f64 = 600.0;
/// after a silent attempt found no session, the form shows without another round trip for this long
const PROVATO: i64 = 600;

const NON_RISPONDE: &str = "Il servizio di accesso non risponde: riprova tra poco.";
const CONFIGURATO_MALE: &str = "Il servizio di accesso non è configurato bene.";
const NON_RIUSCITO: &str = "Accesso non riuscito: riprova.";
const SBAGLIATI: &str = "Nome utente o password sbagliati.";
const SENZA_ACCESSO: &str = "Questo account non ha accesso a EverFit.";
const TROPPI: &str = "Troppi tentativi sbagliati: riprova tra qualche minuto.";

pub fn attivo() -> bool {
    accesso::acceso() && !conf().oidc_issuer.is_empty()
}

fn ritorno() -> String {
    format!("{}/oidc/callback", conf().chi_siamo.trim_end_matches('/'))
}

fn stesso_issuer(a: &str, b: &str) -> bool {
    a.trim_end_matches('/') == b.trim_end_matches('/')
}

/// The Android shell opens the app with `?apk=<versionCode>`: it is carried through the login so the update banner
/// still knows it.
pub fn apk(query: &str) -> Option<String> {
    py::parse_qs(query)
        .get("apk")
        .filter(|v| (1..=9).contains(&v.len()) && v.bytes().all(|b| b.is_ascii_digit()))
        .cloned()
}

pub fn con_apk(base: &str, apk: Option<&str>) -> String {
    match apk {
        Some(a) => format!("{base}?apk={a}"),
        None => base.to_string(),
    }
}

fn destinazione_sicura(valore: &str) -> String {
    let lower = valore.to_ascii_lowercase();
    if valore.len() > 2048
        || !valore.starts_with('/')
        || valore.starts_with("//")
        || valore.contains('\\')
        || valore.chars().any(char::is_control)
        || lower.starts_with("/%2f")
        || lower.starts_with("/%5c")
    {
        return "/".into();
    }
    valore.to_string()
}

fn biscotto_provato() -> String {
    format!("fitm=1; Path=/; Max-Age={PROVATO}; Secure; HttpOnly; SameSite=Lax")
}

/// Set at logout: whoever left this device is not signed in again silently, only with the form or the other options.
pub fn biscotto_uscito() -> String {
    format!(
        "fitz=1; Path=/; Max-Age={}; Secure; HttpOnly; SameSite=Lax",
        accesso::DURATA
    )
}

fn biscotti_entrato() -> Vec<String> {
    vec![
        "fitm=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Lax".into(),
        "fitz=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Lax".into(),
    ]
}

#[derive(Clone)]
struct Indirizzi {
    autorizza: String,
    gettone: String,
    /// end_session_endpoint, empty when the provider has none
    fine: String,
}

static SCOPERTA: Mutex<Option<(Instant, Indirizzi)>> = Mutex::new(None);

/// The provider's endpoints from its discovery document, kept for an hour.
fn indirizzi() -> Esito<Indirizzi> {
    if let Some((quando, i)) = SCOPERTA.lock().unwrap_or_else(|e| e.into_inner()).as_ref()
        && quando.elapsed() < Duration::from_secs(3600)
    {
        return Ok(i.clone());
    }
    let issuer = &conf().oidc_issuer;
    let url = format!(
        "{}/.well-known/openid-configuration",
        issuer.trim_end_matches('/')
    );
    let doc = crate::ai_http::prendi(&url, &[], 10.0).map_err(|e| {
        tracing::error!("EverID: discovery {url} non riuscita ({e:?})");
        Problema::new(502, NON_RISPONDE)
    })?;
    let campo = |k: &str| doc.get(k).and_then(Value::as_str).unwrap_or("").to_string();
    if !stesso_issuer(&campo("issuer"), issuer) {
        tracing::error!("EverID: issuer {:?} diverso da {issuer:?}", campo("issuer"));
        return Err(Problema::new(502, CONFIGURATO_MALE));
    }
    let i = Indirizzi {
        autorizza: campo("authorization_endpoint"),
        gettone: campo("token_endpoint"),
        fine: campo("end_session_endpoint"),
    };
    if i.autorizza.is_empty() || i.gettone.is_empty() {
        return Err(Problema::new(502, CONFIGURATO_MALE));
    }
    *SCOPERTA.lock().unwrap_or_else(|e| e.into_inner()) = Some((Instant::now(), i.clone()));
    Ok(i)
}

fn casuale() -> String {
    URL_SAFE_NO_PAD.encode(accesso::casuali::<32>())
}

fn sfida(verificatore: &str) -> String {
    URL_SAFE_NO_PAD.encode(Sha256::digest(verificatore.as_bytes()))
}

/// state, PKCE verifier, nonce, silent or not and the `apk` query travel in a signed cookie that lives only for the
/// trip.
struct Viaggio {
    stato: String,
    verificatore: String,
    nonce: String,
    muto: bool,
    apk: Option<String>,
    destinazione: String,
}

fn firma_viaggio(segreto: &str, corpo: &str) -> String {
    accesso::firma(segreto, &format!("oidc:{corpo}"))
}

fn biscotto_viaggio(segreto: &str, v: &Viaggio, ora: f64) -> String {
    let corpo = format!(
        "{}.{}.{}.{}.{}{}.{}",
        v.stato,
        v.verificatore,
        v.nonce,
        py::int(ora),
        if v.muto { "m" } else { "n" },
        v.apk.as_deref().unwrap_or(""),
        URL_SAFE_NO_PAD.encode(v.destinazione.as_bytes())
    );
    format!(
        "{COOKIE}={corpo}.{}; Path=/oidc/; Max-Age={}; Secure; HttpOnly; SameSite=Lax",
        firma_viaggio(segreto, &corpo),
        VIAGGIO as i64
    )
}

fn leggi_viaggio(segreto: &str, valore: &str, ora: f64) -> Option<Viaggio> {
    let (corpo, firma) = valore.rsplit_once('.')?;
    if !accesso::uguali(firma, &firma_viaggio(segreto, corpo)) {
        return None;
    }
    let parti: Vec<&str> = corpo.split('.').collect();
    let [stato, verificatore, nonce, quando, modo, destinazione] = parti.as_slice() else {
        return None;
    };
    let quando: f64 = quando.parse().ok()?;
    if !(0.0..=VIAGGIO).contains(&(ora - quando)) {
        return None;
    }
    let muto = match modo.chars().next() {
        Some('m') => true,
        Some('n') => false,
        _ => return None,
    };
    Some(Viaggio {
        stato: stato.to_string(),
        verificatore: verificatore.to_string(),
        nonce: nonce.to_string(),
        muto,
        apk: apk(&format!("apk={}", &modo[1..])),
        destinazione: destinazione_sicura(
            &String::from_utf8(URL_SAFE_NO_PAD.decode(destinazione).ok()?).ok()?,
        ),
    })
}

const VIAGGIO_FINITO: &str = "fito=; Path=/oidc/; Max-Age=0; Secure; HttpOnly; SameSite=Lax";

fn autorizza(
    c: &Ctx,
    muto: bool,
    apk: Option<String>,
    destinazione: String,
    richiedi_login: bool,
) -> Esito<Risposta> {
    let i = indirizzi()?;
    let v = Viaggio {
        stato: casuale(),
        verificatore: casuale(),
        nonce: casuale(),
        muto,
        apk,
        destinazione,
    };
    let mut url =
        url::Url::parse(&i.autorizza).map_err(|_| Problema::new(502, CONFIGURATO_MALE))?;
    url.query_pairs_mut()
        .append_pair("response_type", "code")
        .append_pair("client_id", &conf().oidc_client_id)
        .append_pair("redirect_uri", &ritorno())
        .append_pair("scope", SCOPE)
        .append_pair("state", &v.stato)
        .append_pair("nonce", &v.nonce)
        .append_pair("code_challenge", &sfida(&v.verificatore))
        .append_pair("code_challenge_method", "S256");
    if muto {
        url.query_pairs_mut().append_pair("prompt", "none");
    } else if richiedi_login {
        url.query_pairs_mut().append_pair("prompt", "login");
    }
    Ok(Risposta::testo(302, b"")
        .con("Location", String::from(url))
        .con(
            "Set-Cookie",
            biscotto_viaggio(&c.app.dati.segreto, &v, py::ora()),
        ))
}

/// GET /oidc/login: the normal authorization page ("altre opzioni di accesso").
pub fn entra(c: &Ctx) -> Esito<Risposta> {
    let a = apk(&c.req.query);
    let destinazione = con_apk("/", a.as_deref());
    let uscito = !accesso::leggi_cookie(c.req.intestazione("Cookie"), "fitz").is_empty();
    autorizza(c, false, a, destinazione, uscito)
}

/// A browser opening the app without a session: the silent attempt, unless it was just tried or the person logged out
/// here. None means "show the form".
pub fn prova_muta(c: &Ctx) -> Option<Risposta> {
    if !attivo() || c.req.metodo != "GET" {
        return None;
    }
    if !c
        .req
        .intestazione("Accept")
        .unwrap_or("")
        .contains("text/html")
    {
        return None;
    }
    let biscotti = c.req.intestazione("Cookie");
    let uscito = !accesso::leggi_cookie(biscotti, "fitz").is_empty();
    let a = apk(&c.req.query);
    let destinazione = if c.req.path == "/accedi" {
        con_apk("/", a.as_deref())
    } else {
        destinazione_sicura(&format!(
            "{}{}{}",
            c.req.path,
            if c.req.query.is_empty() { "" } else { "?" },
            c.req.query
        ))
    };
    Some(
        autorizza(c, !uscito, a, destinazione, uscito)
            .unwrap_or_else(|e| Risposta::html(e.codice, accesso::pagina_con(&e.testo, None))),
    )
}

/// Who the service says this is.
#[derive(Debug, PartialEq)]
pub struct Persona {
    /// the account key: stable, unlike the e-mail, which the service does not verify
    pub sub: String,
    pub email: String,
    pub nome: String,
    pub utente: String,
    pub gruppi: Vec<String>,
}

/// The ID token is received over TLS from the token endpoint, authenticated with the client secret: OpenID Connect
/// Core 3.1.3.7 lets TLS stand in for the signature. Issuer, audience, expiry and nonce are still checked.
fn leggi_id_token(
    token: &str,
    nonce: &str,
    ora: f64,
    issuer: &str,
    id: &str,
) -> Result<Persona, &'static str> {
    let corpo = token.split('.').nth(1).ok_or("id_token malformato")?;
    let byte = URL_SAFE_NO_PAD
        .decode(corpo.trim_end_matches('='))
        .map_err(|_| "id_token malformato")?;
    let c: Value = serde_json::from_slice(&byte).map_err(|_| "id_token malformato")?;
    let testo = |k: &str| {
        c.get(k)
            .and_then(Value::as_str)
            .unwrap_or("")
            .trim()
            .to_string()
    };
    if !stesso_issuer(&testo("iss"), issuer) {
        return Err("issuer sbagliato");
    }
    let pubblico = match c.get("aud") {
        Some(Value::String(a)) => a == id,
        Some(Value::Array(a)) => a.iter().any(|x| x.as_str() == Some(id)),
        _ => false,
    };
    if !pubblico || c.get("azp").is_some_and(|a| a.as_str() != Some(id)) {
        return Err("audience sbagliata");
    }
    if c.get("exp").and_then(Value::as_f64).is_none_or(|e| e < ora) {
        return Err("id_token scaduto");
    }
    if !accesso::uguali(&testo("nonce"), nonce) {
        return Err("nonce sbagliato");
    }
    let sub = testo("sub");
    if sub.is_empty() {
        return Err("manca il sub");
    }
    let email = testo("email").to_lowercase();
    if !email.contains('@') {
        return Err("manca l'e-mail");
    }
    let gruppi = c
        .get("groups")
        .and_then(Value::as_array)
        .map(|g| {
            g.iter()
                .filter_map(|x| x.as_str().map(String::from))
                .collect()
        })
        .unwrap_or_default();
    Ok(Persona {
        sub,
        email,
        nome: testo("name"),
        utente: testo("preferred_username"),
        gruppi,
    })
}

fn scambia(i: &Indirizzi, codice: &str, verificatore: &str) -> Esito<String> {
    let conf = conf();
    let corpo = [
        ("grant_type", "authorization_code"),
        ("code", codice),
        ("redirect_uri", &ritorno()),
        ("code_verifier", verificatore),
        ("client_id", &conf.oidc_client_id),
        ("client_secret", &conf.oidc_segreto),
    ]
    .iter()
    .map(|(k, v)| format!("{k}={}", accesso::quote(v)))
    .collect::<Vec<_>>()
    .join("&");
    let guasto = || Problema::new(502, NON_RISPONDE);
    let r = crate::ai_http::client()
        .post(&i.gettone)
        .timeout(Duration::from_secs(15))
        .header("content-type", "application/x-www-form-urlencoded")
        .header("accept", "application/json")
        .body(corpo)
        .send()
        .map_err(|e| {
            tracing::error!("EverID: token endpoint non raggiunto ({e})");
            guasto()
        })?;
    let stato = r.status();
    let testo = r.text().map_err(|_| guasto())?;
    if !stato.is_success() {
        tracing::warn!(
            "EverID: token endpoint {stato}: {}",
            py::taglia(&testo, 300)
        );
        return Err(Problema::new(401, NON_RIUSCITO));
    }
    serde_json::from_str::<Value>(&testo)
        .ok()
        .and_then(|v| v.get("id_token").and_then(Value::as_str).map(String::from))
        .ok_or_else(guasto)
}

fn pagina(codice: u16, testo: &str, muto: bool, apk: Option<&str>) -> Risposta {
    let r =
        Risposta::html(codice, accesso::pagina_con(testo, apk)).con("Set-Cookie", VIAGGIO_FINITO);
    // after a silent attempt the next opening shows the form, not the same refusal
    if muto {
        r.con("Set-Cookie", biscotto_provato())
    } else {
        r
    }
}

/// Opens a session for this person: the admin account for the owner, otherwise their own, created the first time.
fn apri(c: &mut Ctx, p: &Persona, id_token: Option<&str>) -> Esito<Vec<String>> {
    let conf = conf();
    // the owner's e-mail alone is not enough: anyone could type it in their profile on the service
    let capo = !conf.email_capo.is_empty()
        && p.email == conf.email_capo
        && p.gruppi.iter().any(|g| g == ADMIN);
    let utente = c.app.dati.da_everid(p, capo)?;
    let gettone = c.app.dati.apri_sessione(utente.id, "cookie", None, None)?;
    if let Some(t) = id_token {
        c.app.dati.segna_id_token(&gettone, t)?;
    }
    let mut b = accesso::biscotti(&gettone, &utente.nome);
    b.extend(biscotti_entrato());
    c.io = Some(utente);
    Ok(b)
}

fn ha_gruppo(p: &Persona) -> bool {
    p.gruppi.iter().any(|g| g == &conf().oidc_gruppo)
}

/// GET /oidc/callback: back from the service with a code, or with an error after a silent attempt.
pub fn torna(c: &mut Ctx) -> Esito<Risposta> {
    let q = py::parse_qs(&c.req.query);
    let campo = |k: &str| q.get(k).cloned().unwrap_or_default();
    let ora = py::ora();
    let valore = accesso::leggi_cookie(c.req.intestazione("Cookie"), COOKIE);
    let v = leggi_viaggio(&c.app.dati.segreto, &valore, ora);
    let muto = v.as_ref().is_some_and(|v| v.muto);
    let apk = v.as_ref().and_then(|v| v.apk.clone());
    let apk = apk.as_deref();
    let Some(v) = v else {
        return Ok(pagina(400, "Accesso scaduto: riprova.", false, None));
    };
    if !accesso::uguali(&campo("state"), &v.stato) {
        return Ok(pagina(400, "Accesso scaduto: riprova.", muto, apk));
    }
    if !campo("error").is_empty() {
        tracing::info!(
            "EverID: ritorno con errore {:?} (muto {muto})",
            campo("error")
        );
        // login_required after prompt=none: nobody signed in to the service, the app's own form
        if muto
            && matches!(
                campo("error").as_str(),
                "login_required" | "interaction_required"
            )
        {
            let uscito = !accesso::leggi_cookie(c.req.intestazione("Cookie"), "fitz").is_empty();
            return autorizza(c, false, v.apk.clone(), v.destinazione.clone(), uscito);
        }
        return Ok(pagina(401, "Accesso annullato.", false, apk));
    }
    if campo("code").is_empty() {
        return Ok(pagina(400, "Accesso scaduto: riprova.", muto, apk));
    }
    let i = match indirizzi() {
        Ok(i) => i,
        Err(e) => return Ok(pagina(e.codice, &e.testo, muto, apk)),
    };
    let id_token = match scambia(&i, &campo("code"), &v.verificatore) {
        Ok(t) => t,
        Err(e) => return Ok(pagina(e.codice, &e.testo, muto, apk)),
    };
    let p = match leggi_id_token(
        &id_token,
        &v.nonce,
        ora,
        &conf().oidc_issuer,
        &conf().oidc_client_id,
    ) {
        Ok(p) => p,
        Err(perche) => {
            tracing::warn!("EverID: id_token rifiutato ({perche})");
            return Ok(pagina(401, NON_RIUSCITO, muto, apk));
        }
    };
    if !ha_gruppo(&p) {
        tracing::info!("EverID: {} senza il gruppo {}", p.email, conf().oidc_gruppo);
        return Ok(pagina(403, SENZA_ACCESSO, muto, apk));
    }
    let b = match apri(c, &p, Some(&id_token)) {
        Ok(b) => b,
        Err(e) if !e.database => return Ok(pagina(e.codice, &e.testo, muto, apk)),
        Err(e) => return Err(e),
    };
    Ok(Risposta::testo(303, b"")
        .con("Location", v.destinazione)
        .con("Set-Cookie", VIAGGIO_FINITO)
        .biscotti(b))
}

// ---------- disabled form implementation: no HTTP route calls this code ----------

/// The outcome of the form: the cookies of the new session, or the status and sentence to show.
#[allow(dead_code)]
pub enum Modulo {
    Dentro(Vec<String>),
    Rifiuto(u16, String),
}

static FALLITI: LazyLock<Mutex<HashMap<String, VecDeque<f64>>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));

fn falliti() -> std::sync::MutexGuard<'static, HashMap<String, VecDeque<f64>>> {
    let mut m = FALLITI.lock().unwrap_or_else(|e| e.into_inner());
    let ora = py::ora();
    m.retain(|_, v| {
        while v.front().is_some_and(|t| ora - t > FINESTRA) {
            v.pop_front();
        }
        !v.is_empty()
    });
    m
}

fn bloccato(ip: &str, ora: f64) -> bool {
    falliti()
        .get(ip)
        .is_some_and(|v| v.iter().filter(|t| ora - **t <= FINESTRA).count() >= TENTATIVI)
}

fn fallito(ip: &str, ora: f64) {
    falliti().entry(ip.to_string()).or_default().push_back(ora);
}

/// POST /accedi with username (or e-mail) and password: checked on the service, never stored or logged.
#[allow(dead_code)]
pub fn modulo(c: &mut Ctx, utente: &str, password: &str) -> Esito<Modulo> {
    // Caddy sets X-Real-IP from the connection and drops what the client sent
    let ip = c
        .req
        .intestazione("X-Real-IP")
        .unwrap_or("")
        .trim()
        .to_string();
    let ora = py::ora();
    if bloccato(&ip, ora) {
        tracing::warn!("EverID: modulo bloccato per {ip:?}");
        return Ok(Modulo::Rifiuto(429, TROPPI.into()));
    }
    let utente = utente.trim();
    if utente.is_empty() || password.is_empty() || utente.chars().count() > 150 {
        return Ok(Modulo::Rifiuto(401, SBAGLIATI.into()));
    }
    let p = match esamina(utente, password) {
        Esame::Valido(p) => p,
        Esame::NonValido => {
            fallito(&ip, ora);
            return Ok(Modulo::Rifiuto(401, SBAGLIATI.into()));
        }
        Esame::Guasto => return Ok(Modulo::Rifiuto(502, NON_RISPONDE.into())),
    };
    if !ha_gruppo(&p) {
        tracing::info!("EverID: modulo, {} senza il gruppo", p.email);
        return Ok(Modulo::Rifiuto(403, SENZA_ACCESSO.into()));
    }
    match apri(c, &p, None) {
        Ok(b) => Ok(Modulo::Dentro(b)),
        Err(e) if !e.database => Ok(Modulo::Rifiuto(e.codice, e.testo)),
        Err(e) => Err(e),
    }
}

enum Esame {
    Valido(Persona),
    NonValido,
    Guasto,
}

/// The cookies of one conversation with the service's flow executor (session and CSRF token).
#[derive(Default)]
struct Barattolo(Vec<(String, String)>);

impl Barattolo {
    fn prendi(&mut self, h: &reqwest::header::HeaderMap) {
        for v in h.get_all(reqwest::header::SET_COOKIE) {
            let Ok(s) = v.to_str() else { continue };
            let Some((k, val)) = s.split(';').next().and_then(|p| p.split_once('=')) else {
                continue;
            };
            let (k, val) = (k.trim(), val.trim());
            self.0.retain(|(n, _)| n != k);
            if !val.is_empty() && !s.to_ascii_lowercase().contains("max-age=0") {
                self.0.push((k.to_string(), val.to_string()));
            }
        }
    }

    fn valore(&self, k: &str) -> &str {
        self.0
            .iter()
            .find(|(n, _)| n == k)
            .map_or("", |(_, v)| v.as_str())
    }

    fn intestazione(&self) -> String {
        self.0
            .iter()
            .map(|(k, v)| format!("{k}={v}"))
            .collect::<Vec<_>>()
            .join("; ")
    }
}

fn chiama(b: &mut Barattolo, url: &str, corpo: Option<&Value>) -> Result<(u16, Value), ()> {
    let client = crate::ai_http::client();
    let mut r = match corpo {
        Some(v) => client
            .post(url)
            .header("content-type", "application/json")
            .body(v.to_string()),
        None => client.get(url),
    }
    .timeout(Duration::from_secs(15))
    .header("accept", "application/json");
    if !b.0.is_empty() {
        r = r
            .header("x-authentik-csrf", b.valore("authentik_csrf"))
            .header("cookie", b.intestazione());
    }
    let risposta = r.send().map_err(|e| {
        tracing::error!("EverID: flow executor non raggiunto ({e})");
    })?;
    b.prendi(risposta.headers());
    let stato = risposta.status().as_u16();
    let testo = risposta.text().map_err(|_| ())?;
    Ok((stato, serde_json::from_str(&testo).unwrap_or(Value::Null)))
}

/// The service's real login flow with these credentials: identification, then password. Any other step (second
/// factor, denial) or a step asked twice means "not valid" for the form; the person can still use the other options.
fn esamina(utente: &str, password: &str) -> Esame {
    let Ok(u) = url::Url::parse(&conf().oidc_issuer) else {
        return Esame::Guasto;
    };
    let base = u.origin().ascii_serialization();
    let flusso = format!("{base}/api/v3/flows/executor/{FLUSSO}/?query=");
    let mut b = Barattolo::default();
    let Ok((_, mut r)) = chiama(&mut b, &flusso, None) else {
        return Esame::Guasto;
    };
    let mut mandati: Vec<String> = Vec::new();
    loop {
        let comp = r
            .get("component")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        let corpo = match comp.as_str() {
            "xak-flow-redirect" => break,
            "ak-stage-identification" => {
                json!({"component": comp, "uid_field": utente, "password": password})
            }
            "ak-stage-password" => json!({"component": comp, "password": password}),
            "" => return Esame::Guasto,
            altro => {
                tracing::info!("EverID: modulo, passo {altro:?} non gestito");
                return Esame::NonValido;
            }
        };
        if mandati.contains(&comp) {
            return Esame::NonValido;
        }
        mandati.push(comp);
        r = match chiama(&mut b, &flusso, Some(&corpo)) {
            Ok((_, v)) => v,
            Err(()) => return Esame::Guasto,
        };
    }
    let me = match chiama(&mut b, &format!("{base}/api/v3/core/users/me/"), None) {
        Ok((200, v)) => v,
        _ => return Esame::Guasto,
    };
    // the session the check opened on the service is not needed: closed at once
    let _ = chiama(
        &mut b,
        &format!("{base}/api/v3/flows/executor/{FLUSSO_USCITA}/?query="),
        None,
    );
    persona_da_me(&me).map_or(Esame::NonValido, Esame::Valido)
}

fn persona_da_me(me: &Value) -> Option<Persona> {
    let u = me.get("user")?;
    let testo = |k: &str| {
        u.get(k)
            .and_then(Value::as_str)
            .unwrap_or("")
            .trim()
            .to_string()
    };
    if u.get("is_active").and_then(Value::as_bool) != Some(true) {
        return None;
    }
    let sub = testo("uid");
    let email = testo("email").to_lowercase();
    if sub.is_empty() || !email.contains('@') {
        return None;
    }
    let gruppi = u
        .get("groups")
        .and_then(Value::as_array)
        .map(|g| {
            g.iter()
                .filter_map(|x| x.get("name").and_then(Value::as_str).map(String::from))
                .collect()
        })
        .unwrap_or_default();
    Some(Persona {
        sub,
        email,
        nome: testo("name"),
        utente: testo("username"),
        gruppi,
    })
}

/// Logout of a session that came from the authorization page: where to send the browser so the provider session ends
/// too, and comes back to the app. None for every other session, and when the service cannot be reached (the app
/// logout still happens).
pub fn uscita(c: &Ctx) -> Esito<Option<String>> {
    if !attivo() {
        return Ok(None);
    }
    let Some(id_token) = c.app.dati.togli_id_token(&c.gettone)? else {
        return Ok(None);
    };
    let Ok(i) = indirizzi() else { return Ok(None) };
    let Ok(mut url) = url::Url::parse(&i.fine) else {
        return Ok(None);
    };
    url.query_pairs_mut()
        .append_pair("id_token_hint", &id_token)
        .append_pair(
            "post_logout_redirect_uri",
            &format!("{}/", conf().chi_siamo.trim_end_matches('/')),
        );
    Ok(Some(url.into()))
}

#[cfg(test)]
mod test {
    use super::*;

    #[test]
    fn viaggio_firmato_e_breve() {
        let v = Viaggio {
            stato: "s".repeat(43),
            verificatore: "v".repeat(43),
            nonce: "n".repeat(43),
            muto: true,
            apk: Some("23".into()),
            destinazione: "/?apk=23".into(),
        };
        let b = biscotto_viaggio("segreto", &v, 1000.0);
        let valore = b
            .strip_prefix("fito=")
            .and_then(|b| b.split(';').next())
            .unwrap_or("");
        let letto = leggi_viaggio("segreto", valore, 1100.0);
        assert!(letto.is_some_and(|l| l.stato == v.stato
            && l.nonce == v.nonce
            && l.muto
            && l.apk.as_deref() == Some("23")));
        assert!(leggi_viaggio("altro", valore, 1100.0).is_none());
        assert!(leggi_viaggio("segreto", valore, 1000.0 + VIAGGIO + 1.0).is_none());
        let rotto = valore.replacen('s', "t", 1);
        assert!(leggi_viaggio("segreto", &rotto, 1100.0).is_none());
        let n = Viaggio {
            muto: false,
            apk: None,
            ..v
        };
        let b = biscotto_viaggio("segreto", &n, 1000.0);
        let valore = b
            .strip_prefix("fito=")
            .and_then(|b| b.split(';').next())
            .unwrap_or("");
        assert!(
            leggi_viaggio("segreto", valore, 1001.0).is_some_and(|l| !l.muto && l.apk.is_none())
        );
    }

    #[test]
    fn apk_solo_cifre() {
        assert_eq!(apk("apk=23"), Some("23".into()));
        assert_eq!(apk("x=1&apk=7"), Some("7".into()));
        assert_eq!(apk("apk=2a"), None);
        assert_eq!(apk("apk=1234567890"), None);
        assert_eq!(apk(""), None);
        assert_eq!(con_apk("/accedi", Some("23")), "/accedi?apk=23");
        assert_eq!(con_apk("/", None), "/");
    }

    #[test]
    fn destinazione_solo_interna() {
        assert_eq!(
            destinazione_sicura("/index.html?apk=23"),
            "/index.html?apk=23"
        );
        for valore in [
            "https://elsewhere.invalid",
            "//elsewhere.invalid",
            "/%2felsewhere.invalid",
            "/%5celsewhere.invalid",
            "/\\elsewhere.invalid",
            "/\r\nLocation: x",
        ] {
            assert_eq!(destinazione_sicura(valore), "/");
        }
    }

    #[test]
    fn cinque_errori_per_indirizzo() {
        let ora = py::ora();
        for _ in 0..TENTATIVI - 1 {
            fallito("test-a", ora);
        }
        assert!(!bloccato("test-a", ora));
        fallito("test-a", ora);
        assert!(bloccato("test-a", ora));
        assert!(!bloccato("test-b", ora));
        assert!(!bloccato("test-a", ora + FINESTRA + 1.0));
    }

    #[test]
    fn barattolo_tiene_e_toglie() {
        let mut h = reqwest::header::HeaderMap::new();
        for v in [
            "authentik_csrf=abc; Path=/; SameSite=Lax",
            "authentik_session=s1; HttpOnly",
        ] {
            h.append(
                reqwest::header::SET_COOKIE,
                reqwest::header::HeaderValue::from_static(v),
            );
        }
        let mut b = Barattolo::default();
        b.prendi(&h);
        assert_eq!(b.valore("authentik_csrf"), "abc");
        assert_eq!(b.intestazione(), "authentik_csrf=abc; authentik_session=s1");
        let mut h = reqwest::header::HeaderMap::new();
        h.append(
            reqwest::header::SET_COOKIE,
            reqwest::header::HeaderValue::from_static("authentik_session=; Max-Age=0"),
        );
        b.prendi(&h);
        assert_eq!(b.intestazione(), "authentik_csrf=abc");
    }

    #[test]
    fn persona_dal_profilo() {
        let me = json!({"user": {"uid": "u1", "email": "ANNA@EXAMPLE.IT", "name": "Anna", "username": "anna",
            "is_active": true, "groups": [{"name": "app-fit"}, {"name": "altro"}]}});
        assert_eq!(
            persona_da_me(&me),
            Some(Persona {
                sub: "u1".into(),
                email: "anna@example.it".into(),
                nome: "Anna".into(),
                utente: "anna".into(),
                gruppi: vec!["app-fit".into(), "altro".into()],
            })
        );
        let mut spento = me.clone();
        spento["user"]["is_active"] = false.into();
        assert_eq!(persona_da_me(&spento), None);
        let mut senza = me.clone();
        senza["user"]["uid"] = "".into();
        assert_eq!(persona_da_me(&senza), None);
        assert_eq!(persona_da_me(&json!({})), None);
    }

    #[test]
    fn id_token_controllato() {
        let iss = "https://id.example/application/o/everfit/";
        let token = |c: Value| {
            format!(
                "e30.{}.firma",
                URL_SAFE_NO_PAD.encode(serde_json::to_vec(&c).unwrap_or_default())
            )
        };
        let buono = serde_json::json!({
            "iss": iss, "aud": "fit", "exp": 2000, "nonce": "n1", "sub": "abc123",
            "email": "Anna@Example.it", "name": "Anna", "preferred_username": "anna",
            "groups": ["app-fit", "altro"]
        });
        let p = leggi_id_token(
            &token(buono.clone()),
            "n1",
            1000.0,
            iss.trim_end_matches('/'),
            "fit",
        );
        assert_eq!(
            p,
            Ok(Persona {
                sub: "abc123".into(),
                email: "anna@example.it".into(),
                nome: "Anna".into(),
                utente: "anna".into(),
                gruppi: vec!["app-fit".into(), "altro".into()],
            })
        );
        let rifiuta = |k: &str, v: Value, perche: &str| {
            let mut c = buono.clone();
            c[k] = v;
            assert_eq!(
                leggi_id_token(&token(c), "n1", 1000.0, iss, "fit").err(),
                Some(perche),
                "{k}"
            );
        };
        rifiuta("iss", "https://altro/".into(), "issuer sbagliato");
        rifiuta("aud", "altro".into(), "audience sbagliata");
        rifiuta("azp", "altro".into(), "audience sbagliata");
        rifiuta("exp", 999.into(), "id_token scaduto");
        rifiuta("nonce", "n2".into(), "nonce sbagliato");
        rifiuta("sub", "".into(), "manca il sub");
        rifiuta("email", "".into(), "manca l'e-mail");
        assert!(leggi_id_token("rotto", "n1", 1000.0, iss, "fit").is_err());
    }

    #[test]
    fn sfida_pkce_rfc7636() {
        // RFC 7636 appendix B
        assert_eq!(
            sfida("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"),
            "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
        );
    }
}
