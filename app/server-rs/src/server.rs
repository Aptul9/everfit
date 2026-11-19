//! The request handler (server.py class `Fit`): who is asking, the login page, static files and the dispatch to the
//! API. Everything here is synchronous and runs on the blocking pool, never on the async workers.

use crate::accesso;
use crate::conf::conf;
use crate::db::{Dati, Utente};
use crate::errore::{Esito, Problema};
use crate::ponte::Ponte;
use crate::py::{self, get};
use crate::statico;
use serde_json::{Value, json};
use std::collections::HashMap;
use std::path::PathBuf;

pub const MAX_CORPO: usize = 2 * 1024 * 1024;
/// health checks and the scale watcher's waits arrive all the time: they would only be noise in the log
const ZITTI: [&str; 3] = ["/api/health", "/api/bilancia/lavoro", "/api/state/versione"];

pub struct App {
    pub root: PathBuf,
    pub dati: Dati,
    pub ponte: Ponte,
}

pub struct Richiesta {
    pub metodo: String,
    pub path: String,
    pub query: String,
    /// lowercase name -> values, decoded as ISO-8859-1 like http.server does
    pub intestazioni: HashMap<String, Vec<String>>,
    /// the body, always read; None when it was too large or its length invalid
    pub grezzo: Option<Vec<u8>>,
}

impl Richiesta {
    /// `self.headers.get(nome)`: the first value, case-insensitive
    pub fn intestazione(&self, nome: &str) -> Option<&str> {
        self.intestazioni
            .get(&nome.to_ascii_lowercase())
            .and_then(|v| v.first())
            .map(String::as_str)
    }
}

pub struct Risposta {
    pub codice: u16,
    pub corpo: Vec<u8>,
    pub tipo: String,
    pub cache: &'static str,
    pub extra: Vec<(&'static str, String)>,
    /// close the connection after answering (body too large to read)
    pub chiudi: bool,
}

impl Risposta {
    pub fn new(codice: u16, corpo: Vec<u8>, tipo: &str) -> Self {
        Risposta {
            codice,
            corpo,
            tipo: tipo.into(),
            cache: "no-store",
            extra: vec![],
            chiudi: false,
        }
    }

    pub fn testo(codice: u16, corpo: &[u8]) -> Self {
        Self::new(codice, corpo.to_vec(), "text/plain; charset=utf-8")
    }

    pub fn json(codice: u16, v: &Value) -> Self {
        Self::new(
            codice,
            crate::pyjson::compatto(v).into_bytes(),
            "application/json; charset=utf-8",
        )
    }

    pub fn html(codice: u16, corpo: Vec<u8>) -> Self {
        Self::new(codice, corpo, "text/html; charset=utf-8")
    }

    pub fn con(mut self, nome: &'static str, valore: impl Into<String>) -> Self {
        self.extra.push((nome, valore.into()));
        self
    }

    pub fn biscotti(mut self, b: Vec<String>) -> Self {
        self.extra.extend(b.into_iter().map(|v| ("Set-Cookie", v)));
        self
    }
}

/// How the person got in: locale (no login configured), porta (secret path), vecchio (old shared cookie), cookie
#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Via {
    Locale,
    Porta,
    Vecchio,
    Cookie,
}

pub struct Ctx<'a> {
    pub app: &'a App,
    pub req: &'a Richiesta,
    pub io: Option<Utente>,
    pub gettone: String,
    pub via: Option<Via>,
}

