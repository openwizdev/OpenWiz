use serde_json::{Value, json};

const MODEL: &str = "jev-1.14.0";
const MAX_STATE_CHARS: usize = 24_000;
const TAIL_CHARS: usize = 4_000;
const MAX_ANSWER_BYTES: usize = 1_048_576;
const ANSWER_SECONDS: u64 = 20;

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
        let body = json!({
            "model": MODEL,
            "state": bounded(state),
            "questions": questions,
        });
        let output = jev_process(body.to_string().as_bytes())?;
        if !output.status.success() || output.stdout.len() > MAX_ANSWER_BYTES {
            return None;
        }
        serde_json::from_slice(&output.stdout).ok()
    }
}

fn jev_process(request: &[u8]) -> Option<std::process::Output> {
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
    let sent = std::io::Write::write_all(&mut child.stdin.take()?, request);
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(ANSWER_SECONDS);
    while child.try_wait().ok()?.is_none() {
        if sent.is_err() || std::time::Instant::now() > deadline {
            let _ = child.kill();
            let _ = child.wait();
            return None;
        }
        std::thread::sleep(std::time::Duration::from_millis(20));
    }
    child.wait_with_output().ok()
}

pub fn env_decider() -> Box<dyn Decisions> {
    if jev_enabled() {
        Box::new(Http)
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
    text.char_indices().nth(skip).map_or(text, |(at, _)| &text[at..])
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

pub fn plan_limit_with(text: &str, decider: &dyn Decisions) -> bool {
    if exact_plan_limit(text) {
        return true;
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
    let Some(response) = decider.ask(tail(text), questions) else {
        return false;
    };
    let Some(act) = site.get("act").and_then(Value::as_f64) else {
        return false;
    };
    combined(&response, &config, "plan_limit").is_some_and(|value| value >= act)
}

pub fn plan_limit(text: &str) -> bool {
    plan_limit_with(text, env_decider().as_ref())
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
            "Claude usage limit reached",
            &Count(&calls)
        ));
        assert_eq!(calls.get(), 0);
    }

    #[test]
    fn a_paraphrase_needs_a_clear_weighted_yes_and_a_miss_stays_a_miss() {
        let text = "please wait, the plan limit stopped the run";
        assert!(!plan_limit_with(text, &Absent));
        assert!(plan_limit_with(
            text,
            &Scripted(limit_answer(0.96, 0.04, 0.02))
        ));
        assert!(!plan_limit_with(
            text,
            &Scripted(limit_answer(0.55, 0.02, 0.02))
        ));
        assert!(!plan_limit_with(
            text,
            &Scripted(limit_answer(0.8, 0.02, 0.02))
        ));
        assert!(!plan_limit_with(
            "not signed in",
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
        assert!(!plan_limit_with(&text, &seen));
        let sent = seen.0.borrow();
        assert_eq!(sent.chars().count(), TAIL_CHARS);
        assert!(sent.starts_with('é'));
        assert_eq!(tail("short"), "short");
        assert_eq!(tail(""), "");
    }
}
