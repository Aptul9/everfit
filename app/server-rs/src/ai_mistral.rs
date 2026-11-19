//! Mistral (cibo.py `_manda_mistral`, `_manda_mistral_conv`): a queue of models, big ones first, each tried on
//! chat/completions and, for the big ones, on the "conversations" route that the free plan leaves open. A model or
//! route the account's plan does not include is skipped for six hours.

use crate::ai::segna_modello;
use crate::ai_http::{manda as manda_http, stanco};
use crate::conf::conf;
use crate::errore::{Esito, Problema};
use crate::{log, py};
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::sync::{LazyLock, Mutex};
use std::time::Duration;

const CHIUSO_PER: f64 = 6.0 * 3600.0;

/// (fingerprint of the key, model, route) -> until when it is not retried
type Chiusi = HashMap<(String, String, &'static str), f64>;
static CHIUSI: LazyLock<Mutex<Chiusi>> = LazyLock::new(|| Mutex::new(HashMap::new()));

fn chiusi() -> std::sync::MutexGuard<'static, Chiusi> {
    CHIUSI.lock().unwrap_or_else(|e| e.into_inner())
}

/// Never the key itself in memory maps or logs: 12 hex characters of its SHA-256.
fn impronta(chiave: &str) -> String {
    py::taglia(&hex::encode(Sha256::digest(chiave.as_bytes())), 12)
}

/// Whoever tests the key may have just changed plan: the models closed for that key are all checked again.
pub fn dimentica(chiave: &str) {
    let i = impronta(chiave);
    chiusi().retain(|k, _| k.0 != i);
}

/// The chat/completions request sent on the "conversations" route; the answer comes back shaped like
/// chat/completions. Nothing is left stored on their side ("store" false).
fn manda_conv(chiave: &str, corpo: &Value, modello: &str, attesa: f64) -> Esito<Value> {
    let messaggi = py::get(corpo, "messages")
        .as_array()
        .cloned()
        .unwrap_or_default();
    let ruolo = |m: &Value| py::get(m, "role").as_str().unwrap_or("").to_string();
    let sistema: Vec<&str> = messaggi
        .iter()
        .filter(|m| ruolo(m) == "system")
        .filter_map(|m| py::get(m, "content").as_str())
        .collect();
    let sistema = sistema.join("\n\n");
    let voci: Vec<Value> = messaggi
        .iter()
        .filter(|m| ruolo(m) != "system")
        .map(|m| json!({"object": "entry", "type": "message.input", "role": py::get(m, "role"), "content": py::get(m, "content")}))
        .collect();
    let mut argomenti = Map::new();
    for k in ["temperature", "max_tokens", "response_format"] {
        if let Some(v) = corpo.get(k) {
            argomenti.insert(k.into(), v.clone());
        }
    }
    let mut richiesta = json!({"model": modello, "inputs": voci, "stream": false, "store": false, "completion_args": argomenti});
    if !sistema.is_empty() {
        richiesta["instructions"] = Value::String(sistema);
    }
    let auth = format!("Bearer {chiave}");
    let risposta = manda_http(
        &conf().mistral_conv_url,
        &[("Authorization", &auth)],
        &richiesta,
        attesa,
    )?;
    let mut testo = String::new();
    for uscita in py::get(&risposta, "outputs")
        .as_array()
        .into_iter()
        .flatten()
    {
        if uscita.is_object() && py::get(uscita, "type").as_str() == Some("message.output") {
            match py::get(uscita, "content") {
                Value::String(s) => testo.push_str(s),
                Value::Array(parti) => {
                    for p in parti
                        .iter()
                        .filter(|p| py::get(p, "type").as_str() == Some("text"))
                    {
                        testo.push_str(&py::testo(
                            p.get("text").unwrap_or(&Value::String(String::new())),
                        ));
                    }
                }
                _ => {}
            }
        }
    }
    let uso = py::o(py::get(&risposta, "usage"), &Value::Null).clone();
    let uso = if uso.is_null() { json!({}) } else { uso };
    Ok(
        json!({"model": modello, "choices": [{"message": {"role": "assistant", "content": testo}, "finish_reason": "stop"}], "usage": uso}),
    )
}

