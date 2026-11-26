use crate::{allowlist::Invocation, process};
use serde::de::{self, Deserialize, Deserializer, MapAccess, SeqAccess, Visitor};
use serde_json::{Value, json};
use std::{
    fmt,
    path::{Path, PathBuf},
    process::{Command, Stdio},
    sync::{Arc, Condvar, Mutex},
    time::{Instant, SystemTime, UNIX_EPOCH},
};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Error;
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("GitHub App request refused (details withheld)")
    }
}
impl std::error::Error for Error {}

pub trait Clock: Send + Sync {
    fn now_s(&self) -> u64;
}

pub trait Exchange: Send + Sync {
    fn exchange(
        &self,
        installation: u64,
        jwt: &str,
        body: &[u8],
        deadline: Instant,
    ) -> Result<Vec<u8>, Error>;
    fn github(
        &self,
        call: &Call<'_>,
        jwt: &str,
        deadline: Instant,
    ) -> Result<(u16, Vec<u8>), Error> {
        let _ = (call, jwt, deadline);
        Err(Error)
    }
}

pub enum Call<'a> {
    App,
    Installation { repository: &'a str },
    AccessToken { installation: u64, body: &'a [u8] },
}

pub struct SystemClock;
impl Clock for SystemClock {
    fn now_s(&self) -> u64 {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|v| v.as_secs())
            .unwrap_or(0)
    }
}

pub struct Identity {
    pub app_id: u64,
    pub installation_id: u64,
    pub repository: String,
}

pub struct App {
    root: PathBuf,
    identity: Identity,
    mode: Mode,
    gh: PathBuf,
    exchange: Arc<dyn Exchange>,
    clock: Arc<dyn Clock>,
    cache: Mutex<Cache>,
    refreshed: Condvar,
}
enum Cache {
    Empty,
    Refreshing,
    Ready(Cached),
}
#[derive(Clone)]
struct Cached {
    token: String,
    expires: u64,
}
impl App {
    pub fn open(
        root: &Path,
        identity: Identity,
        gh: PathBuf,
        exchange: Arc<dyn Exchange>,
        clock: Arc<dyn Clock>,
    ) -> Result<Self, Error> {
        let mode = match std::env::var_os("OPENWIZ_GITHUB_APP_MODE")
            .as_deref()
            .map(|m| m.to_str())
        {
            None | Some(Some("user")) => Mode::User,
            Some(Some("factory")) => Mode::Factory,
            Some(_) => return Err(Error),
        };
        Self::open_mode(root, identity, mode, gh, exchange, clock)
    }
    pub fn open_mode(
        root: &Path,
        identity: Identity,
        mode: Mode,
        gh: PathBuf,
        exchange: Arc<dyn Exchange>,
        clock: Arc<dyn Clock>,
    ) -> Result<Self, Error> {
        if !root.is_absolute() || identity.app_id == 0 || identity.installation_id == 0 {
            return Err(Error);
        }
        open_key(root, Instant::now() + std::time::Duration::from_secs(15))?;
        let repository = openwiz_core::fleet::starts::Repository::parse(&identity.repository)
            .map_err(|_| Error)?;
        let identity = Identity {
            repository: repository.as_str().to_owned(),
            ..identity
        };
        Ok(Self {
            root: root.to_owned(),
            identity,
            mode,
            gh,
            exchange,
            clock,
            cache: Mutex::new(Cache::Empty),
            refreshed: Condvar::new(),
        })
    }
    pub fn execute(&self, call: &Invocation, deadline: Instant) -> Result<Vec<u8>, Error> {
        if Instant::now() >= deadline {
            return Err(Error);
        }
        let key = open_key(&self.root, deadline)?;
        let cached = self.token(&key, deadline)?;
        if Instant::now() >= deadline {
            return Err(Error);
        }
        let left = cached
            .expires
            .checked_sub(self.clock.now_s())
            .filter(|s| *s > 0)
            .ok_or(Error)?;
        let deadline = deadline.min(Instant::now() + std::time::Duration::from_secs(left));
        process::run_app(
            &self.gh,
            call,
            &cached.token,
            &format!("github.com/{}", self.identity.repository),
            deadline,
        )
        .map_err(|_| Error)
    }
    fn token(&self, key: &Key, deadline: Instant) -> Result<Cached, Error> {
        let mut cache = self.cache.lock().map_err(|_| Error)?;
        loop {
            let now = self.clock.now_s();
            if Instant::now() >= deadline {
                return Err(Error);
            }
            match &*cache {
                Cache::Ready(cached) if now < cached.expires.saturating_sub(300) => {
                    return Ok(cached.clone());
                }
                Cache::Refreshing => {
                    let left = deadline.saturating_duration_since(Instant::now());
                    cache = self
                        .refreshed
                        .wait_timeout(cache, left)
                        .map_err(|_| Error)?
                        .0;
                }
                _ => {
                    *cache = Cache::Refreshing;
                    drop(cache);
                    let minted = self.mint(key, now, deadline);
                    let mut cache = self.cache.lock().map_err(|_| Error)?;
                    *cache = match &minted {
                        Ok(cached) => Cache::Ready(cached.clone()),
                        Err(_) => Cache::Empty,
                    };
                    self.refreshed.notify_all();
                    return minted;
                }
            }
        }
    }
    fn mint(&self, key: &Key, now: u64, deadline: Instant) -> Result<Cached, Error> {
        let jwt = app_jwt(key, self.identity.app_id, now, deadline)?;
        self.owner_bound(&jwt, deadline)?;
        let wanted = permissions();
        let body = token_body(&self.identity.repository, &wanted)?;
        let raw = self.exchange.exchange(
            self.identity.installation_id,
            &jwt,
            body.as_bytes(),
            deadline,
        )?;
        checked_token(&raw, &self.identity.repository, &wanted, false, now)
    }
}