impl Ctx<'_> {
    /// The request body as JSON object: (text, value).
    pub fn corpo(&self) -> Esito<(String, Value)> {
        let Some(grezzo) = &self.req.grezzo else {
            return Err(Problema::new(413, "dimensione non valida"));
        };
        if grezzo.is_empty() {
            return Err(Problema::new(400, "manca il corpo della richiesta"));
        }
        let testo =
            std::str::from_utf8(grezzo).map_err(|_| Problema::new(400, "serve JSON valido"))?;
        let v: Value = serde_json::from_str(testo.trim_start_matches('\u{feff}'))
            .map_err(|_| Problema::new(400, "serve JSON valido"))?;
        if !v.is_object() {
            return Err(Problema::new(400, "serve un oggetto JSON"));
        }
        Ok((testo.to_string(), v))
    }

    pub fn utente(&self) -> &Utente {
        // only called after `riconosci` found someone: the dispatch checks it first
        self.io.as_ref().unwrap_or(&NESSUNO)
    }

    /// Renews the cookies of whoever is in, so the expiry restarts at every opening of the app.
    pub fn biscotti(&self) -> Vec<String> {
        match (self.via, &self.io) {
            (Some(Via::Cookie | Via::Vecchio), Some(u)) => {
                accesso::biscotti(&self.gettone, &u.nome)
            }
            _ => vec![],
        }
    }

    fn riconosci(&mut self) -> Esito<()> {
        let capo = |d: &Dati| d.utente(accesso::CAPO);
        if !accesso::acceso() {
            (self.io, self.via) = (capo(&self.app.dati)?, Some(Via::Locale));
        } else if self.req.intestazione("X-Fit-Accesso") == Some("ok") {
            (self.io, self.via) = (capo(&self.app.dati)?, Some(Via::Porta));
        } else {
            let valore = accesso::leggi_cookie(self.req.intestazione("Cookie"), "fitk");
            let vecchio = &conf().cookie_vecchio;
            if !valore.is_empty() && !vecchio.is_empty() && accesso::uguali(&valore, vecchio) {
                (self.io, self.via) = (capo(&self.app.dati)?, Some(Via::Vecchio));
            } else {
                self.io = self.app.dati.sessione(&valore, "cookie")?;
                self.via = Some(Via::Cookie);
            }
            self.gettone = valore;
        }
        Ok(())
    }
}

static NESSUNO: Utente = Utente {
    id: 0,
    nome: String::new(),
    capo: 0,
    utente: None,
};

/// The login page and its form. It also answers whoever is already in and wants to switch account.
fn accedi(c: &mut Ctx) -> Esito<Risposta> {
    c.riconosci()?;
    if c.req.metodo != "POST" {
        if c.io.is_some() {
            return Ok(Risposta::testo(303, b"").con("Location", "./"));
        }
        return Ok(Risposta::html(200, accesso::pagina("")));
    }
    let modulo = match &c.req.grezzo {
        Some(g) if !g.is_empty() && g.len() <= 2000 => py::parse_qs(&String::from_utf8_lossy(g)),
        _ => HashMap::new(),
    };
    let campo = |n: &str| modulo.get(n).cloned().unwrap_or_default();
    let k = campo("k");
    let macchina = !k.is_empty() || c.req.intestazione("Accept").unwrap_or("").contains("json"); // a script, not the form
    let rispondi = |codice: u16, testo: &str, biscotti: Vec<String>| {
        if macchina {
            let errore = if testo.is_empty() {
                Value::Null
            } else {
                Value::String(testo.into())
            };
            return Risposta::json(codice, &json!({"ok": codice < 300, "errore": errore}))
                .biscotti(biscotti);
        }
        if codice < 300 {
            return Risposta::testo(303, b"")
                .con("Location", "/")
                .biscotti(biscotti);
        }
        Risposta::html(codice, accesso::pagina(testo))
    };
    if !accesso::acceso() {
        return Ok(rispondi(200, "", vec![]));
    }
    if accesso::troppi_sbagli() {
        return Ok(rispondi(
            429,
            "Troppi tentativi sbagliati: riprova tra un'ora.",
            vec![],
        ));
    }
    let d = &c.app.dati;
    let password = {
        let p = campo("password");
        if p.is_empty() { campo("codice") } else { p }
    };
    let utente = if !k.is_empty() {
        d.sessione(&k, "casa")?
    } else {
        d.entra(&campo("utente"), &password)?
    };
    let Some(utente) = utente else {
        if k.is_empty() {
            // an expired Home icon key is not an attempt to guess the password
            accesso::segna_sbaglio();
            // the plan is ready but the account is not yet: whoever tries must know they did not mistype
            if let Some(u) = accesso::nome_utente(&campo("utente"))
                && d.attese()?
                    .iter()
                    .any(|a| get(a, "utente").as_str() == Some(u.as_str()))
            {
                let testo = format!(
                    "Questo account non è ancora attivo: lo deve attivare {} dall'app (Piano, poi Persone).",
                    conf().nome_capo
                );
                return Ok(rispondi(401, &testo, vec![]));
            }
        }
        return Ok(rispondi(401, "Nome utente o password sbagliati.", vec![]));
    };
    let da = (!k.is_empty()).then(|| accesso::impronta(&k));
    let gettone = d.apri_sessione(utente.id, "cookie", None, da)?;
    let b = accesso::biscotti(&gettone, &utente.nome);
    c.io = Some(utente);
    Ok(rispondi(200, "", b))
}

