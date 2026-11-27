#[path = "../src/ghost/blend.rs"]
mod blend;
#[path = "../src/ghost/model.rs"]
mod model;

#[path = "../../../tests/fake-model-server/server.rs"]
mod fake_model_server;

use std::fs;
use std::path::{Path, PathBuf};
use std::thread;
use std::time::{Duration, Instant};

use blend::RecallHit;
use model::{Answer, ContextPack, Session, Settings, Tier};
use serde_json::Value;

const REPLAY_DELAY_MS: u64 = 20;

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("workspace root")
        .to_path_buf()
}

fn read_json(rel: &str) -> Value {
    let path = repo_root().join(rel);
    let text = fs::read_to_string(&path).unwrap_or_else(|e| panic!("read {}: {e}", path.display()));
    serde_json::from_str(&text).unwrap_or_else(|e| panic!("json {}: {e}", path.display()))
}

fn pack() -> ContextPack {
    ContextPack::from_value(&read_json("contracts/fixtures/ghost/context-pack.json"))
        .expect("context pack")
}

fn messages() -> Vec<String> {
    read_json("contracts/fixtures/ghost/replay-set.json")["messages"]
        .as_array()
        .expect("messages")
        .iter()
        .map(|message| message["text"].as_str().expect("message text").to_owned())
        .collect()
}

fn recall(text: &str, confidence: f64, fixed_code: bool) -> RecallHit {
    RecallHit {
        text: text.to_owned(),
        confidence,
        fixed_code,
    }
}

fn p90(samples: &[f64]) -> f64 {
    let mut ordered = samples.to_vec();
    ordered.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let index = (ordered.len() as f64 * 0.9).ceil() as usize - 1;
    ordered[index]
}

fn words(text: &str) -> usize {
    text.split_whitespace().count()
}

fn suggestion(answer: &Answer) -> &model::Suggestion {
    match answer {
        Answer::Suggestion(suggestion) => suggestion,
        Answer::None => panic!("expected a suggestion, got none"),
        Answer::Dropped => panic!("expected a suggestion, got a dropped reply"),
    }
}

#[test]
fn replay_p90_stays_within_150ms() {
    let server = fake_model_server::start(REPLAY_DELAY_MS, " ok", 0.9, false);
    let settings = Settings::llama(&server.url);
    let pack = pack();
    let mut samples = Vec::new();
    for text in messages() {
        let session = Session::new();
        for (index, _) in text.char_indices() {
            let prefix = &text[..=index];
            let started = Instant::now();
            let answer =
                model::answer(&session, &settings, &pack, prefix, (index + 1) as u64, None);
            let elapsed = started.elapsed().as_secs_f64() * 1000.0;
            let ghost = suggestion(&answer);
            assert_eq!(ghost.full_text, format!("{prefix}{}", ghost.text));
            assert!(words(&ghost.text) <= 8 && words(&ghost.text) >= 1);
            assert!((0.0..=1.0).contains(&ghost.confidence));
            samples.push(elapsed);
        }
    }
    let p90 = p90(&samples);
    assert!(
        p90 <= 150.0,
        "p90 keystroke-to-reply was {p90} ms over {samples:?} samples; the budget is 150 ms"
    );
}

#[test]
fn cached_prefix_is_byte_identical_across_keystrokes() {
    let server = fake_model_server::start(0, " and merge", 0.9, false);
    let settings = Settings::from_json(&format!(
        r#"{{"model_base_url":"{}","model":"custom-syn","max_tokens":50,"model_backend":"llama-server"}}"#,
        server.url
    ));
    assert_eq!(settings.model, "custom-syn");
    let pack = pack();
    let cached = model::cached_prefix(&pack);
    let session = Session::new();
    let text = "approve #42 and merge";
    for (index, _) in text.char_indices() {
        let prefix = &text[..=index];
        model::answer(&session, &settings, &pack, prefix, (index + 1) as u64, None);
    }
    let hits = server.hits.lock().unwrap();
    assert_eq!(hits.len(), text.chars().count());
    let mut sent = Vec::new();
    for (index, hit) in hits.iter().enumerate() {
        assert!(hit.finished, "keystroke {index} did not finish");
        assert_eq!(hit.path, "/completion");
        let body: Value = serde_json::from_str(&hit.body).unwrap();
        assert_eq!(body["n_predict"], 8, "at most 8 output tokens");
        assert_eq!(body["cache_prompt"], true);
        let prompt = body["prompt"].as_str().unwrap();
        assert!(
            prompt.starts_with(&cached),
            "keystroke {index} changed the cached prefix"
        );
        sent.push(prompt[cached.len()..].to_owned());
    }
    let mut expected: Vec<String> = text
        .char_indices()
        .map(|(index, _)| {
            let prefix = &text[..=index];
            prefix.strip_suffix(' ').unwrap_or(prefix).to_owned()
        })
        .collect();
    sent.sort();
    expected.sort();
    assert_eq!(sent, expected, "only the typed prefix may change");
    assert!(cached.contains("phrase: all recs\n"));
    assert!(cached.contains("grill: J1 "));
}