impl App {
    fn owner_bound(&self, jwt: &str, deadline: Instant) -> Result<(), Error> {
        let repository = self.identity.repository.as_str();
        let (owner, _) = repository.split_once('/').ok_or(Error)?;
        let answer = |call: Call<'_>| match self.exchange.github(&call, jwt, deadline)? {
            (200, body) if body.len() <= 1024 * 1024 => Ok(body),
            _ => Err(Error),
        };
        let allowed = match self.mode {
            Mode::User => owner.eq_ignore_ascii_case(
                &app_owner(&answer(Call::App)?, self.identity.app_id).ok_or(Error)?,
            ),
            Mode::Factory => factory_named(owner, repository),
        };
        let installation = installation_for(
            &answer(Call::Installation { repository })?,
            self.identity.app_id,
            owner,
        )
        .ok_or(Error)?;
        (allowed && installation == self.identity.installation_id)
            .then_some(())
            .ok_or(Error)
    }
}

fn app_jwt(key: &Key, app_id: u64, now: u64, deadline: Instant) -> Result<String, Error> {
    let message = format!("{}.{}", base64url(br#"{"alg":"RS256","typ":"JWT"}"#), base64url(json!({"iss":app_id.to_string(),"iat":now.saturating_sub(60),"exp":now.checked_add(540).ok_or(Error)?}).to_string().as_bytes()));
    let signature = sign(key, message.as_bytes(), deadline)?;
    Ok(format!("{message}.{}", base64url(&signature)))
}

fn token_body(repository: &str, permissions: &Value) -> Result<String, Error> {
    let name = repository.split_once('/').ok_or(Error)?.1;
    Ok(json!({"repositories":[name],"permissions":permissions}).to_string())
}

fn checked_token(
    raw: &[u8],
    repository: &str,
    permissions: &Value,
    require_repositories: bool,
    now: u64,
) -> Result<Cached, Error> {
    if raw.len() > 1024 * 1024 {
        return Err(Error);
    }
    let value = serde_json::from_slice::<Unique>(raw).map_err(|_| Error)?.0;
    let object = value.as_object().ok_or(Error)?;
    if !["token", "expires_at", "permissions"]
        .iter()
        .all(|k| object.contains_key(*k))
        || object.keys().any(|k| {
            ![
                "token",
                "expires_at",
                "permissions",
                "repositories",
                "repository_selection",
            ]
            .contains(&k.as_str())
        })
    {
        return Err(Error);
    }
    if require_repositories && !object.contains_key("repositories") {
        return Err(Error);
    }
    if let Some(repositories) = object.get("repositories") {
        let repos = repositories.as_array().ok_or(Error)?;
        if repos.len() != 1
            || repos[0]["full_name"]
                .as_str()
                .is_none_or(|name| !name.eq_ignore_ascii_case(repository))
        {
            return Err(Error);
        }
    }
    if let Some(selection) = object.get("repository_selection")
        && !matches!(selection.as_str(), Some("all" | "selected"))
    {
        return Err(Error);
    }
    if &value["permissions"] != permissions {
        return Err(Error);
    }
    let token = value["token"]
        .as_str()
        .filter(|s| {
            !s.is_empty()
                && s.len() <= 16384
                && s.bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b"._~+/-=".contains(&b))
        })
        .ok_or(Error)?;
    let expires = expiry(value["expires_at"].as_str().ok_or(Error)?).ok_or(Error)?;
    if expires <= now || expires > now.checked_add(3900).ok_or(Error)? {
        return Err(Error);
    }
    Ok(Cached {
        token: token.to_owned(),
        expires,
    })
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Mode {
    User,
    Factory,
}

pub const FACTORY_INSTALLATIONS: &[(&str, &[&str])] = &[
    ("jparker2006", &["jparker2006/ClosedWiz"]),
    (
        "openwizdev",
        &[
            "openwizdev/OpenWiz",
            "openwizdev/WizPlugins",
            "openwizdev/WizSkills",
        ],
    ),
];

fn factory_named(account: &str, repository: &str) -> bool {
    FACTORY_INSTALLATIONS.iter().any(|(named, repositories)| {
        named.eq_ignore_ascii_case(account)
            && repositories
                .iter()
                .any(|r| r.eq_ignore_ascii_case(repository))
    })
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Refusal {
    Unavailable,
    NotInstalled,
    Refused,
}

pub struct Minted {
    pub token: String,
    pub expires_at: u64,
}

pub struct SecretApp {
    key: Key,
    app_id: u64,
    mode: Mode,
    exchange: Arc<dyn Exchange>,
    clock: Arc<dyn Clock>,
}

const SECRET_PEM_MAX: usize = 4096;

impl SecretApp {
    pub fn from_secret(
        encoded: &str,
        app_id: u64,
        mode: Mode,
        exchange: Arc<dyn Exchange>,
        clock: Arc<dyn Clock>,
    ) -> Result<Self, Error> {
        if app_id == 0 {
            return Err(Error);
        }
        let pem = base64_decode(encoded.as_bytes()).ok_or(Error)?;
        let text = std::str::from_utf8(&pem).map_err(|_| Error)?;
        let label = text
            .strip_prefix("-----BEGIN ")
            .and_then(|t| t.split_once("-----"))
            .map(|(label, _)| label)
            .ok_or(Error)?;
        if pem.len() > SECRET_PEM_MAX
            || !matches!(label, "PRIVATE KEY" | "RSA PRIVATE KEY")
            || !text.trim_end().ends_with(&format!("-----END {label}-----"))
        {
            return Err(Error);
        }
        Ok(Self {
            key: piped_key(&pem)?,
            app_id,
            mode,
            exchange,
            clock,
        })
    }

    pub fn mint(self, repository: &str, read: bool, deadline: Instant) -> Result<Minted, Refusal> {
        let repository = openwiz_core::fleet::starts::Repository::parse(repository)
            .map_err(|_| Refusal::Refused)?;
        let repository = repository.as_str();
        let (owner, _) = repository.split_once('/').ok_or(Refusal::Refused)?;
        let wanted = if read {
            read_permissions()
        } else {
            permissions()
        };
        let now = self.clock.now_s();
        let jwt =
            app_jwt(&self.key, self.app_id, now, deadline).map_err(|_| Refusal::Unavailable)?;
        drop(self.key);
        let call = |call: Call<'_>, expect: u16| match self.exchange.github(&call, &jwt, deadline) {
            Err(_) => Err(Refusal::Unavailable),
            Ok((status, body)) if status == expect && body.len() <= 1024 * 1024 => Ok(body),
            Ok((404, _)) if matches!(call, Call::Installation { .. }) => Err(Refusal::NotInstalled),
            Ok(_) => Err(Refusal::Refused),
        };
        let app_owner = match self.mode {
            Mode::User => {
                let raw = call(Call::App, 200)?;
                Some(app_owner(&raw, self.app_id).ok_or(Refusal::Refused)?)
            }
            Mode::Factory => None,
        };
        let raw = call(Call::Installation { repository }, 200)?;
        let installation = installation_for(&raw, self.app_id, owner).ok_or(Refusal::Refused)?;
        let allowed = match &app_owner {
            Some(app_owner) => owner.eq_ignore_ascii_case(app_owner),
            None => factory_named(owner, repository),
        };
        if !allowed {
            return Err(Refusal::Refused);
        }
        let body = token_body(repository, &wanted).map_err(|_| Refusal::Refused)?;
        let raw = call(
            Call::AccessToken {
                installation,
                body: body.as_bytes(),
            },
            201,
        )?;
        let minted =
            checked_token(&raw, repository, &wanted, true, now).map_err(|_| Refusal::Refused)?;
        let left = minted.expires.saturating_sub(self.clock.now_s());
        if left <= 300 {
            return Err(Refusal::Refused);
        }
        Ok(Minted {
            token: minted.token,
            expires_at: minted.expires,
        })
    }
}

fn app_owner(raw: &[u8], app_id: u64) -> Option<String> {
    let value = serde_json::from_slice::<Unique>(raw).ok()?.0;
    (value.get("id")?.as_u64()? == app_id)
        .then(|| {
            value
                .get("owner")?
                .get("login")?
                .as_str()
                .map(str::to_owned)
        })
        .flatten()
        .filter(|login| !login.is_empty())
}

fn installation_for(raw: &[u8], app_id: u64, owner: &str) -> Option<u64> {
    let value = serde_json::from_slice::<Unique>(raw).ok()?.0;
    let id = value.get("id")?.as_u64().filter(|id| *id > 0)?;
    (value.get("app_id")?.as_u64()? == app_id
        && value
            .get("account")?
            .get("login")?
            .as_str()?
            .eq_ignore_ascii_case(owner)
        && value.get("repository_selection")?.as_str()? == "selected")
        .then_some(id)
}

fn read_permissions() -> Value {
    json!({"metadata":"read","contents":"read","issues":"read","pull_requests":"read","checks":"read","actions":"read"})
}

#[cfg(target_os = "linux")]
fn piped_key(pem: &[u8]) -> Result<Key, Error> {
    use std::io::Write as _;
    let (reader, mut writer) = std::io::pipe().map_err(|_| Error)?;
    writer.write_all(pem).map_err(|_| Error)?;
    drop(writer);
    Ok(std::fs::File::from(std::os::fd::OwnedFd::from(reader)))
}
#[cfg(not(target_os = "linux"))]
fn piped_key(_: &[u8]) -> Result<Key, Error> {
    Err(Error)
}

fn base64_decode(text: &[u8]) -> Option<Vec<u8>> {
    if text.is_empty() || !text.len().is_multiple_of(4) {
        return None;
    }
    let value = |b: u8| match b {
        b'A'..=b'Z' => Some(b - b'A'),
        b'a'..=b'z' => Some(b - b'a' + 26),
        b'0'..=b'9' => Some(b - b'0' + 52),
        b'+' => Some(62),
        b'/' => Some(63),
        _ => None,
    };
    let mut out = Vec::with_capacity(text.len() / 4 * 3);
    let last = text.len() / 4 - 1;
    for (at, chunk) in text.chunks(4).enumerate() {
        let pad = chunk.iter().rev().take_while(|b| **b == b'=').count();
        if pad > 2 || (pad > 0 && at != last) {
            return None;
        }
        let mut n = 0u32;
        for b in &chunk[..4 - pad] {
            n = (n << 6) | u32::from(value(*b)?);
        }
        n <<= 6 * pad as u32;
        let bytes = [(n >> 16) as u8, (n >> 8) as u8, n as u8];
        if (pad == 1 && bytes[2] != 0) || (pad == 2 && bytes[1] != 0) {
            return None;
        }
        out.extend_from_slice(&bytes[..3 - pad]);
    }
    Some(out)
}

fn expiry(text: &str) -> Option<u64> {
    let b = text.as_bytes();
    if b.len() != 20
        || b[4] != b'-'
        || b[7] != b'-'
        || b[10] != b'T'
        || b[13] != b':'
        || b[16] != b':'
        || b[19] != b'Z'
    {
        return None;
    }
    let number = |a, b| {
        let part = text.get(a..b)?;
        part.bytes().all(|b| b.is_ascii_digit()).then_some(())?;
        part.parse::<u64>().ok()
    };
    let (year, month, day, hour, minute, second) = (
        number(0, 4)?,
        number(5, 7)?,
        number(8, 10)?,
        number(11, 13)?,
        number(14, 16)?,
        number(17, 19)?,
    );
    let leap = |y| y % 4 == 0 && (y % 100 != 0 || y % 400 == 0);
    if !(1970..=9999).contains(&year)
        || !(1..=12).contains(&month)
        || hour > 23
        || minute > 59
        || second > 59
    {
        return None;
    }
    let months = [
        31,
        if leap(year) { 29 } else { 28 },
        31,
        30,
        31,
        30,
        31,
        31,
        30,
        31,
        30,
        31,
    ];
    if day == 0 || day > months[(month - 1) as usize] {
        return None;
    }
    let days: u64 = (1970..year)
        .map(|y| if leap(y) { 366 } else { 365 })
        .sum::<u64>()
        + months[..(month - 1) as usize].iter().sum::<u64>()
        + day
        - 1;
    Some(days * 86400 + hour * 3600 + minute * 60 + second)
}

fn permissions() -> Value {
    json!({"metadata":"read","contents":"write","issues":"write","pull_requests":"write","checks":"read","actions":"read"})
}

#[cfg(target_os = "macos")]
type Key = PathBuf;
#[cfg(not(target_os = "macos"))]
type Key = std::fs::File;

#[cfg(not(target_os = "macos"))]
const OPENSSL_PROGRAM: &str = "/usr/bin/openssl";
#[cfg(not(target_os = "macos"))]
const SIGN_ARGS: [&str; 3] = ["dgst", "-sha256", "-sign"];
#[cfg(not(target_os = "macos"))]
fn sign(key: &Key, message: &[u8], deadline: Instant) -> Result<Vec<u8>, Error> {
    use std::os::fd::AsRawFd;
    if Instant::now() >= deadline {
        return Err(Error);
    }
    let key = format!("/proc/{}/fd/{}", std::process::id(), key.as_raw_fd());
    let child = Command::new(OPENSSL_PROGRAM)
        .args(SIGN_ARGS)
        .arg(key)
        .env_clear()
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|_| Error)?;
    let signature = process::app_output(child, message.to_vec(), deadline).map_err(|_| Error)?;
    if signature.is_empty() || signature.len() > 1024 {
        return Err(Error);
    }
    Ok(signature)
}

#[cfg(all(
    target_os = "linux",
    any(target_arch = "x86_64", target_arch = "aarch64")
))]
fn open_key(root: &Path, _deadline: Instant) -> Result<Key, Error> {
    use std::{
        fs::{self, File, OpenOptions},
        os::{
            fd::AsRawFd,
            unix::fs::{MetadataExt, OpenOptionsExt},
        },
        path::Component,
    };
    #[cfg(target_arch = "x86_64")]
    const NOFOLLOW: i32 = 0o400000;
    #[cfg(target_arch = "x86_64")]
    const DIRECTORY: i32 = 0o200000;
    #[cfg(target_arch = "aarch64")]
    const NOFOLLOW: i32 = 0o100000;
    #[cfg(target_arch = "aarch64")]
    const DIRECTORY: i32 = 0o40000;
    const NONBLOCK: i32 = 0o4000;
    let uid = fs::metadata("/proc/self").map_err(|_| Error)?.uid();
    let directory = |path: &Path| {
        OpenOptions::new()
            .read(true)
            .custom_flags(NOFOLLOW | DIRECTORY | NONBLOCK)
            .open(path)
            .map_err(|_| Error)
    };
    let anchor = |file: &File| PathBuf::from(format!("/proc/self/fd/{}", file.as_raw_fd()));
    let outside_repo = |file: &File| -> Result<(), Error> {
        let path = anchor(file);
        match fs::symlink_metadata(path.join(".git")) {
            Ok(_) => return Err(Error),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
            Err(_) => return Err(Error),
        }
        if path.join("HEAD").exists()
            && (path.join("objects").exists() || path.join("config").exists())
        {
            return Err(Error);
        }
        Ok(())
    };
    let private = |file: &File, dir: bool| -> Result<(), Error> {
        let m = file.metadata().map_err(|_| Error)?;
        if m.uid() != uid
            || m.mode() & 0o077 != 0
            || (if dir {
                !m.is_dir()
            } else {
                !m.is_file() || m.nlink() != 1 || m.len() == 0 || m.len() > 16384
            })
        {
            return Err(Error);
        }
        Ok(())
    };
    let mut dir = directory(Path::new("/"))?;
    for component in root.components() {
        match component {
            Component::RootDir => {}
            Component::Normal(name) => {
                outside_repo(&dir)?;
                dir = directory(&anchor(&dir).join(name))?;
            }
            _ => return Err(Error),
        }
    }
    outside_repo(&dir)?;
    private(&dir, true)?;
    for name in ["service", "app"] {
        dir = directory(&anchor(&dir).join(name))?;
        private(&dir, true)?;
        outside_repo(&dir)?;
    }
    let key = OpenOptions::new()
        .read(true)
        .custom_flags(NOFOLLOW | NONBLOCK)
        .open(anchor(&dir).join("private-key.pem"))
        .map_err(|_| Error)?;
    private(&key, false)?;
    Ok(key)
}

