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
const READ: &str = r#"{"metadata":"read","contents":"read","issues":"read","pull_requests":"read","checks":"read","actions":"read"}"#;
const WRITE: &str = r#"{"metadata":"read","contents":"write","issues":"write","pull_requests":"write","checks":"read","actions":"read"}"#;

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

#[derive(Debug, Clone)]
struct Seen {
    call: String,
    jwt: String,
    body: Option<Value>,
}

type Answer = Option<(u16, Vec<u8>)>;

struct Fake {
    app: Answer,
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
            Call::App => ("app".to_owned(), None, &self.app),
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

fn app_owned_by(owner: &str) -> Answer {
    Some((
        200,
        json!({"id": 1001, "slug": "synthetic-app", "owner": {"login": owner, "type": "User"},
               "permissions": serde_json::from_str::<Value>(WRITE).unwrap()})
        .to_string()
        .into_bytes(),
    ))
}

fn calls(run: &Run) -> Vec<&str> {
    run.seen.iter().map(|s| s.call.as_str()).collect()
}

fn mint_body(run: &Run) -> &Value {
    let seen = run
        .seen
        .iter()
        .find(|s| s.call.starts_with("access_tokens"));
    seen.and_then(|s| s.body.as_ref())
        .expect("a mint was asked for")
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
    run_mode(args, secret, app_id, None, fake, now)
}

fn run_mode(
    args: &[&str],
    secret: Option<&str>,
    app_id: Option<&str>,
    mode: Option<&str>,
    fake: Fake,
    now: u64,
) -> Run {
    let fake = Arc::new(fake);
    let context = Context {
        secret: secret.map(OsString::from),
        app_id: app_id.map(OsString::from),
        mode: mode.map(OsString::from),
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
        app: app_owned_by("synthetic-owner"),
        lookup,
        mint,
        seen: Mutex::new(Vec::new()),
    };
    run_with(args, Some(&key().1), Some(APP_ID), fake, 1000)
}

const WORK: [&str; 3] = ["token", "--repository", "synthetic-owner/work"];
const WORK_READ: [&str; 4] = ["token", "--repository", "synthetic-owner/work", "--read"];

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
            app: app_owned_by(inst["account"].as_str().unwrap()),
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
        assert_eq!(
            calls(&result),
            [
                "app",
                "installation synthetic-owner/work",
                "access_tokens 2002"
            ],
            "{argv:?}"
        );
        assert_eq!(mint_body(&result), &case["request"], "{argv:?}");
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
        let asked = mint_body(&result);
        assert_eq!(
            asked["permissions"],
            serde_json::from_str::<Value>(profile).unwrap()
        );
        assert_eq!(asked["repositories"], json!(["work"]));
        assert_eq!(asked.as_object().unwrap().len(), 2, "nothing else is asked");
    }
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
    assert_eq!(result.seen.len(), 3);
    assert!(result.seen.iter().all(|s| s.jwt == result.seen[0].jwt));
    let parts: Vec<&str> = result.seen[0].jwt.split('.').collect();
    assert_eq!(parts.len(), 3);
    let claims: Value = serde_json::from_slice(&base64url_decode(parts[1])).unwrap();
    assert_eq!(claims, json!({"iss": "1001", "iat": 940, "exp": 1540}));
    let header: Value = serde_json::from_slice(&base64url_decode(parts[0])).unwrap();
    assert_eq!(header, json!({"alg": "RS256", "typ": "JWT"}));
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

const CONTEXT: &str = "openwiz: github token: the App key, App id or App mode is missing or unreadable; no token was minted\n";
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
            app: app_owned_by("synthetic-owner"),
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
    assert_eq!(calls(&result), ["app", "installation synthetic-owner/work"]);
}

