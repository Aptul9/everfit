//! Environment variables, read once at start like the Python modules do at import.

use std::env;
use std::sync::LazyLock;

fn var(k: &str, base: &str) -> String {
    env::var(k).unwrap_or_else(|_| base.to_string())
}

fn num<T: std::str::FromStr>(k: &str, base: T) -> T {
    match env::var(k) {
        Ok(v) => match v.trim().parse() {
            Ok(n) => n,
            Err(_) => {
                eprintln!("{k}: valore non valido ({v:?})");
                std::process::exit(1);
            }
        },
        Err(_) => base,
    }
}

fn elenco(testo: &str) -> Vec<String> {
    testo
        .split(',')
        .map(|m| m.trim().to_string())
        .filter(|m| !m.is_empty())
        .collect()
}

pub struct Conf {
    // accesso.py
    pub cookie_vecchio: String,
    pub codice_capo: String,
    pub hash_capo: String,
    pub nome_capo: String,
    pub utente_capo: String,
    pub acceso: bool,
    // EverID (OpenID Connect): off while issuer, client id or secret is missing
    pub oidc_issuer: String,
    pub oidc_client_id: String,
    pub oidc_segreto: String,
    pub oidc_gruppo: String,
    pub email_capo: String,
    /// username and password login next to EverID; always on while EverID is not configured
    pub login_codice: bool,
    // server.py
    pub fuso: jiff::tz::TimeZone,
    // spinta.py
    pub chi_siamo: String,
    pub spinta_prova: String,
    // cibo.py
    pub ai_url: String,
    pub ai_modello: String,
    pub gemini_url: String,
    pub gemini_modello: String,
    pub gemini_chat_leggero: bool,
    pub mistral_url: String,
    pub mistral_grandi: Vec<String>,
    pub mistral_piccoli: Vec<String>,
    pub mistral_conv_url: String,
    pub locale_url: String,
    pub locale_modello: String,
    pub locale_per_tutti: bool,
    pub locale_fili: i64,
    pub locale_finestra: i64,
    pub locale_lotto: i64,
    pub locale_sveglio: String,
    pub locale_segnalibri: bool,
    pub attesa_locale: f64,
    pub attesa_assistente: f64,
    pub attesa_altro: f64,
    pub attesa_riserva: f64,
    // assistente.py
    pub all_ora: usize,
    pub spinta_ai: f64,
    pub locale_dopo: f64,
}

pub static CONF: LazyLock<Conf> = LazyLock::new(|| {
    let codice_capo: String = var("FIT_CODICE", "")
        .chars()
        .filter(|c| crate::py::alnum(*c))
        .collect();
    let nome_capo = {
        let n = var("FIT_NOME", "").trim().to_string();
        if n.is_empty() { "Admin".to_string() } else { n }
    };
    let utente = env::var("FIT_UTENTE")
        .ok()
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| nome_capo.clone());
    let utente_capo = crate::accesso::nome_utente(&utente).unwrap_or_else(|| "admin".into());
    let fuso_nome = var("FIT_FUSO", "Europe/Rome");
    let fuso = jiff::tz::TimeZone::get(&fuso_nome).unwrap_or_else(|_| {
        eprintln!("FIT_FUSO: fuso sconosciuto ({fuso_nome:?})");
        std::process::exit(1);
    });
    let mistral_url = var(
        "FIT_MISTRAL_URL",
        "https://api.mistral.ai/v1/chat/completions",
    );
    let mistral_conv_url = match env::var("FIT_MISTRAL_CONV_URL") {
        Ok(v) => v,
        Err(_) if mistral_url.contains("/chat/completions") => {
            mistral_url.replace("/chat/completions", "/conversations")
        }
        Err(_) => String::new(),
    };
    let oidc_issuer = var("FIT_OIDC_ISSUER", "").trim().to_string();
    let oidc_client_id = var("FIT_OIDC_CLIENT_ID", "").trim().to_string();
    let oidc_segreto = var("FIT_OIDC_CLIENT_SECRET", "").trim().to_string();
    let oidc = !oidc_issuer.is_empty() && !oidc_client_id.is_empty() && !oidc_segreto.is_empty();
    Conf {
        cookie_vecchio: var("FIT_COOKIE", "").trim().to_string(),
        acceso: !codice_capo.is_empty(),
        login_codice: !oidc || var("FIT_LOGIN_CODICE", "1").trim() != "0",
        oidc_issuer: if oidc { oidc_issuer } else { String::new() },
        oidc_client_id,
        oidc_segreto,
        oidc_gruppo: var("FIT_OIDC_GRUPPO", "app-fit").trim().to_string(),
        email_capo: var("FIT_OWNER_EMAIL", "").trim().to_lowercase(),
        codice_capo,
        hash_capo: var("FIT_OWNER_HASH", ""),
        nome_capo,
        utente_capo,
        fuso,
        chi_siamo: var("FIT_SITO", "https://fit.example.com"),
        spinta_prova: var("FIT_SPINTA_PROVA", ""),
        ai_url: var("FIT_AI_URL", "https://api.anthropic.com/v1/messages"),
        ai_modello: var("FIT_MODELLO_FOTO", "claude-opus-5-5"),
        gemini_url: var(
            "FIT_GEMINI_URL",
            "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent",
        ),
        gemini_modello: var("FIT_MODELLO_GEMINI", "gemini-3.8-flash"),
        gemini_chat_leggero: var("FIT_GEMINI_CHAT", "leggero") != "principale",
        mistral_grandi: elenco(&var(
            "FIT_MODELLI_MISTRAL",
            "mistral-medium-latest,mistral-small-latest",
        )),
        mistral_piccoli: elenco(&var(
            "FIT_MODELLI_MISTRAL_PICCOLI",
            "ministral-14b-latest,ministral-8b-latest",
        )),
        mistral_url,
        mistral_conv_url,
        locale_url: var("FIT_LOCALE_URL", "").trim_end_matches('/').to_string(),
        locale_modello: var("FIT_MODELLO_LOCALE", "gemma4:e4b"),
        locale_per_tutti: var("FIT_LOCALE_PER", "capo") == "tutti",
        locale_fili: num("FIT_LOCALE_FILI", 3),
        locale_finestra: num("FIT_LOCALE_FINESTRA", 8192),
        locale_lotto: num("FIT_LOCALE_LOTTO", 128),
        locale_sveglio: var("FIT_LOCALE_SVEGLIO", "24h"),
        locale_segnalibri: var("FIT_LOCALE_SEGNALIBRI", "") == "1",
        attesa_locale: num("FIT_ATTESA_LOCALE", 900.0),
        attesa_assistente: num("FIT_ATTESA_ASSISTENTE", 30.0),
        attesa_altro: num("FIT_ATTESA_AI", 45.0),
        attesa_riserva: num("FIT_ATTESA_RISERVA", 15.0),
        all_ora: num("FIT_DOMANDE_ORA", 60),
        spinta_ai: num("FIT_SPINTA_AI", 12.0),
        locale_dopo: num("FIT_LOCALE_DOPO", 25.0),
    }
});

pub fn conf() -> &'static Conf {
    &CONF
}