#[cfg(not(any(
    target_os = "macos",
    all(
        target_os = "linux",
        any(target_arch = "x86_64", target_arch = "aarch64")
    )
)))]
fn open_key(_: &Path, _: Instant) -> Result<Key, Error> {
    Err(Error)
}

#[cfg(target_os = "macos")]
const PYTHON_PROGRAM: &str = "/usr/bin/python3";
#[cfg(target_os = "macos")]
const SECURITY_SCRIPT: &str = include_str!("../../../../tools/install/platform/security.py");
#[cfg(target_os = "macos")]
fn key_tool(root: &Path, mode: &str, input: &[u8], deadline: Instant) -> Result<Vec<u8>, Error> {
    if Instant::now() >= deadline || !matches!(mode, "inspect" | "sign") {
        return Err(Error);
    }
    let child = Command::new(PYTHON_PROGRAM)
        .args(["-I", "-c", SECURITY_SCRIPT, mode])
        .arg(root)
        .env_clear()
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|_| Error)?;
    process::app_output(child, input.to_vec(), deadline).map_err(|_| Error)
}
#[cfg(target_os = "macos")]
fn sign(root: &Key, message: &[u8], deadline: Instant) -> Result<Vec<u8>, Error> {
    let signature = key_tool(root, "sign", message, deadline)?;
    if signature.is_empty() || signature.len() > 1024 {
        return Err(Error);
    }
    Ok(signature)
}
#[cfg(target_os = "macos")]
fn open_key(root: &Path, deadline: Instant) -> Result<Key, Error> {
    key_tool(root, "inspect", &[], deadline)?;
    Ok(root.to_owned())
}

