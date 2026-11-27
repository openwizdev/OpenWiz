use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

const TESTS: &str = env!("CARGO_MANIFEST_DIR");

fn root() -> PathBuf {
    Path::new(TESTS).parent().unwrap().to_path_buf()
}

fn check(case: &str, floor: &str, log: &str) -> (bool, String) {
    let dir = env::temp_dir().join(format!("openwiz-test-floor-{case}-{}", std::process::id()));
    fs::create_dir_all(&dir).unwrap();
    let (floor_file, log_file) = (dir.join("floor.json"), dir.join("run.log"));
    fs::write(&floor_file, floor).unwrap();
    fs::write(&log_file, log).unwrap();
    let out = Command::new("sh")
        .current_dir(root())
        .arg("ci/rust-tests.sh")
        .arg("--floor-check")
        .arg(&floor_file)
        .arg(&log_file)
        .output()
        .expect("run sh");
    let _ = fs::remove_dir_all(&dir);
    let text =
        String::from_utf8_lossy(&out.stdout).into_owned() + &String::from_utf8_lossy(&out.stderr);
    (out.status.success(), text)
}

fn summary(n: u32) -> String {
    format!(
        "running 3 tests\n\
         test result: ok. {a} passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.01s\n\
         \x20  Doc-tests openwiz_core\n\
         test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s\n\
         test result: FAILED. 500 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.01s\n\
         a test printed: test result: ok. 900 passed\n\
         test result: ok. {b} passed; 0 failed; 2 ignored; 0 measured; 4 filtered out; finished in 0.02s\n",
        a = n / 2,
        b = n - n / 2,
    )
}

const FLOOR: &str = "{\"rust\": 100}\n";
const HINT: &str =
    "rust-tests: ran 201 tests, more than 100 over the floor 100: raise it in ci/test-floor.json";

#[test]
fn a_run_below_the_floor_fails_with_one_line() {
    let (ok, out) = check("below", FLOOR, &summary(99));
    assert!(!ok, "a run below the floor passed:\n{out}");
    assert!(
        out.lines()
            .any(|l| l == "ran 99 tests, floor is 100: a suite stopped loading"),
        "no floor line:\n{out}"
    );
}

#[test]
fn a_run_at_the_floor_passes_and_prints_the_count() {
    let (ok, out) = check("at", FLOOR, &summary(100));
    assert!(ok, "a run at the floor failed:\n{out}");
    assert!(
        out.lines()
            .any(|l| l == "rust-tests: ran 100 tests, floor is 100"),
        "no count:\n{out}"
    );
    assert!(!out.contains("raise it"), "a hint at the floor:\n{out}");
}

#[test]
fn a_run_far_above_the_floor_passes_with_a_hint() {
    let (ok, out) = check("above", FLOOR, &summary(201));
    assert!(ok, "a run above the floor failed:\n{out}");
    assert!(out.lines().any(|l| l == HINT), "no hint:\n{out}");
    let (ok, out) = check("edge", FLOOR, &summary(200));
    assert!(
        ok && !out.contains("raise it"),
        "a hint at the floor plus 100:\n{out}"
    );
}

#[test]
fn an_unreadable_floor_fails_closed() {
    for floor in [
        "{}",
        "{\"rust\": -5}",
        "{\"rust\": \"100\"}",
        "{\"rust\": 100, \"x\": 1}",
    ] {
        let (ok, out) = check("bad", floor, &summary(1000));
        assert!(!ok, "floor {floor} passed:\n{out}");
        assert!(out.contains("has no rust floor"), "floor {floor}:\n{out}");
    }
}

#[test]
fn the_committed_floor_is_a_positive_multiple_of_ten() {
    let text = fs::read_to_string(root().join("ci/test-floor.json")).expect("ci/test-floor.json");
    let value: serde_json::Value = serde_json::from_str(&text).unwrap();
    let object = value.as_object().unwrap();
    assert_eq!(object.len(), 1, "only the rust floor: {text}");
    let floor = object["rust"].as_u64().expect("a whole number");
    assert!(floor > 0 && floor.is_multiple_of(10), "floor {floor}");
}
