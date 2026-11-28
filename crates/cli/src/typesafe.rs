use serde_json::{Value, json};

const MODEL: &str = "jev-1.14.0";
const MAX_STATE_CHARS: usize = 24_000;
const TAIL_CHARS: usize = 4_000;
const MAX_ANSWER_BYTES: usize = 1_048_576;
const ANSWER_SECONDS: u64 = 10;

pub trait Decisions {
    fn ask(&self, state: &str, questions: &Value) -> Option<Value>;
}

pub struct Absent;

impl Decisions for Absent {
    fn ask(&self, _: &str, _: &Value) -> Option<Value> {
        None
    }
}

#[cfg(test)]
pub struct Scripted(pub Value);

#[cfg(test)]
impl Decisions for Scripted {
    fn ask(&self, _: &str, _: &Value) -> Option<Value> {
        Some(self.0.clone())
    }
}

struct Http {
    deadline: std::time::Instant,
}

impl Decisions for Http {
    fn ask(&self, state: &str, questions: &Value) -> Option<Value> {
        let body = json!({
            "model": MODEL,
            "state": bounded(state),
            "questions": questions,
        });
        let until = answer_until(std::time::Instant::now(), self.deadline);
        let answer = jev_process(body.to_string().as_bytes(), until)?;
        serde_json::from_slice(&answer).ok()
    }
}

fn answer_until(now: std::time::Instant, deadline: std::time::Instant) -> std::time::Instant {
    let left = deadline.saturating_duration_since(now) / 2;
    now + left.min(std::time::Duration::from_secs(ANSWER_SECONDS))
}

fn jev_process(request: &[u8], until: std::time::Instant) -> Option<Vec<u8>> {
    let exe = std::env::current_exe().ok()?.canonicalize().ok()?;
    let target = exe.ancestors().nth(2)?;
    if target.file_name()? != "target" {
        return None;
    }
    let tool = target.parent()?.join("tools/typesafe/ask.py");
    let meta = std::fs::symlink_metadata(&tool).ok()?;
    if !meta.is_file() || meta.file_type().is_symlink() {
        return None;
    }
    if tool
        .ancestors()
        .skip(1)
        .any(|p| !std::fs::symlink_metadata(p).is_ok_and(|m| !m.file_type().is_symlink()))
    {
        return None;
    }
    let key = std::env::var_os("TYPESAFE_API_KEY")?;
    run_ask(&tool, &key, request, until)
}

fn run_ask(
    tool: &std::path::Path,
    key: &std::ffi::OsStr,
    request: &[u8],
    until: std::time::Instant,
) -> Option<Vec<u8>> {
    let mut child = std::process::Command::new("/usr/bin/python3")
        .arg("-I")
        .arg(tool)
        .env_clear()
        .env("OPENWIZ_JEV", "1")
        .env("TYPESAFE_API_KEY", key)
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::null())
        .spawn()
        .ok()?;
    let stdout = child.stdout.take();
    let reader = std::thread::spawn(move || {
        let mut answer = Vec::new();
        if let Some(out) = stdout {
            let limit = MAX_ANSWER_BYTES as u64 + 1;
            let _ = std::io::Read::read_to_end(&mut std::io::Read::take(out, limit), &mut answer);
        }
        answer
    });
    let stdin = child.stdin.take();
    let request = request.to_vec();
    let writer = std::thread::spawn(move || {
        stdin.is_some_and(|mut input| std::io::Write::write_all(&mut input, &request).is_ok())
    });
    let finished = loop {
        match child.try_wait() {
            Ok(Some(status)) => break Some(status),
            Ok(None) if std::time::Instant::now() < until => {
                std::thread::sleep(std::time::Duration::from_millis(20));
            }
            _ => break None,
        }
    };
    if finished.is_none() {
        let _ = child.kill();
        let _ = child.wait();
    }
    let sent = writer.join().unwrap_or(false);
    let answer = reader.join().ok()?;
    finished
        .filter(|status| sent && status.success() && answer.len() <= MAX_ANSWER_BYTES)
        .map(|_| answer)
}

