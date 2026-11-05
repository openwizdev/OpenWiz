//! GI-P6 (#2547): `openwiz github token` mints an installation token, read-only
//! with `--read`, and leaks nothing. Synthetic fixtures and a fake exchange
//! (the adapter's `Exchange` seam) only: no network, no real key or token.
//! The key is generated per run by `/usr/bin/openssl`, as the adapter's tests do.
//! The program cases run cli-agent's fixture `openwiz` with an empty environment.
#![cfg(target_os = "linux")]

use std::ffi::OsString;
use std::process::Command;
use std::sync::{Arc, Mutex, OnceLock};
use std::time::Instant;

use openwiz_adapter_github::app::{Call, Clock, Error, Exchange};
use openwiz_cli::github_token::{self, Context, Parsed, TokenArgs};
use serde_json::{Value, json};

const APP_ID: &str = "1001";
const FIXTURE: &str = include_str!("../../contracts/fixtures/github-identity/token-exchange.json");
/// The contract's read profile (contracts/github-identity.v1.md), a literal.
const READ: &str = r#"{"metadata":"read","contents":"read","issues":"read","pull_requests":"read","checks":"read","actions":"read"}"#;
/// The App's profile, a literal from the same contract.
const WRITE: &str = r#"{"metadata":"read","contents":"write","issues":"write","pull_requests":"write","checks":"read","actions":"read"}"#;

/// A synthetic RSA key, and its secret form (base64 of the PEM, one line).
fn key() -> &'static (String, String) {
    static KEY: OnceLock<(String, String)> = OnceLock::new();
    KEY.get_or_init(|| {
        let out = Command::new("/usr/bin/openssl")
            .args([
                "genpkey",
                "-algorithm",
                "RSA",
                "-pkeyopt",
                "rsa_keygen_bits:2048",
            ])
            .env_clear()
            .output()
            .unwrap();
        assert!(out.status.success());
        let pem = String::from_utf8(out.stdout).unwrap();
        let encoded = base64(pem.as_bytes());
        (pem, encoded)
    })
}

fn base64(bytes: &[u8]) -> String {
    const ABC: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::new();
    for chunk in bytes.chunks(3) {
        let n = (u32::from(chunk[0]) << 16)
            | (u32::from(*chunk.get(1).unwrap_or(&0)) << 8)
            | u32::from(*chunk.get(2).unwrap_or(&0));
        for at in 0..4 {
            out.push(if at <= chunk.len() {
                ABC[((n >> (18 - at * 6)) & 63) as usize] as char
            } else {
                '='
            });
        }
    }
    out
}

/// `1970-01-01Thh:mm:ssZ` for the fixture's controlled clock (under a day).
fn iso(seconds: u64) -> String {
    assert!(seconds < 86_400);
    format!(
        "1970-01-01T{:02}:{:02}:{:02}Z",
        seconds / 3600,
        seconds / 60 % 60,
        seconds % 60
    )
}

struct Fixed(u64);
impl Clock for Fixed {
    fn now_s(&self) -> u64 {
        self.0
    }
}

/// One recorded call: what the seam received, as text.
#[derive(Debug, Clone)]
struct Seen {
    call: String,
    jwt: String,
    body: Option<Value>,
}

/// One scripted GitHub answer: status and body; `None` is a lost reply.
type Answer = Option<(u16, Vec<u8>)>;

/// GitHub's two answers, scripted; `None` is a lost reply.
struct Fake {
    lookup: Option<(u16, Vec<u8>)>,
    mint: Option<(u16, Vec<u8>)>,
    seen: Mutex<Vec<Seen>>,
}
impl Exchange for Fake {
    fn exchange(&self, _: u64, _: &str, _: &[u8], _: Instant) -> Result<Vec<u8>, Error> {
        panic!("the token command uses the status-reading call only");
    }
    fn github(&self, call: &Call<'_>, jwt: &str, _: Instant) -> Result<(u16, Vec<u8>), Error> {
        let (name, body, answer) = match call {
            Call::Installation { repository } => {
                (format!("installation {repository}"), None, &self.lookup)
            }
            Call::AccessToken { installation, body } => (
                format!("access_tokens {installation}"),
                Some(serde_json::from_slice(body).unwrap()),
                &self.mint,
            ),
        };
        self.seen.lock().unwrap().push(Seen {
            call: name,
            jwt: jwt.to_owned(),
            body,
        });
        answer.clone().ok_or(Error)
    }
}