#[test]
fn superseded_request_is_cancelled_and_its_reply_dropped() {
    let server = fake_model_server::start(300, " later", 0.9, false);
    let settings = Settings::llama(&server.url);
    let pack = pack();
    let session = Session::new();
    let session2 = session.clone();
    let settings2 = settings.clone();
    let pack2 = pack.clone();
    let first =
        thread::spawn(move || model::answer(&session2, &settings2, &pack2, "ship", 1, None));
    thread::sleep(Duration::from_millis(40));
    let second = model::answer(&session, &settings, &pack, "ship magic", 2, None);
    let first = first.join().unwrap();
    assert_eq!(first, Answer::Dropped);
    let ghost = suggestion(&second);
    assert!(ghost.full_text.starts_with("ship magic"));
    let hits = server.hits.lock().unwrap();
    assert!(
        hits.iter().any(|hit| !hit.finished),
        "the superseded connection was not dropped: {hits:?}"
    );
}

#[test]
fn a_reply_typed_past_is_dropped() {
    let server = fake_model_server::start(300, " later", 0.9, false);
    let settings = Settings::llama(&server.url);
    let pack = pack();
    let session = Session::new();
    let session2 = session.clone();
    let settings2 = settings.clone();
    let pack2 = pack.clone();
    let first =
        thread::spawn(move || model::answer(&session2, &settings2, &pack2, "ship", 1, None));
    thread::sleep(Duration::from_millis(40));
    session.note_typed("ship magic");
    assert_eq!(first.join().unwrap(), Answer::Dropped);
    let _ = server;
}

#[test]
fn another_session_is_not_cancelled() {
    let server = fake_model_server::start(40, " ok", 0.9, false);
    let settings = Settings::llama(&server.url);
    let pack = pack();
    let one = Session::new();
    let two = Session::new();
    let settings2 = settings.clone();
    let pack2 = pack.clone();
    let other = thread::spawn(move || model::answer(&two, &settings2, &pack2, "J", 1, None));
    let kept = model::answer(&one, &settings, &pack, "J1", 1, None);
    assert_eq!(suggestion(&kept).tier, Tier::SmallModel);
    assert_eq!(suggestion(&other.join().unwrap()).tier, Tier::SmallModel);
}

