//! EP1 transport guards and shared-slot behavior, using private synthetic FIFOs.
use crate::{
    e11_plan_support as p,
    fake::{self, Fake},
    http::{self, Gated, TestServer},
    support::FakeGh,
};
use openwiz_adapter_github::plan::Request;
use openwiz_server::{Config, Limits, Plan};
use serde_json::{Value, json};
use std::{
    fs,
    io::Write,
    process::Command,
    sync::{Arc, Condvar, Mutex},
    thread,
    time::{Duration, Instant},
};

fn assert_status_multiset(mut logged: Vec<&str>, expected: Vec<u16>) {
    let mut expected: Vec<_> = expected.iter().map(u16::to_string).collect();
    logged.sort_unstable();
    expected.sort_unstable();
    assert_eq!(logged, expected);
}

#[test]
fn e11_plan_log_status_multiset_rejects_noncanonical_fields_and_wrong_counts() {
    assert_status_multiset(vec!["400", "200", "400"], vec![200, 400, 400]);
    for logged in [
        vec!["+200", "400", "400"],
        vec!["0200", "400", "400"],
        vec!["200", "200", "400"],
        vec!["200", "400"],
        vec!["200", "400", "400", "400"],
    ] {
        assert!(
            std::panic::catch_unwind(|| assert_status_multiset(
                logged.clone(),
                vec![200, 400, 400]
            ))
            .is_err(),
            "accepted invalid log statuses: {logged:?}"
        );
    }
}

#[test]
fn e11_plan_exact_get_has_all_existing_guards_and_private_route_logs() {
    let gh = p::github("ep1-guards", p::responses(vec![], vec![]));
    let room = Fake::new("ep1-guards-room", "normal");
    let log = Arc::new(Mutex::new(vec![]));
    let lines = log.clone();
    let first_not_found = (Mutex::new(false), Condvar::new());
    let server = openwiz_server::start_with_plan(
        openwiz_server::bind(0).unwrap(),
        Default::default(),
        Arc::new(room.source()),
        Arc::new(fake::clock()),
        Arc::new(move |line| {
            let status = line.split_whitespace().nth(2).unwrap();
            let (observed, ready) = &first_not_found;
            // The response is already sent. Hold its 421 log until a later
            // request's 404 is logged, reproducing CI's callback order.
            if status == "421" {
                let (seen, _) = ready
                    .wait_timeout_while(observed.lock().unwrap(), Duration::from_secs(5), |seen| {
                        !*seen
                    })
                    .unwrap();
                assert!(*seen, "the later 404 callback did not arrive");
            }
            lines.lock().unwrap().push(line.to_owned());
            if status == "404" {
                *observed.lock().unwrap() = true;
                ready.notify_one();
            }
        }),
        None,
        Some(Plan::with_program(gh.program())),
    )
    .unwrap();
    let s = TestServer {
        addr: server.local_addr(),
        server,
        log,
    };
    let mut expected = vec![];
    for method in [
        "HEAD",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "OPTIONS",
        "CONNECT",
        "TRACE",
        "SYNTHETIC",
    ] {
        let r = s.request(method, "/api/v1/plan");
        assert_eq!(r.status, 405);
        assert_eq!(r.header("Allow"), Some("GET"));
        crate::c3_routes::headers(&r);
        expected.push((PLAN, 405));
        if method == "HEAD" {
            assert!(r.body.is_empty());
            assert_eq!(r.header("Content-Length"), None);
        }
    }
    for suffix in ["?", "?secret=synthetic-secret", "?limit=1", "?x=1&x=2"] {
        let r = s.get(&format!("/api/v1/plan{suffix}"));
        assert_eq!(r.status, 400);
        crate::c3_routes::headers(&r);
        expected.push((PLAN, 400));
    }
    for framing in [
        "Content-Length: 1\r\n",
        "Transfer-Encoding: chunked\r\n",
        "Content-Length: 0\r\nContent-Length: 0\r\n",
    ] {
        let r = s.send(
            format!(
                "GET /api/v1/plan HTTP/1.1\r\nHost: {}\r\n{framing}\r\nx",
                s.host()
            )
            .as_bytes(),
        );
        assert_eq!(r.status, 400);
        crate::c3_routes::headers(&r);
        expected.push((PLAN, 400));
    }
    let r = s.send(b"GET /api/v1/plan HTTP/1.1\r\nHost: foreign.example.invalid\r\n\r\n");
    assert_eq!(r.status, 421);
    expected.push((PLAN, 421));
    for path in ["/api/v1/plan/", "/api/v1/Plan", "/api/v1/plan/902"] {
        assert_eq!(s.get(path).status, 404);
        expected.push(("-", 404));
    }
    assert!(gh.invocations().is_empty());
    assert!(room.invocations().is_empty());
    let r = s.get("/api/v1/plan");
    assert_eq!(r.status, 200);
    crate::c3_routes::headers(&r);
    expected.push((PLAN, 200));
    let log = s.settled_log();
    let lines: Vec<_> = log.lines().collect();
    let position = |status| {
        lines
            .iter()
            .position(|line| line.split_whitespace().nth(2) == Some(status))
            .unwrap()
    };
    // The 421's log line was held until the later 404 logged (#423).
    assert!(position("404") < position("421"));
    // Callback order is unconstrained; the (route, status) pairs, their exact
    // text and counts are not (#429).
    assert_route_log(&log, &expected);
    assert!(!log.contains("synthetic-secret"));
    assert_eq!(gh.invocations().len(), 3);
}

