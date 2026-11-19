//! Per-account AI keys and the order of the services (cibo.py motore_*, parere.py fila/stato/salva/togli).

use crate::conf::conf;
use crate::errore::{Esito, Problema};
use regex::Regex;
use serde_json::{Map, Value, json};
use std::path::{Path, PathBuf};
use std::sync::LazyLock;

/// in order of preference: (name, environment variable that counts as the admin's key)
pub const SERVIZI: [(&str, &str); 3] = [
    ("anthropic", "ANTHROPIC_API_KEY"),
    ("gemini", "GEMINI_API_KEY"),
    ("mistral", "MISTRAL_API_KEY"),
];
pub const MOTORI: [&str; 3] = ["anthropic", "gemini", "mistral"];

static RE_CHIAVE: LazyLock<Regex> = LazyLock::new(|| crate::py::re(r"^[A-Za-z0-9_\-.]{20,300}$"));

/// (name, key) of the service an account uses first; `riserve` are the others it has a key for, same order.
#[derive(Debug, Clone, PartialEq)]
pub struct Motore {
    pub nome: String,
    pub chiave: String,
    pub riserve: Vec<(String, String)>,
}

impl Motore {
    pub fn uno(nome: &str, chiave: &str) -> Motore {
        Motore {
            nome: nome.into(),
            chiave: chiave.into(),
            riserve: vec![],
        }
    }

    pub fn coppia(&self) -> (String, String) {
        (self.nome.clone(), self.chiave.clone())
    }
}

fn leggi(percorso: &Path) -> Option<String> {
    let t = std::fs::read_to_string(percorso).ok()?;
    let t = t.trim();
    (!t.is_empty()).then(|| t.to_string())
}

pub fn percorso_chiave(cartella: &Path, utente: i64, nome: &str) -> PathBuf {
    cartella.join("chiavi").join(format!("{utente}-{nome}.key"))
}

/// ("locale", "") if that account may use the AI running on the VM.
pub fn locale_di(utente: i64) -> Option<Motore> {
    let c = conf();
    (!c.locale_url.is_empty() && (c.locale_per_tutti || utente == 1))
        .then(|| Motore::uno("locale", ""))
}

/// (name, key) of that service for that account, or None without a key.
pub fn motore_di(cartella: &Path, utente: i64, nome: &str) -> Option<Motore> {
    if nome == "locale" {
        return locale_di(utente);
    }
    let variabile = SERVIZI.iter().find(|(n, _)| *n == nome)?.1;
    let mut k = leggi(&percorso_chiave(cartella, utente, nome));
    if k.is_none() && utente == 1 {
        k = std::env::var(variabile)
            .ok()
            .map(|v| v.trim().to_string())
            .filter(|v| !v.is_empty());
        if k.is_none() {
            k = leggi(&cartella.join(format!("{nome}.key")));
        }
    }
    k.map(|k| Motore::uno(nome, &k))
}

/// `motore_di` with a name that may not be a string (Python's dict lookup returns None for anything unknown).
pub fn motore_di_v(cartella: &Path, utente: i64, nome: &Value) -> Option<Motore> {
    nome.as_str().and_then(|n| motore_di(cartella, utente, n))
}

/// Which service the account uses, with the reserves behind it, or None if it has no key at all.
pub fn motore_ai(cartella: &Path, utente: i64) -> Option<Motore> {
    let tutti: Vec<Motore> = SERVIZI
        .iter()
        .filter_map(|(n, _)| motore_di(cartella, utente, n))
        .collect();
    let mut it = tutti.into_iter();
    let mut primo = it.next()?;
    primo.riserve = it.map(|m| m.coppia()).collect();
    Some(primo)
}

/// Who answers that account's assistant, in order: services with a key, then the VM's AI if allowed.
pub fn fila(cartella: &Path, utente: i64) -> Vec<String> {
    let mut nomi: Vec<String> = match motore_ai(cartella, utente) {
        Some(m) => std::iter::once(m.nome.clone())
            .chain(m.riserve.iter().map(|r| r.0.clone()))
            .collect(),
        None => vec![],
    };
    if locale_di(utente).is_some() {
        nomi.push("locale".into());
    }
    nomi
}

/// Which keys the account has (not their value), which engine it uses and which are reserves.
pub fn stato(cartella: &Path, utente: i64) -> Value {
    let motore = motore_ai(cartella, utente);
    let mut chiavi = Map::new();
    for m in MOTORI {
        chiavi.insert(
            m.into(),
            Value::Bool(motore_di(cartella, utente, m).is_some()),
        );
    }
    json!({"motore": motore.map(|m| m.nome), "fila": fila(cartella, utente), "chiavi": chiavi})
}

pub fn salva_chiave(cartella: &Path, utente: i64, motore: &Value, chiave: &Value) -> Esito<()> {
    let chiave = crate::py::testo_o(chiave).trim().to_string();
    let Some(motore) = motore.as_str().filter(|m| MOTORI.contains(m)) else {
        return Err(Problema::new(400, "Servizio sconosciuto"));
    };
    if !RE_CHIAVE.is_match(&chiave) {
        return Err(Problema::new(
            400,
            "Questa non sembra una chiave: copiala intera, senza spazi.",
        ));
    }
    let percorso = percorso_chiave(cartella, utente, motore);
    let io = |e: std::io::Error| Problema::new(500, e.to_string());
    let dir = percorso
        .parent()
        .ok_or_else(|| Problema::new(500, "cartella delle chiavi non valida"))?;
    let mut b = std::fs::DirBuilder::new();
    b.recursive(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::DirBuilderExt;
        b.mode(0o700);
    }
    b.create(dir).map_err(io)?;
    let mut provvisorio = percorso.clone().into_os_string();
    provvisorio.push(".tmp");
    let mut o = std::fs::OpenOptions::new();
    o.write(true).create(true).truncate(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        o.mode(0o600);
    }
    {
        use std::io::Write;
        let mut f = o.open(&provvisorio).map_err(io)?;
        writeln!(f, "{chiave}").map_err(io)?;
    }
    std::fs::rename(&provvisorio, &percorso).map_err(io)
}

pub fn togli_chiave(cartella: &Path, utente: i64, motore: &str) -> Esito<()> {
    if !MOTORI.contains(&motore) {
        return Err(Problema::new(400, "Servizio sconosciuto"));
    }
    let mut percorsi = vec![percorso_chiave(cartella, utente, motore)];
    if utente == 1 {
        percorsi.push(cartella.join(format!("{motore}.key"))); // the key from before accounts was the admin's
    }
    for p in percorsi {
        let _ = std::fs::remove_file(p);
    }
    Ok(())
}
