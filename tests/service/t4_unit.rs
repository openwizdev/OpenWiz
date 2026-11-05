//! C2 fixture proof of the user unit's rules. Live kill/reboot belongs to T11.
use std::collections::BTreeMap;
use std::path::Path;

fn unit_rules(text: &str) -> BTreeMap<String, String> {
    let mut section = "";
    let mut rules = BTreeMap::new();
    for line in text.lines().map(str::trim) {
        if line.starts_with('[') && line.ends_with(']') {
            section = &line[1..line.len() - 1];
        } else if !line.starts_with('#')
            && let Some((key, value)) = line.split_once('=')
        {
            let name = format!("{section}.{key}");
            assert!(
                rules.insert(name, value.to_owned()).is_none(),
                "duplicate unit rule"
            );
        }
    }
    rules
}

#[test]
fn unit_restarts_on_every_exit_and_is_enabled_at_boot() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let text = std::fs::read_to_string(root.join("deploy/pc/openwiz.service"))
        .expect("T4 must supply the PC user unit");
    let rules = unit_rules(&text);
    for (key, value) in [
        ("Service.Type", "simple"),
        ("Service.WorkingDirectory", "%h/.local/lib/openwiz/source"),
        (
            "Service.ExecStart",
            "%h/.local/lib/openwiz/current/openwiz-service",
        ),
        ("Service.Restart", "always"),
        ("Service.RestartSec", "5"),
        ("Service.UMask", "0077"),
        (
            "Service.Environment",
            "OPENWIZ_STATE_DIR=%h/.local/state/openwiz",
        ),
        ("Service.KillMode", "control-group"),
        ("Install.WantedBy", "default.target"),
        ("Unit.StartLimitIntervalSec", "0"),
    ] {
        assert_eq!(rules.get(key).map(String::as_str), Some(value), "{key}");
    }
    assert!(
        !rules.contains_key("Service.User"),
        "a user unit runs as its owner"
    );
}

#[path = "t4_setup.rs"]
mod setup;
