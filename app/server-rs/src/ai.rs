//! Asking the AI services (cibo.py `chiedi_struttura`, `chiedi_json`, `_in_fila`): one function per kind of
//! question, each sent to the account's first service and, when that one is full or silent, to the next one.

use crate::ai_gemini as gemini;
use crate::ai_http::{self, manda};
use crate::ai_locale as locale;
use crate::ai_mistral as mistral;
use crate::chiavi::Motore;
use crate::conf::conf;
use crate::errore::{Esito, Problema};
use crate::{log, py};
use serde_json::{Value, json};
use std::cell::RefCell;

/// (mime type, base64) of a photo sent with the last question
pub type Immagine = (String, String);
/// ("io" | "ai", text), oldest first
pub type Messaggi = [(String, String)];

/// `schema` of `chiedi_struttura`: none ("answer in JSON"), or a schema made for the person (VM's AI, small Mistral models).
/// Python's `schema=True` default has no caller, so it is not ported.
#[derive(Clone, Copy)]
pub enum Schema<'a> {
    No,
    Forma(&'a Value),
}

thread_local! {
    /// `_ultimo`: who wrote the last answer of this request, and with which model
    static ULTIMO: RefCell<(Option<String>, Option<String>)> = const { RefCell::new((None, None)) };
}

pub fn segna_modello(m: &str) {
    ULTIMO.with(|u| u.borrow_mut().1 = Some(m.to_string()));
}

/// The name of the service that gave the last answer of this request: it may be a reserve.
pub fn chi_ha_risposto(motore: &Motore) -> String {
    ULTIMO
        .with(|u| u.borrow().0.clone())
        .unwrap_or_else(|| motore.nome.clone())
}

/// The model that wrote the last answer of this request, when known.
pub fn quale_modello() -> Option<String> {
    ULTIMO.with(|u| u.borrow().1.clone())
}

/// Whoever has keys for several services does not stop when one says "too many requests", does not answer or
/// answers unreadably: the same question goes to the next. If nobody makes it, the first error comes back.
fn in_fila(
    motore: &Motore,
    mut chiedi: impl FnMut(&Motore) -> Esito<Option<Value>>,
) -> Esito<Option<Value>> {
    let mut fila: Vec<Motore> = std::iter::once(motore.coppia())
        .chain(motore.riserve.iter().cloned())
        .map(|(n, k)| Motore::uno(&n, &k))
        .collect();
    // whoever just went down with all its models goes last (ai_gemini::ferma)
    fila.sort_by_key(|m| gemini::fermo(&m.nome));
    ULTIMO.with(|u| *u.borrow_mut() = (None, None));
    let mut primo: Option<Problema> = None;
    for (i, uno) in fila.iter().enumerate() {
        let esito = match chiedi(uno) {
            Ok(e) => e,
            Err(e) if e.per_tutti() => return Err(e), // a wrong question is wrong for everyone
            Err(e) => {
                primo.get_or_insert(e);
                None
            }
        };
        if esito.is_some() {
            ULTIMO.with(|u| u.borrow_mut().0 = Some(uno.nome.clone()));
            return Ok(esito);
        }
        if let Some(dopo) = fila.get(i + 1) {
            log!("AI: {} non ce l'ha fatta, passo a {}", uno.nome, dopo.nome);
        }
    }
    match primo {
        Some(e) => Err(e),
        None => Ok(None),
    }
}

fn ruolo<'a>(chi: &str, altro: &'a str) -> &'a str {
    if chi == "io" { "user" } else { altro }
}

/// The conversation as Gemini wants it; the photo, if any, goes with the last question.
pub fn per_gemini(messaggi: &Messaggi, immagine: Option<&Immagine>) -> Vec<Value> {
    let mut c: Vec<Value> = messaggi
        .iter()
        .map(|(chi, t)| json!({"role": ruolo(chi, "model"), "parts": [{"text": t}]}))
        .collect();
    if let (Some((tipo, dati)), Some(ultimo)) = (immagine, c.last_mut())
        && ultimo["role"] == "user"
        && let Some(parti) = ultimo["parts"].as_array_mut()
    {
        parti.insert(0, json!({"inline_data": {"mime_type": tipo, "data": dati}}));
    }
    c
}

