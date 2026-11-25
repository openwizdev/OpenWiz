use std::fs::{self, DirBuilder, OpenOptions};
use std::io::{self, Read, Write};
use std::os::unix::fs::{DirBuilderExt, OpenOptionsExt};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};

use super::protocol::Surface;

const CODE_TTL_SECS: u64 = 600;
static ENTROPY_COUNTER: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Debug, Serialize, Deserialize)]
struct PendingCode {
    code: String,
    expires_at: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
struct ActiveToken {
    token: String,
    surface: Surface,
    created_at: u64,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
struct PairingState {
    pending_codes: Vec<PendingCode>,
    tokens: Vec<ActiveToken>,
}

#[derive(Clone, Debug)]
pub struct PairingStore {
    path: Option<PathBuf>,
    state: PairingState,
}

impl PairingStore {
    pub fn in_memory() -> Self {
        Self {
            path: None,
            state: PairingState::default(),
        }
    }

    pub fn from_file(path: PathBuf) -> io::Result<Self> {
        let mut store = Self {
            path: Some(path),
            state: PairingState::default(),
        };
        store.reload_if_backed()?;
        Ok(store)
    }

    pub fn default_file_path() -> Option<PathBuf> {
        let var = |name: &str| std::env::var_os(name);
        crate::state::default_state_dir(&var)
            .ok()
            .map(|dir| dir.join("ghost").join("pairing.json"))
    }

    pub fn issue_code(&mut self) -> io::Result<String> {
        self.reload_if_backed()?;
        let now = now_secs();
        self.prune_expired(now);
        let raw = random_hex(8);
        let code = format!(
            "GW-{}-{}-{}",
            raw[0..4].to_ascii_uppercase(),
            raw[4..8].to_ascii_uppercase(),
            raw[8..12].to_ascii_uppercase(),
        );
        self.state.pending_codes.push(PendingCode {
            code: code.clone(),
            expires_at: now.saturating_add(CODE_TTL_SECS),
        });
        self.save_if_backed()?;
        Ok(code)
    }

    pub fn exchange_code(&mut self, code: &str, surface: Surface) -> io::Result<Option<String>> {
        self.reload_if_backed()?;
        let now = now_secs();
        self.prune_expired(now);

        let mut matched_idx = None;
        for (i, entry) in self.state.pending_codes.iter().enumerate() {
            if ct_eq(entry.code.as_bytes(), code.as_bytes()) && matched_idx.is_none() {
                matched_idx = Some(i);
            }
        }
        let Some(idx) = matched_idx else {
            return Ok(None);
        };
        self.state.pending_codes.remove(idx);

        let token = format!("tok_{}", random_hex(16));
        self.state.tokens.push(ActiveToken {
            token: token.clone(),
            surface,
            created_at: now,
        });
        self.save_if_backed()?;
        Ok(Some(token))
    }

    pub fn verify_token(&mut self, candidate: &str) -> bool {
        let _ = self.reload_if_backed();
        let mut ok = false;
        for entry in &self.state.tokens {
            if ct_eq(entry.token.as_bytes(), candidate.as_bytes()) {
                ok = true;
            }
        }
        ok
    }

    pub fn revoke_token(&mut self, candidate: &str) -> io::Result<bool> {
        self.reload_if_backed()?;
        let before = self.state.tokens.len();
        self.state
            .tokens
            .retain(|entry| !ct_eq(entry.token.as_bytes(), candidate.as_bytes()));
        let removed = self.state.tokens.len() < before;
        if removed {
            self.save_if_backed()?;
        }
        Ok(removed)
    }

    fn prune_expired(&mut self, now: u64) {
        self.state.pending_codes.retain(|c| c.expires_at > now);
    }

    fn reload_if_backed(&mut self) -> io::Result<()> {
        let Some(path) = &self.path else {
            return Ok(());
        };
        match fs::read_to_string(path) {
            Ok(text) => {
                if let Ok(parsed) = serde_json::from_str::<PairingState>(&text) {
                    self.state = parsed;
                }
                Ok(())
            }
            Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(()),
            Err(e) => Err(e),
        }
    }

    fn save_if_backed(&self) -> io::Result<()> {
        let Some(path) = &self.path else {
            return Ok(());
        };
        if let Some(parent) = path.parent() {
            ensure_private_dir(parent)?;
        }
        let tmp = path.with_extension(format!(
            "tmp.{}",
            ENTROPY_COUNTER.fetch_add(1, Ordering::Relaxed)
        ));
        let json = serde_json::to_vec_pretty(&self.state).map_err(io::Error::other)?;
        {
            let mut f = OpenOptions::new()
                .write(true)
                .create(true)
                .truncate(true)
                .mode(0o600)
                .open(&tmp)?;
            f.write_all(&json)?;
            f.sync_all()?;
        }
        fs::rename(&tmp, path)
    }
}

pub fn ct_eq(a: &[u8], b: &[u8]) -> bool {
    let max_len = a.len().max(b.len());
    let mut diff: u8 = if a.len() == b.len() { 0 } else { 1 };
    for i in 0..max_len {
        let x = a.get(i).copied().unwrap_or(0);
        let y = b.get(i).copied().unwrap_or(0);
        diff |= x ^ y;
    }
    diff == 0
}

fn ensure_private_dir(dir: &Path) -> io::Result<()> {
    if dir.exists() {
        return Ok(());
    }
    DirBuilder::new().recursive(true).mode(0o700).create(dir)
}

fn now_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

fn random_hex(num_bytes: usize) -> String {
    let mut buf = vec![0u8; num_bytes];
    let filled = fs::File::open("/dev/urandom")
        .and_then(|mut f| f.read_exact(&mut buf))
        .is_ok();
    if !filled {
        let mut seed = now_secs()
            ^ (u64::from(std::process::id()) << 32)
            ^ ENTROPY_COUNTER.fetch_add(1, Ordering::Relaxed);
        for b in &mut buf {
            seed = seed
                .wrapping_mul(6364136223846793005)
                .wrapping_add(1442695040888963407);
            *b = (seed >> 56) as u8;
        }
    }
    let mut out = String::with_capacity(num_bytes * 2);
    for b in buf {
        out.push_str(&format!("{b:02x}"));
    }
    out
}
