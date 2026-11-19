#![forbid(unsafe_code)]

//! EverFit server: serves the app's files and keeps each person's data in SQLite. Drop-in replacement of the Python
//! server (app/server/server.py): same flags, environment, API and database.
//!
//!     fit --root public --data /data --port 8080

mod accesso;
mod ai;
mod ai_gemini;
mod ai_http;
mod ai_locale;
mod ai_mistral;
mod api;
mod assistente;
mod assistente_azioni;
mod chiavi;
mod cibo;
mod conf;
mod db;
mod db_avvisi;
mod db_stato;
mod errore;
mod lavori;
mod parere;
mod ponte;
mod py;
mod pyjson;
mod server;
mod spinta;
mod statico;

use bytes::Bytes;
use http_body_util::{BodyExt, Full, Limited};
use hyper::body::Incoming;
use hyper::header::{HeaderName, HeaderValue};
use hyper::{Request, Response, StatusCode};
use hyper_util::rt::{TokioIo, TokioTimer};
use server::{App, MAX_CORPO, Richiesta, Risposta};
use std::collections::HashMap;
use std::convert::Infallible;
use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;
use tokio::net::TcpListener;

/// Headers must arrive within this time, bodies too: a client that stalls does not hold a thread forever.
const TEMPO_INTESTAZIONI: Duration = Duration::from_secs(30);
const TEMPO_CORPO: Duration = Duration::from_secs(60);
/// On SIGTERM, how long open requests (the longest is a 30 s scale long-poll) get to finish.
const TEMPO_CHIUSURA: Duration = Duration::from_secs(35);

struct Argomenti {
    root: PathBuf,
    data: PathBuf,
    host: String,
    port: u16,
    piani: Option<PathBuf>,
}

const USO: &str =
    "uso: fit [--root ROOT] [--data DATA] [--host HOST] [--port PORT] [--piani PIANI]";

fn argomenti() -> Result<Argomenti, String> {
    let mut a = Argomenti {
        root: "public".into(),
        data: "data".into(),
        host: "0.0.0.0".into(),
        port: 8080,
        piani: None,
    };
    let mut it = std::env::args().skip(1);
    while let Some(arg) = it.next() {
        if arg == "-h" || arg == "--help" {
            println!("{USO}");
            std::process::exit(0);
        }
        let (nome, valore) = match arg.split_once('=') {
            Some((n, v)) if n.starts_with("--") => (n.to_string(), v.to_string()),
            _ => (
                arg.clone(),
                it.next().ok_or_else(|| format!("{arg}: manca il valore"))?,
            ),
        };
        match nome.as_str() {
            "--root" => a.root = valore.into(),
            "--data" => a.data = valore.into(),
            "--host" => a.host = valore,
            "--port" => {
                a.port = valore
                    .parse()
                    .map_err(|_| format!("--port: numero non valido ({valore})"))?
            }
            "--piani" => a.piani = Some(valore.into()),
            _ => return Err(format!("argomento sconosciuto: {nome}")),
        }
    }
    Ok(a)
}

fn inizia_log() {
    use tracing_subscriber::{EnvFilter, fmt};
    let filtro = EnvFilter::try_from_env("FIT_LOG").unwrap_or_else(|_| EnvFilter::new("info"));
    // JSON lines for the container (structured, one event per line); FIT_LOG_FORMATO=testo for a terminal
    if std::env::var("FIT_LOG_FORMATO").as_deref() == Ok("testo") {
        fmt().with_env_filter(filtro).with_target(false).init();
    } else {
        fmt()
            .json()
            .flatten_event(true)
            .with_current_span(false)
            .with_env_filter(filtro)
            .with_target(false)
            .init();
    }
}