fn per_anthropic(messaggi: &Messaggi, immagine: Option<&Immagine>) -> Vec<Value> {
    let mut c: Vec<Value> = messaggi
        .iter()
        .map(|(chi, t)| json!({"role": ruolo(chi, "assistant"), "content": t}))
        .collect();
    if let (Some((tipo, dati)), Some(ultimo)) = (immagine, c.last_mut())
        && ultimo["role"] == "user"
    {
        let testo = ultimo["content"].take();
        ultimo["content"] = json!([{"type": "image", "source": {"type": "base64", "media_type": tipo, "data": dati}}, {"type": "text", "text": testo}]);
    }
    c
}

/// The conversation as Mistral (and the other services speaking like OpenAI) wants it.
pub fn per_mistral(sistema: &str, messaggi: &Messaggi, immagine: Option<&Immagine>) -> Vec<Value> {
    let mut c = vec![json!({"role": "system", "content": sistema})];
    c.extend(
        messaggi
            .iter()
            .map(|(chi, t)| json!({"role": ruolo(chi, "assistant"), "content": t})),
    );
    if let (Some((tipo, dati)), Some(ultimo)) = (immagine, c.last_mut())
        && ultimo["role"] == "user"
    {
        let testo = ultimo["content"].take();
        ultimo["content"] = json!([{"type": "text", "text": testo}, {"type": "image_url", "image_url": format!("data:{tipo};base64,{dati}")}]);
    }
    c
}

/// The dictionary of an answer that had to be JSON; if the service answered in words, those words.
fn struttura(scritto: &str, chi: &str, fine: &Value) -> Option<Value> {
    if let Some(m) = crate::cibo::json_da(scritto) {
        return Some(Value::Object(m));
    }
    let l = scritto.trim_start();
    if !scritto.trim().is_empty()
        && !(l.starts_with('{') || l.starts_with('[') || l.starts_with("```"))
    {
        return Some(json!({"risposta": scritto.trim(), "azioni": []})); // answered in words: fine anyway
    }
    log!(
        "AI: risposta di {} non leggibile ({} caratteri, fine {})",
        chi,
        scritto.chars().count(),
        py::testo(fine)
    );
    None
}

fn anthropic(chiave: &str, corpo: Value) -> Esito<Value> {
    let c = conf();
    manda(
        &c.ai_url,
        &[("x-api-key", chiave), ("anthropic-version", "2023-06-01")],
        &corpo,
        75.0,
    )
}

fn uso_strumento(risposta: &Value) -> Option<Value> {
    risposta
        .get("content")?
        .as_array()?
        .iter()
        .find(|b| b.get("type").and_then(Value::as_str) == Some("tool_use"))
        .map(|b| b.get("input").cloned().unwrap_or(Value::Null))
}

/// Text of a Gemini answer, the "thought" parts left out; None when the answer has no candidates.
pub fn testo_gemini(risposta: &Value) -> Option<(String, Value)> {
    let candidato = risposta.get("candidates")?.as_array()?.first()?;
    let parti = candidato.get("content")?.get("parts")?.as_array()?;
    let testo = parti
        .iter()
        .filter(|p| !py::vero(py::get(p, "thought")))
        .map(|p| py::get(p, "text").as_str().unwrap_or(""))
        .collect();
    Some((testo, py::get(candidato, "finishReason").clone()))
}

/// Like a chat, but the answer comes in the shape described by `strumento`: used by the assistant, which besides
/// answering says what to do in the app. None when the service wrote nothing readable.
#[expect(
    clippy::too_many_arguments,
    reason = "same parameters as the Python function it ports, kept for side-by-side review"
)]
pub fn chiedi_struttura(
    motore: &Motore,
    sistema: &str,
    messaggi: &Messaggi,
    strumento: &Value,
    gettoni: i64,
    schema: Schema<'_>,
    immagine: Option<&Immagine>,
    tappe: &[String],
) -> Esito<Option<Value>> {
    in_fila(motore, |m| {
        struttura_da(
            m, sistema, messaggi, strumento, gettoni, schema, immagine, tappe,
        )
    })
}