pub fn env_decider(deadline: std::time::Instant) -> Box<dyn Decisions> {
    if jev_enabled() {
        Box::new(Http { deadline })
    } else {
        Box::new(Absent)
    }
}

fn jev_enabled() -> bool {
    let opted_in = std::env::var_os("OPENWIZ_JEV").is_some_and(|value| value == "1");
    opted_in
        && std::env::var_os("TYPESAFE_API_KEY").is_some_and(|value| {
            std::str::from_utf8(value.as_encoded_bytes())
                .ok()
                .is_some_and(|text| !text.trim().is_empty())
        })
}

fn bounded(state: &str) -> String {
    state.chars().take(MAX_STATE_CHARS).collect()
}

fn tail(text: &str) -> &str {
    let skip = text.chars().count().saturating_sub(TAIL_CHARS);
    text.char_indices()
        .nth(skip)
        .map_or(text, |(at, _)| &text[at..])
}

pub fn noul(response: &Value, name: &str) -> Option<f64> {
    let answer = response.get("answers")?.get(name)?;
    if answer.get("type")?.as_str()? != "noul" {
        return None;
    }
    let value = answer.get("noul")?.as_f64()?;
    (0.0..=1.0).contains(&value).then_some(value)
}

pub fn exact_plan_limit(text: &str) -> bool {
    text.lines().any(|line| {
        let line = line.trim();
        line == "Claude usage limit reached"
            || line == "You've hit your limit"
            || line
                .strip_prefix("You've hit your limit · resets ")
                .is_some_and(|rest| !rest.is_empty())
    })
}

fn config() -> Value {
    serde_json::from_str(include_str!("../../../tools/typesafe/config.json"))
        .expect("tools/typesafe/config.json is json")
}

fn combined(response: &Value, config: &Value, site_name: &str) -> Option<f64> {
    let site = config.get("sites")?.get(site_name)?;
    let no = config.get("noul")?.get("no")?.as_f64()?;
    let yes = config.get("noul")?.get("yes")?.as_f64()?;
    let terms = site.get("terms")?.as_array()?;
    let mut parts = Vec::new();
    for term in terms {
        let mut value = noul(response, term.get("question")?.as_str()?)?;
        if value > no && value < yes {
            return None;
        }
        if term.get("invert").and_then(Value::as_bool).unwrap_or(false) {
            value = 1.0 - value;
        }
        parts.push((term.get("weight")?.as_f64()?, value));
    }
    match site.get("combine")?.as_str()? {
        "weighted_sum" => Some(parts.iter().map(|(weight, value)| weight * value).sum()),
        "noisy_or" => {
            let product = parts.iter().fold(1.0, |acc, (weight, value)| {
                acc * (1.0 - (weight * value).clamp(0.0, 1.0))
            });
            Some(1.0 - product)
        }
        _ => None,
    }
}

pub fn plan_limit_with(texts: &[&str], decider: &dyn Decisions) -> bool {
    if texts.iter().any(|text| exact_plan_limit(text)) {
        return true;
    }
    let joined = texts.join("\n");
    if joined.trim().is_empty() {
        return false;
    }
    let config = config();
    let Some(site) = config
        .get("sites")
        .and_then(|sites| sites.get("plan_limit"))
    else {
        return false;
    };
    let Some(questions) = site.get("questions") else {
        return false;
    };
    let Some(response) = decider.ask(tail(&joined), questions) else {
        return false;
    };
    let Some(act) = site.get("act").and_then(Value::as_f64) else {
        return false;
    };
    combined(&response, &config, "plan_limit").is_some_and(|value| value >= act)
}

