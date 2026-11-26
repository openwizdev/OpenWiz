//! Jev decisions for fleet tick. The key is read only from `TYPESAFE_API_KEY`.
//! A missing key or a failed call returns no answer, and the caller keeps its
//! previous rule. The HTTP call is the documented `POST /v1/systemone`, done
//! by `tools/typesafe/ask.py` so the key stays in the environment and off the
//! command line.

use serde_json::{Value, json};
use std::path::PathBuf;
use std::process::{Command, Stdio};

const MODEL: &str = "jev-1.14.0";
const MAX_STATE_CHARS: usize = 24_000;
/// A false yes restarts a builder on another model family, or accepts a
/// review verdict. The docs' starting point is 0.7; this is higher because
/// acting on a false yes is expensive.
const ACT: f64 = 0.9;

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

struct Http;

impl Decisions for Http {
    fn ask(&self, state: &str, questions: &Value) -> Option<Value> {
        let script = ask_script()?;
        let body = json!({
            "model": MODEL,
            "state": bounded(state),
            "questions": questions,
        });
        let mut child = Command::new("python3")
            .arg("-I")
            .arg(&script)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .ok()?;
        {
            let stdin = child.stdin.as_mut()?;
            use std::io::Write as _;
            stdin.write_all(body.to_string().as_bytes()).ok()?;
        }
        let output = child.wait_with_output().ok()?;
        if !output.status.success() || output.stdout.len() > 1_048_576 {
            return None;
        }
        serde_json::from_slice(&output.stdout).ok()
    }
}

pub fn env_decider() -> Box<dyn Decisions> {
    if key_present() {
        Box::new(Http)
    } else {
        Box::new(Absent)
    }
}

fn key_present() -> bool {
    std::env::var_os("TYPESAFE_API_KEY").is_some_and(|value| {
        std::str::from_utf8(value.as_encoded_bytes())
            .ok()
            .is_some_and(|text| !text.trim().is_empty())
    })
}

fn bounded(state: &str) -> String {
    state.chars().take(MAX_STATE_CHARS).collect()
}

fn ask_script() -> Option<PathBuf> {
    let mut starts = Vec::new();
    if let Ok(cwd) = std::env::current_dir() {
        starts.push(cwd);
    }
    if let Ok(exe) = std::env::current_exe()
        && let Some(dir) = exe.parent()
    {
        starts.push(dir.to_path_buf());
    }
    for start in starts {
        let mut dir = start;
        for _ in 0..8 {
            let candidate = dir.join("tools/typesafe/ask.py");
            if candidate.is_file() {
                return Some(candidate);
            }
            if !dir.pop() {
                break;
            }
        }
    }
    None
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

const LIMIT_QUESTION: &str =
    "The session output says this Claude run stopped because its plan usage limit was reached.";

pub fn plan_limit_with(text: &str, decider: &dyn Decisions) -> bool {
    if exact_plan_limit(text) {
        return true;
    }
    let questions = json!({
        "limit": {
            "type": "noul",
            "instructions": LIMIT_QUESTION,
            "criteria": {
                "true": "The text says a plan, quota, or rate limit stopped the run and it should wait.",
                "false": "The text is ordinary work, a normal failure, or a sign-in problem."
            }
        }
    });
    decider
        .ask(text, &questions)
        .and_then(|response| noul(&response, "limit"))
        .is_some_and(|value| value >= ACT)
}

pub fn plan_limit(text: &str) -> bool {
    plan_limit_with(text, env_decider().as_ref())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn limit_answer(value: f64) -> Value {
        json!({"answers": {"limit": {"type": "noul", "noul": value}}})
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
            "Claude usage limit reached",
            &Count(&calls)
        ));
        assert_eq!(calls.get(), 0);
    }

    #[test]
    fn a_paraphrase_needs_a_high_noul_and_a_miss_stays_a_miss() {
        assert!(!plan_limit_with(
            "please wait, the plan limit stopped the run",
            &Absent
        ));
        assert!(plan_limit_with(
            "please wait, the plan limit stopped the run",
            &Scripted(limit_answer(0.95))
        ));
        assert!(!plan_limit_with(
            "please wait, the plan limit stopped the run",
            &Scripted(limit_answer(0.5))
        ));
        assert!(!plan_limit_with(
            "not signed in",
            &Scripted(limit_answer(0.1))
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
            let recorded = case["recorded_noul"].as_f64();
            old_hit += usize::from(exact_plan_limit(text) == expected);
            let shaped = exact_plan_limit(text) || recorded.is_some_and(|value| value >= ACT);
            shaped_hit += usize::from(shaped == expected);
        }
        assert_eq!((cases.len(), old_hit, shaped_hit), (9, 7, 8));
    }

    #[test]
    fn ask_without_a_key_exits_without_printing() {
        let Some(script) = ask_script() else {
            panic!("tools/typesafe/ask.py was not found by walking up from the process");
        };
        let output = Command::new("python3")
            .arg("-I")
            .arg(&script)
            .env_remove("TYPESAFE_API_KEY")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .and_then(|mut child| {
                use std::io::Write as _;
                child.stdin.as_mut().unwrap().write_all(b"{}")?;
                drop(child.stdin.take());
                child.wait_with_output()
            })
            .unwrap();
        assert!(!output.status.success());
        assert!(output.stdout.is_empty());
        assert!(output.stderr.is_empty());
    }
}
