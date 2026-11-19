//! `Errore` (server.py) and `Problema` (cibo.py) are one type here: a status code and a sentence for the phone, plus
//! what the AI chain needs to decide where to go next. The HTTP layer maps it to the same status and JSON as Python.

#[derive(Debug, Clone, Default)]
pub struct Problema {
    pub codice: u16,
    pub testo: String,
    /// the service refused the key
    pub chiave: bool,
    /// the remote service's own status code
    pub remoto: Option<i64>,
    pub attesa: Option<f64>,
    pub giornaliero: bool,
    pub dettaglio: String,
    pub perche: Option<String>,
    pub chiuso: bool,
    /// a database error: the server answers 500 "database non disponibile"
    pub database: bool,
}

impl Problema {
    pub fn new(codice: u16, testo: impl Into<String>) -> Self {
        Problema {
            codice,
            testo: testo.into(),
            ..Default::default()
        }
    }

    /// The same error, for a request that must not be retried elsewhere ("a wrong question is wrong for all").
    pub fn per_tutti(&self) -> bool {
        self.codice < 500 && self.remoto != Some(429)
    }
}

impl std::fmt::Display for Problema {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.testo)
    }
}

impl std::error::Error for Problema {}

impl From<rusqlite::Error> for Problema {
    fn from(e: rusqlite::Error) -> Self {
        Problema {
            codice: 500,
            testo: e.to_string(),
            database: true,
            ..Default::default()
        }
    }
}

pub type Esito<T> = Result<T, Problema>;

/// `raise Errore(codice, testo)`
pub fn errore<T>(codice: u16, testo: impl Into<String>) -> Esito<T> {
    Err(Problema::new(codice, testo))
}

/// One log line (the `print(..., flush=True)` of the Python server), as a tracing event.
#[macro_export]
macro_rules! log {
    ($($t:tt)*) => {
        tracing::info!($($t)*)
    };
}