/// Reads the body the way server.py does: always (a body left in the pipe would be read glued to the next request
/// on the same connection), never more than MAX_CORPO. None when too large or with an invalid length.
async fn leggi_corpo(req: Request<Incoming>) -> (hyper::http::request::Parts, Option<Vec<u8>>) {
    let (parti, corpo) = req.into_parts();
    let lunghezza = parti
        .headers
        .get(hyper::header::CONTENT_LENGTH)
        .map(|v| v.to_str().ok().and_then(|s| s.trim().parse::<usize>().ok()));
    if matches!(lunghezza, Some(None)) || matches!(lunghezza, Some(Some(n)) if n > MAX_CORPO) {
        return (parti, None);
    }
    let letto = tokio::time::timeout(TEMPO_CORPO, Limited::new(corpo, MAX_CORPO).collect()).await;
    let grezzo = match letto {
        Ok(Ok(c)) => Some(c.to_bytes().to_vec()),
        _ => None,
    };
    (parti, grezzo)
}

fn costruisci(r: Risposta, head: bool) -> Response<Full<Bytes>> {
    let n = r.corpo.len();
    let mut out = Response::new(Full::new(if head {
        Bytes::new()
    } else {
        Bytes::from(r.corpo)
    }));
    *out.status_mut() = StatusCode::from_u16(r.codice).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR);
    let h = out.headers_mut();
    let mut metti = |k: &str, v: &str| {
        if let (Ok(k), Ok(v)) = (HeaderName::try_from(k), HeaderValue::try_from(v)) {
            h.append(k, v);
        }
    };
    metti("Server", "fit");
    metti("Content-Type", &r.tipo);
    metti("Content-Length", &n.to_string());
    metti("Cache-Control", r.cache);
    metti("X-Content-Type-Options", "nosniff");
    metti("Referrer-Policy", "no-referrer");
    for (k, v) in &r.extra {
        metti(k, v);
    }
    if r.chiudi {
        metti("Connection", "close");
    }
    out
}

async fn servi(app: Arc<App>, req: Request<Incoming>) -> Result<Response<Full<Bytes>>, Infallible> {
    let (parti, grezzo) = leggi_corpo(req).await;
    let metodo = parti.method.as_str().to_string();
    let path = parti.uri.path().to_string();
    let mut intestazioni: HashMap<String, Vec<String>> = HashMap::new();
    for (k, v) in &parti.headers {
        intestazioni
            .entry(k.as_str().to_string())
            .or_default()
            .push(py::latin1(v.as_bytes()));
    }
    let head = metodo == "HEAD";
    let noti = ["GET", "HEAD", "PUT", "POST", "DELETE"];
    if !noti.contains(&metodo.as_str()) {
        // BaseHTTPRequestHandler answers 501 to methods it has no do_<METHOD> for
        return Ok(costruisci(
            Risposta::html(501, b"Unsupported method".to_vec()),
            false,
        ));
    }
    let richiesta = Richiesta {
        metodo: metodo.clone(),
        path: path.clone(),
        query: parti.uri.query().unwrap_or("").to_string(),
        intestazioni,
        grezzo,
    };
    let esito = tokio::task::spawn_blocking(move || server::gestisci(&app, &richiesta)).await;
    let (risposta, chi) = match esito {
        Ok(r) => r,
        Err(e) => {
            tracing::error!(errore = %e, "richiesta interrotta");
            (
                Risposta::json(500, &serde_json::json!({"errore": "errore interno"})),
                None,
            )
        }
    };
    // without the part after "?": searches and weighing identifiers pass there
    if !server::zitto(&path) {
        let chi = chi.map(|u| format!("u{u}")).unwrap_or_else(|| "-".into());
        tracing::info!(
            codice = risposta.codice,
            "{chi} {metodo} {path} {}",
            risposta.codice
        );
    }
    Ok(costruisci(risposta, head))
}