const PLAN: &str = "/api/v1/plan";

/// The server's log for `expected`'s requests, one line each, in any order
/// (#429): the same (route, status) pairs, each as many times, and every
/// route the plan's or `-`.
fn assert_route_log(log: &str, expected: &[(&str, u16)]) {
    let mut logged: Vec<_> = log
        .lines()
        .map(|line| {
            let fields: Vec<_> = line.split_whitespace().collect();
            assert!(fields[1] == PLAN || fields[1] == "-", "route in {line:?}");
            (fields[1].to_owned(), fields[2].to_owned())
        })
        .collect();
    let mut want: Vec<_> = expected
        .iter()
        .map(|(route, status)| ((*route).to_owned(), status.to_string()))
        .collect();
    logged.sort();
    want.sort();
    assert_eq!(logged, want);
}

/// #429: the server writes a request's log line after it answers, so two
/// quick requests can log in either order under load (every test target at
/// once). The check takes the lines in any order, and still refuses a wrong
/// status or route, a line missing or one too many.
#[test]
fn e11_the_route_log_check_takes_the_lines_in_any_order() {
    let expected = [(PLAN, 405), (PLAN, 400), ("-", 404), (PLAN, 200)];
    let swapped = "HEAD /api/v1/plan 405 0ms\nGET - 404 0ms\nGET /api/v1/plan 400 0ms\nGET /api/v1/plan 200 3ms\n";
    assert_route_log(swapped, &expected);
    let refused = [
        (
            "a wrong status",
            "HEAD /api/v1/plan 405 0ms\nGET /api/v1/plan 404 0ms\nGET - 404 0ms\nGET /api/v1/plan 200 3ms\n",
        ),
        (
            "a line missing",
            "HEAD /api/v1/plan 405 0ms\nGET /api/v1/plan 400 0ms\nGET /api/v1/plan 200 3ms\n",
        ),
        (
            "a line too many",
            "HEAD /api/v1/plan 405 0ms\nGET /api/v1/plan 400 0ms\nGET - 404 0ms\nGET /api/v1/plan 200 3ms\nGET /api/v1/plan 200 3ms\n",
        ),
        (
            "another route",
            "HEAD /api/v1/plan 405 0ms\nGET /api/v1/plan 400 0ms\nGET /api/v1/plan/902 404 0ms\nGET /api/v1/plan 200 3ms\n",
        ),
    ];
    for (what, log) in refused {
        let caught = std::panic::catch_unwind(|| assert_route_log(log, &expected));
        assert!(caught.is_err(), "{what}: accepted");
    }
}