#[expect(
    clippy::too_many_arguments,
    reason = "same parameters as the Python function it ports, kept for side-by-side review"
)]
fn struttura_da(
    m: &Motore,
    sistema: &str,
    messaggi: &Messaggi,
    strumento: &Value,
    gettoni: i64,
    schema: Schema<'_>,
    immagine: Option<&Immagine>,
    tappe: &[String],
) -> Esito<Option<Value>> {
    let c = conf();
    let input_schema = py::get(strumento, "input_schema");
    match m.nome.as_str() {
        "gemini" => {
            let mut generazione = json!({"temperature": 0.3, "maxOutputTokens": gettoni, "response_mime_type": "application/json"});
            if !matches!(schema, Schema::No) {
                generazione["response_schema"] = gemini::schema(input_schema);
            }
            let corpo = |g: &Value| json!({"system_instruction": {"parts": [{"text": sistema}]}, "contents": per_gemini(messaggi, immagine), "generationConfig": g});
            let risposta = if gemini::pensiero() {
                generazione["thinkingConfig"] = json!({"thinkingBudget": 2048});
                match gemini::manda(
                    &m.chiave,
                    &corpo(&generazione),
                    c.attesa_assistente,
                    c.gemini_chat_leggero,
                ) {
                    Err(e) if e.remoto == Some(400) => {
                        // not every model accepts it: from here on it is not sent any more
                        log!("AI: il modello non accetta il limite al ragionamento, riprovo senza");
                        gemini::senza_pensiero();
                        if let Some(g) = generazione.as_object_mut() {
                            g.shift_remove("thinkingConfig");
                        }
                        gemini::manda(
                            &m.chiave,
                            &corpo(&generazione),
                            c.attesa_assistente,
                            c.gemini_chat_leggero,
                        )?
                    }
                    r => r?,
                }
            } else {
                gemini::manda(
                    &m.chiave,
                    &corpo(&generazione),
                    c.attesa_assistente,
                    c.gemini_chat_leggero,
                )?
            };
            let uso = py::get(&risposta, "usageMetadata");
            let (scritto, fine) = testo_gemini(&risposta).unwrap_or_default();
            log!(
                "AI: assistente, {} token letti, {} di ragionamento, {} scritti, fine {}",
                py::testo(py::get(uso, "promptTokenCount")),
                py::testo(py::get(uso, "thoughtsTokenCount")),
                py::testo(py::get(uso, "candidatesTokenCount")),
                py::testo(&fine)
            );
            Ok(struttura(&scritto, "Gemini", &fine))
        }
        "locale" => {
            let forma = match schema {
                Schema::Forma(f) => Some(f),
                Schema::No => None,
            };
            let scritto = locale::chiedi(
                sistema,
                messaggi,
                forma,
                immagine,
                gettoni.min(900),
                0.2,
                "assistente",
                tappe,
            )?;
            Ok(struttura(&scritto, "locale", &Value::Null))
        }
        "mistral" => {
            let (mut corpo, modelli) = match schema {
                // the small models, held by the hand like the VM's AI: the answer is closed in the person's schema
                Schema::Forma(f) => (
                    json!({"max_tokens": gettoni.min(900), "temperature": 0.2,
                           "response_format": {"type": "json_schema", "json_schema": {"name": "risposta", "schema": f, "strict": true}}}),
                    &c.mistral_piccoli,
                ),
                // the big ones like Gemini: "answer in JSON" and that is all, the shape is written in the instructions
                _ => (
                    json!({"max_tokens": gettoni, "temperature": 0.3, "response_format": {"type": "json_object"}}),
                    &c.mistral_grandi,
                ),
            };
            corpo["messages"] = Value::Array(per_mistral(sistema, messaggi, immagine));
            let risposta = mistral::manda(&m.chiave, &corpo, c.attesa_assistente, Some(modelli))?;
            Ok(struttura(
                &mistral::scritto(&risposta, "assistente"),
                "Mistral",
                &Value::Null,
            ))
        }
        _ => {
            let risposta = anthropic(
                &m.chiave,
                json!({"model": c.ai_modello, "max_tokens": gettoni, "system": format!("{sistema} Rispondi sempre chiamando lo strumento."),
                       "tools": [strumento], "tool_choice": {"type": "tool", "name": py::get(strumento, "name")},
                       "messages": per_anthropic(messaggi, immagine)}),
            )?;
            Ok(uso_strumento(&risposta).filter(Value::is_object))
        }
    }
}

