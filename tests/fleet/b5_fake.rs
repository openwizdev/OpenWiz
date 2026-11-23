use serde_json::{Value, json};
use std::ffi::OsStr;
use std::fs;
use std::os::unix::fs::DirBuilderExt;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Output, Stdio};
use std::sync::{Arc, Mutex, OnceLock, Weak};
use std::time::{Duration, Instant};

pub const HEAD10: &str = "1010101010101010101010101010101010101010";
pub const HEAD11: &str = "1111111111111111111111111111111111111111";
pub const BASE: &str = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
pub const APPROVAL: &str = "**Plan graph approved by Jake, 2026-10-30, revision 1:** \"approved\"\n\n| Ticket | Title | Blocked by | Label |\n| --- | --- | --- | --- |\n| #10 | Synthetic ticket 10 | none | ready-for-agent |\n| #11 | Synthetic ticket 11 | #10 | ready-for-agent |\n\nFingerprint: `5a46b243aa88e90eaae1c4332f4d625154c4299a6fc3f15f9f75bc6ab414c66c`\n\n```text\nplan-graph revision v2\nspec #9 body sha256 e8ed494ca2bac1d6fd37b4742dcf45b43ac1180e687098745590f3692f90a71a\nticket #10 blocked-by none body sha256 60c009f9e72945c1dc45fe9f9bd9cd09dc092b5f87fcb23e3c873cf4372dca9e title Synthetic ticket 10\nticket #11 blocked-by #10 body sha256 04673879b8ae2d96eec6d0e9cc48f8fe4b3d735792fc246107f6661b40de4f3e title Synthetic ticket 11\n```\n";
pub const IDENTITY: &str = "## GitHub identity\n| Setting | Value |\n| --- | --- |\n| Record authors | `openwiz[bot]`, `syn-owner` |\n";
pub fn node_in(path: &OsStr, cache: Option<&Path>) -> Option<PathBuf> {
    let cached = cache.map(|p| p.join("node/24.22.1/x64/bin/node"));
    std::env::split_paths(path)
        .map(|p| p.join("node"))
        .chain(cached)
        .find_map(|p| p.is_file().then(|| p.canonicalize().unwrap()))
}
pub fn node() -> PathBuf {
    node_in(
        &std::env::var_os("PATH").unwrap_or_default(),
        std::env::var_os("RUNNER_TOOL_CACHE")
            .as_deref()
            .map(Path::new),
    )
    .expect("Node 24.22.1, required by docs/agents/fleet.md")
}

