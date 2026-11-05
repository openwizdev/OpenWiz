//! Installed startup gate. Existing source deployments keep their prior path.
//! Removing this gate requires the separately approved activation prerequisites;
//! there is deliberately no runtime flag, environment or config bypass.
pub fn check(executable: &std::path::Path) -> Result<(), String> {
    // #2379: a packaged build starts only when its own installer-valid package
    // and T9's applied activation record bind this exact build, owner, root,
    // runtime state and config. Login is reported as unknown (LE1). Every
    // unread or unexpected input refuses. The rules mirror the installer's
    // `manifest_at`/`verify_installed`/`path_guard` and T9's `journal()`.
    use openwiz_core::messaging::sha256_hex;
    use serde_json::Value;
    use std::{
        collections::BTreeSet,
        fs,
        os::unix::fs::MetadataExt,
        path::{Component, Path},
    };
    const TARGETS: [&str; 3] = [
        "aarch64-apple-darwin",
        "x86_64-apple-darwin",
        "x86_64-unknown-linux-gnu",
    ];
    const PROGRAMS: [&str; 3] = ["openwiz", "openwiz-service", "openwiz-server"];
    // tools/install/install.py REQUIRED; the t12 proof reads the installer's list.
    const REQUIRED: [&str; 20] = [
        "openwiz",
        "openwiz-service",
        "openwiz-server",
        "web/openwiz-build.txt",
        "runtime/openwiz-build.txt",
        "web/index.html",
        "web/setup.html",
        "runtime/install.py",
        "runtime/pull.py",
        "runtime/skills/setup/SKILL.md",
        "runtime/skills/grill/SKILL.md",
        "runtime/skills/plan-graph/SKILL.md",
        "runtime/skills/launch-fleet/SKILL.md",
        "runtime/skills/launch-fleet/scripts/fleet.sh",
        "runtime/setup/setup.py",
        "runtime/setup/store.py",
        "runtime/github-app/setup.py",
        "runtime/github-app/app.py",
        "runtime/github-app/manifest.json",
        "runtime/cloudroom/cloudroom.py",
    ];
    const EFFECTS: &str = "Enable and start the owner user unit openwiz.service.";
    const REASON: &str = "Reconcile the exact PC activation and App record before continuing.";
    const SAFE: u64 = 1 << 53;
    // Typed shapes refuse duplicate, unknown and mistyped keys; the key-set
    // checks below additionally require every nullable key to be present.
    #[derive(serde::Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Manifest {
        schema: String,
        version: String,
        source: String,
        target: String,
        setup_api: u64,
        archive: String,
        archive_sha256: String,
        archive_bytes: u64,
        assets: Vec<Asset>,
    }
    #[derive(serde::Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Asset {
        path: String,
        sha256: String,
        bytes: u64,
        mode: String,
    }
    #[derive(serde::Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Journal {
        schema: String,
        request: Request,
        operation: Operation,
        created_at: u64,
        updated_at: u64,
        started_at: Option<u64>,
        record_at: Option<u64>,
        record_state: String,
        outcome: String,
    }
    #[derive(serde::Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Request {
        schema: String,
        host: String,
        action: String,
        operation_id: String,
        binding: Binding,
        revision: u64,
        request_hash: String,
    }
    #[derive(serde::Deserialize, serde::Serialize)]
    #[serde(deny_unknown_fields)]
    struct Binding {
        owner_uid: u64,
        unit: String,
        root: String,
        state_root: String,
        repository: String,
        project: String,
        runtime: String,
        build: String,
        config_sha256: String,
        unit_sha256: String,
        app_id: u64,
        installation_id: u64,
        service_issue: u64,
    }
    #[derive(serde::Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Operation {
        operation_id: String,
        kind: String,
        phase: String,
        fingerprint: String,
        effects: Vec<String>,
        reason: String,
    }
    let refuse = |why: &str| {
        Err(format!(
            "Activation remains closed: {why}; login: unknown. Reconcile the installed PC activation."
        ))
    };
    let build = executable
        .parent()
        .ok_or("cannot locate the service package")?;
    // A damaged/missing manifest must not reclassify a packaged build as a
    // source deployment. Source updater builds have no packaged runtime.
    let packaged = ["install-manifest.json", "runtime"].iter().any(|marker| {
        !matches!(fs::symlink_metadata(build.join(marker)),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound)
    });
    if !packaged {
        return Ok(());
    }
    let Ok(owner) = fs::metadata("/proc/self").map(|m| m.uid()) else {
        return refuse("the effective owner is unreadable");
    };
    // Owner-held, not group/other accessible, the expected kind, singly linked.
    let private = |path: &Path, directory: bool| {
        fs::symlink_metadata(path).is_ok_and(|m| {
            m.uid() == owner
                && m.mode() & 0o077 == 0
                && if directory {
                    m.is_dir()
                } else {
                    m.is_file() && m.nlink() == 1
                }
        })
    };
    let read = |path: &Path, limit: u64| -> Option<Vec<u8>> {
        let bytes = private(path, false)
            .then(|| fs::read(path).ok())
            .flatten()?;
        (bytes.len() as u64 <= limit).then_some(bytes)
    };
    let hex = |text: &str, n: usize| {
        text.len() == n
            && text
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    };
    let charset = |text: &str, extra: &[u8]| {
        text.bytes()
            .all(|b| b.is_ascii_alphanumeric() || extra.contains(&b))
    };
    let version = |text: &str, digits: usize| {
        let parts: Vec<_> = text.split('.').collect();
        parts.len() == 3
            && parts[0] == "0"
            && parts[1..]
                .iter()
                .all(|p| (1..=digits).contains(&p.len()) && p.bytes().all(|b| b.is_ascii_digit()))
    };
    // install.path_guard: absolute and plain, every existing ancestor a real dir.
    let plain = |path: &Path| {
        path.is_absolute()
            && path
                .components()
                .all(|c| matches!(c, Component::RootDir | Component::Normal(_)))
            && path.ancestors().all(|p| match fs::symlink_metadata(p) {
                Ok(m) => m.is_dir(),
                Err(e) => e.kind() == std::io::ErrorKind::NotFound,
            })
    };
    // T9's binding paths: ASCII, '/' plus 1..=1023 characters, no control
    // character and no empty, '.' or '..' component.
    let binding_path = |text: &str| {
        text.is_ascii()
            && (2..=1024).contains(&text.len())
            && text.starts_with('/')
            && !text.bytes().any(|b| b < 0x20 || b == 0x7f)
            && text[1..].split('/').all(|p| !["", ".", ".."].contains(&p))
    };
    let keys = |value: &Value, expected: &[&str]| {
        value.as_object().is_some_and(|map| {
            map.len() == expected.len() && expected.iter().all(|k| map.contains_key(*k))
        })
    };

    // The selected build and its installer-valid manifest.
    let name = build.file_name().and_then(|n| n.to_str()).unwrap_or("");
    let builds = build.parent().filter(|p| p.ends_with("service/builds"));
    let Some(state) = builds.and_then(Path::parent).and_then(Path::parent) else {
        return refuse("the build is outside an installed state root");
    };
    if !hex(name, 40) || !plain(build) || !private(build, true) {
        return refuse("the installed build is not a private verified selection");
    }
    let Some(manifest) = read(&build.join("install-manifest.json"), 4 * 1024 * 1024)
        .and_then(|b| serde_json::from_slice::<Manifest>(&b).ok())
    else {
        return refuse("the installed manifest is unreadable");
    };
    let bundle_ok = manifest
        .archive
        .strip_suffix(".tar.gz")
        .is_some_and(|stem| !stem.is_empty() && charset(stem, b"_.-"));
    if manifest.schema != "openwiz.install.v1"
        || manifest.source != name
        || !version(&manifest.version, usize::MAX)
        || !TARGETS.contains(&manifest.target.as_str())
        || manifest.setup_api != 1
        || !bundle_ok
        || !hex(&manifest.archive_sha256, 64)
        || manifest.archive_bytes == 0
        || manifest.assets.is_empty()
    {
        return refuse("the installed manifest is not an installer-valid package");
    }
    let identity = format!(
        "openwiz.package.v1\n{}\n{}\n{}\n",
        manifest.version, manifest.source, manifest.target
    );
    let mut listed = BTreeSet::new();
    for asset in &manifest.assets {
        let program = PROGRAMS.contains(&asset.path.as_str());
        let safe = charset(&asset.path, b"_+./-")
            && !asset.path.starts_with('/')
            && asset
                .path
                .split('/')
                .all(|p| !p.is_empty() && !p.starts_with('.'))
            && (program || asset.path.starts_with("web/") || asset.path.starts_with("runtime/"));
        let overlaps = listed.iter().any(|p: &String| {
            p == &asset.path
                || asset.path.starts_with(&format!("{p}/"))
                || p.starts_with(&format!("{}/", asset.path))
        });
        let mode = if program || asset.path.ends_with(".sh") {
            "0700"
        } else {
            "0600"
        };
        let path = build.join(&asset.path);
        let matches = safe
            && !overlaps
            && hex(&asset.sha256, 64)
            && asset.mode == mode
            && fs::symlink_metadata(&path)
                .is_ok_and(|m| format!("{:04o}", m.mode() & 0o7777) == asset.mode)
            && read(&path, asset.bytes).is_some_and(|data| {
                data.len() as u64 == asset.bytes && sha256_hex(&data) == asset.sha256
            });
        if !matches {
            return refuse("an installed asset differs from the verified manifest");
        }
        listed.insert(asset.path.clone());
    }
    if !REQUIRED.iter().all(|r| listed.contains(*r)) {
        return refuse("the installed package lacks a required asset");
    }
    let stamp = (sha256_hex(identity.as_bytes()), identity.len() as u64);
    if manifest
        .assets
        .iter()
        .filter(|a| a.path == "web/openwiz-build.txt" || a.path == "runtime/openwiz-build.txt")
        .any(|a| (a.sha256.clone(), a.bytes) != stamp)
    {
        return refuse("the web/runtime build identity differs");
    }
    let mut found = BTreeSet::new();
    let mut pending = vec![build.to_path_buf()];
    while let Some(directory) = pending.pop() {
        let Ok(entries) = fs::read_dir(&directory) else {
            return refuse("the installed build is unreadable");
        };
        for entry in entries {
            let Ok(path) = entry.map(|e| e.path()) else {
                return refuse("the installed build is unreadable");
            };
            if private(&path, true) {
                pending.push(path);
            } else if let Some(relative) = path
                .strip_prefix(build)
                .ok()
                .and_then(Path::to_str)
                .filter(|_| private(&path, false))
            {
                found.insert(relative.to_owned());
            } else {
                return refuse("the installed build holds an unverified entry");
            }
        }
    }
    found.remove("install-manifest.json");
    if found != listed {
        return refuse("the installed build holds an unlisted asset");
    }

    // The runtime state this service will actually use must be this one.
    let Ok(runtime_state) = openwiz_store::default_state_dir(&|n| std::env::var_os(n)) else {
        return refuse("the runtime state directory is unavailable");
    };
    if runtime_state != state
        || !plain(state)
        || !["", "service", "setup"]
            .iter()
            .all(|d| private(&state.join(d), true))
    {
        return refuse("the runtime state is not this installation's private state");
    }

    // T9's journal, with exactly T9's reader invariants.
    let Some(raw) = read(&state.join("setup/pc-activation.json"), 64 * 1024) else {
        return refuse("no readable PC activation record");
    };
    let (Ok(journal), Ok(shape)) = (
        serde_json::from_slice::<Journal>(&raw),
        serde_json::from_slice::<Value>(&raw),
    ) else {
        return refuse("the PC activation record is malformed");
    };
    let (request, binding, operation) = (
        &journal.request,
        &journal.request.binding,
        &journal.operation,
    );
    let present = keys(
        &shape,
        &[
            "schema",
            "request",
            "operation",
            "created_at",
            "updated_at",
            "started_at",
            "record_at",
            "record_state",
            "outcome",
        ],
    );
    let between =
        |t: Option<u64>| t.is_none_or(|t| journal.created_at <= t && t <= journal.updated_at);
    let runtime_ok = binding
        .runtime
        .split_once(' ')
        .is_some_and(|(v, s)| version(v, 10) && hex(s, 40) && s == binding.build);
    let repository_ok = binding.repository.split_once('/').is_some_and(|(o, n)| {
        (1..=39).contains(&o.len())
            && charset(o, b"-")
            && (1..=100).contains(&n.len())
            && charset(n, b"_.-")
            && n != "."
            && n != ".."
    });
    let project_ok = (1..=128).contains(&binding.project.len())
        && !binding.project.starts_with('-')
        && charset(&binding.project, b"_-");
    let shaped = present
        && journal.schema == "openwiz.pc-activation.v1.journal"
        && request.schema == "openwiz.pc-activation.v1"
        && request.host == "pc"
        && request.action == "enable_start"
        && hex(&request.operation_id, 32)
        && request.revision < SAFE
        && binding.owner_uid < SAFE
        && binding.unit == "openwiz.service"
        && binding_path(&binding.root)
        && binding_path(&binding.state_root)
        && repository_ok
        && project_ok
        && runtime_ok
        && hex(&binding.config_sha256, 64)
        && hex(&binding.unit_sha256, 64)
        && [
            binding.app_id,
            binding.installation_id,
            binding.service_issue,
        ]
        .iter()
        .all(|n| (1..SAFE).contains(n))
        && operation.operation_id == request.operation_id
        && operation.kind == "activate_engine"
        && hex(&operation.fingerprint, 64)
        && operation.effects == [EFFECTS]
        && operation.reason == REASON
        && (1..SAFE).contains(&journal.created_at)
        && (journal.created_at..SAFE).contains(&journal.updated_at)
        && between(journal.started_at)
        && between(journal.record_at)
        && ["pending", "unsent", "uncertain", "confirmed"].contains(&journal.record_state.as_str())
        && ["proposed", "held", "applied"].contains(&journal.outcome.as_str())
        && ["proposed", "applied", "refused", "uncertain"].contains(&operation.phase.as_str())
        && (!["uncertain", "applied"].contains(&operation.phase.as_str())
            || journal.started_at.is_some())
        && (journal.outcome != "applied"
            || (operation.phase == "applied" && journal.record_state == "confirmed"))
        && (journal.record_state == "pending" || operation.phase == "applied")
        && (["pending", "unsent"].contains(&journal.record_state.as_str())
            || journal.record_at.is_some());
    if !shaped {
        return refuse("the PC activation record is malformed");
    }
    let Ok(canonical) = serde_json::to_value(binding) else {
        return refuse("the PC activation record is malformed");
    };
    let hash = sha256_hex(
        serde_json::json!({"kind":"activate_engine","request":{"binding":canonical,"revision":request.revision}})
            .to_string()
            .as_bytes(),
    );
    if request.request_hash != hash || operation.fingerprint != hash {
        return refuse("the PC activation record is malformed");
    }
    if journal.outcome != "applied" {
        return refuse("the PC activation is not applied with a confirmed record");
    }

    // The actual service config, strictly read, and the exact installation.
    let Some(config_bytes) = read(&state.join("service/config.json"), 1024 * 1024) else {
        return refuse("the service config is unreadable");
    };
    let Ok(config) = std::str::from_utf8(&config_bytes)
        .map_err(|_| String::new())
        .and_then(|text| crate::document::read(crate::document::Document::Config, text))
    else {
        return refuse("the service config is invalid");
    };
    let configured = (
        format!(
            "{}/{}",
            config["repository"]["owner"].as_str().unwrap_or(""),
            config["repository"]["name"].as_str().unwrap_or("")
        ),
        config["project"].as_str().unwrap_or(""),
        config["github_app"]["app_id"].as_u64(),
        config["github_app"]["installation_id"].as_u64(),
        config["service_issue"].as_u64(),
    );
    let root = Path::new(&binding.root);
    let selected = plain(root)
        && private(root, true)
        && fs::symlink_metadata(root.join("current"))
            .is_ok_and(|m| m.file_type().is_symlink() && m.uid() == owner)
        && fs::read_link(root.join("current")).is_ok_and(|target| target == build);
    let bound = binding.owner_uid == u64::from(owner)
        && Path::new(&binding.state_root) == state
        && binding.build == manifest.source
        && binding.runtime == format!("{} {}", manifest.version, manifest.source)
        && binding.config_sha256 == sha256_hex(&config_bytes)
        && configured
            == (
                binding.repository.clone(),
                binding.project.as_str(),
                Some(binding.app_id),
                Some(binding.installation_id),
                Some(binding.service_issue),
            )
        && selected;
    if !bound {
        return refuse("the PC activation record does not bind this installation");
    }
    eprintln!("openwiz-service: installed handover verified; login: unknown");
    Ok(())
}