/// Steps from the iPhone shortcut, which has no app cookie: it uses the steps code, in "Authorization: Bearer" or as
/// "codice" in the JSON. None when there is no code (then the cookie counts, as always).
fn passi_dal_comando(c: &mut Ctx) -> Esito<Option<Risposta>> {
    let auth = c.req.intestazione("Authorization").unwrap_or("");
    let mut codice = if auth.to_lowercase().starts_with("bearer ") {
        auth.chars().skip(7).collect::<String>().trim().to_string()
    } else {
        String::new()
    };
    let grezzo = c
        .req
        .grezzo
        .as_deref()
        .filter(|g| !g.is_empty())
        .unwrap_or(b"{}");
    let dati: Option<Value> = std::str::from_utf8(grezzo)
        .ok()
        .and_then(|t| serde_json::from_str(t).ok());
    if codice.is_empty()
        && let Some(d) = dati.as_ref().filter(|d| d.is_object())
    {
        codice = py::testo_o(get(d, "codice")).trim().to_string();
    }
    if codice.is_empty() {
        return Ok(None);
    }
    let Some(u) = c.app.dati.utente_dei_passi(&codice)? else {
        return Ok(Some(Risposta::json(
            401,
            &json!({"errore": "codice dei passi sbagliato: rifallo dall'app, in Piano, Passi dall'iPhone"}),
        )));
    };
    c.io = Some(Utente {
        id: u,
        nome: String::new(),
        capo: 0,
        utente: None,
    }); // only for the log
    let Some(dati) = dati.filter(|d| d.is_object()) else {
        return Ok(Some(Risposta::json(
            400,
            &json!({"errore": "serve un oggetto JSON con i passi"}),
        )));
    };
    match c
        .app
        .dati
        .salva_passi(u, get(&dati, "passi"), get(&dati, "giorno"))
    {
        Ok(esito) => {
            crate::log!(
                "passi u{}: {} il {}",
                u,
                py::testo(get(&esito, "passi")),
                py::testo(get(&esito, "giorno"))
            );
            Ok(Some(Risposta::json(200, &esito)))
        }
        Err(e) if !e.database => {
            crate::log!("passi u{}: rifiutati ({})", u, e.testo);
            Ok(Some(Risposta::json(e.codice, &json!({"errore": e.testo}))))
        }
        Err(e) => Err(e),
    }
}

/// Whoever has not logged in only sees the page asking for the code.
fn fuori(c: &Ctx) -> Esito<Risposta> {
    let path = c.req.path.as_str();
    if path.starts_with("/api/") {
        return Ok(Risposta::json(
            401,
            &json!({"errore": "serve il codice di accesso"}),
        ));
    }
    // icon and name of the app serve the login page too; Android checks the asset links without any cookie
    let pubblico = path.starts_with("/icons/")
        || path == "/manifest.webmanifest"
        || path == "/.well-known/assetlinks.json";
    if (c.req.metodo == "GET" || c.req.metodo == "HEAD") && pubblico {
        return statico(c);
    }
    // 401, not 200: so the service worker does not take this page for the app and store it
    Ok(Risposta::html(401, accesso::pagina("")))
}

/// `start_url` with the Home icon key after "#k=", keeping any query string (the Android app adds "?apk=N").
fn start_url_con_chiave(start_url: &Value, chiave: &str) -> String {
    let base = start_url.as_str().unwrap_or("./");
    let base = base.split('#').next().unwrap_or("");
    let base = if base.is_empty() { "./" } else { base };
    format!("{base}#k={chiave}")
}