fn installation(id: u64, account: &str, selection: &str) -> Vec<u8> {
    json!({"id": id, "app_id": 1001, "account": {"login": account, "type": "User"},
           "repository_selection": selection, "target_type": "User", "events": []})
    .to_string()
    .into_bytes()
}

fn answer(token: &str, expires_at: u64, repository: &str, permissions: &str) -> Vec<u8> {
    json!({"token": token, "expires_at": iso(expires_at), "repository_selection": "selected",
           "repositories": [{"full_name": repository}],
           "permissions": serde_json::from_str::<Value>(permissions).unwrap()})
    .to_string()
    .into_bytes()
}

struct Run {
    code: i32,
    stdout: String,
    stderr: String,
    seen: Vec<Seen>,
}

fn run_with(
    args: &[&str],
    secret: Option<&str>,
    app_id: Option<&str>,
    fake: Fake,
    now: u64,
) -> Run {
    let fake = Arc::new(fake);
    let context = Context {
        secret: secret.map(OsString::from),
        app_id: app_id.map(OsString::from),
        exchange: fake.clone(),
        clock: Arc::new(Fixed(now)),
    };
    let (mut stdout, mut stderr) = (Vec::new(), Vec::new());
    let args: Vec<String> = args.iter().map(|a| (*a).to_owned()).collect();
    let code = github_token::run(&args, context, &mut stdout, &mut stderr);
    let seen = fake.seen.lock().unwrap().clone();
    Run {
        code,
        stdout: String::from_utf8(stdout).unwrap(),
        stderr: String::from_utf8(stderr).unwrap(),
        seen,
    }
}

fn run(args: &[&str], lookup: Option<(u16, Vec<u8>)>, mint: Option<(u16, Vec<u8>)>) -> Run {
    let fake = Fake {
        lookup,
        mint,
        seen: Mutex::new(Vec::new()),
    };
    run_with(args, Some(&key().1), Some(APP_ID), fake, 1000)
}

const WORK: [&str; 3] = ["token", "--repository", "synthetic-owner/work"];
const WORK_READ: [&str; 4] = ["token", "--repository", "synthetic-owner/work", "--read"];

/// No key material, in any form, and no token except a success's stdout.
fn assert_secret_free(run: &Run, tokens: &[&str]) {
    let (pem, encoded) = key();
    let body: String = pem.lines().filter(|l| !l.starts_with("-----")).collect();
    let pieces = [
        &body[..40],
        &body[body.len() - 40..],
        &encoded[..40],
        "PRIVATE KEY",
    ];
    let mut places = vec![("stderr", run.stderr.clone())];
    for seen in &run.seen {
        places.push(("seam call", seen.call.clone()));
        places.push(("seam JWT", seen.jwt.clone()));
        places.push((
            "seam body",
            seen.body.as_ref().map(Value::to_string).unwrap_or_default(),
        ));
    }
    if run.code != 0 {
        places.push(("stdout", run.stdout.clone()));
    }
    for (place, text) in &places {
        for piece in pieces.iter().copied().chain(tokens.iter().copied()) {
            assert!(
                !text.contains(piece),
                "{place} holds secret material: {text}"
            );
        }
        for seen in &run.seen {
            if *place == "stderr" || *place == "stdout" {
                assert!(!text.contains(&seen.jwt), "{place} holds the App JWT");
            }
        }
    }
}

// --- With a fake exchange: the fixture's cases (contracts/fixtures/github-identity) ---

