//! EverID login: OpenID Connect authorization code flow with PKCE against `FIT_OIDC_ISSUER`. The EverID account
//! (`sub`) gets its own EverFit account at the first login, the admin one for the owner, and needs the
//! `FIT_OIDC_GRUPPO` group. Logout ends the EverID session too.

use crate::accesso;
use crate::conf::conf;
use crate::errore::{Esito, Problema};
use crate::py;
use crate::server::{Ctx, Risposta};
use base64::Engine;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::sync::Mutex;
use std::time::{Duration, Instant};

/// how long the trip to EverID and back may take
const VIAGGIO: f64 = 600.0;
const COOKIE: &str = "fito";
const SCOPE: &str = "openid email profile";
/// the EverID group whose members may take over the admin account with the owner's e-mail
const ADMIN: &str = "everid-admins";

pub fn attivo() -> bool {
    accesso::acceso() && !conf().oidc_issuer.is_empty()
}

fn ritorno() -> String {
    format!("{}/oidc/callback", conf().chi_siamo.trim_end_matches('/'))
}

fn stesso_issuer(a: &str, b: &str) -> bool {
    a.trim_end_matches('/') == b.trim_end_matches('/')
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
        Problema::new(502, "EverID non risponde: riprova tra poco.")
    })?;
    let campo = |k: &str| doc.get(k).and_then(Value::as_str).unwrap_or("").to_string();
    if !stesso_issuer(&campo("issuer"), issuer) {
        tracing::error!("EverID: issuer {:?} diverso da {issuer:?}", campo("issuer"));
        return Err(Problema::new(502, "EverID non è configurato bene."));
    }
    let i = Indirizzi {
        autorizza: campo("authorization_endpoint"),
        gettone: campo("token_endpoint"),
        fine: campo("end_session_endpoint"),
    };
    if i.autorizza.is_empty() || i.gettone.is_empty() {
        return Err(Problema::new(502, "EverID non è configurato bene."));
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

/// state, PKCE verifier and nonce travel in a signed cookie that lives only for the trip.
struct Viaggio {
    stato: String,
    verificatore: String,
    nonce: String,
}

fn firma_viaggio(segreto: &str, corpo: &str) -> String {
    accesso::firma(segreto, &format!("oidc:{corpo}"))
}

fn biscotto_viaggio(segreto: &str, v: &Viaggio, ora: f64) -> String {
    let corpo = format!(
        "{}.{}.{}.{}",
        v.stato,
        v.verificatore,
        v.nonce,
        py::int(ora)
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
    let [stato, verificatore, nonce, quando] = parti.as_slice() else {
        return None;
    };
    let quando: f64 = quando.parse().ok()?;
    if !(0.0..=VIAGGIO).contains(&(ora - quando)) {
        return None;
    }
    Some(Viaggio {
        stato: stato.to_string(),
        verificatore: verificatore.to_string(),
        nonce: nonce.to_string(),
    })
}

const VIAGGIO_FINITO: &str = "fito=; Path=/oidc/; Max-Age=0; Secure; HttpOnly; SameSite=Lax";

/// GET /oidc/login: off to EverID.
pub fn entra(c: &Ctx) -> Esito<Risposta> {
    let i = indirizzi()?;
    let v = Viaggio {
        stato: casuale(),
        verificatore: casuale(),
        nonce: casuale(),
    };
    let mut url = url::Url::parse(&i.autorizza)
        .map_err(|_| Problema::new(502, "EverID non è configurato bene."))?;
    url.query_pairs_mut()
        .append_pair("response_type", "code")
        .append_pair("client_id", &conf().oidc_client_id)
        .append_pair("redirect_uri", &ritorno())
        .append_pair("scope", SCOPE)
        .append_pair("state", &v.stato)
        .append_pair("nonce", &v.nonce)
        .append_pair("code_challenge", &sfida(&v.verificatore))
        .append_pair("code_challenge_method", "S256");
    Ok(Risposta::testo(302, b"")
        .con("Location", String::from(url))
        .con(
            "Set-Cookie",
            biscotto_viaggio(&c.app.dati.segreto, &v, py::ora()),
        ))
}

/// Who EverID says this is, from an ID token that came straight from the token endpoint.
#[derive(Debug, PartialEq)]
pub struct Persona {
    /// the EverID account key: stable, unlike the e-mail, which EverID does not verify
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
    let guasto = || Problema::new(502, "EverID non risponde: riprova tra poco.");
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
        return Err(Problema::new(
            401,
            "Accesso con EverID non riuscito: riprova.",
        ));
    }
    serde_json::from_str::<Value>(&testo)
        .ok()
        .and_then(|v| v.get("id_token").and_then(Value::as_str).map(String::from))
        .ok_or_else(guasto)
}

fn pagina(codice: u16, testo: &str) -> Risposta {
    Risposta::html(codice, accesso::pagina(testo)).con("Set-Cookie", VIAGGIO_FINITO)
}

/// GET /oidc/callback: back from EverID with a code.
pub fn torna(c: &mut Ctx) -> Esito<Risposta> {
    let q = py::parse_qs(&c.req.query);
    let campo = |k: &str| q.get(k).cloned().unwrap_or_default();
    if !campo("error").is_empty() {
        tracing::info!("EverID: ritorno con errore {:?}", campo("error"));
        return Ok(pagina(401, "Accesso con EverID annullato."));
    }
    let ora = py::ora();
    let valore = accesso::leggi_cookie(c.req.intestazione("Cookie"), COOKIE);
    let Some(v) = leggi_viaggio(&c.app.dati.segreto, &valore, ora) else {
        return Ok(pagina(400, "Accesso scaduto: riprova."));
    };
    if campo("code").is_empty() || !accesso::uguali(&campo("state"), &v.stato) {
        return Ok(pagina(400, "Accesso scaduto: riprova."));
    }
    let i = indirizzi()?;
    let id_token = match scambia(&i, &campo("code"), &v.verificatore) {
        Ok(t) => t,
        Err(e) => return Ok(pagina(e.codice, &e.testo)),
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
            return Ok(pagina(401, "Accesso con EverID non riuscito: riprova."));
        }
    };
    let gruppo = &conf().oidc_gruppo;
    if !p.gruppi.iter().any(|g| g == gruppo) {
        tracing::info!("EverID: {} senza il gruppo {gruppo}", p.email);
        return Ok(pagina(
            403,
            "Il tuo account EverID non ha accesso a EverFit.",
        ));
    }
    let conf = conf();
    // the owner's e-mail alone is not enough: anyone could type it in their EverID profile
    let capo = !conf.email_capo.is_empty()
        && p.email == conf.email_capo
        && p.gruppi.iter().any(|g| g == ADMIN);
    let utente = match c.app.dati.da_everid(&p, capo) {
        Ok(u) => u,
        Err(e) if !e.database => return Ok(pagina(e.codice, &e.testo)),
        Err(e) => return Err(e),
    };
    let gettone = c.app.dati.apri_sessione(utente.id, "cookie", None, None)?;
    c.app.dati.segna_id_token(&gettone, &id_token)?;
    let b = accesso::biscotti(&gettone, &utente.nome);
    c.io = Some(utente);
    Ok(Risposta::testo(303, b"")
        .con("Location", "/")
        .con("Set-Cookie", VIAGGIO_FINITO)
        .biscotti(b))
}

/// Logout of a session that came from EverID: where to send the browser so the EverID session ends too, and comes
/// back to the login page. None for every other session, and when EverID cannot be reached (the app logout still
/// happens).
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
        };
        let b = biscotto_viaggio("segreto", &v, 1000.0);
        let valore = b
            .strip_prefix("fito=")
            .and_then(|b| b.split(';').next())
            .unwrap_or("");
        let letto = leggi_viaggio("segreto", valore, 1100.0);
        assert!(letto.is_some_and(|l| l.stato == v.stato && l.nonce == v.nonce));
        assert!(leggi_viaggio("altro", valore, 1100.0).is_none());
        assert!(leggi_viaggio("segreto", valore, 1000.0 + VIAGGIO + 1.0).is_none());
        let rotto = valore.replacen('s', "t", 1);
        assert!(leggi_viaggio("segreto", &rotto, 1100.0).is_none());
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