pub fn statico(c: &Ctx) -> Esito<Risposta> {
    let root = &c.app.root;
    let Some((rel, pieno)) = statico::trova(root, &c.req.path) else {
        return Ok(Risposta::testo(404, b"Non trovato"));
    };
    let io_err = |e: std::io::Error| Problema::new(404, e.to_string());
    let mut corpo = std::fs::read(&pieno).map_err(io_err)?;
    let meta = std::fs::metadata(&pieno).map_err(io_err)?;
    let mut etag = statico::etag(&meta);
    if rel == "sw.js" {
        // the service worker carries the app version: change a file, it changes, and the device updates by itself
        let (versione, file) = statico::guscio(root);
        let testo = String::from_utf8_lossy(&corpo)
            .replace("__VERSIONE__", &versione)
            .replace("'__FILE__'", &crate::pyjson::ascii(&json!(file)));
        corpo = testo.into_bytes();
        etag = format!("\"{versione}\"");
    } else if rel == "manifest.webmanifest"
        && matches!(c.via, Some(Via::Cookie | Via::Vecchio))
        && c.io.is_some()
    {
        // the iPhone Home icon does not see Safari's cookies: it starts with a key in the address (after the #)
        let mut manifest: Value =
            serde_json::from_slice(&corpo).map_err(|e| Problema::new(500, e.to_string()))?;
        let k = c.app.dati.chiave_casa(c.utente().id, &c.gettone)?;
        manifest["start_url"] =
            Value::String(start_url_con_chiave(get(&manifest, "start_url"), &k));
        return Ok(Risposta::new(
            200,
            crate::pyjson::largo(&manifest).into_bytes(),
            "application/manifest+json; charset=utf-8",
        ));
    }
    let immagine = rel.starts_with("img/") || rel.starts_with("icons/");
    let cache = if immagine {
        "public, max-age=604800"
    } else {
        "no-cache"
    };
    if c.req.intestazione("If-None-Match") == Some(etag.as_str()) {
        let mut r = Risposta::testo(304, b"").con("ETag", etag);
        r.cache = cache;
        return Ok(r);
    }
    let mut tipo = statico::tipo(&pieno).to_string();
    if tipo.starts_with("text/")
        || tipo == "application/json"
        || tipo == "application/manifest+json"
    {
        tipo.push_str("; charset=utf-8");
    }
    let mut r = Risposta::new(200, corpo, &tipo).con("ETag", etag);
    r.cache = cache;
    Ok(r)
}

fn errore_api(e: Problema) -> Risposta {
    if e.database {
        tracing::error!("errore database: {}", e.testo);
        return Risposta::json(500, &json!({"errore": "database non disponibile"}));
    }
    Risposta::json(e.codice, &json!({"errore": e.testo}))
}

fn dentro(c: &mut Ctx) -> Esito<Risposta> {
    let (metodo, path) = (c.req.metodo.clone(), c.req.path.clone());
    if path == "/api/health" {
        return Ok(Risposta::json(200, &json!({"ok": true})));
    }
    if path == "/accedi" {
        return accedi(c);
    }
    if path == "/api/passi"
        && metodo == "POST"
        && let Some(r) = passi_dal_comando(c)?
    {
        return Ok(r);
    }
    c.riconosci()?;
    if c.io.is_none() {
        return fuori(c);
    }
    if !path.starts_with("/api/") {
        if metodo == "GET" || metodo == "HEAD" {
            return statico(c);
        }
        return Ok(Risposta::json(
            405,
            &json!({"errore": "metodo non ammesso"}),
        ));
    }
    let m = if metodo == "HEAD" {
        "GET"
    } else {
        metodo.as_str()
    };
    Ok(crate::api::api(c, m, &path).unwrap_or_else(errore_api))
}

/// One request, start to end. Returns the answer and who asked (for the log).
pub fn gestisci(app: &App, req: &Richiesta) -> (Risposta, Option<i64>) {
    let mut c = Ctx {
        app,
        req,
        io: None,
        gettone: String::new(),
        via: None,
    };
    let mut r = dentro(&mut c).unwrap_or_else(errore_api);
    if req.grezzo.is_none() {
        r.chiudi = true; // too large to read: answer and close
    }
    let chi = c.io.as_ref().map(|u| u.id);
    (r, chi)
}

pub fn zitto(path: &str) -> bool {
    ZITTI.iter().any(|z| path.starts_with(z))
}