#[test]
fn gi_p6_each_fixture_case_gives_its_exit_stdout_stderr_and_exact_request() {
    let fixture: Value = serde_json::from_str(FIXTURE).unwrap();
    let now = fixture["now"].as_u64().unwrap();
    assert_eq!(now, 1000);
    let cases = fixture["cases"].as_array().unwrap();
    assert_eq!(cases.len(), 3);
    for case in cases {
        let argv: Vec<&str> = case["argv"]
            .as_array()
            .unwrap()
            .iter()
            .map(|a| a.as_str().unwrap())
            .collect();
        assert_eq!(argv[..2], ["openwiz", "github"]);
        let inst = &case["installation"];
        let token = case["answer"]["token"].as_str().unwrap();
        let fake = Fake {
            lookup: Some((
                200,
                installation(
                    inst["id"].as_u64().unwrap(),
                    inst["account"].as_str().unwrap(),
                    inst["repository_selection"].as_str().unwrap(),
                ),
            )),
            mint: Some((
                201,
                answer(
                    token,
                    case["answer"]["expires_at"].as_u64().unwrap(),
                    case["answer"]["repositories"][0]["full_name"]
                        .as_str()
                        .unwrap(),
                    &case["answer"]["permissions"].to_string(),
                ),
            )),
            seen: Mutex::new(Vec::new()),
        };
        let result = run_with(&argv[2..], Some(&key().1), Some(APP_ID), fake, now);
        let exit = case["exit"].as_i64().unwrap() as i32;
        assert_eq!(result.code, exit, "{argv:?}: {}", result.stderr);
        assert_eq!(result.stdout, case["stdout"].as_str().unwrap(), "{argv:?}");
        if let Some(stderr) = case["stderr"].as_str() {
            assert_eq!(result.stderr, stderr, "{argv:?}");
        }
        // Exactly two calls: the lookup for that repository, then the mint
        // for the installation found, asking exactly the fixture's request.
        let calls: Vec<&str> = result.seen.iter().map(|s| s.call.as_str()).collect();
        assert_eq!(
            calls,
            ["installation synthetic-owner/work", "access_tokens 2002"],
            "{argv:?}"
        );
        assert_eq!(
            result.seen[1].body.as_ref().unwrap(),
            &case["request"],
            "{argv:?}"
        );
        if exit != 0 {
            assert_secret_free(&result, &[token]);
        } else {
            assert_secret_free(&result, &[]);
        }
    }
}

#[test]
fn gi_p6_read_asks_for_exactly_the_read_profile_and_write_for_the_apps() {
    for (args, profile) in [(&WORK_READ[..], READ), (&WORK[..], WRITE)] {
        let result = run(
            args,
            Some((200, installation(2002, "synthetic-owner", "selected"))),
            Some((
                201,
                answer(
                    "synthetic-installation-token",
                    4600,
                    "synthetic-owner/work",
                    profile,
                ),
            )),
        );
        assert_eq!(result.code, 0, "{args:?}: {}", result.stderr);
        let asked = result.seen[1].body.as_ref().unwrap();
        assert_eq!(
            asked["permissions"],
            serde_json::from_str::<Value>(profile).unwrap()
        );
        assert_eq!(asked["repositories"], json!(["work"]));
        assert_eq!(asked.as_object().unwrap().len(), 2, "nothing else is asked");
    }
    // --read granted write (or any other profile) is refused: exactly what was asked.
    let result = run(
        &WORK_READ,
        Some((200, installation(2002, "synthetic-owner", "selected"))),
        Some((
            201,
            answer(
                "synthetic-installation-token",
                4600,
                "synthetic-owner/work",
                WRITE,
            ),
        )),
    );
    assert_eq!((result.code, result.stdout.as_str()), (5, ""));
    assert_secret_free(&result, &["synthetic-installation-token"]);
}

#[test]
fn gi_p6_the_jwt_authenticates_as_the_app_for_an_installation_token() {
    let result = run(
        &WORK,
        Some((200, installation(2002, "synthetic-owner", "selected"))),
        Some((
            201,
            answer(
                "synthetic-installation-token",
                4600,
                "synthetic-owner/work",
                WRITE,
            ),
        )),
    );
    assert_eq!(result.code, 0, "{}", result.stderr);
    // One App JWT, used for both calls; issued by this App id, at the clock.
    assert_eq!(result.seen[0].jwt, result.seen[1].jwt);
    let parts: Vec<&str> = result.seen[0].jwt.split('.').collect();
    assert_eq!(parts.len(), 3);
    let claims: Value = serde_json::from_slice(&base64url_decode(parts[1])).unwrap();
    assert_eq!(claims, json!({"iss": "1001", "iat": 940, "exp": 1540}));
    let header: Value = serde_json::from_slice(&base64url_decode(parts[0])).unwrap();
    assert_eq!(header, json!({"alg": "RS256", "typ": "JWT"}));
    // The signature verifies against the synthetic key's public half.
    let dir = std::env::temp_dir().join(format!("ow-gi5-{}", std::process::id()));
    super::dirs::private_dir_all(&dir).unwrap();
    let public = Command::new("/usr/bin/openssl")
        .args(["pkey", "-pubout"])
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .spawn()
        .and_then(|mut child| {
            use std::io::Write as _;
            child.stdin.take().unwrap().write_all(key().0.as_bytes())?;
            child.wait_with_output()
        })
        .unwrap();
    std::fs::write(dir.join("public.pem"), public.stdout).unwrap();
    std::fs::write(dir.join("signature"), base64url_decode(parts[2])).unwrap();
    std::fs::write(dir.join("message"), format!("{}.{}", parts[0], parts[1])).unwrap();
    let verified = Command::new("/usr/bin/openssl")
        .args(["dgst", "-sha256", "-verify"])
        .arg(dir.join("public.pem"))
        .arg("-signature")
        .arg(dir.join("signature"))
        .arg(dir.join("message"))
        .output()
        .unwrap();
    std::fs::remove_dir_all(&dir).unwrap();
    assert!(
        verified.status.success(),
        "the App JWT is signed by the secret's key"
    );
}