fn gated(name: &str, limits: Limits) -> (Fake, FakeGh, Arc<Gated>, TestServer, String) {
    let gh = p::github(name, p::responses(vec![], vec![]));
    let fifo = gh.dir.join("plan-pipe");
    assert!(
        Command::new("mkfifo")
            .arg(&fifo)
            .status()
            .unwrap()
            .success()
    );
    let path = gh.dir.join("plan.json");
    let scenario: Value = serde_json::from_str(&fs::read_to_string(&path).unwrap()).unwrap();
    let output = scenario["responses"][2]["stdout"]
        .as_str()
        .unwrap()
        .to_owned();
    use std::os::unix::fs::PermissionsExt;
    let wrapper = gh.dir.join("gated-gh");
    let dir = gh.dir.display();
    let script = format!(
        "#!/bin/sh\nif ln '{dir}/gated-gh' '{dir}/gate-once' 2>/dev/null; then\n: > '{dir}/gate-entered'\ncat '{dir}/plan-pipe' >/dev/null\nfi\nexec '{}' \"$@\"\n",
        gh.program().display()
    );
    // A sibling fork must never inherit a writable executable descriptor.
    // Only the writer child opens this inode; wait before starting the server.
    let mut writer = Command::new("/bin/sh")
        .args(["-c", "umask 077; cat > \"$1\"", "fixture-writer"])
        .arg(&wrapper)
        .stdin(std::process::Stdio::piped())
        .spawn()
        .unwrap();
    writer
        .stdin
        .take()
        .unwrap()
        .write_all(script.as_bytes())
        .unwrap();
    assert!(writer.wait().unwrap().success(), "write gated gh wrapper");
    fs::set_permissions(&wrapper, fs::Permissions::from_mode(0o700)).unwrap();
    let room = Fake::new(&format!("{name}-room"), "normal");
    let gate = Arc::new(Gated::new(Arc::new(room.source())));
    let log = Arc::new(Mutex::new(vec![]));
    let lines = log.clone();
    let server = openwiz_server::start_with_plan(
        openwiz_server::bind(0).unwrap(),
        Config {
            limits,
            ..Default::default()
        },
        gate.clone(),
        Arc::new(fake::clock()),
        Arc::new(move |line| lines.lock().unwrap().push(line.to_owned())),
        None,
        Some(Plan::with_program(wrapper)),
    )
    .unwrap();
    let s = TestServer {
        addr: server.local_addr(),
        server,
        log,
    };
    (room, gh, gate, s, output)
}
fn wait_gate(gh: &FakeGh) {
    let until = Instant::now() + Duration::from_secs(5);
    while !gh.dir.join("gate-entered").is_file() {
        assert!(
            Instant::now() < until,
            "GitHub wrapper did not reach its gate"
        );
        thread::yield_now();
    }
}
fn release(gh: &FakeGh, output: &str) {
    fs::OpenOptions::new()
        .write(true)
        .open(gh.dir.join("plan-pipe"))
        .unwrap()
        .write_all(output.as_bytes())
        .unwrap();
}
fn ungate(gh: &FakeGh, output: &str) {
    let path = gh.dir.join("plan.json");
    let mut v: Value = serde_json::from_str(&fs::read_to_string(&path).unwrap()).unwrap();
    v["responses"][2] = json!({"argv":Request::Issues.argv(None),"stdout":output});
    fs::write(path, v.to_string()).unwrap();
}

