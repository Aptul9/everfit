//! HTTP to the AI services and the food catalogue (cibo.py `_manda`, `_scarica`): one reused client, a timeout per
//! request, and the services' errors turned into sentences the phone can show.

use crate::errore::{Esito, Problema};
use crate::{log, py};
use reqwest::blocking::Client;
use serde_json::{Map, Value, json};
use std::sync::LazyLock;
use std::time::Duration;

pub const UA: &str = "EverFit/1.0 (app personale di dieta)";

static CLIENT: LazyLock<Client> = LazyLock::new(|| {
    // rustls with the ring provider (no C toolchain for the static build); roots from the system CA store
    let _ = rustls::crypto::ring::default_provider().install_default();
    Client::builder()
        .user_agent(UA)
        .connect_timeout(Duration::from_secs(10))
        .build()
        .unwrap_or_else(|e| {
            tracing::error!("client HTTP non creato: {e}");
            Client::new()
        })
});

/// The one HTTP client of the process, reused for every outgoing request.
pub fn client() -> &'static Client {
    &CLIENT
}

static RE_RITARDO: LazyLock<regex::Regex> = LazyLock::new(|| py::re(r"^(\d+(?:\.\d+)?)s$"));

pub fn durata(secondi: f64) -> Duration {
    Duration::try_from_secs_f64(secondi.max(0.001)).unwrap_or(Duration::from_secs(3600))
}

fn netloc(url: &str) -> String {
    reqwest::Url::parse(url)
        .ok()
        .map(|u| match u.port() {
            Some(p) => format!("{}:{p}", u.host_str().unwrap_or("")),
            None => u.host_str().unwrap_or("").to_string(),
        })
        .unwrap_or_default()
}

pub fn tipo_errore(e: &reqwest::Error) -> &'static str {
    if e.is_timeout() {
        "TimeoutError"
    } else if e.is_connect() {
        "ConnectionError"
    } else if e.is_decode() || e.is_body() {
        "ValueError"
    } else {
        "URLError"
    }
}

/// GET returning JSON. `Err(Some(code))` when the server answered with an error status, `Err(None)` when it did
/// not answer or the answer was not JSON.
pub fn prendi(url: &str, intestazioni: &[(&str, &str)], attesa: f64) -> Result<Value, Option<u16>> {
    let mut r = CLIENT.get(url).timeout(durata(attesa));
    for (k, v) in intestazioni {
        r = r.header(*k, *v);
    }
    let risposta = r.send().map_err(|_| None)?;
    if !risposta.status().is_success() {
        return Err(Some(risposta.status().as_u16()));
    }
    let testo = risposta.text().map_err(|_| None)?;
    serde_json::from_str(&testo).map_err(|_| None)
}

/// POST JSON to an AI service. Errors become sentences that can be shown on the phone.
pub fn manda(url: &str, intestazioni: &[(&str, &str)], corpo: &Value, attesa: f64) -> Esito<Value> {
    let mut r = CLIENT
        .post(url)
        .timeout(durata(attesa))
        .header("content-type", "application/json")
        .body(crate::pyjson::ascii(corpo));
    for (k, v) in intestazioni {
        r = r.header(*k, *v);
    }
    let muto = |tipo: &str| {
        // silent or unreachable: the log keeps it, otherwise nobody would know about this error
        log!(
            "AI: nessuna risposta da {} in {} s ({})",
            netloc(url),
            crate::pyjson::float_repr(attesa),
            tipo
        );
        Problema::new(502, "Il servizio di AI non risponde. Riprova tra poco.")
    };
    let risposta = r.send().map_err(|e| muto(tipo_errore(&e)))?;
    let codice = risposta.status().as_u16();
    if risposta.status().is_success() {
        let testo = risposta.text().map_err(|e| muto(tipo_errore(&e)))?;
        return serde_json::from_str(&testo).map_err(|_| muto("JSONDecodeError"));
    }
    let intestazione = |n: &str| {
        risposta
            .headers()
            .get(n)
            .and_then(|v| v.to_str().ok())
            .map(str::to_string)
    };
    let dopo = intestazione("Retry-After");
    let limite_minuto = intestazione("x-ratelimit-limit-req-minute");
    let testo = risposta.text().unwrap_or_default();
    Err(problema_da(
        codice,
        &testo,
        dopo.as_deref(),
        limite_minuto.as_deref(),
    ))
}