fn base64url_decode(text: &str) -> Vec<u8> {
    let value = |b: u8| match b {
        b'A'..=b'Z' => b - b'A',
        b'a'..=b'z' => b - b'a' + 26,
        b'0'..=b'9' => b - b'0' + 52,
        b'-' => 62,
        b'_' => 63,
        _ => panic!("not base64url"),
    };
    let (mut out, mut bits, mut n) = (Vec::new(), 0, 0u32);
    for b in text.bytes() {
        n = (n << 6) | u32::from(value(b));
        bits += 6;
        if bits >= 8 {
            bits -= 8;
            out.push((n >> bits) as u8);
        }
    }
    out
}

#[test]
fn gi_p6_an_expired_near_expiry_or_overlong_token_is_refused() {
    // now 1000: 300 s or less left, already expired, or more than 3900 s away.
    for expires_at in [1000, 900, 1300, 1299, 4901, 9000] {
        let result = run(
            &WORK,
            Some((200, installation(2002, "synthetic-owner", "selected"))),
            Some((
                201,
                answer(
                    "synthetic-guarded-token",
                    expires_at,
                    "synthetic-owner/work",
                    WRITE,
                ),
            )),
        );
        assert_eq!(result.code, 5, "expires_at {expires_at}: {}", result.stderr);
        assert_eq!(result.stdout, "", "expires_at {expires_at}");
        assert_eq!(
            result.stderr,
            "openwiz: github token: GitHub refused the token (details withheld); no token was printed\n"
        );
        assert_secret_free(&result, &["synthetic-guarded-token"]);
    }
    // The boundaries just inside: 301 s left, and exactly 3900 s.
    for expires_at in [1301, 4900] {
        let result = run(
            &WORK,
            Some((200, installation(2002, "synthetic-owner", "selected"))),
            Some((
                201,
                answer(
                    "synthetic-guarded-token",
                    expires_at,
                    "synthetic-owner/work",
                    WRITE,
                ),
            )),
        );
        assert_eq!(result.code, 0, "expires_at {expires_at}: {}", result.stderr);
        assert_eq!(result.stdout, "synthetic-guarded-token\n");
        assert_eq!(result.stderr, format!("expires_at {expires_at}\n"));
    }
}

// --- Missing secret, unknown repository, refused exchange: the contract's exits ---

const CONTEXT: &str =
    "openwiz: github token: the App key or App id is missing or unreadable; no token was minted\n";
const UNREACHABLE: &str =
    "openwiz: github token: GitHub gave no complete answer; no token was minted\n";
const NOT_INSTALLED: &str =
    "openwiz: github token: the repository is not covered by an installation of this App\n";
const REFUSED: &str =
    "openwiz: github token: GitHub refused the token (details withheld); no token was printed\n";

#[test]
fn gi_p6_a_missing_or_unreadable_secret_or_app_id_exits_1_before_any_call() {
    let encoded = key().1.clone();
    let not_pem = base64(b"synthetic, not a key\n");
    let wrapped = format!("{}\n{}", &encoded[..64], &encoded[64..]);
    // Cut inside the END line, whatever the key's length: never a whole PEM.
    let pem = key().0.trim_end();
    let truncated = base64(&pem.as_bytes()[..pem.len() - 6]);
    let cases: [(Option<&str>, Option<&str>); 10] = [
        (None, Some(APP_ID)),
        (Some(""), Some(APP_ID)),
        (Some("not base64!"), Some(APP_ID)),
        (Some(&not_pem), Some(APP_ID)),
        (Some(&wrapped), Some(APP_ID)),
        (Some(&truncated), Some(APP_ID)),
        (Some(&encoded), None),
        (Some(&encoded), Some("0")),
        (Some(&encoded), Some("01001")),
        (Some(&encoded), Some("app-1001")),
    ];
    for (secret, app_id) in cases {
        let fake = Fake {
            lookup: Some((200, installation(2002, "synthetic-owner", "selected"))),
            mint: Some((
                201,
                answer(
                    "synthetic-installation-token",
                    4600,
                    "synthetic-owner/work",
                    WRITE,
                ),
            )),
            seen: Mutex::new(Vec::new()),
        };
        let result = run_with(&WORK, secret, app_id, fake, 1000);
        assert_eq!(result.code, 1, "{app_id:?}");
        assert_eq!(result.stdout, "");
        assert_eq!(result.stderr, CONTEXT);
        assert!(
            result.seen.is_empty(),
            "no call without a usable key and App id"
        );
        assert_secret_free(&result, &["synthetic-installation-token"]);
    }
}