/// The same request to the models in `modelli` (all of them when None: big ones first, then small), one after
/// the other until one answers. If nobody did, the error of the first one that was only full or silent (it tells
/// the app how long to wait); if everything was closed, an error with `chiuso` set.
pub fn manda(
    chiave: &str,
    corpo: &Value,
    attesa: f64,
    modelli: Option<&Vec<String>>,
) -> Esito<Value> {
    let c = conf();
    let auth = format!("Bearer {chiave}");
    let imp = impronta(chiave);
    let inizio = py::ora();
    let ora = inizio;
    let tutti: Vec<String>;
    let elenco = match modelli {
        Some(m) if !m.is_empty() => m,
        _ => {
            tutti = c
                .mistral_grandi
                .iter()
                .chain(&c.mistral_piccoli)
                .cloned()
                .collect();
            &tutti
        }
    };
    let mut pieno: Option<Problema> = None;
    let mut primo: Option<String> = None;
    for modello in elenco {
        let grande = c.mistral_grandi.contains(modello);
        let strade: &[&'static str] = if grande && !c.mistral_conv_url.is_empty() {
            &["chat", "conversations"]
        } else {
            &["chat"]
        };
        for &strada in strade {
            let chiave_chiuso = (imp.clone(), modello.clone(), strada);
            if chiusi().get(&chiave_chiuso).is_some_and(|fino| ora < *fino) {
                continue;
            }
            if let Some(p) = &pieno {
                if py::ora() - inizio > attesa {
                    return Err(p.clone()); // waited long enough: whoever asked is looking at the phone
                }
                if p.remoto == Some(429) && c.mistral_url.contains("api.mistral.ai") {
                    std::thread::sleep(Duration::from_millis(1200)); // the free plan takes one request a second
                }
            }
            let primo_nome = primo.get_or_insert_with(|| modello.clone()).clone();
            let esito = if strada == "chat" {
                let mut corpo_m = corpo.clone();
                corpo_m["model"] = Value::String(modello.clone());
                manda_http(
                    &c.mistral_url,
                    &[("Authorization", &auth)],
                    &corpo_m,
                    attesa,
                )
            } else {
                manda_conv(chiave, corpo, modello, attesa)
            };
            match esito {
                Ok(risposta) => {
                    if *modello != primo_nome {
                        log!(
                            "AI: risposto da {} ({} era pieno o muto)",
                            modello,
                            primo_nome
                        );
                    }
                    segna_modello(modello);
                    return Ok(risposta);
                }
                Err(e) if e.chiuso => {
                    chiusi().insert(chiave_chiuso, py::ora() + CHIUSO_PER);
                    log!(
                        "AI: con questa chiave Mistral non lascia usare {} per la strada {}: per {} ore non la riprovo",
                        modello,
                        strada,
                        (CHIUSO_PER / 3600.0) as i64
                    );
                }
                Err(e) if !stanco(&e) => return Err(e),
                Err(e) => {
                    pieno.get_or_insert(e);
                    break; // full or silent: the other route has the same cap, on to the next model
                }
            }
        }
    }
    if let Some(p) = pieno {
        return Err(p);
    }
    Err(Problema {
        codice: 429,
        testo: "Con il tuo piano Mistral non lascia usare i modelli che servono all'app.".into(),
        remoto: Some(429),
        giornaliero: true,
        perche: Some("non lascia usare i suoi modelli con questo piano".into()),
        chiuso: true,
        ..Default::default()
    })
}

/// The text of a Mistral answer; the log keeps how many token it cost.
pub fn scritto(risposta: &Value, cosa: &str) -> String {
    let uso = py::get(risposta, "usage");
    let scelta = risposta
        .get("choices")
        .and_then(Value::as_array)
        .and_then(|a| a.first())
        .filter(|s| s.is_object())
        .cloned()
        .unwrap_or(json!({}));
    let contenuto = scelta
        .get("message")
        .and_then(|m| m.get("content"))
        .cloned()
        .unwrap_or(Value::Null);
    let testo = match &contenuto {
        // the content may arrive in pieces
        Value::Array(parti) => parti
            .iter()
            .filter(|p| py::get(p, "type").as_str() == Some("text"))
            .map(|p| py::testo(p.get("text").unwrap_or(&Value::String(String::new()))))
            .collect(),
        v => py::testo_o(v),
    };
    log!(
        "AI: {} ({}), {} token letti, {} scritti, fine {}",
        cosa,
        py::testo(py::get(risposta, "model")),
        py::testo(py::get(uso, "prompt_tokens")),
        py::testo(py::get(uso, "completion_tokens")),
        py::testo(py::get(&scelta, "finish_reason"))
    );
    testo.trim().to_string()
}