#[test]
fn no_model_server_answers_from_recall_without_error() {
    let settings = Settings::llama("http://127.0.0.1:1");
    let started = Instant::now();
    let answer = model::answer(
        &Session::new(),
        &settings,
        &pack(),
        "J1",
        1,
        Some(recall(" all recs", 0.9, true)),
    );
    assert!(started.elapsed() < Duration::from_millis(500));
    let ghost = suggestion(&answer);
    assert_eq!(ghost.tier, Tier::Recall);
    assert_eq!(ghost.tier.as_str(), "recall");
    assert_eq!(ghost.text, " all recs");
    assert_eq!(ghost.full_text, "J1 all recs");

    let off = Settings::from_json("not json");
    let foreign = Settings::from_json(r#"{"model_base_url":"http://example.com:80"}"#);
    assert!(foreign.base_url.is_empty());
    let started = Instant::now();
    let answer = model::answer(
        &Session::new(),
        &foreign,
        &pack(),
        "J1",
        1,
        Some(recall(" all recs", 0.8, true)),
    );
    assert!(started.elapsed() < Duration::from_millis(50));
    assert_eq!(suggestion(&answer).tier, Tier::Recall);
    let answer = model::answer(
        &Session::new(),
        &off,
        &pack(),
        "zzq",
        1,
        Some(recall("nope", 0.1, false)),
    );
    assert_eq!(answer, Answer::None);
}

#[test]
fn recall_and_the_logprob_gate_blend() {
    let pack = pack();
    let fixed = fake_model_server::start(0, " something else", 0.95, false);
    let answer = model::answer(
        &Session::new(),
        &Settings::llama(&fixed.url),
        &pack,
        "J1",
        1,
        Some(recall(" all recs", 0.55, true)),
    );
    let ghost = suggestion(&answer);
    assert_eq!(ghost.tier, Tier::Recall);
    assert_eq!(ghost.text, " all recs");

    let weak = fake_model_server::start(0, " maybe", 0.05, false);
    let answer = model::answer(
        &Session::new(),
        &Settings::llama(&weak.url),
        &pack,
        "all r",
        1,
        Some(recall("ecs", 0.6, false)),
    );
    let ghost = suggestion(&answer);
    assert_eq!(ghost.tier, Tier::Recall);
    assert_eq!(ghost.text, "ecs");
    assert_eq!(ghost.full_text, "all recs");

    let neither = fake_model_server::start(0, " maybe", 0.05, false);
    let answer = model::answer(
        &Session::new(),
        &Settings::llama(&neither.url),
        &pack,
        "zzq",
        1,
        Some(recall("nope", 0.1, false)),
    );
    assert_eq!(answer, Answer::None);

    let blocked = fake_model_server::start(0, " force push the branch", 0.95, false);
    let answer = model::answer(
        &Session::new(),
        &Settings::llama(&blocked.url),
        &pack,
        "please",
        1,
        Some(recall(" stop", 0.7, false)),
    );
    assert_eq!(suggestion(&answer).text, " stop");
    assert_eq!(suggestion(&answer).tier, Tier::Recall);
}

#[test]
fn trailing_space_sentence_and_eight_words() {
    let server = fake_model_server::start(0, " #42 and merge", 0.9, false);
    let session = Session::new();
    let answer = model::answer(
        &session,
        &Settings::llama(&server.url),
        &pack(),
        "approve ",
        1,
        None,
    );
    let ghost = suggestion(&answer);
    assert_eq!(ghost.text, "#42 and merge");
    assert_eq!(ghost.full_text, "approve #42 and merge");
    let prompt = fake_model_server::prompt_of(&server.hits.lock().unwrap()[0].body).unwrap();
    assert!(prompt.ends_with("approve"));
    assert!(!prompt.ends_with("approve "));

    let sentence = fake_model_server::start(0, " Hello there. And more words", 0.9, false);
    let answer = model::answer(
        &Session::new(),
        &Settings::llama(&sentence.url),
        &pack(),
        "say",
        1,
        None,
    );
    let ghost = suggestion(&answer);
    assert_eq!(ghost.text, " Hello there.");
    assert_eq!(ghost.full_text, "say Hello there.");

    let long = fake_model_server::start(
        0,
        " one two three four five six seven eight nine",
        0.9,
        false,
    );
    let answer = model::answer(
        &Session::new(),
        &Settings::llama(&long.url),
        &pack(),
        "count",
        1,
        None,
    );
    let ghost = suggestion(&answer);
    assert_eq!(words(&ghost.text), 8);
    assert_eq!(ghost.text, " one two three four five six seven eight");

    let partial = fake_model_server::start(0, "alpha beta partial", 0.9, true);
    let answer = model::answer(
        &Session::new(),
        &Settings::llama(&partial.url),
        &pack(),
        "go ",
        1,
        None,
    );
    assert_eq!(suggestion(&answer).text, "alpha beta");
}

#[test]
fn ollama_raw_completion_is_blended_and_ends_at_the_first_newline() {
    let server = fake_model_server::start(0, " and merge\nthen review.", 0.85, false);
    let settings = Settings::ollama(&server.url);
    let answer = model::answer(&Session::new(), &settings, &pack(), "approve", 4, None);
    let ghost = suggestion(&answer);
    assert_eq!(ghost.tier, Tier::SmallModel);
    assert_eq!(ghost.text, " and merge");
    assert_eq!(ghost.full_text, "approve and merge");
    let hit = &server.hits.lock().unwrap()[0];
    assert_eq!(hit.path, "/api/generate");
    let body: Value = serde_json::from_str(&hit.body).unwrap();
    assert_eq!(body["raw"], true);
    assert_eq!(body["stream"], false);
    assert_eq!(body["options"]["num_predict"], 8);
    assert_eq!(body["model"], model::DEFAULT_MODEL);
}