struct Unique(Value);
impl<'de> Deserialize<'de> for Unique {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        struct Once;
        impl<'de> Visitor<'de> for Once {
            type Value = Unique;
            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("JSON with each key once")
            }
            fn visit_map<A: MapAccess<'de>>(self, mut a: A) -> Result<Unique, A::Error> {
                let mut map = serde_json::Map::new();
                while let Some((key, value)) = a.next_entry::<String, Unique>()? {
                    if map.insert(key, value.0).is_some() {
                        return Err(de::Error::custom("duplicate key"));
                    }
                }
                Ok(Unique(Value::Object(map)))
            }
            fn visit_seq<A: SeqAccess<'de>>(self, mut a: A) -> Result<Unique, A::Error> {
                let mut values = Vec::new();
                while let Some(value) = a.next_element::<Unique>()? {
                    values.push(value.0);
                }
                Ok(Unique(Value::Array(values)))
            }
            fn visit_bool<E: de::Error>(self, v: bool) -> Result<Unique, E> {
                Ok(Unique(v.into()))
            }
            fn visit_u64<E: de::Error>(self, v: u64) -> Result<Unique, E> {
                Ok(Unique(v.into()))
            }
            fn visit_i64<E: de::Error>(self, v: i64) -> Result<Unique, E> {
                Ok(Unique(v.into()))
            }
            fn visit_f64<E: de::Error>(self, v: f64) -> Result<Unique, E> {
                serde_json::Number::from_f64(v)
                    .map(|n| Unique(Value::Number(n)))
                    .ok_or_else(|| de::Error::custom("number"))
            }
            fn visit_str<E: de::Error>(self, v: &str) -> Result<Unique, E> {
                Ok(Unique(v.into()))
            }
            fn visit_unit<E: de::Error>(self) -> Result<Unique, E> {
                Ok(Unique(Value::Null))
            }
        }
        d.deserialize_any(Once)
    }
}

