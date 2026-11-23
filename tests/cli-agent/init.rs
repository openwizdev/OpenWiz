use super::*;

fn openwiz() -> PathBuf {
    let built = Command::new(env!("CARGO"))
        .args(["build", "-p", "openwiz-cli", "--bin", "openwiz", "--locked"])
        .current_dir(ROOT)
        .output()
        .unwrap();
    assert!(
        built.status.success(),
        "{}",
        String::from_utf8_lossy(&built.stderr)
    );
    Path::new(env!("CARGO_TARGET_TMPDIR"))
        .parent()
        .unwrap()
        .join("debug/openwiz")
}

struct Installed {
    root: PathBuf,
}

impl Installed {
    fn new(name: &str, with_runtime: bool) -> Self {
        let root = std::env::temp_dir().join(format!("openwiz-init-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        dirs::private_dir_all(root.join("bin")).unwrap();
        place::place(&openwiz(), &root.join("openwiz"));
        if with_runtime {
            dirs::private_dir_all(root.join("runtime/setup")).unwrap();
            for file in ["init.py", "store.py"] {
                fs::copy(
                    Path::new(ROOT).join("tools/install/setup").join(file),
                    root.join("runtime/setup").join(file),
                )
                .unwrap();
            }
        }
        place::place(
            &Path::new(ROOT).join("tools/install/tests/init/fake_gh.py"),
            &root.join("bin/gh"),
        );
        let world = serde_json::json!({"user":{"login":"synthetic-owner","type":"User"},"faults":[],"log":[],
            "repos":{"synthetic-owner/synthetic-app":{"full_name":"synthetic-owner/synthetic-app","private":true,
            "visibility":"private","default_branch":"main","permissions":{"push":true},
            "owner":{"login":"synthetic-owner","type":"User"},"description":null,"homepage":null,
            "labels":[],"pulls":[],"branches":{"main":{}}}}});
        fs::write(root.join("world.json"), world.to_string()).unwrap();
        Installed { root }
    }

    fn run(&self, args: &[&str]) -> Output {
        Command::new(self.root.join("openwiz"))
            .args(args)
            .env_clear()
            .env(
                "PATH",
                format!("{}:/usr/bin:/bin", self.root.join("bin").display()),
            )
            .env("HOME", self.root.join("home"))
            .env("OPENWIZ_STATE_DIR", self.root.join("state"))
            .env("FAKE_GH_WORLD", self.root.join("world.json"))
            .stdin(Stdio::null())
            .output()
            .unwrap()
    }

    fn writes(&self) -> usize {
        let world: Value =
            serde_json::from_slice(&fs::read(self.root.join("world.json")).unwrap()).unwrap();
        world["log"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|c| c[0] != "GET")
            .count()
    }
}

impl Drop for Installed {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

#[test]
fn installed_init_previews_and_applies_through_the_packaged_runtime() {
    let installed = Installed::new("apply", true);
    let preview = installed.run(&["init", "--repository", "synthetic-owner/synthetic-app"]);
    assert_eq!(
        preview.status.code(),
        Some(0),
        "{}",
        String::from_utf8_lossy(&preview.stderr)
    );
    let text = String::from_utf8(preview.stdout).unwrap();
    assert!(text.starts_with(
        "Brain: in-repository synthetic-owner/synthetic-app in .openwiz/brain; change it with the brain_location setting.\n"
    ));
    let id = text
        .lines()
        .find_map(|l| l.strip_prefix("Operation: "))
        .unwrap()
        .to_owned();
    let next = format!(
        "Apply it: openwiz init --yes --operation {id} --repository synthetic-owner/synthetic-app"
    );
    assert!(text.lines().any(|l| l == next), "{text}");
    assert_eq!(installed.writes(), 0);
    let mut apply: Vec<&str> = next["Apply it: openwiz ".len()..].split(' ').collect();
    apply.push("--json");
    let applied = installed.run(&apply);
    assert_eq!(applied.status.code(), Some(0));
    let report: Value = serde_json::from_slice(&applied.stdout).unwrap();
    assert_eq!(report["kind"], "init_result");
    assert_eq!(report["outcome"], "applied");
    assert_eq!(report["operation_id"], id.as_str());
    assert_eq!(
        report["pull_requests"][0]["repository"],
        "synthetic-owner/synthetic-app"
    );
    assert!(installed.writes() > 0);
}

#[test]
fn installed_init_refuses_without_its_runtime_and_on_bad_arguments() {
    let bare = Installed::new("bare", false);
    let out = bare.run(&[
        "init",
        "--repository",
        "synthetic-owner/synthetic-app",
        "--json",
    ]);
    assert_eq!(out.status.code(), Some(1));
    let report: Value = serde_json::from_slice(&out.stdout).unwrap();
    assert_eq!(report["schema"], "openwiz.cli-error.v1");
    assert_eq!(report["command"], "init");
    assert_eq!(report["error"]["kind"], "unavailable");
    assert!(!bare.root.join("state").exists());
    let installed = Installed::new("usage", true);
    for args in [
        vec!["init", "--yes"],
        vec!["init", "--operation", "0123456789abcdef0123456789abcdef"],
        vec!["init", "--json", "--json"],
        vec!["init", "--repository"],
        vec!["init", "--placement", "companion"],
    ] {
        let out = installed.run(&args);
        assert_eq!(out.status.code(), Some(2), "{args:?}");
        if args.contains(&"--json") {
            let report: Value = serde_json::from_slice(&out.stdout).unwrap();
            assert_eq!(report["error"]["kind"], "usage");
        } else {
            assert!(out.stdout.is_empty(), "{args:?}");
        }
    }
    assert!(!installed.root.join("state").exists());
    assert_eq!(installed.writes(), 0);
}

#[test]
fn init_help_is_source_free_and_listed_in_agent_discovery() {
    let bare = Installed::new("help", false);
    let out = bare.run(&["init", "--help", "--json"]);
    assert_eq!(out.status.code(), Some(0));
    let help: Value = serde_json::from_slice(&out.stdout).unwrap();
    assert_eq!(help["schema"], "openwiz.cli-help.v1");
    assert!(
        help["text"]
            .as_str()
            .unwrap()
            .contains("no placement question")
    );
    let out = bare.run(&["help", "--agent"]);
    let catalogue: Value = serde_json::from_slice(&out.stdout).unwrap();
    let names: Vec<_> = catalogue["commands"]
        .as_array()
        .unwrap()
        .iter()
        .map(|c| c["name"].as_str().unwrap())
        .collect();
    assert!(names.contains(&"init") && names.contains(&"init.apply"));
    assert!(!bare.root.join("state").exists());
}