pub fn plan_limit(texts: &[&str], deadline: std::time::Instant) -> bool {
    plan_limit_with(texts, env_decider(deadline).as_ref())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn limit_answer(plan: f64, ordinary: f64, sign_in: f64) -> Value {
        json!({"answers": {
            "plan_limit": {"type": "noul", "noul": plan},
            "ordinary_work": {"type": "noul", "noul": ordinary},
            "sign_in": {"type": "noul", "noul": sign_in}
        }})
    }

    #[test]
    fn an_exact_line_does_not_ask() {
        let calls = std::cell::Cell::new(0u8);
        struct Count<'a>(&'a std::cell::Cell<u8>);
        impl Decisions for Count<'_> {
            fn ask(&self, _: &str, _: &Value) -> Option<Value> {
                self.0.set(self.0.get() + 1);
                None
            }
        }
        assert!(plan_limit_with(
            &["Claude usage limit reached"],
            &Count(&calls)
        ));
        assert!(plan_limit_with(
            &["ordinary build output", "Claude usage limit reached"],
            &Count(&calls)
        ));
        assert_eq!(calls.get(), 0);
    }

    #[test]
    fn a_paraphrase_needs_a_clear_weighted_yes_and_a_miss_stays_a_miss() {
        let text = "please wait, the plan limit stopped the run";
        assert!(!plan_limit_with(&[text], &Absent));
        assert!(plan_limit_with(
            &[text],
            &Scripted(limit_answer(0.96, 0.04, 0.02))
        ));
        assert!(!plan_limit_with(
            &[text],
            &Scripted(limit_answer(0.55, 0.02, 0.02))
        ));
        assert!(!plan_limit_with(
            &[text],
            &Scripted(limit_answer(0.8, 0.02, 0.02))
        ));
        assert!(!plan_limit_with(
            &["not signed in"],
            &Scripted(limit_answer(0.12, 0.1, 0.94))
        ));
    }

    #[test]
    fn recorded_plan_limit_counts() {
        let raw = include_str!("../../../tools/typesafe/fixtures/plan_limit.json");
        let data: Value = serde_json::from_str(raw).unwrap();
        let cases = data["cases"].as_array().unwrap();
        let mut old_hit = 0;
        let mut shaped_hit = 0;
        for case in cases {
            let text = case["text"].as_str().unwrap();
            let expected = case["expected"].as_bool().unwrap();
            let recorded = &case["recorded"];
            old_hit += usize::from(exact_plan_limit(text) == expected);
            let shaped = if exact_plan_limit(text) {
                true
            } else if recorded.is_null() {
                false
            } else {
                combined(recorded, &config(), "plan_limit").is_some_and(|value| {
                    value >= config()["sites"]["plan_limit"]["act"].as_f64().unwrap()
                })
            };
            shaped_hit += usize::from(shaped == expected);
        }
        assert_eq!((cases.len(), old_hit, shaped_hit), (9, 8, 8));
    }

    #[test]
    fn only_the_tail_of_a_long_output_is_sent() {
        struct Seen(std::cell::RefCell<String>);
        impl Decisions for Seen {
            fn ask(&self, state: &str, _: &Value) -> Option<Value> {
                *self.0.borrow_mut() = state.to_owned();
                None
            }
        }
        let text = format!("{}é{}", "x".repeat(10_000), "y".repeat(TAIL_CHARS - 1));
        let seen = Seen(std::cell::RefCell::new(String::new()));
        assert!(!plan_limit_with(&[&text], &seen));
        let sent = seen.0.borrow();
        assert_eq!(sent.chars().count(), TAIL_CHARS);
        assert!(sent.starts_with('é'));
        assert_eq!(tail("short"), "short");
        assert_eq!(tail(""), "");
    }

    fn ask_script(dir: &str, body: &str) -> std::path::PathBuf {
        let folder = std::env::temp_dir().join(format!("openwiz-jev-{dir}-{}", std::process::id()));
        std::fs::create_dir_all(&folder).unwrap();
        let path = folder.join("ask.py");
        std::fs::write(&path, body).unwrap();
        path
    }

    fn soon(millis: u64) -> std::time::Instant {
        std::time::Instant::now() + std::time::Duration::from_millis(millis)
    }

    #[test]
    fn a_large_answer_is_drained_while_the_helper_runs() {
        let tool = ask_script(
            "large",
            "import sys\nsys.stdin.read()\nprint('{\"pad\": \"' + 'x' * 200000 + '\"}')\n",
        );
        let started = std::time::Instant::now();
        let answer = run_ask(&tool, std::ffi::OsStr::new("synthetic"), b"{}", soon(5_000));
        assert!(answer.is_some_and(|bytes| bytes.len() > 200_000));
        assert!(started.elapsed() < std::time::Duration::from_secs(4));
    }

    #[test]
    fn an_answer_over_the_cap_is_refused() {
        let tool = ask_script(
            "huge",
            "import sys\nsys.stdin.read()\nsys.stdout.write('x' * 2000000)\n",
        );
        assert_eq!(
            run_ask(&tool, std::ffi::OsStr::new("synthetic"), b"{}", soon(5_000)),
            None
        );
    }

    #[test]
    fn a_slow_helper_is_stopped_at_its_deadline() {
        let tool = ask_script("slow", "import time\ntime.sleep(30)\n");
        let started = std::time::Instant::now();
        assert_eq!(
            run_ask(&tool, std::ffi::OsStr::new("synthetic"), b"{}", soon(300)),
            None
        );
        assert!(started.elapsed() < std::time::Duration::from_secs(3));
    }

    #[test]
    fn the_helper_gets_a_cleared_environment_with_the_opt_in_and_the_key() {
        let tool = ask_script(
            "env",
            "import json, os, sys\nsys.stdin.read()\nprint(json.dumps(dict(os.environ)))\n",
        );
        let answer = run_ask(&tool, std::ffi::OsStr::new("synthetic"), b"{}", soon(5_000)).unwrap();
        let seen: serde_json::Map<String, Value> = serde_json::from_slice(&answer).unwrap();
        assert_eq!(seen["OPENWIZ_JEV"], "1");
        assert_eq!(seen["TYPESAFE_API_KEY"], "synthetic");
        for inherited in ["HOME", "PATH", "USER", "GH_TOKEN", "PYTHONPATH"] {
            assert!(!seen.contains_key(inherited), "{inherited} leaked");
        }
    }

    #[test]
    fn a_request_larger_than_the_pipe_is_bounded_by_the_deadline() {
        let tool = ask_script(
            "pipe",
            "import sys, time\ntime.sleep(30)\nsys.stdin.read()\n",
        );
        let request = vec![b'x'; 1 << 20];
        let started = std::time::Instant::now();
        assert_eq!(
            run_ask(
                &tool,
                std::ffi::OsStr::new("synthetic"),
                &request,
                soon(300)
            ),
            None
        );
        assert!(started.elapsed() < std::time::Duration::from_secs(3));
    }

    #[test]
    fn a_large_request_read_promptly_is_answered() {
        let tool = ask_script(
            "bigin",
            "import sys\ndata = sys.stdin.read()\nprint('{\"n\": %d}' % len(data))\n",
        );
        let request = vec![b'x'; 1 << 20];
        let answer = run_ask(
            &tool,
            std::ffi::OsStr::new("synthetic"),
            &request,
            soon(5_000),
        )
        .unwrap();
        let seen: Value = serde_json::from_slice(&answer).unwrap();
        assert_eq!(seen["n"], 1 << 20);
    }

    #[test]
    fn jev_gets_at_most_half_the_remaining_budget() {
        let now = std::time::Instant::now();
        let secs = std::time::Duration::from_secs;
        assert_eq!(answer_until(now, now + secs(8)), now + secs(4));
        assert_eq!(
            answer_until(now, now + secs(600)),
            now + secs(ANSWER_SECONDS)
        );
        assert_eq!(answer_until(now, now), now);
    }
}