/// FitAI answered and nobody came to collect the answer (app closed): a notification goes out.
fn avviso_fitai(app: Arc<App>) -> lavori::AlTermine {
    let re = py::re(r"\*\*|\s+");
    Box::new(move |utente, numero, codice, risposta| {
        if codice != 200 {
            return;
        }
        let testo = py::testo_o(py::get(risposta, "testo"));
        let testo = re
            .replace_all(
                &testo,
                |m: &regex::Captures| if &m[0] == "**" { "" } else { " " },
            )
            .trim()
            .to_string();
        let breve = if testo.chars().count() > 140 {
            format!("{}…", py::taglia(&testo, 140))
        } else {
            testo
        };
        if let Err(e) = app.dati.avvisa(
            utente,
            &format!("fitai-{numero}"),
            "FitAI ti ha risposto",
            &breve,
            Some("./?apri=fitai"),
        ) {
            tracing::warn!("avviso FitAI non partito: {}", e.testo);
        }
    })
}

fn in_sottofondo(app: &Arc<App>) {
    // Conversations with the assistant are not kept: once a week, Sunday to Monday night (2-4 server time, UTC),
    // those of every account are deleted.
    let a = app.clone();
    std::thread::spawn(move || {
        loop {
            std::thread::sleep(Duration::from_secs(600));
            let ora = jiff::Timestamp::now().to_zoned(jiff::tz::TimeZone::UTC);
            let lunedi = ora.date().to_string();
            if ora.weekday() != jiff::civil::Weekday::Monday || !(2..4).contains(&ora.hour()) {
                continue;
            }
            let giro = || -> errore::Esito<()> {
                if a.dati.impostazione("chat_pulite", None)?.as_deref() != Some(lunedi.as_str()) {
                    log!(
                        "pulizia: conversazioni cancellate per {} account",
                        a.dati.pulisci_chat()?
                    );
                    a.dati.impostazione("chat_pulite", Some(&lunedi))?;
                }
                Ok(())
            };
            if let Err(e) = giro() {
                log!(
                    "pulizia: non riuscita ({})",
                    if e.database { "database" } else { "errore" }
                );
            }
        }
    });
    // lunch and dinner reminders: one round a minute
    let a = app.clone();
    std::thread::spawn(move || {
        loop {
            std::thread::sleep(Duration::from_secs(60));
            if let Err(e) = a.dati.giro_promemoria() {
                log!(
                    "promemoria: giro non riuscito ({})",
                    if e.database { "database" } else { "errore" }
                );
            }
        }
    });
    if !conf::conf().locale_url.is_empty() {
        // the AI on the VM: loaded now and kept in memory (a nudge every six hours), so what it read is not lost
        std::thread::spawn(|| {
            std::thread::sleep(Duration::from_secs(15));
            loop {
                ai_locale::sveglia();
                std::thread::sleep(Duration::from_secs(6 * 3600));
            }
        });
    }
}

async fn segnale_di_fine() {
    let ctrl_c = async {
        let _ = tokio::signal::ctrl_c().await;
    };
    #[cfg(unix)]
    let term = async {
        match tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate()) {
            Ok(mut s) => {
                s.recv().await;
            }
            Err(_) => std::future::pending::<()>().await,
        }
    };
    #[cfg(not(unix))]
    let term = std::future::pending::<()>();
    tokio::select! { () = ctrl_c => {}, () = term => {} }
}