/// Asks the chosen service and wants the answer in the shape described by `strumento`. None if unreadable.
pub fn chiedi_json(
    motore: &Motore,
    sistema: &str,
    testo: &str,
    strumento: &Value,
    immagine: Option<&Immagine>,
    gettoni: i64,
) -> Esito<Option<Value>> {
    in_fila(motore, |m| {
        json_da_servizio(m, sistema, testo, strumento, immagine, gettoni)
    })
}

fn json_da_servizio(
    m: &Motore,
    sistema: &str,
    testo: &str,
    strumento: &Value,
    immagine: Option<&Immagine>,
    gettoni: i64,
) -> Esito<Option<Value>> {
    let c = conf();
    let input_schema = py::get(strumento, "input_schema");
    let domanda = [("io".to_string(), testo.to_string())];
    match m.nome.as_str() {
        "gemini" => {
            let mut parti: Vec<Value> = immagine
                .map(|(t, d)| json!({"inline_data": {"mime_type": t, "data": d}}))
                .into_iter()
                .collect();
            parti.push(json!({"text": testo}));
            let corpo = json!({
                "system_instruction": {"parts": [{"text": format!("{sistema} Rispondi solo con il JSON richiesto.")}]},
                "contents": [{"role": "user", "parts": parti}],
                "generationConfig": {"response_mime_type": "application/json", "response_schema": gemini::schema(input_schema)},
            });
            let risposta = gemini::manda(&m.chiave, &corpo, c.attesa_altro, false)?;
            // json.loads("null") is None in Python: no answer either
            match testo_gemini(&risposta)
                .and_then(|(t, _)| serde_json::from_str::<Value>(&t).ok())
                .filter(|v| !v.is_null())
            {
                Some(v) => Ok(Some(v)),
                None => {
                    log!(
                        "AI: risposta di Gemini non leggibile: {}",
                        py::taglia(&crate::pyjson::ascii(&risposta), 300)
                    );
                    Ok(None)
                }
            }
        }
        "locale" => {
            let nome = py::testo(py::get(strumento, "name"));
            let scritto = locale::chiedi(
                &format!("{sistema} Rispondi solo con il JSON richiesto."),
                &domanda,
                Some(input_schema),
                immagine,
                gettoni,
                0.2,
                &nome,
                &[],
            )?;
            Ok(crate::cibo::json_da(&scritto).map(Value::Object))
        }
        "mistral" => {
            let forma = format!(
                " Rispondi solo con un oggetto JSON che rispetta questo schema: {}",
                crate::pyjson::largo(input_schema)
            );
            let corpo = json!({"messages": per_mistral(&format!("{sistema}{forma}"), &domanda, immagine), "max_tokens": gettoni,
                               "temperature": 0.2, "response_format": {"type": "json_object"}});
            let risposta = mistral::manda(&m.chiave, &corpo, c.attesa_altro, None)?;
            Ok(crate::cibo::json_da(&mistral::scritto(
                &risposta,
                &py::testo(py::get(strumento, "name")),
            ))
            .map(Value::Object))
        }
        _ => {
            let mut contenuto: Vec<Value> =
                immagine.map(|(t, d)| json!({"type": "image", "source": {"type": "base64", "media_type": t, "data": d}})).into_iter().collect();
            contenuto.push(json!({"type": "text", "text": testo}));
            let risposta = anthropic(
                &m.chiave,
                json!({"model": c.ai_modello, "max_tokens": gettoni, "system": format!("{sistema} Rispondi sempre chiamando lo strumento."),
                       "tools": [strumento], "tool_choice": {"type": "tool", "name": py::get(strumento, "name")},
                       "messages": [{"role": "user", "content": contenuto}]}),
            )?;
            Ok(uso_strumento(&risposta).filter(|v| !v.is_null()))
        }
    }
}

pub use ai_http::stanco;
