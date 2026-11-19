//! Gemini (cibo.py `_manda_gemini` and its state): the main model, the "lite" reserve model with its own limits,
//! the pause after the main one goes silent, and the switch to a newer Flash when the configured one disappears.

use crate::ai::segna_modello;
use crate::ai_http::{self, manda as manda_http, stanco};
use crate::conf::conf;
use crate::errore::{Esito, Problema};
use crate::{log, py};
use serde_json::{Map, Value};
use std::sync::{LazyLock, Mutex, MutexGuard};

struct Stato {
    modello: String,
    /// does the model accept a limit on reasoning (thinkingConfig)? found out at the first request
    pensiero: bool,
    /// None: not looked up yet; Some(None): looked up, no reserve
    riserva: Option<Option<String>>,
    fermo: f64,
    cadute: u32,
    riposa: f64,
}

static STATO: LazyLock<Mutex<Stato>> = LazyLock::new(|| {
    Mutex::new(Stato {
        modello: conf().gemini_modello.clone(),
        pensiero: true,
        riserva: None,
        fermo: 0.0,
        cadute: 0,
        riposa: 0.0,
    })
});

static RE_PRECISO: LazyLock<regex::Regex> =
    LazyLock::new(|| py::re(r"^gemini-(\d+(?:\.\d+)?)-flash$"));
static RE_LARGO: LazyLock<regex::Regex> =
    LazyLock::new(|| py::re(r"^gemini-(\d+(?:\.\d+)?)-flash"));
static RE_ESCLUSI: LazyLock<regex::Regex> =
    LazyLock::new(|| py::re(r"lite|image|tts|live|audio|native"));
static RE_LITE: LazyLock<regex::Regex> =
    LazyLock::new(|| py::re(r"^gemini-(\d+(?:\.\d+)?)-flash-lite$"));

fn stato() -> MutexGuard<'static, Stato> {
    STATO.lock().unwrap_or_else(|e| e.into_inner())
}

pub fn pensiero() -> bool {
    stato().pensiero
}

pub fn senza_pensiero() {
    stato().pensiero = false;
}

/// Has that service just gone down with all its models? Then for a while the others are asked first.
pub fn fermo(nome: &str) -> bool {
    nome == "gemini" && py::ora() < stato().fermo
}

/// Whoever presses "Prova" wants to know how it is now: Gemini goes back to its place in the queue.
pub fn riprova() {
    let mut s = stato();
    s.fermo = 0.0;
    s.cadute = 0;
}

/// The same schema as the tool, written the way Gemini wants it (types in capitals).
pub fn schema(s: &Value) -> Value {
    match s {
        Value::Array(a) => Value::Array(a.iter().map(schema).collect()),
        Value::Object(o) => {
            let mut m = Map::new();
            for (k, v) in o {
                let nuovo = match (k.as_str(), v) {
                    ("type", Value::String(t)) => Value::String(t.to_uppercase()),
                    ("properties", Value::Object(p)) => {
                        Value::Object(p.iter().map(|(n, x)| (n.clone(), schema(x))).collect())
                    }
                    ("items", x) => schema(x),
                    _ => v.clone(),
                };
                m.insert(k.clone(), nuovo);
            }
            Value::Object(m)
        }
        other => other.clone(),
    }
}

fn con_modello() -> bool {
    conf().gemini_url.contains("%s")
}

fn indirizzo(modello: &str) -> String {
    let url = &conf().gemini_url;
    if url.contains("%s") {
        url.replacen("%s", modello, 1)
    } else {
        url.clone()
    }
}

fn modelli(chiave: &str) -> Option<Vec<(String, Vec<String>)>> {
    let base = conf()
        .gemini_url
        .split("/models/")
        .next()
        .unwrap_or("")
        .to_string();
    let d = ai_http::prendi(
        &format!("{base}/models?pageSize=200"),
        &[("x-goog-api-key", chiave)],
        15.0,
    )
    .ok()?;
    let lista = d.get("models")?.as_array()?;
    Some(
        lista
            .iter()
            .map(|m| {
                let nome = py::testo_o(py::get(m, "name"))
                    .rsplit('/')
                    .next()
                    .unwrap_or("")
                    .to_string();
                let metodi = py::get(m, "supportedGenerationMethods")
                    .as_array()
                    .map(|a| {
                        a.iter()
                            .filter_map(|x| x.as_str().map(String::from))
                            .collect()
                    })
                    .unwrap_or_default();
                (nome, metodi)
            })
            .collect(),
    )
}

/// `max(lista)` over (version, name) pairs as Python compares tuples.
fn massimo(lista: Vec<(f64, String)>) -> Option<String> {
    lista
        .into_iter()
        .max_by(|a, b| a.0.total_cmp(&b.0).then_with(|| a.1.cmp(&b.1)))
        .map(|x| x.1)
}

/// Google's model names change: if the configured one no longer exists, the latest Flash the key can use.
fn scegli_modello(chiave: &str) -> Option<String> {
    let (mut stabili, mut altri) = (Vec::new(), Vec::new());
    for (nome, metodi) in modelli(chiave)? {
        if !metodi.iter().any(|m| m == "generateContent") {
            continue;
        }
        if let Some(c) = RE_PRECISO.captures(&nome) {
            stabili.push((c[1].parse().unwrap_or(0.0), nome));
        } else if let Some(c) = RE_LARGO.captures(&nome)
            && !RE_ESCLUSI.is_match(&nome)
        {
            altri.push((c[1].parse().unwrap_or(0.0), nome));
        }
    }
    massimo(if !stabili.is_empty() { stabili } else { altri })
}

