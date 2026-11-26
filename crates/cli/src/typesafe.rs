//! Jev decisions for fleet tick. The key is read only from `TYPESAFE_API_KEY`.
//! A missing key or a failed call returns no answer, and the caller keeps its
//! previous rule. The HTTP call is the documented `POST /v1/systemone`, done
//! by `tools/typesafe/ask.py` so the key stays in the environment and off the
//! command line.

use openwiz_core::fleet::model::Commit;
use serde_json::{Value, json};
use std::path::PathBuf;
use std::process::{Command, Stdio};

const MODEL: &str = "jev-1.14.0";
const MAX_STATE_CHARS: usize = 24_000;

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

fn config() -> Value {
    serde_json::from_str(include_str!("../../../tools/typesafe/config.json"))
        .expect("tools/typesafe/config.json is json")
}

/// Weighted sum or noisy-or from `config.json`. `None` is the uncertain band
/// or a response that does not match the site, and the caller falls back.
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
    let Some(response) = decider.ask(text, questions) else {
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

struct Chosen {
    name: String,
    probability: f64,
    confidence: f64,
}

fn choice(response: &Value, name: &str) -> Option<Chosen> {
    let answer = response.get("answers")?.get(name)?;
    if answer.get("type")?.as_str()? != "choice" {
        return None;
    }
    let picked = answer.get("choice")?.as_str()?;
    let confidence = answer.get("confidence")?.as_f64()?;
    let probability = answer.get("probabilities")?.get(picked)?.as_f64()?;
    if !(0.0..=1.0).contains(&confidence) || !(0.0..=1.0).contains(&probability) {
        return None;
    }
    Some(Chosen {
        name: picked.to_owned(),
        probability,
        confidence,
    })
}

fn exact_verdict(line: &str) -> Option<&'static str> {
    let rest = line.strip_prefix("VERDICT: ")?;
    let (word, commit) = rest.split_once(" at ")?;
    Commit::parse(commit)?;
    match word {
        "APPROVE" => Some("APPROVE"),
        "CHANGES" => Some("CHANGES"),
        _ => None,
    }
}

/// Rename the word on a `VERDICT:` line that already names a full commit.
/// `None` means leave the line alone: it is already exact, the commit does not
/// parse, Jev is unsure, or the call failed.
pub fn canonical_verdict_line(line: &str, decider: &dyn Decisions) -> Option<String> {
    if exact_verdict(line).is_some() {
        return None;
    }
    let rest = line.strip_prefix("VERDICT: ")?;
    let (_, commit) = rest.split_once(" at ")?;
    let commit = Commit::parse(commit)?;
    let questions = json!({
        "kind": {
            "type": "choice",
            "instructions": "What verdict does this review comment give?",
            "criteria": {
                "approve": "The reviewer approves the commit.",
                "changes": "The reviewer wants changes on the commit.",
                "not_a_verdict": "This is not an approve or changes verdict."
            }
        },
        "is_verdict": {
            "type": "noul",
            "instructions": "This comment is a reviewer's approve or request-changes verdict for the commit it names.",
            "criteria": {
                "true": "The reviewer is giving a verdict on that commit.",
                "false": "The line only mentions a verdict, or it is not one."
            }
        }
    });
    let response = decider.ask(line, &questions)?;
    let chosen = choice(&response, "kind")?;
    if chosen.probability < ACT || chosen.confidence < ACT || noul(&response, "is_verdict")? < ACT {
        return None;
    }
    let word = match chosen.name.as_str() {
        "approve" => "APPROVE",
        "changes" => "CHANGES",
        _ => return None,
    };
    Some(format!("VERDICT: {word} at {}", commit.as_str()))
}

pub fn verdict_text(body: &str, decider: &dyn Decisions) -> String {
    let Some(first) = body.lines().next() else {
        return body.to_owned();
    };
    let Some(line) = canonical_verdict_line(first, decider) else {
        return body.to_owned();
    };
    match body.split_once('\n') {
        Some((_, rest)) => format!("{line}\n{rest}"),
        None => line,
    }
}

#[cfg(test)]
fn accepted_verdict(line: &str, decider: &dyn Decisions) -> Option<&'static str> {
    if let Some(word) = exact_verdict(line) {
        return Some(word);
    }
    exact_verdict(&canonical_verdict_line(line, decider)?)
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

    #[test]
    fn a_rewritten_verdict_keeps_the_findings() {
        let sha = "ab".repeat(20);
        let body = format!("VERDICT: APPROVED at {sha}\n\n- **R1 [low]** synthetic");
        let text = verdict_text(&body, &Scripted(verdict_body("approve", 0.97, 0.96, 0.95)));
        assert_eq!(
            text,
            format!("VERDICT: APPROVE at {sha}\n\n- **R1 [low]** synthetic")
        );
    }

    #[test]
    fn recorded_verdict_counts() {
        let raw = include_str!("../../../tools/typesafe/fixtures/verdict.json");
        let data: Value = serde_json::from_str(raw).unwrap();
        let cases = data["cases"].as_array().unwrap();
        let mut old_hit = 0;
        let mut shaped_hit = 0;
        for case in cases {
            let line = case["line"].as_str().unwrap();
            let expected = case["expected"].as_str();
            let recorded = &case["recorded"];
            let old = exact_verdict(line);
            let shaped = accepted_verdict(line, &Scripted(recorded.clone()));
            old_hit += usize::from(old == expected);
            shaped_hit += usize::from(shaped == expected);
        }
        assert_eq!((cases.len(), old_hit, shaped_hit), (9, 5, 8));
    }

    fn verdict_body(name: &str, probability: f64, confidence: f64, noul: f64) -> Value {
        let mut probabilities = serde_json::Map::new();
        for key in ["approve", "changes", "not_a_verdict"] {
            probabilities.insert(
                key.to_owned(),
                json!(if key == name { probability } else { 0.0 }),
            );
        }
        json!({
            "answers": {
                "kind": {
                    "type": "choice",
                    "choice": name,
                    "confidence": confidence,
                    "probabilities": probabilities
                },
                "is_verdict": {"type": "noul", "noul": noul}
            }
        })
    }
}