fn base64url(bytes: &[u8]) -> String {
    const ABC: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
    let mut out = String::new();
    for chunk in bytes.chunks(3) {
        let n = (u32::from(chunk[0]) << 16)
            | (u32::from(*chunk.get(1).unwrap_or(&0)) << 8)
            | u32::from(*chunk.get(2).unwrap_or(&0));
        for at in 0..chunk.len() + 1 {
            out.push(ABC[((n >> (18 - at * 6)) & 63) as usize] as char);
        }
    }
    out
}

#[derive(Default)]
pub struct CurlExchange;
const CURL_PROGRAM: &str = "/usr/bin/curl";
const CURL_ARGS: [&str; 15] = [
    "--disable",
    "--silent",
    "--show-error",
    "--fail-with-body",
    "--max-time",
    "15",
    "--proto",
    "=https",
    "--max-redirs",
    "0",
    "--config",
    "-",
    "--write-out",
    "\\n%{http_code}",
    "--no-progress-meter",
];
impl Exchange for CurlExchange {
    fn exchange(
        &self,
        installation: u64,
        jwt: &str,
        body: &[u8],
        deadline: Instant,
    ) -> Result<Vec<u8>, Error> {
        if Instant::now() >= deadline
            || installation == 0
            || !jwt
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"._-".contains(&b))
        {
            return Err(Error);
        }
        let config = token_config(installation, jwt, body)?;
        let child = Command::new(CURL_PROGRAM)
            .args(CURL_ARGS)
            .env_clear()
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|_| Error)?;
        let result =
            process::app_output(child, config.into_bytes(), deadline).map_err(|_| Error)?;
        token_answer(result)
    }
    fn github(
        &self,
        call: &Call<'_>,
        jwt: &str,
        deadline: Instant,
    ) -> Result<(u16, Vec<u8>), Error> {
        if Instant::now() >= deadline {
            return Err(Error);
        }
        let config = Self::status_call(call, jwt)?;
        let child = Command::new(CURL_PROGRAM)
            .args(CURL_STATUS_ARGS)
            .env_clear()
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|_| Error)?;
        let result =
            process::app_output(child, config.into_bytes(), deadline).map_err(|_| Error)?;
        status_answer(result)
    }
}