/// The error answer of a service as a `Problema` (Google and Anthropic: {"error": {"message", "details"}};
/// Mistral: {"message": ...} or {"detail": ...}).
pub fn problema_da(
    codice: u16,
    testo: &str,
    retry_after: Option<&str>,
    limite_minuto: Option<&str>,
) -> Problema {
    let scritto = match serde_json::from_str::<Value>(testo) {
        Ok(v @ Value::Object(_)) => v,
        _ => Value::Object(Map::new()),
    };
    let vuoto = Value::String(String::new());
    let e0 = py::get(&scritto, "error");
    let errore = if e0.is_object() {
        e0.clone()
    } else {
        let m = py::o(
            e0,
            py::o(
                py::get(&scritto, "message"),
                py::o(py::get(&scritto, "detail"), &vuoto),
            ),
        );
        json!({"message": m})
    };
    let dettaglio = errore.get("message").map(py::testo).unwrap_or_default();
    // Google also says which limit was hit and when to retry
    let mut attesa: Option<f64> = None;
    let mut quote: Vec<Value> = Vec::new();
    for pezzo in errore
        .get("details")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
    {
        if !pezzo.is_object() {
            continue;
        }
        if let Some(c) = RE_RITARDO.captures(&py::testo_o(py::get(pezzo, "retryDelay"))) {
            attesa = c[1].parse().ok();
        }
        for v in pezzo
            .get("violations")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
        {
            if v.is_object() {
                let q = py::o(py::get(v, "quotaId"), py::get(v, "quotaMetric"));
                quote.push(Value::String(py::testo_o(q)));
            }
        }
    }
    let giornaliero = quote
        .iter()
        .filter_map(Value::as_str)
        .any(|q| q.contains("PerDay") || q.to_lowercase().contains("per_day"));
    if attesa.is_none() && codice == 429 {
        // the other services say it in the header
        attesa = retry_after
            .and_then(crate::cibo::num_str)
            .filter(|d| (0.0..=3600.0).contains(d));
    }
    let limiti = if codice == 429 {
        format!(
            " | limiti: {}, riprovare tra {} s",
            py::repr(&Value::Array(quote)),
            attesa
                .map(crate::pyjson::float_repr)
                .unwrap_or("None".into())
        )
    } else {
        String::new()
    };
    log!(
        "AI: errore {} {}{}",
        codice,
        py::taglia(&dettaglio, 160),
        limiti
    );
    let base = Problema {
        remoto: Some(codice as i64),
        dettaglio: dettaglio.clone(),
        ..Default::default()
    };
    // Mistral: a model the account's plan does not include, or that no longer exists. Not the key's fault, and
    // waiting does not help: another model is tried.
    let tipo = py::testo_o(py::get(&scritto, "type"));
    let zero = codice == 429 && limite_minuto.is_some_and(|v| v.trim() == "0");
    if zero
        || (codice == 403
            && (tipo == "tier_not_allowed" || dettaglio.contains("subscription tier")))
        || ((codice == 400 || codice == 404) && tipo == "invalid_model")
    {
        return Problema {
            codice: 429,
            testo:
                "Con il tuo piano questo servizio non lascia usare i modelli che servono all'app."
                    .into(),
            remoto: Some(429),
            giornaliero: true,
            perche: Some("non lascia usare i suoi modelli con questo piano".into()),
            chiuso: true,
            ..base
        };
    }
    if codice == 401
        || codice == 403
        || dettaglio.contains("API key")
        || dettaglio.contains("api key")
    {
        let perche = if dettaglio.is_empty() {
            String::new()
        } else {
            format!(
                " Il servizio dice: {}",
                crate::cibo::pulisci(&dettaglio, 160)
            )
        };
        return Problema {
            codice: 502,
            testo: format!("Il servizio non accetta questa chiave.{perche}"),
            chiave: true,
            ..base
        };
    }
    if codice == 429 {
        let testo = if giornaliero {
            "Per oggi le richieste gratuite di questo servizio sono finite: riprova domani."
        } else {
            "Il servizio gratuito ha un limite al minuto: riprova tra poco."
        };
        return Problema {
            codice: 429,
            testo: testo.into(),
            attesa,
            giornaliero,
            ..base
        };
    }
    Problema {
        codice: 502,
        testo: format!("Il servizio di AI non ha risposto bene (errore {codice}). Riprova."),
        ..base
    }
}

/// The service said "too many requests", is overloaded or did not answer in time: worth trying elsewhere.
pub fn stanco(e: &Problema) -> bool {
    !e.chiave && e.remoto.is_none_or(|r| r == 429 || r >= 500)
}

#[cfg(test)]
mod test {
    use super::*;

    #[test]
    fn errori_dei_servizi() {
        let e = problema_da(
            429,
            r#"{"error":{"message":"quota","details":[{"retryDelay":"7s","violations":[{"quotaId":"X-FreeTier"}]}]}}"#,
            None,
            None,
        );
        assert_eq!((e.codice, e.attesa, e.giornaliero), (429, Some(7.0), false));
        let e = problema_da(
            429,
            r#"{"error":{"message":"q","details":[{"violations":[{"quotaId":"GenerateRequestsPerDayPerProjectPerModel"}]}]}}"#,
            None,
            None,
        );
        assert!(e.giornaliero && e.testo.contains("domani"));
        let e = problema_da(429, r#"{"message":"Rate limit"}"#, None, Some("0"));
        assert!(e.chiuso && e.giornaliero);
        let e = problema_da(
            400,
            r#"{"error":{"message":"API key not valid."}}"#,
            None,
            None,
        );
        assert!(e.chiave && e.codice == 502 && e.testo.ends_with("API key not valid."));
        let e = problema_da(429, r#"{"message":"x"}"#, Some("3"), None);
        assert_eq!(e.attesa, Some(3.0));
        assert!(stanco(&problema_da(503, "{}", None, None)));
    }
}
