//! The model running on the VM (cibo.py, Ollama): one request at a time, the still parts of the context read ahead
//! of the question so that the engine only reads what changed, and the answer forced into a JSON schema.

use crate::ai::{Immagine, Messaggi, segna_modello};
use crate::ai_http::manda as manda_http;
use crate::conf::conf;
use crate::errore::Esito;
use crate::{log, py};
use serde_json::{Value, json};
use sha1::{Digest, Sha1};
use std::sync::{LazyLock, Mutex, MutexGuard};

struct Stato {
    /// does the engine accept "think": false?
    pensa: bool,
    /// fingerprints of the still parts already read
    tappe: Vec<String>,
}

static STATO: Mutex<Stato> = Mutex::new(Stato {
    pensa: true,
    tappe: Vec::new(),
});
/// one request at a time: the engine does one at a time anyway
static UNO: LazyLock<Mutex<()>> = LazyLock::new(|| Mutex::new(()));

fn stato() -> MutexGuard<'static, Stato> {
    STATO.lock().unwrap_or_else(|e| e.into_inner())
}

fn uno() -> MutexGuard<'static, ()> {
    UNO.lock().unwrap_or_else(|e| e.into_inner())
}

fn corpo(messaggi: Vec<Value>, gettoni: i64, temperatura: f64) -> Value {
    let c = conf();
    let mut corpo = json!({"model": c.locale_modello, "messages": messaggi, "stream": false, "keep_alive": c.locale_sveglio,
        "options": {"temperature": temperatura, "num_ctx": c.locale_finestra, "num_predict": gettoni, "num_thread": c.locale_fili}});
    if c.locale_lotto > 0 {
        corpo["options"]["num_batch"] = Value::from(c.locale_lotto);
    }
    if stato().pensa {
        corpo["think"] = Value::Bool(false); // no separate reasoning: on a CPU it is tens of seconds more
    }
    corpo
}

fn chiama(mut corpo: Value) -> Esito<Value> {
    let c = conf();
    let url = format!("{}/api/chat", c.locale_url);
    match manda_http(&url, &[], &corpo, c.attesa_locale) {
        Err(e)
            if e.remoto == Some(400)
                && e.dettaglio.to_lowercase().contains("think")
                && corpo.get("think").is_some() =>
        {
            stato().pensa = false; // this model has no reasoning to switch off
            if let Some(o) = corpo.as_object_mut() {
                o.shift_remove("think");
            }
            manda_http(&url, &[], &corpo, c.attesa_locale)
        }
        r => r,
    }
}

/// Has the model read the parts that do not change. `tappe` are ever longer system texts, each starting with the
/// previous one. Usually the last one is enough; for bookmark models they are read one by one, only those changed.
fn scalda_dentro(tappe: &[String]) -> Esito<()> {
    let impronte: Vec<String> = tappe
        .iter()
        .map(|t| hex::encode(Sha1::digest(t.as_bytes())))
        .collect();
    let segnalibri = conf().locale_segnalibri;
    for (i, testo) in tappe.iter().enumerate() {
        let gia = {
            let s = stato();
            s.tappe.len() > i && s.tappe[..=i] == impronte[..=i]
        };
        if (!segnalibri && i + 1 < tappe.len()) || gia {
            continue;
        }
        let inizio = py::ora();
        let risposta = chiama(corpo(
            vec![
                json!({"role": "system", "content": testo}),
                json!({"role": "user", "content": "ok"}),
            ],
            1,
            0.0,
        ))?;
        stato().tappe = impronte[..=i].to_vec();
        log!(
            "AI: locale, letta la parte ferma {} di {} ({} token) in {:.0} s",
            i + 1,
            tappe.len(),
            py::testo(py::get(&risposta, "prompt_eval_count")),
            py::ora() - inizio
        );
    }
    Ok(())
}

/// Prepares the model for a person before a question reaches it (assistente::scalda).
pub fn scalda(tappe: &[String]) -> Esito<()> {
    if conf().locale_url.is_empty() || tappe.is_empty() {
        return Ok(());
    }
    let _uno = uno();
    scalda_dentro(tappe)
}

/// At start and every few hours: loads the model and keeps it in memory without reading anything. If Ollama does
/// not answer it does not matter.
pub fn sveglia() {
    let c = conf();
    if c.locale_url.is_empty() {
        return;
    }
    // the same options as real questions: with others Ollama would reload the model and lose what it had read
    let opzioni = corpo(vec![], 1, 0.0)["options"].take();
    let _ = manda_http(
        &format!("{}/api/generate", c.locale_url),
        &[],
        &json!({"model": c.locale_modello, "keep_alive": c.locale_sveglio, "options": opzioni}),
        180.0,
    );
}

/// A question to the model on the VM. `forma` is the JSON schema the engine enforces while the model writes, so a
/// wrong shape or an identifier that does not exist cannot come out. Returns the written text.
#[expect(
    clippy::too_many_arguments,
    reason = "same parameters as the Python function it ports, kept for side-by-side review"
)]
pub fn chiedi(
    sistema: &str,
    messaggi: &Messaggi,
    forma: Option<&Value>,
    immagine: Option<&Immagine>,
    gettoni: i64,
    temperatura: f64,
    cosa: &str,
    tappe: &[String],
) -> Esito<String> {
    let mut contenuti = vec![json!({"role": "system", "content": sistema})];
    contenuti.extend(messaggi.iter().map(
        |(chi, t)| json!({"role": if chi == "io" { "user" } else { "assistant" }, "content": t}),
    ));
    if let (Some((_, dati)), Some(ultimo)) = (immagine, contenuti.last_mut())
        && ultimo["role"] == "user"
    {
        ultimo["images"] = json!([dati]);
    }
    let mut c = corpo(contenuti, gettoni, temperatura);
    c["format"] = forma
        .filter(|f| py::vero(f))
        .cloned()
        .unwrap_or_else(|| Value::String("json".into()));
    let risposta = {
        let _uno = uno();
        if !tappe.is_empty() && conf().locale_segnalibri {
            // the other models read what is missing while answering, without an extra round
            let utili: Vec<String> = tappe
                .iter()
                .filter(|t| sistema.starts_with(t.as_str()))
                .cloned()
                .collect();
            scalda_dentro(&utili)?;
        }
        chiama(c)?
    };
    let secondi = |k: &str| py::float(py::get(&risposta, k)).unwrap_or(0.0) / 1e9;
    log!(
        "AI: {} (locale {}), {} token in tutto, lettura {:.0} s, {} scritti in {:.0} s, in tutto {:.0} s, fine {}",
        cosa,
        py::testo(py::get(&risposta, "model")),
        py::testo(py::get(&risposta, "prompt_eval_count")),
        secondi("prompt_eval_duration"),
        py::testo(py::get(&risposta, "eval_count")),
        secondi("eval_duration"),
        secondi("total_duration"),
        py::testo(py::get(&risposta, "done_reason"))
    );
    segna_modello(&conf().locale_modello);
    Ok(
        py::testo_o(py::get(py::get(&risposta, "message"), "content"))
            .trim()
            .to_string(),
    )
}