/// The latest "lite" Flash the key can use: it has limits of its own, separate from the main model's.
fn modello_di_riserva(chiave: &str) -> Option<String> {
    let principale = {
        let mut s = stato();
        if let Some(r) = &s.riserva {
            return r.clone();
        }
        s.riserva = Some(None); // concurrent requests see "no reserve" until the lookup ends, as in Python
        s.modello.clone()
    };
    let leggeri: Vec<(f64, String)> = modelli(chiave)
        .unwrap_or_default()
        .into_iter()
        .filter(|(nome, metodi)| {
            metodi.iter().any(|m| m == "generateContent") && *nome != principale
        })
        .filter_map(|(nome, _)| {
            RE_LITE
                .captures(&nome)
                .and_then(|c| c[1].parse().ok())
                .map(|v| (v, nome))
        })
        .collect();
    let scelta = massimo(leggeri);
    log!(
        "AI: modello di riserva: {}",
        scelta.as_deref().unwrap_or("None")
    );
    stato().riserva = Some(scelta.clone());
    scelta
}

/// Main and reserve both failed. If at least one stayed silent or was overloaded, Gemini goes to the back of the
/// queue for a while: 5, 10, 20, 40, 60 minutes, doubling at each fall in a row.
fn ferma(errori: &[&Problema]) {
    if !errori.iter().any(|e| e.remoto.is_none_or(|r| r >= 500)) {
        return;
    }
    let mut s = stato();
    s.cadute += 1;
    let minuti = 60u32.min(5 * 2u32.saturating_pow(s.cadute - 1));
    s.fermo = py::ora() + f64::from(minuti) * 60.0;
    drop(s);
    log!(
        "AI: Gemini non risponde con nessun modello: per {} minuti si chiede prima agli altri servizi",
        minuti
    );
}

fn chiama(modello: &str, chiave: &str, corpo: &Value, attesa: f64) -> Esito<Value> {
    manda_http(
        &indirizzo(modello),
        &[("x-goog-api-key", chiave)],
        corpo,
        attesa,
    )
}

/// One request to Gemini. `leggero` goes straight to the reserve model (the chat).
pub fn manda(chiave: &str, corpo: &Value, attesa: f64, leggero: bool) -> Esito<Value> {
    let breve = attesa.min(conf().attesa_riserva); // the light model answers in seconds: if it is silent, it is silent
    let mut caduta: Option<Problema> = None; // the reserve's error, if it was already tried in this request
    let riposa = stato().riposa;
    if con_modello()
        && (leggero || py::ora() < riposa)
        && let Some(riserva) = modello_di_riserva(chiave)
    {
        match chiama(&riserva, chiave, corpo, breve) {
            Ok(r) => {
                segna_modello(&riserva);
                stato().cadute = 0;
                return Ok(r);
            }
            Err(e) => caduta = Some(e),
        }
    }
    let modello = stato().modello.clone();
    let e = match chiama(&modello, chiave, corpo, attesa) {
        Ok(r) => {
            segna_modello(&modello);
            let mut s = stato();
            s.riposa = 0.0;
            s.cadute = 0;
            return Ok(r);
        }
        Err(e) => e,
    };
    if stanco(&e) && con_modello() {
        // main model full, overloaded or silent: the reserve is tried; if it fails too, the main one's error stays
        stato().riposa = py::ora() + if e.giornaliero { 3600.0 } else { 600.0 };
        let riserva = if caduta.is_some() {
            None
        } else {
            modello_di_riserva(chiave)
        };
        if let Some(riserva) = riserva {
            return match chiama(&riserva, chiave, corpo, breve) {
                Ok(r) => {
                    log!(
                        "AI: risposto dal modello di riserva {} (il principale riposa per {} minuti)",
                        riserva,
                        if e.giornaliero { 60 } else { 10 }
                    );
                    segna_modello(&riserva);
                    stato().cadute = 0;
                    Ok(r)
                }
                Err(secondo) => {
                    ferma(&[&e, &secondo]);
                    Err(e)
                }
            };
        }
        if let Some(c) = &caduta {
            ferma(&[&e, c]);
        }
        return Err(e);
    }
    if e.remoto != Some(404) || !con_modello() {
        return Err(e);
    }
    let Some(nuovo) = scegli_modello(chiave).filter(|n| *n != modello) else {
        return Err(e);
    };
    log!("AI: il modello {} non c'e', passo a {}", modello, nuovo);
    stato().modello = nuovo.clone();
    segna_modello(&nuovo);
    chiama(&nuovo, chiave, corpo, attesa)
}

#[cfg(test)]
mod test {
    use super::*;
    use serde_json::json;

    #[test]
    fn schema_in_maiuscolo() {
        let s = json!({"type": "object", "properties": {"a": {"type": "array", "items": {"type": "string"}}}, "required": ["a"]});
        assert_eq!(
            schema(&s),
            json!({"type": "OBJECT", "properties": {"a": {"type": "ARRAY", "items": {"type": "STRING"}}}, "required": ["a"]})
        );
    }

    #[test]
    fn massimo_come_le_tuple() {
        assert_eq!(
            massimo(vec![
                (4.0, "b".into()),
                (4.0, "c".into()),
                (3.8, "z".into())
            ]),
            Some("c".into())
        );
        assert_eq!(massimo(vec![]), None);
    }
}