#[test]
fn gi_p6_an_unknown_repository_exits_3_and_never_mints() {
    let result = run(
        &WORK,
        Some((404, br#"{"message":"Not Found"}"#.to_vec())),
        None,
    );
    assert_eq!(
        (result.code, result.stdout.as_str(), result.stderr.as_str()),
        (3, "", NOT_INSTALLED)
    );
    let calls: Vec<&str> = result.seen.iter().map(|s| s.call.as_str()).collect();
    assert_eq!(calls, ["installation synthetic-owner/work"]);
}

#[test]
fn gi_p6_a_refused_exchange_or_an_answer_outside_the_contract_exits_5() {
    let good_lookup = || Some((200, installation(2002, "synthetic-owner", "selected")));
    let token = "synthetic-refused-token";
    let cases: Vec<(&str, Answer, Answer, usize)> = vec![
        ("lookup refused", Some((403, b"{}".to_vec())), None, 1),
        ("installation of all repositories", Some((200, installation(2002, "synthetic-owner", "all"))), None, 1),
        ("another account's installation", Some((200, installation(2002, "synthetic-other", "selected"))), None, 1),
        ("another App's installation", Some((200, br#"{"id":2002,"app_id":1002,"account":{"login":"synthetic-owner"},"repository_selection":"selected"}"#.to_vec())), None, 1),
        ("duplicate installation id", Some((200, br#"{"id":2002,"id":2003,"app_id":1001,"account":{"login":"synthetic-owner"},"repository_selection":"selected"}"#.to_vec())), None, 1),
        ("mint refused", good_lookup(), Some((403, format!(r#"{{"message":"{token}"}}"#).into_bytes())), 2),
        ("mint answered 200, not 201", good_lookup(), Some((200, answer(token, 4600, "synthetic-owner/work", WRITE))), 2),
        ("another repository granted", good_lookup(), Some((201, answer(token, 4600, "synthetic-owner/other", WRITE))), 2),
        ("wider permissions granted", good_lookup(), Some((201, answer(token, 4600, "synthetic-owner/work", r#"{"metadata":"read","contents":"write","issues":"write","pull_requests":"write","checks":"read","actions":"read","administration":"write"}"#))), 2),
        ("no repositories in the answer", good_lookup(), Some((201, json!({"token": token, "expires_at": iso(4600), "permissions": serde_json::from_str::<Value>(WRITE).unwrap()}).to_string().into_bytes())), 2),
        ("not JSON", good_lookup(), Some((201, format!("{token}\n").into_bytes())), 2),
    ];
    for (why, lookup, mint, calls) in cases {
        let result = run(&WORK, lookup, mint);
        assert_eq!(result.code, 5, "{why}: {}", result.stderr);
        assert_eq!(result.stdout, "", "{why}");
        assert_eq!(result.stderr, REFUSED, "{why}");
        assert_eq!(result.seen.len(), calls, "{why}");
        assert_secret_free(&result, &[token]);
    }
}

#[test]
fn gi_p6_a_lost_reply_is_a_failure_exit_1_never_a_token() {
    for (lookup, mint, calls) in [
        (None, None, 1),
        (
            Some((200, installation(2002, "synthetic-owner", "selected"))),
            None,
            2,
        ),
    ] {
        let result = run(&WORK, lookup, mint);
        assert_eq!(
            (result.code, result.stdout.as_str(), result.stderr.as_str()),
            (1, "", UNREACHABLE)
        );
        assert_eq!(result.seen.len(), calls);
    }
}

// --- Usage and help ---

#[test]
fn gi_p6_usage_errors_exit_2_naming_no_value_and_calling_nothing() {
    let secretish = "ghs_syntheticPastedValue";
    for args in [
        vec![],
        vec!["token"],
        vec!["mint", "--repository", "synthetic-owner/work"],
        vec!["token", "--repository"],
        vec!["token", "--repository", secretish],
        vec![
            "token",
            "--repository",
            "synthetic-owner/work",
            "--repository",
            "synthetic-owner/work",
        ],
        vec!["token", "--repository", "synthetic-owner/work", secretish],
        vec![
            "token",
            "--repository",
            "synthetic-owner/work",
            "--read=yes",
        ],
        vec!["token", "--repository", "synthetic-owner/work", "--json"],
        vec!["token", "--repository", "../work"],
    ] {
        let result = run(&args, None, None);
        assert_eq!(result.code, 2, "{args:?}");
        assert_eq!(result.stdout, "", "{args:?}");
        assert!(
            result.stderr.starts_with("openwiz: github token: "),
            "{args:?}: {}",
            result.stderr
        );
        assert!(
            result
                .stderr
                .ends_with(" (see openwiz github token --help)\n"),
            "{args:?}"
        );
        assert_eq!(result.stderr.lines().count(), 1);
        assert!(!result.stderr.contains(secretish), "{args:?}");
        assert!(result.seen.is_empty(), "{args:?}");
    }
}

#[test]
fn gi_p6_the_parser_takes_the_contracts_form() {
    let parse = |args: &[&str]| {
        github_token::parse(&args.iter().map(|a| (*a).to_owned()).collect::<Vec<_>>())
    };
    let token = |repository: &str, read| {
        Ok(Parsed::Token(TokenArgs {
            repository: repository.to_owned(),
            read,
        }))
    };
    assert_eq!(parse(&WORK), token("synthetic-owner/work", false));
    assert_eq!(parse(&WORK_READ), token("synthetic-owner/work", true));
    assert_eq!(
        parse(&["token", "--read", "--repository=Synthetic-Owner/Work"]),
        token("synthetic-owner/work", true)
    );
    assert_eq!(parse(&["token", "--help"]), Ok(Parsed::Help));
    assert_eq!(parse(&["-h"]), Ok(Parsed::Help));
}

#[test]
fn gi_p6_help_prints_usage_and_reads_nothing() {
    let result = run(&["token", "--help"], None, None);
    assert_eq!(result.code, 0);
    assert_eq!(result.stdout, github_token::HELP);
    assert!(result.stderr.is_empty() && result.seen.is_empty());
    assert!(openwiz_cli::help().contains(github_token::USAGE));
    assert!(openwiz_cli::help().contains(github_token::HELP));
}

// --- The real program: routing, the environment, and secrecy on stderr ---

#[test]
fn gi_p6_the_openwiz_program_routes_github_token_and_refuses_without_the_secret() {
    let program = super::fixture_cli();
    // No secret in the environment: exit 1 before any GitHub call (curl never runs).
    let out = Command::new(program)
        .args(["github", "token", "--repository", "synthetic-owner/work"])
        .env_clear()
        .env("OPENWIZ_GITHUB_APP_ID", APP_ID)
        .output()
        .unwrap();
    assert_eq!(out.status.code(), Some(1));
    assert!(out.stdout.is_empty());
    assert_eq!(String::from_utf8(out.stderr).unwrap(), CONTEXT);
    // A malformed secret: also exit 1, and stderr holds none of it.
    let out = Command::new(program)
        .args([
            "github",
            "token",
            "--repository",
            "synthetic-owner/work",
            "--read",
        ])
        .env_clear()
        .env("OPENWIZ_GITHUB_APP_KEY", &key().1[..400])
        .env("OPENWIZ_GITHUB_APP_ID", APP_ID)
        .output()
        .unwrap();
    assert_eq!(out.status.code(), Some(1));
    assert!(out.stdout.is_empty());
    let stderr = String::from_utf8(out.stderr).unwrap();
    assert_eq!(stderr, CONTEXT);
    // Usage reaches the command's own parser, not the inventory's.
    let out = Command::new(program)
        .args(["github", "token"])
        .env_clear()
        .output()
        .unwrap();
    assert_eq!(out.status.code(), Some(2));
    assert!(
        String::from_utf8(out.stderr)
            .unwrap()
            .starts_with("openwiz: github token: ")
    );
}