pub struct World {
    pub dir: PathBuf,
    server: Arc<FakeServer>,
}
impl World {
    pub fn new(name: &str) -> Self {
        let dir = std::env::temp_dir().join(format!("openwiz-b5-{}-{name}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::DirBuilder::new()
            .recursive(true)
            .mode(0o700)
            .create(&dir)
            .unwrap();
        let node = node();
        let server = shared_server(&node);
        std::os::unix::fs::symlink(server.dir.join("fake.cjs"), dir.join("fake.cjs")).unwrap();
        std::os::unix::fs::symlink(server.dir.join("fake.sock"), dir.join("fake.sock")).unwrap();
        for name in ["gh", "room-cli"] {
            std::os::unix::fs::symlink("fake.cjs", dir.join(name)).unwrap();
        }
        let bin = dir.join("bin");
        fs::DirBuilder::new().mode(0o700).create(&bin).unwrap();
        let client = client();
        if let Err(error) = fs::hard_link(&client, bin.join("gh")) {
            assert_eq!(error.kind(), std::io::ErrorKind::CrossesDevices);
            let copied = Command::new(&node)
                .args([
                    "-e",
                    "require('node:fs').copyFileSync(process.argv[1], process.argv[2])",
                ])
                .arg(&client)
                .arg(bin.join("gh"))
                .output()
                .expect("copy the client across filesystems");
            assert!(copied.status.success(), "{copied:?}");
        }
        fs::hard_link(bin.join("gh"), bin.join("room-cli")).unwrap();
        let fixture =
            PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("fixtures/room-cli-v127/new-thread");
        let template: Value = serde_json::from_str(
            &fs::read_to_string(fixture.join("thread-show-active.json")).unwrap(),
        )
        .unwrap();
        let receipt: Value = serde_json::from_str(
            &fs::read_to_string(fixture.join("spawn-receipt-created.json")).unwrap(),
        )
        .unwrap();
        let mut catalogue: Value =
            serde_json::from_str(&fs::read_to_string(fixture.join("cloud-status.json")).unwrap())
                .unwrap();
        for h in catalogue["harnesses"].as_array_mut().unwrap() {
            match h["id"].as_str() {
                Some("codex") => h["models"][0]["model"] = "gpt-6.1-sol".into(),
                Some("claude-code") => h["models"][0]["model"] = "claude-opus-5-5".into(),
                _ => {}
            }
        }
        let rows = vec![
            json!({"n":9,"title":"Synthetic graph","body":"Synthetic graph","subs":[10,11],"blockers":[],"labels":[],"closed":false}),
            json!({"n":10,"title":"Synthetic ticket 10","body":"**Owned paths:** `crates/example/one.rs`\n**Relies on:** nothing","subs":[],"blockers":[],"labels":["ready-for-agent"],"closed":false}),
            json!({"n":11,"title":"Synthetic ticket 11","body":"**Owned paths:** `crates/example/two.rs`\n**Relies on:** nothing","subs":[],"blockers":[10],"labels":["ready-for-agent"],"closed":false}),
        ];
        let now = 1_793_400_000_000_u64;
        let rules = "## Builder\n| Setting | Value | `room-cli thread spawn` flag |\n| --- | --- | --- |\n| Harness | Claude Code | `--provider claude-code` |\n| Model | Opus | `--model claude-opus-5-5` |\n| Effort | XHigh | `--reasoning-level xhigh` |\n## Reviewer\n| Setting | Value | `room-cli thread spawn` flag |\n| --- | --- | --- |\n| Harness | Codex | `--provider codex` |\n| Model | Sol | `--model gpt-6.1-sol` |\n| Effort | High | `--reasoning-level high` |\n## CI checks\n| Check | Runs | Required on |\n| --- | --- | --- |\n| `rust` | tests | `main` |\n## Standing merge rules\n| Pull request | Review | Merged by, and when |\n| --- | --- | --- |\n| A ticket in an approved plan graph | its reviewer | The loop, as soon as the reviewer's APPROVE names that exact commit and CI is green |\n";
        let codex = "| Setting | Value | `room-cli thread spawn` flag |\n| --- | --- | --- |\n| Harness | Codex | `--provider codex` |\n| Model | Sol | `--model gpt-6.1-sol` |\n| Effort | High | `--reasoning-level high` |\n";
        let claude = "| Setting | Value | `room-cli thread spawn` flag |\n| --- | --- | --- |\n| Harness | Claude | `--provider claude-code` |\n| Model | Opus | `--model claude-opus-5-5` |\n| Effort | High | `--reasoning-level high` |\n";
        let rules = format!(
            "{rules}\n## Builder for small tickets\n{codex}## Reviewer for Claude-built\n{codex}## Reviewer for GPT-built\n{claude}{IDENTITY}"
        );
        let world = Self { dir, server };
        world.save(&json!({"issues":rows,"prs":[],"comments":{"9":[{"id":100,"body":APPROVAL,"created":now,"updated":now}]},"threads":{},"base":BASE,"rules":rules,"template":template,"receipt":receipt,"catalogue":catalogue,"next":1000,"spawn_count":0,"merge_bodies":[],"overrides":{},"crash":"","timeline":{},"fail_record":""}));
        world
    }
    pub fn load(&self) -> Value {
        serde_json::from_slice(&fs::read(self.dir.join("world.json")).unwrap()).unwrap()
    }

    pub fn save(&self, v: &Value) {
        fs::write(self.dir.join("world.json"), serde_json::to_vec(v).unwrap()).unwrap();
    }
    pub fn change(&self, f: impl FnOnce(&mut Value)) {
        let mut s = self.load();
        f(&mut s);
        self.save(&s);
    }
    pub fn command(&self, args: &[&str]) -> Command {
        let mut c = Command::new(crate::support::openwiz_release());
        c.args(args)
            .env(
                "PATH",
                format!(
                    "{}:{}",
                    self.dir.join("bin").display(),
                    std::env::var("PATH").unwrap_or_default()
                ),
            )
            .env("OPENWIZ_STATE_DIR", self.dir.join("state"))
            .env(
                "OPENWIZ_FIXTURE_PROGRAM",
                self.dir.join("bin").join("room-cli"),
            )
            .env_remove("OPENWIZ_FIXTURE_ROOT")
            .env_remove("OPENWIZ_FIXTURE_READ_TIMEOUT_MS")
            .env_remove("OPENWIZ_ORCHESTRATOR_THREAD_ID");
        c
    }
    pub fn run(&self, args: &[&str]) -> Output {
        self.command(args).output().unwrap()
    }
    pub fn pr(&self, ticket: u64) {
        self.change(|s|{
        let head=if ticket==10{HEAD10}else{HEAD11};let base=s["base"].clone();
        s["prs"].as_array_mut().unwrap().push(json!({"n":ticket+100,"ticket":ticket,"head":head,"base":base,"merged":false,"report":null,"files":[],"subject":"Synthetic green","ci":"success"}));
    });
    }
    pub fn approve(&self, ticket: u64) {
        self.change(|s|{
        let pr=s["prs"].as_array_mut().unwrap().iter_mut().find(|p|p["ticket"]==ticket).unwrap();
        let text=format!("VERDICT: APPROVE at {}",pr["head"].as_str().unwrap());pr["report"]=text.clone().into();
        s["next"]=json!(s["next"].as_u64().unwrap()+1);
        let id=s["next"].clone();let key=(ticket+100).to_string();
        if s["comments"][&key].is_null(){s["comments"][&key]=json!([])}
        s["comments"][key].as_array_mut().unwrap().push(json!({"id":id,"body":text,"created":1_793_400_010_000_u64,"updated":1_793_400_010_000_u64}));
    });
    }
    pub fn calls(&self) -> Vec<(String, Vec<String>)> {
        fs::read_to_string(self.dir.join("calls.log"))
            .unwrap_or_default()
            .lines()
            .map(|l| serde_json::from_str(l).unwrap())
            .collect()
    }
    pub fn writes(&self) -> Vec<(String, Vec<String>)> {
        self.calls()
            .into_iter()
            .inspect(|(tool, args)| {
                if tool == "gh"
                    && let Some(at) = args.iter().position(|a| a == "--body")
                {
                    assert!(
                        !args[at + 1].contains("thr_"),
                        "public record leaks a thread: {}",
                        args[at + 1]
                    );
                }
            })
            .filter(|(tool, a)| {
                if tool == "room-cli" {
                    a.first().is_some_and(|s| s == "thread")
                        && a.get(1)
                            .is_some_and(|s| ["spawn", "tell", "archive"].contains(&s.as_str()))
                } else {
                    a.get(1).is_some_and(|s| {
                        ["comment", "edit", "close", "merge"].contains(&s.as_str())
                    })
                }
            })
            .collect()
    }
}
impl Drop for World {
    fn drop(&mut self) {
        self.server.drop_world(&self.dir);
        if !std::thread::panicking() {
            let _ = fs::remove_dir_all(&self.dir);
        }
    }
}

struct FakeServer {
    dir: PathBuf,
    child: Mutex<Child>,
}

impl FakeServer {
    fn drop_world(&self, world: &Path) {
        let _ = self.control(world, "--drop-world");
    }

    fn control(&self, world: &Path, tool: &str) -> Option<Vec<u8>> {
        use std::io::{Read, Write};
        use std::os::unix::net::UnixStream;
        let mut socket = UnixStream::connect(self.dir.join("fake.sock")).ok()?;
        socket.set_read_timeout(Some(Duration::from_secs(2))).ok()?;
        socket
            .set_write_timeout(Some(Duration::from_secs(2)))
            .ok()?;
        let mut request = Vec::new();
        for field in [world.to_str().unwrap(), tool] {
            request.extend_from_slice(&(field.len() as u32).to_be_bytes());
            request.extend_from_slice(field.as_bytes());
        }
        socket
            .write_all(&(request.len() as u32).to_be_bytes())
            .ok()?;
        socket.write_all(&request).ok()?;
        let mut reply = Vec::new();
        socket.read_to_end(&mut reply).ok()?;
        Some(reply)
    }
}

impl Drop for FakeServer {
    fn drop(&mut self) {
        let child = self.child.get_mut().unwrap_or_else(|p| p.into_inner());
        let _ = child.kill();
        let _ = child.wait();
        let _ = fs::remove_dir_all(&self.dir);
    }
}

fn shared_server(node: &Path) -> Arc<FakeServer> {
    static SERVER: Mutex<Weak<FakeServer>> = Mutex::new(Weak::new());
    let mut slot = SERVER.lock().unwrap_or_else(|p| p.into_inner());
    if let Some(server) = slot.upgrade() {
        return server;
    }
    static GENERATION: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);
    let generation = GENERATION.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
    let dir = Path::new(env!("CARGO_TARGET_TMPDIR"))
        .join(format!("b5-server-{}-{generation}", std::process::id()));
    let _ = fs::remove_dir_all(&dir);
    fs::DirBuilder::new()
        .recursive(true)
        .mode(0o700)
        .create(&dir)
        .unwrap();
    let written = Command::new(node)
        .args([
            "-e",
            "require('node:fs').writeFileSync(process.argv[1], process.argv[2], {mode: 0o700})",
        ])
        .arg(dir.join("fake.cjs"))
        .arg(SCRIPT.replacen("#!/usr/bin/env node", &format!("#!{}", node.display()), 1))
        .output()
        .expect("run the fixture script writer");
    assert!(
        written.status.success(),
        "fixture script writer: {}",
        String::from_utf8_lossy(&written.stderr)
    );
    let server = Arc::new(FakeServer {
        child: Mutex::new(serve(node, &dir)),
        dir,
    });
    *slot = Arc::downgrade(&server);
    server
}

fn serve(node: &Path, dir: &Path) -> Child {
    struct Reap(Option<Child>);
    impl Drop for Reap {
        fn drop(&mut self) {
            if let Some(child) = &mut self.0 {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    }
    let log = fs::File::create(dir.join("fake-server.log")).unwrap();
    let server = Command::new(node)
        .arg(dir.join("fake.cjs"))
        .arg("--serve")
        .arg(dir)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(log)
        .spawn()
        .expect("start the world's fake");
    let mut owned = Reap(Some(server));
    let server = owned.0.as_mut().unwrap();
    let until = Instant::now() + Duration::from_secs(10);
    while !dir.join("fake.ready").exists() {
        if let Some(status) = server.try_wait().unwrap() {
            panic!(
                "the world's fake exited {status}: {}",
                fs::read_to_string(dir.join("fake-server.log")).unwrap_or_default()
            );
        }
        assert!(Instant::now() < until, "the world's fake never listened");
        std::thread::sleep(Duration::from_millis(2));
    }
    owned.0.take().unwrap()
}

fn client() -> PathBuf {
    static BUILT: OnceLock<PathBuf> = OnceLock::new();
    static LOCK: Mutex<()> = Mutex::new(());
    let _guard = LOCK.lock().unwrap_or_else(|p| p.into_inner());
    BUILT
        .get_or_init(|| {
            let dir = Path::new(env!("CARGO_TARGET_TMPDIR")).join("b5-client");
            fs::DirBuilder::new()
                .recursive(true)
                .mode(0o700)
                .create(&dir)
                .unwrap();
            let name = {
                use std::hash::{Hash, Hasher};
                let mut hash = std::collections::hash_map::DefaultHasher::new();
                CLIENT.hash(&mut hash);
                format!("client-{:016x}", hash.finish())
            };
            let program = dir.join(&name);
            if program.is_file() {
                return program;
            }
            let source = dir.join(format!("{name}-{}.rs", std::process::id()));
            fs::write(&source, CLIENT).unwrap();
            let built_at = dir.join(format!("{name}-{}", std::process::id()));
            let rustc = std::env::var_os("CARGO")
                .map(PathBuf::from)
                .and_then(|cargo| cargo.parent().map(|bin| bin.join("rustc")))
                .filter(|rustc| rustc.is_file())
                .unwrap_or_else(|| PathBuf::from("rustc"));
            let built = Command::new(rustc)
                .args(["--edition", "2021", "-O", "-C", "strip=symbols", "-o"])
                .arg(&built_at)
                .arg(&source)
                .output()
                .expect("run rustc");
            assert!(
                built.status.success(),
                "build the B5 fake's client: {}",
                String::from_utf8_lossy(&built.stderr)
            );
            fs::rename(&built_at, &program).unwrap();
            let _ = fs::remove_file(&source);
            program
        })
        .clone()
}

const CLIENT: &str = r#"
use std::io::{Read, Write};
use std::os::unix::ffi::OsStrExt;
use std::os::unix::net::UnixStream;
use std::process::exit;

fn field(out: &mut Vec<u8>, bytes: &[u8]) {
    out.extend_from_slice(&(bytes.len() as u32).to_be_bytes());
    out.extend_from_slice(bytes);
}

fn number(bytes: &[u8], at: usize) -> u32 {
    u32::from_be_bytes([bytes[at], bytes[at + 1], bytes[at + 2], bytes[at + 3]])
}

fn main() {
    let exe = std::env::current_exe().expect("its own path");
    let world = exe.parent().and_then(|bin| bin.parent()).expect("its world");
    let mut request = Vec::new();
    field(&mut request, world.as_os_str().as_bytes());
    field(&mut request, exe.file_name().expect("its name").as_bytes());
    field(&mut request, std::process::id().to_string().as_bytes());
    field(&mut request, std::os::unix::process::parent_id().to_string().as_bytes());
    for arg in std::env::args_os().skip(1) {
        field(&mut request, arg.as_bytes());
    }
    let mut socket = UnixStream::connect(world.join("fake.sock")).unwrap_or_else(|e| {
        eprintln!("B5 fake client: {e}");
        exit(1)
    });
    socket.write_all(&(request.len() as u32).to_be_bytes()).expect("frame the call");
    socket.write_all(&request).expect("send the call");
    let mut reply = Vec::new();
    socket.read_to_end(&mut reply).expect("read the answer");
    if reply.len() < 12 {
        eprintln!("B5 fake client: no answer");
        exit(1);
    }
    let code = number(&reply, 0) as i32;
    let out = number(&reply, 4) as usize;
    let err = number(&reply, 8) as usize;
    if reply.len() != 12 + out + err {
        eprintln!("B5 fake client: a cut answer");
        exit(1);
    }
    let _ = std::io::stderr().write_all(&reply[12 + out..]);
    let mut stdout = std::io::stdout().lock();
    let _ = stdout.write_all(&reply[12..12 + out]);
    let _ = stdout.flush();
    exit(code);
}
"#;

const SCRIPT: &str = r#"#!/usr/bin/env node
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const wait = ms => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
class Reply {
  constructor(code, value) { this.code = code; this.value = value; }
}
// One call, exactly as one fake process made it before #1259: `tool` with
// arguments `a`, in world `d`. `id` names its active files (that process's
// id) and `ppid` is its caller. Returns its exit code, stdout and stderr.
function call(d, tool, a, id, ppid) {
const lock = path.join(d, 'world.lock');
// An exclusive private file serializes concurrent fake calls without another tool.
for (;;) {
  try { fs.closeSync(fs.openSync(lock, 'wx', 0o600)); break; }
  catch (e) { if (e.code !== 'EEXIST') throw e; wait(5); }
}
let held = true;
let workflowActive = null;
function unlock() { if (held) { fs.unlinkSync(lock); held = false; } }
const original = fs.readFileSync(path.join(d, 'world.json'), 'utf8');
const s = JSON.parse(original);
fs.appendFileSync(path.join(d, 'calls.log'), JSON.stringify([tool, a]) + '\n');
function save() {
  const updated = JSON.stringify(s);
  if (updated === original) return;
  fs.writeFileSync(path.join(d, 'world.new'), updated);
  fs.renameSync(path.join(d, 'world.new'), path.join(d, 'world.json'));
}
function answer(v) {
  save();
  if (tool === 'gh' && a.includes('--paginate') && typeof v !== 'string') {
    v = v.map(page => JSON.stringify(page)).join('\n');
  }
  throw new Reply(0, v);
}
function no() { save(); throw new Reply(97); }
const is = (...args) => JSON.stringify(a) === JSON.stringify(args);
const prefix = (...args) => args.every((v, i) => a[i] === v);
const flag = name => a[a.indexOf(name) + 1];
const issue = n => s.issues.find(i => i.n === n);
const pr = n => s.prs.find(p => p.n === n);
// Default synthetic inventory; privacy is returned separately and can differ.
const repository = s.repository ?? 'jparker2006/ClosedWiz';
const repoUrl = 'https://github.invalid/' + repository;
const url = n => repoUrl + '/issues/' + n;
const commentUrl = (n, id) => url(n) + '#issuecomment-' + id;
// #718: a comment row as the requested projection shapes it. A projection
// that asks for `author` gets the stored one (a planted outsider, or null for
// a deleted account), else the factory's App; one that doesn't gets none.
const FACTORY = 'openwiz[bot]';
function projected(c) {
  if (typeof c !== 'object' || c === null || Array.isArray(c)) return c;
  const {author, ...rest} = c;
  return flag('--jq').includes('author:') ? {...rest, author: author === undefined ? FACTORY : author} : rest;
}
function comment(n, body) {
  if (s.fail_record && body.startsWith(s.fail_record)) no();
  const c = {id: ++s.next, body, created: s.comment_time ?? 1793400010000, updated: s.comment_time ?? 1793400010000};
  (s.comments[n] ??= []).push(c);
  if (body === 'launch-fleet: started') {
    (s.comments[n] ??= []).push({id: ++s.next, body: 'launch-fleet: start checked, branch synthetic-branch-' + n, created: c.created, updated: c.updated});
  }
  if (body.startsWith('launch-fleet: started, thread ')) {
    const thread = body.slice('launch-fleet: started, thread '.length);
    (s.comments[n] ??= []).push({id: ++s.next, body: 'launch-fleet: start checked, thread ' + thread + ', branch synthetic-branch-' + n, created: c.created, updated: c.updated});
  }
  return commentUrl(n, c.id);
}
function row(i) {
  const links = ns => ({nodes: ns.map(n => ({id: 'syn-issue-' + n, number: n,
    state: 'OPEN', title: 'Synthetic', url: 'https://example.invalid/issues/' + n})), totalCount: ns.length});
  return {blockedBy: links(i.blockers), body: i.body, id: 'syn-issue-' + i.n,
    labels: i.labels.map(l => ({id: 'syn-label-' + l, name: l, description: 'Synthetic', color: 'ffffff'})),
    milestone: null, number: i.n, state: i.closed ? 'CLOSED' : 'OPEN', subIssues: links(i.subs), title: i.title};
}
function prrow(p) {
  return {baseRefName: p.branch ?? 'main', closingIssuesReferences: [{id: 'syn-issue-' + p.ticket,
    number: p.ticket, repository: {id: 'syn-repo', name: repository.split('/')[1],
      owner: {id: 'syn-owner', login: repository.split('/')[0]}}, url: p.closing_url ?? url(p.ticket)}],
    headRefName: 'synthetic-branch-' + p.ticket, headRefOid: p.head, isDraft: p.draft ?? false,
    mergeCommit: p.merged ? {oid: p.merge ?? 'a'.repeat(40)} : null,
    mergedAt: p.merged ? (p.merged_at ?? '2026-10-31T00:00:00Z') : null,
    number: p.n, state: p.merged ? 'MERGED' : p.closed ? 'CLOSED' : 'OPEN'};
}
// Synthetic concurrency rendezvous: arrivals, not elapsed speed, prove overlap.
function rendezvous(group, key, count, value, pages = false) {
  save(); unlock();
  const prefix = group + '-arrival-';
  fs.writeFileSync(path.join(d, prefix + key), 'arrived');
  const deadline = Date.now() + 3000;
  while (fs.readdirSync(d).filter(n => n.startsWith(prefix)).length < count) {
    if (Date.now() >= deadline) throw new Reply(97);
    wait(5);
  }
  fs.appendFileSync(path.join(d, group + '-released'), key + '\n');
  throw new Reply(0, pages ? value.map(page => JSON.stringify(page)).join('\n') : value);
}
function run() {
  if (tool === 'gh' && a.includes('--slurp') && a.includes('--jq')) throw new Reply(1, 'the --slurp option is not supported with --jq or --template');
  const override = s.overrides[JSON.stringify([tool, a])];
  if (override != null) {
    if (Number.isInteger(override)) throw new Reply(override);
    if (override.fake_exit !== undefined) throw new Reply(override.fake_exit, override.fake_stdout);
    const workflow = s.workflow_barriers?.[a[1]];
    if (workflow) {
      workflowActive = path.join(d, 'workflow-active-' + id);
      fs.writeFileSync(workflowActive, 'active');
      const active = fs.readdirSync(d).filter(n => n.startsWith('workflow-active-')).length;
      const peakPath = path.join(d, 'workflow-peak');
      const peak = fs.existsSync(peakPath) ? Number(fs.readFileSync(peakPath, 'utf8')) : 0;
      fs.writeFileSync(peakPath, String(Math.max(peak, active)));
      rendezvous(workflow.group, String(workflow.id), workflow.count, override, true);
    }
    answer(override);
  }
  if (tool === 'gh') {
    if (is('repo', 'view', '--json', 'nameWithOwner,isPrivate')) answer(s.repository_privacy ?? {
      nameWithOwner: repository, isPrivate: repository.toLowerCase() === 'jparker2006/closedwiz'});
    if (s.inventory_barrier) {
      if (prefix('repo', 'view')) rendezvous('inventory', 'repo', 3, {defaultBranchRef: {name: 'main'}, nameWithOwner: repository, url: repoUrl});
      if (prefix('issue', 'list')) rendezvous('inventory', 'issues', 3, s.issues.map(row));
      if (prefix('pr', 'list')) rendezvous('inventory', 'prs', 3, s.prs.map(p => ({...prrow(p), title: 'Synthetic PR ' + p.n})));
    }

    if (is('repo', 'view', '--json', 'defaultBranchRef,nameWithOwner,url')) answer({
      defaultBranchRef: {name: 'main'}, nameWithOwner: repository,
      url: repoUrl});
    if (prefix('issue', 'list')) answer(s.issues.map(row));
    if (prefix('pr', 'list')) answer(s.prs.map(p => {
      const r = {...prrow(p), title: 'Synthetic PR ' + p.n}; if (p.no_closes) r.closingIssuesReferences = []; return r;
    }));
    if (prefix('api', 'graphql')) answer({data: {repository: {pullRequest: {isMergeQueueEnabled: false}}}});
    if (a[0] === 'api') {
      const p = a[1].replace(/^repos\/\{owner\}\/\{repo\}\//, '');
      if (p.startsWith('git/ref/heads/')) {
        const value = {sha: s.base};
        // Synthetic base move after a chosen snapshot, before the next read.
        if (s.move_base_after_reads && --s.move_base_after_reads === 0) s.base = 'c'.repeat(40);
        answer(value);
      }
      if (p.startsWith('contents/docs/agents/fleet.md?ref=')) answer(s.rules);
      if (p === 'issues/comments?per_page=100' || /^issues\/comments\?per_page=100&page=[1-9][0-9]*$/.test(p)) {
        const rows = Object.entries(s.comments).flatMap(([n,cs]) => cs.map(c => ({...c, issue_url: 'https://github.invalid/api/v3/repos/' + repository + '/issues/' + n})));
        const page = Number(p.split('&page=')[1] ?? 1);
        const pages = s.repository_comment_pages;
        if (pages && pages[page - 1] === undefined) no();
        const value = structuredClone(p.includes('&page=') ? (pages ? pages[page - 1] : rows.slice((page - 1) * 100, page * 100)) : (pages ?? [rows]));
        if (Array.isArray(value)) value.forEach((r, i) => { value[i] = Array.isArray(r) ? r.map(projected) : projected(r); });
        // Keep the planning snapshot valid while revoking its live approval.
        if (page === 1 && s.revoke_approval_after_comments) { s.revoke_approval_after_comments = false; s.comments['9'] = []; }
        if (page === 1 && s.duplicate_placement_after_comments) { s.duplicate_placement_after_comments = false; s.issues.push({...structuredClone(s.issues[0]), n: 19}); }
        if (page === 1 && s.flip_rules) { s.flip_rules = false; s.base = 'c'.repeat(40); s.rules = s.rules.replaceAll('--model claude-opus-5-5', '--model syn-changed-builder'); }
        // Synthetic slow pages: one aggregate process exceeds READ_TIMEOUT;
        // individual page calls finish within it, without holding the fake lock.
        if (s.repository_comment_delay_ms) {
          const activePath = path.join(d, 'comment-active-' + id);
          fs.writeFileSync(activePath, String(page));
          const active = fs.readdirSync(d).filter(n => n.startsWith('comment-active-')).length;
          const peakPath = path.join(d, 'comment-peak');
          const peak = fs.existsSync(peakPath) ? Number(fs.readFileSync(peakPath, 'utf8')) : 0;
          fs.writeFileSync(peakPath, String(Math.max(peak, active)));
          const output = a.includes('--paginate') ? value.map(v => JSON.stringify(v)).join('\n') : value;
          save(); unlock();
          wait(s.repository_comment_delay_ms * (a.includes('--paginate') ? value.length : 1));
          fs.unlinkSync(activePath);
          throw new Reply(0, output);
        }
        answer(value);
      }
      if (p.startsWith('issues/')) {
        const [, n, kind] = p.split('/');
        if (kind.startsWith('comments?')) {
          answer([(s.comments[n] ?? []).map(projected)]);
        }
        if (kind.startsWith('timeline?')) {
          const value = [s.timeline[n] ?? []];
          if (s.flip_approval_on_timeline) { s.comments['9'] = []; s.flip_approval_on_timeline = false; }
          answer(value);
        }
      }
      if (p.startsWith('commits/')) {
        const head = p.split('/').at(-1); answer({sha: head, subject: s.prs.find(p => p.head === head).subject});
      }
      if (p.startsWith('compare/')) {
        if (s.compare_barrier) {
          save(); unlock();
          fs.writeFileSync(path.join(d, 'comparison-' + p.split('/')[1].split('...')[0]), 'ready');
          while (fs.readdirSync(d).filter(n => n.startsWith('comparison-')).length < 2) wait(5);
          throw new Reply(0, {status: 'identical', behind_by: 0});
        }
        answer({status: 'identical', behind_by: 0});
      }
      if (p.startsWith('pulls/')) {
        const value = structuredClone([pr(Number(p.split('/')[1])).files]);
        if (s.merge_contract_after_files) {
          s.merge_contract_after_files = false;
          s.prs.push({...structuredClone(s.prs[0]), n: 131, head: 'c'.repeat(40), merge: 'd'.repeat(40), files: [{path: 'contracts/synthetic.v1.md', previous: null, status: 'modified'}]});
          s.base = 'e'.repeat(40);
        }
        answer(value);
      }
      if (p.startsWith('actions/runs?')) {
        const head = p.split('head_sha=')[1].split('&')[0];
        const ps = s.prs.filter(p => p.head === head);
        const runs = [{total_count: ps.length, runs: ps.map(p => ({id: p.n, head_sha: head,
          event: 'pull_request', run_attempt: 1, updated: 1793400010000,
          prs: [{number: p.n, head, base: p.base}]}))}];
        if (s.ci_barrier) rendezvous('ci', head, s.ci_barrier, runs, true);
        answer(runs);
      }
      if (p.startsWith('actions/runs/')) {
        const item = pr(Number(p.split('/')[2]));
        answer([{total_count: 1, jobs: [{id: item.n * 10, name: 'rust', status: 'completed',
          conclusion: item.ci, head_sha: item.head, run_id: item.n}]}]);
      }
      no();
    }
    if (prefix('pr', 'checks')) {
      const p = pr(Number(a[2]));
      const bucket = {success: 'pass', failure: 'fail', skipped: 'skipping', cancelled: 'cancel', pending: 'pending'}[p.ci];
      answer([{bucket, name: 'rust'}, ...(s.extra_checks ?? [])]);
    }
    if (['issue', 'pr'].includes(a[0]) && a.length > 2) {
      const n = Number(a[2]), kind = a[1];
      if (kind === 'comment' && a[3] === '--body') answer(comment(n, a[4]));
      if (kind === 'close') {
        if (s.fail_close_once) { s.fail_close_once = false; no(); }
        issue(n).closed = true; answer('closed');
      }
      if (kind === 'merge') {
        const p = pr(n); if (flag('--match-head-commit') !== p.head) no();
        p.merged = true; s.merge_bodies.push(flag('--body')); s.base = 'a'.repeat(40);
        issue(p.ticket).closed = true; answer('merged');
      }
      if (kind === 'edit') {
        const i = issue(n), label = a[4];
        if (a[3] === '--add-label' && !i.labels.includes(label)) i.labels.push(label);
        if (a[3] === '--remove-label') i.labels = i.labels.filter(x => x !== label);
        answer('edited');
      }
      if (kind === 'view' && a[3] === '--json') {
        const fields = a[4];
        if (fields === 'baseRefName,closingIssuesReferences,headRefName,headRefOid,isDraft,mergeCommit,mergedAt,number,state') answer(prrow(pr(n)));
        if (fields === 'comments') answer({comments: (s.comments[n] ?? []).map(c => ({
          id: 'syn-comment-' + c.id, author: null, authorAssociation: 'OWNER', body: c.body,
          createdAt: '2026-10-30T00:00:00Z', includesCreatedEdit: false, isMinimized: false,
          minimizedReason: null, reactionGroups: [], url: commentUrl(n, c.id), viewerDidAuthor: true}))});
        if (fields === 'url') answer({url: url(n)});
        if (fields === 'state') answer({state: issue(n).closed ? 'CLOSED' : 'OPEN'});
        if (fields === 'labels') answer({labels: row(issue(n)).labels});
        if (fields === 'state,mergeCommit,headRefOid') {
          const p = pr(n); answer({state: p.merged ? 'MERGED' : p.closed ? 'CLOSED' : 'OPEN',
            mergeCommit: p.merged ? {oid: 'a'.repeat(40)} : null, headRefOid: p.head});
        }
      }
    }
    no();
  }
  if (is('--version')) answer('v127');
  if (prefix('project', 'list')) {
    const rows = [{id: 'prj_syn_0001', kind: 'standard', name: 'Synthetic project',
      gitRemoteUrl: 'https://github.com/' + repository + '.git',
      createdAt: 1700000000000, updatedAt: 1700000000000, sources: []}];
    if (s.project_changed) {
      const moved = structuredClone(rows[0]); moved.gitRemoteUrl = 'https://github.com/synthetic-owner/another-repo.git';
      rows[0].id = 'prj_syn_new'; rows.push(moved);
    }
    if (s.flip_project) { s.flip_project = false; s.project_changed = true; }
    answer(a.includes('--hidden') ? [] : rows);
  }
  if (is('cloud', 'status', '--json')) answer(s.catalogue);
  if (prefix('thread', 'spawn')) {
    const thread = 'thr_syn_b5_' + ++s.spawn_count;
    const provider = flag('--provider'), model = flag('--model'), effort = flag('--reasoning-level'), prompt = flag('--prompt');
    const ticket = prompt.split('builder for #')[1]?.split('.')[0];
    s.threads[thread] = {provider, model, effort, archived: false, prompt,
      branch: ticket ? 'synthetic-branch-' + ticket : null};
    const receipt = {...structuredClone(s.receipt), id: thread, providerId: provider, title: 'Synthetic anonymous thread'};
    if (s.crash === 'timeout') { save(); unlock(); wait(120000); }
    if (s.crash === 'after-spawn') { save(); process.kill(ppid, 'SIGKILL'); }
    answer(receipt);
  }
  if (prefix('thread', 'show')) {
    const t = s.threads[a[2]]; if (!t) no();
    const v = structuredClone(s.template);
    Object.assign(v.thread, {id: a[2], providerId: t.provider, archivedAt: t.archived ? 1793400020000 : null,
      status: 'idle', queuedWork: 'none', hasPendingInteraction: false});
    v.execution = {model: t.model, reasoningLevel: t.effort}; answer(v);
  }
  if (prefix('thread', 'list')) answer(Object.entries(s.threads).map(([id, t]) => ({
    ...structuredClone(s.template.thread), id, title: t.title ?? 'Synthetic anonymous thread',
    projectId: t.project ?? 'prj_syn_0001', providerId: t.provider,
    archivedAt: t.archived ? 1793400020000 : null, queuedWork: 'none', hasPendingInteraction: false,
    environmentBranchName: t.branch ?? null
  })));
  if (prefix('cloud', 'thread-workspace')) answer({branch: s.threads[a[2]].branch ?? 'synthetic-branch-10', head: 'a'.repeat(40), path: '/synthetic/workspace'});
  if (prefix('thread', 'archive')) { s.threads[a[2]].archived = true; answer({}); }
  if (prefix('thread', 'output')) {
    const t = s.threads[a[2]];
    const report = t.prompt.includes('reviewer') ? pr(Number(t.prompt.split('pull request #')[1].split(' ')[0])).report : null;
    answer({output: t.output ?? report ?? '', error: null});
  }
  // Synthetic values in #571's target-bound sent receipt shape.
  if (prefix('thread', 'tell')) answer({threadId: a[2], ok: true, delivery: 'sent', mode: flag('--mode')});
  no();
}
let reply, err = '';
try { run(); }
catch (e) {
  if (e instanceof Reply) reply = e;
  else { err = String(e.stack) + '\n'; reply = new Reply(1); }
} finally { unlock(); }
const out = reply.value === undefined ? ''
  : (typeof reply.value === 'string' ? reply.value : JSON.stringify(reply.value)) + '\n';
if (workflowActive) fs.unlinkSync(workflowActive);
return {code: reply.code, out, err};
}
// The long-lived fake: each call from a world's `bin/` client runs in a
// worker of its own, reused once it has answered, so calls overlap exactly
// as fake processes did. A client that dies before its answer (a caller's
// kill) stops its worker, as that kill stopped the fake's process.
function serve(d) {
  const net = require('node:net');
  const {Worker} = require('node:worker_threads');
  const idle = [];
  const worlds = new Map();
  const parent = process.ppid;
  setInterval(() => { if (process.ppid !== parent) process.exit(0); }, 500).unref();
  const fields = buf => {
    const out = [];
    for (let o = 0; o < buf.length;) {
      if (o + 4 > buf.length) throw new Error('short field length');
      const n = buf.readUInt32BE(o);
      if (o + 4 + n > buf.length) throw new Error('short field');
      out.push(buf.subarray(o + 4, o + 4 + n).toString('utf8'));
      o += 4 + n;
    }
    if (out.length < 2) throw new Error('missing world or tool');
    return out;
  };
  net.createServer({allowHalfOpen: true}, conn => {
    let request = Buffer.alloc(0), dispatched = false;
    let worker = null, answered = false, stopping = null;
    let finish = () => {};
    const cancel = () => {
      if (worker && !answered && !stopping) {
        worker.removeAllListeners('message');
        worker.removeAllListeners('error');
        worker.on('error', () => {});
        stopping = worker.terminate().then(finish, finish);
      }
      conn.destroy();
      return stopping;
    };
    conn.b5cancel = cancel;
    // The request has its own length: EOF now means peer death. Keep a
    // cancelled worker registered until terminate() joins it, so settling
    // and world teardown acknowledge actual completion, not just disconnect.
    conn.on('error', cancel);
    conn.on('end', cancel);
    conn.on('close', cancel);
    conn.on('data', chunk => {
      if (dispatched) { cancel(); return; }
      request = Buffer.concat([request, chunk]);
      if (request.length < 4) return;
      const length = request.readUInt32BE(0);
      if (length > 1024 * 1024 || request.length > length + 4) { cancel(); return; }
      if (request.length < length + 4) return;
      dispatched = true;
      let decoded;
      try { decoded = fields(request.subarray(4)); }
      catch (_) { cancel(); return; }
      const [world, tool, id, ppid, ...a] = decoded;
      if (tool === '--settled') {
        Promise.all([...(worlds.get(world) ?? [])].map(other => other.b5done)).then(() => conn.end());
        return;
      }
      if (tool === '--drop-world') {
        const pending = [...(worlds.get(world) ?? [])];
        Promise.all(pending.map(other => other.b5cancel())).then(() => conn.end());
        return;
      }
      if (decoded.length < 4) { cancel(); return; }
      const connections = worlds.get(world) ?? new Set();
      worlds.set(world, connections);
      connections.add(conn);
      let done;
      conn.b5done = new Promise(resolve => { done = resolve; });
      finish = () => {
        connections.delete(conn);
        if (!connections.size) worlds.delete(world);
        done();
      };
      worker = idle.pop() ?? new Worker(__filename, {argv: ['--worker']});
      const reply = r => {
        answered = true;
        finish();
        const out = Buffer.from(r.out), err = Buffer.from(r.err);
        const head = Buffer.alloc(12);
        head.writeInt32BE(r.code, 0); head.writeUInt32BE(out.length, 4); head.writeUInt32BE(err.length, 8);
        conn.end(Buffer.concat([head, out, err]));
      };
      worker.once('message', r => { worker.removeAllListeners('error'); idle.push(worker); reply(r); });
      worker.once('error', e => reply({code: 1, out: '', err: String(e && e.stack) + '\n'}));
      worker.postMessage({d: world, tool, id, ppid: Number(ppid), a});
    });
  }).listen(path.join(d, 'fake.sock'), () => fs.writeFileSync(path.join(d, 'fake.ready'), String(process.pid)));
}
const {isMainThread, parentPort} = require('node:worker_threads');
if (!isMainThread) {
  parentPort.on('message', m => {
    let r;
    try { r = call(m.d, m.tool, m.a, m.id, m.ppid); }
    catch (e) { r = {code: 1, out: '', err: String(e.stack) + '\n'}; }
    parentPort.postMessage(r);
  });
} else if (process.argv[2] === '--serve') {
  serve(process.argv[3]);
} else {
  // One call per process: the world's own `gh` and `room-cli`.
  const r = call(path.dirname(process.argv[1]), path.basename(process.argv[1]),
    process.argv.slice(2), process.pid, process.ppid);
  if (r.err) fs.writeSync(2, r.err);
  const output = Buffer.from(r.out);
  for (let offset = 0; offset < output.length;) offset += fs.writeSync(1, output, offset);
  process.exit(r.code);
}
"#;