const CURL_STATUS_ARGS: [&str; 14] = [
    "--disable",
    "--silent",
    "--show-error",
    "--max-time",
    "15",
    "--proto",
    "=https",
    "--max-redirs",
    "0",
    "--config",
    "-",
    "--write-out",
    "\\n%{http_code}",
    "--no-progress-meter",
];
impl CurlExchange {
    fn status_call(call: &Call<'_>, jwt: &str) -> Result<String, Error> {
        if !jwt
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"._-".contains(&b))
        {
            return Err(Error);
        }
        let (url, post) = match call {
            Call::App => ("app".to_owned(), String::new()),
            Call::Installation { repository } => {
                let parsed = openwiz_core::fleet::starts::Repository::parse(repository)
                    .map_err(|_| Error)?;
                if parsed.as_str() != *repository {
                    return Err(Error);
                }
                (format!("repos/{repository}/installation"), String::new())
            }
            Call::AccessToken { installation, body } => {
                if *installation == 0 {
                    return Err(Error);
                }
                let data = serde_json::to_string(std::str::from_utf8(body).map_err(|_| Error)?)
                    .map_err(|_| Error)?;
                (
                    format!("app/installations/{installation}/access_tokens"),
                    format!(
                        "request = \"POST\"\nheader = \"Content-Type: application/json\"\ndata = {data}\n"
                    ),
                )
            }
        };
        Ok(format!(
            "url = \"https://api.github.com/{url}\"\n{post}header = \"Authorization: Bearer {jwt}\"\nheader = \"Accept: application/vnd.github+json\"\nheader = \"X-GitHub-Api-Version: 2026-03-10\"\n"
        ))
    }
}
fn status_answer(mut result: Vec<u8>) -> Result<(u16, Vec<u8>), Error> {
    let at = result.len().checked_sub(4).ok_or(Error)?;
    let tail = result.get(at..).ok_or(Error)?;
    if tail[0] != b'\n' || !tail[1..].iter().all(u8::is_ascii_digit) {
        return Err(Error);
    }
    let status = std::str::from_utf8(&tail[1..])
        .ok()
        .and_then(|s| s.parse::<u16>().ok())
        .filter(|s| (100..=599).contains(s))
        .ok_or(Error)?;
    result.truncate(at);
    Ok((status, result))
}

fn token_config(installation: u64, jwt: &str, body: &[u8]) -> Result<String, Error> {
    Ok(format!(
        "url = \"https://api.github.com/app/installations/{installation}/access_tokens\"\nrequest = \"POST\"\nheader = \"Authorization: Bearer {jwt}\"\nheader = \"Accept: application/vnd.github+json\"\nheader = \"Content-Type: application/json\"\nheader = \"X-GitHub-Api-Version: 2026-03-10\"\ndata = {}\n",
        serde_json::to_string(std::str::from_utf8(body).map_err(|_| Error)?).map_err(|_| Error)?
    ))
}
fn token_answer(mut result: Vec<u8>) -> Result<Vec<u8>, Error> {
    if !result.ends_with(b"\n201") {
        return Err(Error);
    }
    result.truncate(result.len() - 4);
    Ok(result)
}

#[cfg(test)]
#[path = "app_transport_tests.rs"]
mod transport_tests;