#[test]
fn gi_p6_a_refused_exchange_or_an_answer_outside_the_contract_exits_5() {
    let good_lookup = || Some((200, installation(2002, "synthetic-owner", "selected")));
    let token = "synthetic-refused-token";
    let cases: Vec<(&str, Answer, Answer, usize)> = vec![
        ("lookup refused", Some((403, b"{}".to_vec())), None, 2),
        ("installation of all repositories", Some((200, installation(2002, "synthetic-owner", "all"))), None, 2),
        ("another account's installation", Some((200, installation(2002, "synthetic-other", "selected"))), None, 2),
        ("another App's installation", Some((200, br#"{"id":2002,"app_id":1002,"account":{"login":"synthetic-owner"},"repository_selection":"selected"}"#.to_vec())), None, 2),
        ("duplicate installation id", Some((200, br#"{"id":2002,"id":2003,"app_id":1001,"account":{"login":"synthetic-owner"},"repository_selection":"selected"}"#.to_vec())), None, 2),
        ("mint refused", good_lookup(), Some((403, format!(r#"{{"message":"{token}"}}"#).into_bytes())), 3),
        ("mint answered 200, not 201", good_lookup(), Some((200, answer(token, 4600, "synthetic-owner/work", WRITE))), 3),
        ("another repository granted", good_lookup(), Some((201, answer(token, 4600, "synthetic-owner/other", WRITE))), 3),
        ("wider permissions granted", good_lookup(), Some((201, answer(token, 4600, "synthetic-owner/work", r#"{"metadata":"read","contents":"write","issues":"write","pull_requests":"write","checks":"read","actions":"read","administration":"write"}"#))), 3),
        ("no repositories in the answer", good_lookup(), Some((201, json!({"token": token, "expires_at": iso(4600), "permissions": serde_json::from_str::<Value>(WRITE).unwrap()}).to_string().into_bytes())), 3),
        ("not JSON", good_lookup(), Some((201, format!("{token}\n").into_bytes())), 3),
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
    for (app, lookup, mint, calls) in [
        (None, None, None, 1),
        (app_owned_by("synthetic-owner"), None, None, 2),
        (
            app_owned_by("synthetic-owner"),
            Some((200, installation(2002, "synthetic-owner", "selected"))),
            None,
            3,
        ),
    ] {
        let fake = Fake {
            app,
            lookup,
            mint,
            seen: Mutex::new(Vec::new()),
        };
        let result = run_with(&WORK, Some(&key().1), Some(APP_ID), fake, 1000);
        assert_eq!(
            (result.code, result.stdout.as_str(), result.stderr.as_str()),
            (1, "", UNREACHABLE)
        );
        assert_eq!(result.seen.len(), calls);
    }
}

fn factory_installations() -> Vec<(String, String)> {
    let text = include_str!("../../contracts/github-identity.v1.md");
    let start = text.find("```json\n").unwrap() + 8;
    let end = start + text[start..].find("\n```").unwrap();
    let pin: Value = serde_json::from_str(&text[start..end]).unwrap();
    let mut found = Vec::new();
    for i in pin["installations"].as_array().unwrap() {
        for r in i["repositories"].as_array().unwrap() {
            found.push((
                i["account"].as_str().unwrap().to_owned(),
                r.as_str().unwrap().to_owned(),
            ));
        }
    }
    found
}

type Bound<'a> = (Option<&'a str>, &'a str, String, String, i32, Vec<&'a str>);

#[test]
fn j48_a_user_app_mints_only_on_its_owners_account_and_the_factory_only_when_explicit() {
    let named = factory_installations();
    let factory_owner = named.last().unwrap().0.clone();
    let cross = named
        .iter()
        .find(|(a, _)| *a != factory_owner)
        .unwrap()
        .clone();
    let token = "synthetic-bound-token";
    let mut cases: Vec<Bound> = vec![
        (
            None,
            "synthetic-owner",
            "synthetic-owner".into(),
            "synthetic-owner/work".into(),
            0,
            vec!["app", "installation", "access_tokens"],
        ),
        (
            Some("user"),
            "synthetic-owner",
            "synthetic-owner".into(),
            "synthetic-owner/work".into(),
            0,
            vec!["app", "installation", "access_tokens"],
        ),
        (
            None,
            "synthetic-elsewhere",
            "synthetic-owner".into(),
            "synthetic-owner/work".into(),
            5,
            vec!["app", "installation"],
        ),
        (
            Some("user"),
            "Synthetic-Elsewhere",
            "synthetic-owner".into(),
            "synthetic-owner/work".into(),
            5,
            vec!["app", "installation"],
        ),
        (
            None,
            &factory_owner,
            cross.0.clone(),
            cross.1.clone(),
            5,
            vec!["app", "installation"],
        ),
        (
            Some("factory"),
            &factory_owner,
            cross.0.clone(),
            format!("{}/synthetic-unnamed", cross.0),
            5,
            vec!["installation"],
        ),
        (
            Some("factory"),
            &factory_owner,
            "synthetic-owner".into(),
            "synthetic-owner/work".into(),
            5,
            vec!["installation"],
        ),
    ];
    for (account, repository) in &named {
        cases.push((
            Some("factory"),
            &factory_owner,
            account.clone(),
            repository.clone(),
            0,
            vec!["installation", "access_tokens"],
        ));
    }
    for (mode, owner, account, repository, exit, expected) in cases {
        let why = format!("{mode:?} {owner} {account} {repository}");
        let fake = Fake {
            app: app_owned_by(owner),
            lookup: Some((200, installation(2002, &account, "selected"))),
            mint: Some((201, answer(token, 4600, &repository, WRITE))),
            seen: Mutex::new(Vec::new()),
        };
        let args = ["token", "--repository", repository.as_str()];
        let result = run_mode(&args, Some(&key().1), Some(APP_ID), mode, fake, 1000);
        assert_eq!(result.code, exit, "{why}: {}", result.stderr);
        let names: Vec<&str> = calls(&result)
            .into_iter()
            .map(|c| c.split(' ').next().unwrap())
            .collect();
        assert_eq!(names, expected, "{why}");
        if exit == 0 {
            assert_eq!(result.stdout, format!("{token}\n"), "{why}");
        } else {
            assert_eq!(
                (result.stdout.as_str(), result.stderr.as_str()),
                ("", REFUSED),
                "{why}"
            );
            assert_secret_free(&result, &[token]);
        }
    }
}

#[test]
fn j48_an_unreadable_mode_or_a_revoked_or_foreign_app_key_mints_nothing() {
    let good = || Fake {
        app: app_owned_by("synthetic-owner"),
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
    for mode in ["", "public", "Factory", "factory "] {
        let result = run_mode(
            &WORK,
            Some(&key().1),
            Some(APP_ID),
            Some(mode),
            good(),
            1000,
        );
        assert_eq!(
            (result.code, result.stderr.as_str()),
            (1, CONTEXT),
            "{mode:?}"
        );
        assert!(result.seen.is_empty(), "{mode:?}");
    }
    for app in [
        Some((401, br#"{"message":"Bad credentials"}"#.to_vec())),
        Some((
            200,
            br#"{"id":1002,"owner":{"login":"synthetic-owner"}}"#.to_vec(),
        )),
        Some((200, br#"{"id":1001}"#.to_vec())),
    ] {
        let fake = Fake { app, ..good() };
        let result = run_with(&WORK, Some(&key().1), Some(APP_ID), fake, 1000);
        assert_eq!((result.code, result.stderr.as_str()), (5, REFUSED));
        assert_eq!(calls(&result), ["app"]);
    }
}

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

#[test]
fn gi_p6_the_openwiz_program_routes_github_token_and_refuses_without_the_secret() {
    let program = super::fixture_cli();
    let out = Command::new(program)
        .args(["github", "token", "--repository", "synthetic-owner/work"])
        .env_clear()
        .env("OPENWIZ_GITHUB_APP_ID", APP_ID)
        .output()
        .unwrap();
    assert_eq!(out.status.code(), Some(1));
    assert!(out.stdout.is_empty());
    assert_eq!(String::from_utf8(out.stderr).unwrap(), CONTEXT);
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

struct ServiceFake {
    repository: String,
    app: Answer,
    lookup: Answer,
    exchanges: Mutex<u32>,
}
impl Exchange for ServiceFake {
    fn exchange(&self, installation: u64, _: &str, _: &[u8], _: Instant) -> Result<Vec<u8>, Error> {
        assert_eq!(installation, 2002);
        *self.exchanges.lock().unwrap() += 1;
        Ok(answer(
            "synthetic-service-token",
            4600,
            &self.repository,
            WRITE,
        ))
    }
    fn github(&self, call: &Call<'_>, _: &str, _: Instant) -> Result<(u16, Vec<u8>), Error> {
        match call {
            Call::App => self.app.clone().ok_or(Error),
            Call::Installation { .. } => self.lookup.clone().ok_or(Error),
            Call::AccessToken { .. } => panic!("the service mints through exchange"),
        }
    }
}

#[test]
fn r3_the_service_app_never_exchanges_for_another_owners_or_another_installation() {
    use openwiz_adapter_github::allowlist::Invocation;
    use openwiz_adapter_github::app::{App, Identity, Mode};
    let root = std::env::temp_dir().join(format!("ow-606-r3-{}", std::process::id()));
    super::dirs::private_dir_all(root.join("service/app")).unwrap();
    let key_path = root.join("service/app/private-key.pem");
    std::fs::write(&key_path, &key().0).unwrap();
    std::fs::set_permissions(
        &key_path,
        std::os::unix::fs::PermissionsExt::from_mode(0o600),
    )
    .unwrap();
    let foreign_app = br#"{"id":2002,"app_id":1002,"account":{"login":"synthetic-owner"},"repository_selection":"selected"}"#;
    let cases: Vec<(&str, Answer, Answer, u32)> = vec![
        (
            "its owner's own installation",
            app_owned_by("synthetic-owner"),
            Some((200, installation(2002, "synthetic-owner", "selected"))),
            1,
        ),
        (
            "an App owned by another account",
            app_owned_by("synthetic-elsewhere"),
            Some((200, installation(2002, "synthetic-owner", "selected"))),
            0,
        ),
        (
            "another installation than the configured one",
            app_owned_by("synthetic-owner"),
            Some((200, installation(2003, "synthetic-owner", "selected"))),
            0,
        ),
        (
            "every repository",
            app_owned_by("synthetic-owner"),
            Some((200, installation(2002, "synthetic-owner", "all"))),
            0,
        ),
        (
            "another App's installation",
            app_owned_by("synthetic-owner"),
            Some((200, foreign_app.to_vec())),
            0,
        ),
        (
            "a revoked key",
            Some((401, b"{}".to_vec())),
            Some((200, installation(2002, "synthetic-owner", "selected"))),
            0,
        ),
        (
            "a lost App answer",
            None,
            Some((200, installation(2002, "synthetic-owner", "selected"))),
            0,
        ),
    ];
    for (why, app, lookup, exchanged) in cases {
        let fake = Arc::new(ServiceFake {
            repository: "synthetic-owner/work".into(),
            app,
            lookup,
            exchanges: Mutex::new(0),
        });
        let identity = Identity {
            app_id: 1001,
            installation_id: 2002,
            repository: "synthetic-owner/work".into(),
        };
        let client = App::open_mode(
            &root,
            identity,
            Mode::User,
            "/nonexistent/gh".into(),
            fake.clone(),
            Arc::new(Fixed(1000)),
        )
        .unwrap();
        let call = Invocation::new(&["issue", "view", "901", "--json", "comments"]).unwrap();
        assert!(
            client
                .execute(&call, Instant::now() + std::time::Duration::from_secs(10))
                .is_err(),
            "{why}"
        );
        assert_eq!(*fake.exchanges.lock().unwrap(), exchanged, "{why}");
    }
    let named = factory_installations();
    let factory_owner = named.last().unwrap().0.clone();
    let (cross_account, cross_repository) = named
        .iter()
        .find(|(a, _)| *a != factory_owner)
        .unwrap()
        .clone();
    for (why, mode, repository, exchanged) in [
        (
            "a named cross-account installation, factory mode",
            Mode::Factory,
            cross_repository.clone(),
            1,
        ),
        (
            "the same installation without the setting",
            Mode::User,
            cross_repository.clone(),
            0,
        ),
        (
            "an unnamed repository, factory mode",
            Mode::Factory,
            format!("{cross_account}/synthetic-unnamed"),
            0,
        ),
    ] {
        let fake = Arc::new(ServiceFake {
            repository: repository.clone(),
            app: app_owned_by(&factory_owner),
            lookup: Some((200, installation(2002, &cross_account, "selected"))),
            exchanges: Mutex::new(0),
        });
        let identity = Identity {
            app_id: 1001,
            installation_id: 2002,
            repository,
        };
        let client = App::open_mode(
            &root,
            identity,
            mode,
            "/nonexistent/gh".into(),
            fake.clone(),
            Arc::new(Fixed(1000)),
        )
        .unwrap();
        let call = Invocation::new(&["issue", "view", "901", "--json", "comments"]).unwrap();
        assert!(
            client
                .execute(&call, Instant::now() + std::time::Duration::from_secs(10))
                .is_err(),
            "{why}"
        );
        assert_eq!(*fake.exchanges.lock().unwrap(), exchanged, "{why}");
    }
    std::fs::remove_dir_all(&root).unwrap();
}