fn main() -> std::process::ExitCode {
    if std::env::args().skip(1).eq(["--healthcheck"]) {
        use std::io::{Read, Write};
        use std::net::{Ipv4Addr, TcpStream};
        let timeout = Duration::from_secs(3);
        let address = SocketAddr::from((Ipv4Addr::LOCALHOST, 8080));
        let check = || -> std::io::Result<bool> {
            let mut stream = TcpStream::connect_timeout(&address, timeout)?;
            stream.set_read_timeout(Some(timeout))?;
            stream.set_write_timeout(Some(timeout))?;
            stream.write_all(
                b"GET /api/health HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n",
            )?;
            let mut status = [0; 13];
            stream.read_exact(&mut status)?;
            Ok(&status == b"HTTP/1.1 200 ")
        };
        return if matches!(check(), Ok(true)) {
            std::process::ExitCode::SUCCESS
        } else {
            std::process::ExitCode::FAILURE
        };
    }
    let a = match argomenti() {
        Ok(a) => a,
        Err(e) => {
            eprintln!("{USO}\nfit: errore: {e}");
            return std::process::ExitCode::from(2);
        }
    };
    inizia_log();
    let piani = a
        .piani
        .clone()
        .unwrap_or_else(|| a.root.join("..").join("server").join("piani"));
    let dati = match db::Dati::new(&a.data, piani) {
        Ok(d) => d,
        Err(e) => {
            tracing::error!("database non aperto: {}", e.testo);
            return std::process::ExitCode::FAILURE;
        }
    };
    let app = Arc::new(App {
        root: a.root.clone(),
        dati,
        ponte: ponte::Ponte::default(),
    });
    let rt = match tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
    {
        Ok(rt) => rt,
        Err(e) => {
            tracing::error!("runtime non avviato: {e}");
            return std::process::ExitCode::FAILURE;
        }
    };
    let esito = rt.block_on(ascolta(app.clone(), &a));
    rt.shutdown_timeout(Duration::from_secs(1));
    // everything written so far goes into the main file: a copy of fit.db alone is then complete
    match app.dati.con().and_then(|c| {
        Ok(c.query_row("PRAGMA wal_checkpoint(TRUNCATE)", [], |r| {
            r.get::<_, i64>(0)
        })?)
    }) {
        Ok(_) => log!("fit fermato, database consolidato"),
        Err(e) => tracing::warn!("checkpoint finale non riuscito: {}", e.testo),
    }
    esito
}

async fn ascolta(app: Arc<App>, a: &Argomenti) -> std::process::ExitCode {
    let indirizzo = format!("{}:{}", a.host, a.port);
    let listener = match TcpListener::bind(&indirizzo).await {
        Ok(l) => l,
        Err(e) => {
            tracing::error!("non riesco ad ascoltare su {indirizzo}: {e}");
            return std::process::ExitCode::FAILURE;
        }
    };
    log!(
        "fit in ascolto su {}:{}, file in {}, database {}, accesso {}",
        a.host,
        a.port,
        a.root.display(),
        app.dati.percorso.display(),
        if accesso::acceso() {
            "con codice"
        } else {
            "libero (solo in locale)"
        }
    );
    lavori::al_termine(avviso_fitai(app.clone()));
    in_sottofondo(&app);
    let mut http = hyper::server::conn::http1::Builder::new();
    http.timer(TokioTimer::new())
        .header_read_timeout(TEMPO_INTESTAZIONI)
        // header names written as http.server writes them ("Location", "Set-Cookie"): clients that read them
        // case-sensitively, like the black-box tests, see the same as with the Python server
        .title_case_headers(true)
        .keep_alive(true);
    let chiusura = hyper_util::server::graceful::GracefulShutdown::new();
    let fine = segnale_di_fine();
    tokio::pin!(fine);
    loop {
        tokio::select! {
            accettata = listener.accept() => {
                let (flusso, _da): (_, SocketAddr) = match accettata {
                    Ok(x) => x,
                    Err(e) => {
                        tracing::warn!("connessione non accettata: {e}");
                        continue;
                    }
                };
                let app = app.clone();
                let servizio = hyper::service::service_fn(move |req| servi(app.clone(), req));
                let conn = chiusura.watch(http.serve_connection(TokioIo::new(flusso), servizio));
                tokio::spawn(async move {
                    let _ = conn.await;
                });
            }
            () = &mut fine => {
                log!("segnale di fine: smetto di accettare, aspetto le richieste aperte");
                break;
            }
        }
    }
    drop(listener);
    if tokio::time::timeout(TEMPO_CHIUSURA, chiusura.shutdown())
        .await
        .is_err()
    {
        tracing::warn!(
            "richieste ancora aperte dopo {} s: chiudo lo stesso",
            TEMPO_CHIUSURA.as_secs()
        );
    }
    std::process::ExitCode::SUCCESS
}