#[test]
fn e11_plan_shares_inflight_only_and_competes_with_inventory_for_two_slots() {
    let (_room, gh, gate, s, output) = gated(
        "ep1-flight",
        Limits {
            slot_wait: Duration::from_millis(80),
            ..Default::default()
        },
    );
    let addr = s.addr;
    let inventory = thread::spawn(move || http::get(addr, "/api/v1/inventory"));
    gate.wait_held(1);
    let a = thread::spawn(move || http::get(addr, "/api/v1/plan"));
    wait_gate(&gh);
    let b = thread::spawn(move || http::get(addr, "/api/v1/plan"));
    s.wait_for("shared plan and inventory", |s| {
        s.core_runs == 2 && s.attached == 3
    });
    let r = s.get("/api/v1/inventory?limit=2");
    assert_eq!(r.status, 503);
    assert_eq!(r.header("Retry-After"), Some("5"));
    assert_eq!(gh.invocations().len(), 0);
    assert_eq!(gate.runs(), 1);
    release(&gh, &output);
    gate.open();
    let a = a.join().unwrap();
    let b = b.join().unwrap();
    assert_eq!(a.status, 200);
    assert_eq!(a.body, b.body);
    assert_eq!(inventory.join().unwrap().status, 200);
    s.wait_for("runs released", |s| s.core_runs == 0);
    ungate(&gh, &output);
    assert_eq!(s.get("/api/v1/plan").status, 200);
    assert_eq!(gh.invocations().len(), 6);
}
#[test]
fn e11_plan_deadline_retains_its_slot_until_the_source_really_finishes() {
    let (_room, gh, gate, s, output) = gated(
        "ep1-deadline",
        Limits {
            // The gate forces expiration; allow healthy recovery launches too.
            request_deadline: Duration::from_secs(2),
            slot_wait: Duration::from_millis(60),
            ..Default::default()
        },
    );
    let addr = s.addr;
    let plan = thread::spawn(move || http::get(addr, "/api/v1/plan"));
    wait_gate(&gh);
    assert_eq!(plan.join().unwrap().status, 504);
    assert_eq!(s.server.stats().core_runs, 1);
    let inventory = thread::spawn(move || http::get(addr, "/api/v1/inventory"));
    gate.wait_held(1);
    let r = s.get("/api/v1/inventory?limit=2");
    assert_eq!(r.status, 503);
    assert_eq!(r.header("Retry-After"), Some("5"));
    assert_eq!(s.get("/api/v1/plan").status, 504);
    assert_eq!(gh.invocations().len(), 0);
    assert_eq!(s.server.stats().core_runs, 2);
    release(&gh, &output);
    gate.open();
    assert_eq!(inventory.join().unwrap().status, 504);
    s.wait_for("timed out sources actually finish", |s| s.core_runs == 0);
    ungate(&gh, &output);
    let recovered = s.get("/api/v1/plan");
    assert_eq!(recovered.status, 200, "{}", recovered.text());
    assert_eq!(gh.invocations().len(), 6);
}

/// Keep a real inherited writer alive across wrapper startup, then compare
/// with a child that closes only that descriptor before the same delay.
#[test]
fn e11_gated_wrapper_starts_after_an_unrelated_fork() {
    const CHILD: &str = "OW_E11_FORK_PROBE_CHILD";
    if std::env::var_os(CHILD).is_some() {
        assert_eq!(
            std::env::var("OW_E11_ROOT_PID").unwrap(),
            std::process::id().to_string(),
            "the descriptor-inheritance probe must be loaded"
        );
        let (_room, gh, _gate, s, output) = gated(
            "ep1-inherited-writer",
            Limits {
                request_deadline: Duration::from_millis(350),
                slot_wait: Duration::from_millis(60),
                ..Default::default()
            },
        );
        let addr = s.addr;
        let plan = thread::spawn(move || http::get(addr, "/api/v1/plan"));
        wait_gate(&gh);
        assert_eq!(plan.join().unwrap().status, 504);
        assert_eq!(s.server.stats().core_runs, 1);
        assert_eq!(gh.invocations().len(), 0);
        release(&gh, &output);
        s.wait_for("the gated plan really finishes", |s| s.core_runs == 0);
        assert_eq!(gh.invocations().len(), 3);
        return;
    }

    use std::os::unix::fs::DirBuilderExt;
    let dir = std::env::temp_dir().join(format!("ow-e11-fork-probe-{}", std::process::id()));
    fs::DirBuilder::new().mode(0o700).create(&dir).unwrap();
    let source = dir.join("hold-writer.c");
    let library = dir.join("hold-writer.so");
    // This shim changes no production code. At the real fixture's close it
    // forks before closing the writable descriptor; a pipe acknowledges the
    // child's state. Both modes delay exec equally, only descriptor ownership
    // differs. The constructor marker proves the child loaded the probe.
    fs::write(
        &source,
        br#"#define _GNU_SOURCE
#include <dlfcn.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

static pid_t retained_child = -1;
__attribute__((constructor)) static void root_pid(void) {
    char pid[32];
    snprintf(pid, sizeof(pid), "%ld", (long)getpid());
    setenv("OW_E11_ROOT_PID", pid, 0);
}
__attribute__((destructor)) static void reap_child(void) {
    if (retained_child > 0) waitpid(retained_child, NULL, 0);
}
int close(int fd) {
    int (*original)(int) = dlsym(RTLD_NEXT, "close");
    const char *root = getenv("OW_E11_ROOT_PID");
    if (root && atol(root) == (long)getpid() && retained_child == -1) {
        char link[64], path[PATH_MAX];
        snprintf(link, sizeof(link), "/proc/self/fd/%d", fd);
        ssize_t n = readlink(link, path, sizeof(path)-1);
        int mode = fcntl(fd, F_GETFL);
        if (n > 0 && mode >= 0 && (mode & O_ACCMODE) != O_RDONLY) {
            path[n] = 0;
            const char *suffix = "/ep1-inherited-writer/gated-gh";
            size_t length = strlen(suffix);
            if ((size_t)n >= length && strcmp(path+n-length, suffix) == 0) {
                int ack[2];
                if (pipe(ack) != 0) _exit(91);
                pid_t child = fork();
                if (child == -1) _exit(92);
                if (child == 0) {
                    original(ack[0]);
                    const char *keep = getenv("OW_E11_KEEP");
                    if (!keep || strcmp(keep, "1") != 0) original(fd);
                    if (write(ack[1], "x", 1) != 1) _exit(93);
                    original(ack[1]);
                    struct timespec delay = {0, 750000000};
                    nanosleep(&delay, NULL);
                    execl("/bin/true", "true", (char *)NULL);
                    _exit(94);
                }
                retained_child = child;
                original(ack[1]);
                char byte;
                if (read(ack[0], &byte, 1) != 1) _exit(95);
                original(ack[0]);
                const char *note = "e11 probe: child acknowledged inherited writer state\n";
                write(STDERR_FILENO, note, strlen(note));
            }
        }
    }
    return original(fd);
}
"#,
    )
    .unwrap();
    let compiled = Command::new("cc")
        .args(["-shared", "-fPIC", "-Wall", "-Wextra", "-Werror"])
        .arg(&source)
        .args(["-ldl", "-o"])
        .arg(&library)
        .output()
        .unwrap();
    assert!(
        compiled.status.success(),
        "{}",
        String::from_utf8_lossy(&compiled.stderr)
    );
    let results: Vec<_> = ["0", "1"]
        .into_iter()
        .map(|mode| {
            let out = Command::new(std::env::current_exe().unwrap())
                .args([
                    "--exact",
                    "e11_plan_bounds::e11_gated_wrapper_starts_after_an_unrelated_fork",
                    "--nocapture",
                ])
                .env("LD_PRELOAD", &library)
                .env(CHILD, "1")
                .env("OW_E11_KEEP", mode)
                .env_remove("OW_E11_ROOT_PID")
                .output()
                .unwrap();
            (mode, out)
        })
        .collect();
    fs::remove_dir_all(&dir).unwrap();
    for (mode, out) in results {
        assert!(
            out.status.success(),
            "inherited writer mode {mode}:\n{}\n{}",
            String::from_utf8_lossy(&out.stdout),
            String::from_utf8_lossy(&out.stderr)
        );
    }
}
