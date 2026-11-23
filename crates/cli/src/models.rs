use std::fs::File;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};

use openwiz_adapter_cloudroom::allowlist::{Invocation, SpawnArgs};
use openwiz_core::limits::READ_TIMEOUT;
use openwiz_core::models::write::{Asked, RowOutcome, set};
use openwiz_core::models::{
    Choice, FLEET_FILE, Family, Form, From, Pick, Role, RoleRead, SNAPSHOT_FILE, Show, SpawnFlags,
    read,
};
use openwiz_core::new_thread::operation::NewThreadClient;
use openwiz_core::new_thread::options::{
    CloudOptions, J255_CLAUDE_MODEL, J255_CODEX_MODEL, J255_EFFORT, OptionsSource, OptionsState,
    cloud_options, local_options,
};
use openwiz_core::ops::Clock;
use rustix::fd::{AsFd, OwnedFd};
use rustix::fs::{Access, AtFlags, CWD, FileType, Gid, Mode, OFlags, Uid, XattrFlags};
use rustix::io::Errno;
use serde_json::{Value, json};

use crate::{EXIT_OK, EXIT_READ_FAILED, EXIT_USAGE, clean, help, utc};

pub const EXIT_NO_OPTIONS: i32 = 13;
pub const EXIT_REFUSED: i32 = 5;

pub fn run_models(
    args: &[String],
    client: &dyn NewThreadClient,
    clock: &dyn Clock,
    stdout: &mut dyn Write,
    stderr: &mut dyn Write,
) -> i32 {
    run_models_in(args, Path::new("."), client, clock, stdout, stderr)
}

pub fn run_models_in(
    args: &[String],
    root: &Path,
    client: &dyn NewThreadClient,
    clock: &dyn Clock,
    stdout: &mut dyn Write,
    stderr: &mut dyn Write,
) -> i32 {
    let lister: Option<AclLister> = if std::env::consts::OS == "macos" {
        Some(&macos_ls)
    } else {
        None
    };
    run_models_listing_acls(args, root, client, clock, lister, stdout, stderr)
}

pub fn run_models_listing_acls(
    args: &[String],
    root: &Path,
    client: &dyn NewThreadClient,
    clock: &dyn Clock,
    lister: Option<AclLister>,
    stdout: &mut dyn Write,
    stderr: &mut dyn Write,
) -> i32 {
    if matches!(
        args.first().map(String::as_str),
        Some("show" | "list" | "set")
    ) {
        let acl = lister.map(|lister| AclCheck {
            lister,
            dir: root.join("docs/agents"),
        });
        return run_form(args, root, client, clock, acl, stdout, stderr);
    }
    let (mut json, mut host) = (false, None);
    let mut args_iter = args.iter().map(String::as_str);
    while let Some(arg) = args_iter.next() {
        match arg {
            "--help" | "-h" => {
                let _ = stdout.write_all(
                    crate::response::help(
                        crate::response::Request::for_command("models", args).json,
                        help(),
                    )
                    .as_bytes(),
                );
                return EXIT_OK;
            }
            "--json" => json = true,
            "--host" => {
                if let Err(why) = parse_host(&mut host, args_iter.next()) {
                    return usage(stderr, &why);
                }
            }
            other => {
                return usage(stderr, &format!("models has no option {}", clean(other)));
            }
        }
    }
    let options = read_options(client, clock, host);
    let printed = if json {
        let mut out = serde_json::to_string_pretty(&options)
            .unwrap_or_else(|e| format!("{{\"error\": \"{e}\"}}"));
        out.push('\n');
        out
    } else {
        render_options(&options)
    };
    let _ = stdout.write_all(printed.as_bytes());
    let _ = stdout.flush();
    match options.state {
        OptionsState::Offered => EXIT_OK,
        OptionsState::NoOptions { .. } => EXIT_NO_OPTIONS,
    }
}

fn usage(stderr: &mut dyn Write, why: &str) -> i32 {
    let _ = writeln!(
        stderr,
        "openwiz: {why}; nothing was read (see openwiz --help)"
    );
    EXIT_USAGE
}

fn valid_host(name: &str) -> bool {
    name.len() <= 40
        && name != "cloudroom"
        && name.split('-').all(|part| {
            !part.is_empty()
                && part
                    .bytes()
                    .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit())
        })
}

fn parse_host<'a>(host: &mut Option<&'a str>, value: Option<&'a str>) -> Result<(), String> {
    if host.is_some() {
        return Err("models takes --host once".to_owned());
    }
    *host = Some(value.filter(|name| valid_host(name)).ok_or_else(|| {
        "models --host needs cloud, local, boat or a valid driver name".to_owned()
    })?);
    Ok(())
}

fn saved_host() -> Option<String> {
    let dir = crate::state::default_state_dir(&|name| std::env::var_os(name)).ok()?;
    let saved: Value =
        serde_json::from_reader(File::open(dir.join("setup/state.json")).ok()?).ok()?;
    if saved["schema"] != "openwiz.setup-state.v1" {
        return None;
    }
    saved["project"]["host"]
        .as_str()
        .filter(|name| valid_host(name))
        .map(ToOwned::to_owned)
}

fn read_options(
    client: &dyn NewThreadClient,
    clock: &dyn Clock,
    host: Option<&str>,
) -> CloudOptions {
    let saved = if host.is_none() { saved_host() } else { None };
    if host
        .or(saved.as_deref())
        .is_some_and(|name| name != "cloud")
    {
        let path = std::env::var_os("PATH");
        let installed = |program: &str| {
            path.as_ref().is_some_and(|path| {
                std::env::split_paths(path).any(|dir| {
                    let candidate = dir.join(program);
                    candidate.is_file() && rustix::fs::access(&candidate, Access::EXEC_OK).is_ok()
                })
            })
        };
        return local_options(installed("claude"), installed("codex"), clock.now());
    }
    read_cloud_options(client, clock)
}

fn read_cloud_options(client: &dyn NewThreadClient, clock: &dyn Clock) -> CloudOptions {
    cloud_options(
        client.catalogue(clock.monotonic() + READ_TIMEOUT),
        client.cli_levels(),
        clock.now(),
    )
}

pub fn render_options(options: &CloudOptions) -> String {
    let mut out = format!(
        "openwiz models · read {} · {}\n",
        utc(options.read_at),
        clean(&options.label)
    );
    if let OptionsState::NoOptions { text, .. } = &options.state {
        out.push_str(&format!("no options: {}\n", clean(text)));
    }
    for harness in &options.harnesses {
        out.push_str(&format!(
            "{} (spawn provider {})\n",
            clean(&harness.harness),
            clean(&harness.provider)
        ));
        for model in &harness.models {
            out.push_str(&format!(
                "  {}: {}\n",
                clean(&model.model),
                clean(&model.efforts.join(", "))
            ));
        }
    }
    for harness in &options.unavailable {
        out.push_str(&format!(
            "{}: {}\n",
            clean(&harness.harness),
            clean(&harness.text)
        ));
    }
    out
}

enum Parsed {
    Help,
    Show,
    List {
        save: bool,
    },
    Set {
        role: Role,
        asked: Option<[String; 3]>,
    },
}

const SET_USAGE: &str = "models set takes <role> <provider> <model> <effort>, or \
                         <small-builder|fixer> follows-builder";

fn parse_form(args: &[String]) -> Result<(Parsed, bool, Option<&str>), String> {
    let form = args[0].as_str();
    let (mut json, mut save, mut words, mut host) = (false, false, Vec::new(), None);
    let mut args_iter = args[1..].iter().map(String::as_str);
    while let Some(arg) = args_iter.next() {
        match arg {
            "--help" | "-h" => return Ok((Parsed::Help, false, None)),
            "--host" if form != "list" => parse_host(&mut host, args_iter.next())?,
            "--json" if !json => json = true,
            "--save" if form == "list" && !save => save = true,
            "--json" | "--save" => return Err(format!("models {form} takes {arg} once")),
            other if other.starts_with('-') => {
                return Err(format!("models {form} has no option {}", clean(other)));
            }
            other => words.push(other),
        }
    }
    let parsed = match (form, &words[..]) {
        ("show", []) => Parsed::Show,
        ("list", []) => Parsed::List { save },
        ("show" | "list", _) => return Err(format!("models {form} takes no operands")),
        (_, [role, rest @ ..]) => {
            let role = Role::from_token(role).ok_or_else(|| {
                format!(
                    "models set has no role {}: orchestrator, builder, reviewer, \
                     small-builder or fixer",
                    clean(role)
                )
            })?;
            match rest {
                ["follows-builder"] if role.can_follow() => Parsed::Set { role, asked: None },
                [p, m, e] => Parsed::Set {
                    role,
                    asked: Some([p.to_string(), m.to_string(), e.to_string()]),
                },
                _ => return Err(SET_USAGE.to_owned()),
            }
        }
        _ => return Err(SET_USAGE.to_owned()),
    };
    Ok((parsed, json, host))
}

fn run_form(
    args: &[String],
    root: &Path,
    client: &dyn NewThreadClient,
    clock: &dyn Clock,
    acl: Option<AclCheck<'_>>,
    stdout: &mut dyn Write,
    stderr: &mut dyn Write,
) -> i32 {
    let (parsed, json, host) = match parse_form(args) {
        Ok(parsed) => parsed,
        Err(why) => return usage(stderr, &why),
    };
    let form = args[0].as_str();
    let fleet = || {
        std::fs::read_to_string(root.join(FLEET_FILE))
            .map_err(|e| format!("cannot read {FLEET_FILE}: {e}"))
    };
    let outcome = match parsed {
        Parsed::Help => {
            let text = crate::response::help(
                crate::response::Request::for_command("models", args).json,
                help(),
            );
            return emit(stdout, stderr, (EXIT_OK, text));
        }
        Parsed::Show => fleet().and_then(|text| read_fleet(&text)).map(|show| {
            let out = if json {
                document(&show)
            } else {
                show_text(&show)
            };
            (EXIT_OK, out)
        }),
        Parsed::List { save } => {
            let checkout = save.then(|| Checkout::open(root));
            let options = read_options(client, clock, None);
            let agents = checkout.map(|checkout| checkout.and_then(|c| Agents::open(&c, acl)));
            let text = match &agents {
                Some(agents) => agents.as_ref().ok().and_then(|a| a.read(FLEET_FILE).ok()),
                None => fleet().ok(),
            };
            let current = text.and_then(|text| read_fleet(&text).ok());
            let snapshot = snapshot(&options, current.as_ref());
            let offered = matches!(options.state, OptionsState::Offered);
            let saved = save && offered;
            let written = match agents {
                Some(agents) if saved => {
                    let text = document(&snapshot);
                    agents.and_then(|agents| put_all(&agents, &[(SNAPSHOT_FILE, &text)]))
                }
                _ => Ok(()),
            };
            written.map(|()| {
                let code = if offered { EXIT_OK } else { EXIT_NO_OPTIONS };
                let out = if json {
                    document(&json!({
                        "schema": "openwiz.models-list.v1",
                        "offered": snapshot,
                        "saved": if saved { json!(SNAPSHOT_FILE) } else { Value::Null },
                    }))
                } else {
                    format!(
                        "{}{}",
                        render_options(&options),
                        recommended_text(&snapshot)
                    )
                };
                (code, out)
            })
        }
        Parsed::Set { role, asked } => Checkout::open(root)
            .and_then(|checkout| Agents::open(&checkout, acl))
            .and_then(|agents| {
                agents.lock()?;
                let text = agents.read(FLEET_FILE)?;
                run_set(&text, role, asked, &agents, json, &|| {
                    read_options(client, clock, host)
                })
            }),
    };
    match outcome {
        Ok(printed) => emit(stdout, stderr, printed),
        Err(why) => {
            let _ = writeln!(stderr, "openwiz: models {form}: {}", clean(&why));
            EXIT_READ_FAILED
        }
    }
}

pub(crate) fn spawn_flags() -> Result<SpawnFlags, String> {
    let (provider, model, effort) = ("claude-code", "syn-models-flags", "medium");
    let request = format!("ow1-{}", "0".repeat(40));
    let args = SpawnArgs::new("syn-models", provider, model, effort, &request, "syn")
        .map_err(|_| "the allowlist refused the synthetic flags invocation".to_owned())?;
    let argv = Invocation::ThreadSpawn(args).argv();
    let word = |value: &str| {
        let at = argv.iter().position(|w| w == value).filter(|&at| at > 0);
        at.map(|at| argv[at - 1].clone())
            .ok_or_else(|| "the allowlist's spawn flags were not found".to_owned())
    };
    Ok(SpawnFlags {
        provider: word(provider)?,
        model: word(model)?,
        effort: word(effort)?,
    })
}

fn read_fleet(text: &str) -> Result<Show, String> {
    read(text, &spawn_flags()?)
}

fn run_set(
    text: &str,
    role: Role,
    asked: Option<[String; 3]>,
    agents: &Agents,
    json: bool,
    read_options: &dyn Fn() -> CloudOptions,
) -> Result<(i32, String), String> {
    let before = read_fleet(text)?.roles.get(role).clone();
    let (asked_doc, asked) = match &asked {
        None => (json!({"follows": "builder"}), None),
        Some([p, m, e]) => (
            json!({"provider": p, "model": m, "effort": e}),
            Some([p, m, e]),
        ),
    };
    let refused = |code: i32, outcome: &str, reason: &str, why: String, offered: Value| {
        let report = json!({
            "schema": "openwiz.models-set.v1", "outcome": outcome, "role": role,
            "asked": asked_doc, "before": before, "after": null,
            "models_table_added": false, "older_tables": [], "files": [], "warnings": [],
            "refusal": {"reason": reason, "text": why}, "offered": offered,
        });
        let out = if json {
            document(&report)
        } else {
            let mut out = format!("{}\n", clean(&why));
            if let Some(harnesses) = report["offered"].as_array() {
                out.push_str(&harness_lines(harnesses));
            }
            out
        };
        Ok((code, out))
    };
    let (chosen, options, unlisted) = match asked {
        None => (Asked::Follows, None, false),
        Some([p, m, e]) => {
            let options = read_options();
            if let OptionsState::NoOptions { text, .. } = &options.state {
                return refused(
                    EXIT_NO_OPTIONS,
                    "no_options",
                    "no_options",
                    text.clone(),
                    Value::Null,
                );
            }
            let offered = json!(offered_harnesses(&options));
            let listed = is_offered(&options, p, m, e);
            let installed = options.source == Some(OptionsSource::Local)
                && options
                    .harnesses
                    .iter()
                    .any(|harness| harness.provider == *p);
            if !listed && !installed {
                let why = format!("not offered: {p} {m} {e}; nothing was changed");
                return refused(EXIT_REFUSED, "refused", "not_offered", why, offered);
            }
            let Some(choice) = Choice::named(p, m, e) else {
                let why = format!(
                    "cannot be written to the Models table: {p} {m} {e}; nothing was changed"
                );
                return refused(EXIT_REFUSED, "refused", "not_writable", why, offered);
            };
            (Asked::Choice(choice), Some(options), !listed)
        }
    };
    let result = set(text, role, &chosen, &spawn_flags()?)?;
    if agents.read(FLEET_FILE).ok().as_deref() != Some(text) {
        return Err(format!(
            "{FLEET_FILE} changed while set ran, so nothing was written; run it again"
        ));
    }
    let offered = options.as_ref().map(|options| {
        let current = read_fleet(result.text.as_deref().unwrap_or(text)).ok();
        document(&snapshot(options, current.as_ref()))
    });
    let mut writes = Vec::new();
    if let Some(offered) = &offered {
        writes.push((SNAPSHOT_FILE, offered.as_str()));
    }
    if let Some(new) = &result.text {
        writes.push((FLEET_FILE, new.as_str()));
    }
    put_all(agents, &writes)?;
    let mut files: Vec<&str> = writes.iter().map(|(rel, _)| *rel).collect();
    files.reverse();
    let outcome = if result.text.is_some() {
        "changed"
    } else {
        "unchanged"
    };
    let mut report = json!({
        "schema": "openwiz.models-set.v1", "outcome": outcome, "role": role,
        "asked": asked_doc, "before": before, "after": result.after,
        "models_table_added": result.models_table_added, "older_tables": result.older_tables,
        "files": files, "warnings": result.warnings, "refusal": null, "offered": null,
    });
    if json {
        if unlisted {
            report["listed"] = json!(false);
        }
        return Ok((EXIT_OK, document(&report)));
    }
    let mut out = format!(
        "{}: {} -> {}\n",
        role.row(),
        role_text(&before),
        role_text(&result.after)
    );
    for row in result
        .older_tables
        .iter()
        .filter(|r| r.outcome != RowOutcome::Unchanged)
    {
        let word = if row.outcome == RowOutcome::Kept {
            "kept"
        } else {
            "changed"
        };
        out.push_str(&format!("{}: {word}\n", row.table));
    }
    for warning in &result.warnings {
        out.push_str(&format!("{}\n", warning.text()));
    }
    for file in files {
        out.push_str(&format!("wrote {file}\n"));
    }
    Ok((EXIT_OK, clean_lines(&out)))
}

fn offered_harnesses(options: &CloudOptions) -> Vec<Value> {
    options
        .harnesses
        .iter()
        .map(|h| json!({"harness": h.harness, "provider": h.provider, "models": h.models}))
        .collect()
}

fn is_offered(options: &CloudOptions, provider: &str, model: &str, effort: &str) -> bool {
    options.harnesses.iter().any(|h| {
        h.provider == provider
            && h.models
                .iter()
                .any(|m| m.model == model && m.efforts.iter().any(|e| e == effort))
    })
}

fn snapshot(options: &CloudOptions, current: Option<&Show>) -> Value {
    let recommend = |c: Option<Choice>, source: &str| {
        let offered = c
            .as_ref()
            .is_some_and(|c| is_offered(options, &c.provider, &c.model, &c.effort));
        json!({"choice": c, "source": source, "offered": offered})
    };
    let j255 = "OpenWiz's current choice (J255)";
    let orchestrator = match current {
        Some(show) if show.read == Form::ModelsTable => recommend(
            Some(show.roles.orchestrator.choice.clone()),
            "your current Orchestrator row",
        ),
        Some(show) => recommend(
            Some(show.roles.orchestrator.choice.clone()),
            "your current Builder table (the older tables have no Orchestrator row)",
        ),
        None => recommend(None, "no fleet.md read"),
    };
    json!({
        "schema": "openwiz.models-offered.v1",
        "read_at": options.read_at,
        "label": options.label,
        "state": options.state,
        "harnesses": offered_harnesses(options),
        "unavailable": options.unavailable,
        "recommended": {
            "orchestrator": orchestrator,
            "builder": recommend(Choice::named("claude-code", J255_CLAUDE_MODEL, J255_EFFORT), j255),
            "reviewer": recommend(Choice::named("codex", J255_CODEX_MODEL, J255_EFFORT), j255),
        },
    })
}

fn recommended_text(snapshot: &Value) -> String {
    let mut out = String::new();
    for (key, row) in [
        ("orchestrator", "Orchestrator"),
        ("builder", "Builder"),
        ("reviewer", "Reviewer"),
    ] {
        let rec = &snapshot["recommended"][key];
        let source = rec["source"].as_str().unwrap_or_default();
        let line = match &rec["choice"] {
            Value::Null => format!("recommended {row}: none ({source})"),
            c => {
                let shown = format!(
                    "{} {} on {} ({} {} {})",
                    c["names"]["model"].as_str().unwrap_or_default(),
                    c["names"]["effort"].as_str().unwrap_or_default(),
                    c["names"]["harness"].as_str().unwrap_or_default(),
                    c["provider"].as_str().unwrap_or_default(),
                    c["model"].as_str().unwrap_or_default(),
                    c["effort"].as_str().unwrap_or_default(),
                );
                if rec["offered"] == true {
                    format!("recommended {row}: {shown}, {source}")
                } else {
                    format!("recommended {row}: not offered now: {shown}")
                }
            }
        };
        out.push_str(&clean(&line));
        out.push('\n');
    }
    out
}

fn role_text(role: &RoleRead) -> String {
    match role.follows {
        Some(_) => format!("follows Builder: {}", role.choice.shown()),
        None => role.choice.shown(),
    }
}

fn pick_text(pick: &Pick) -> String {
    let from = match pick.from {
        From::Waits => return "waits".to_owned(),
        From::Reviewer => "Reviewer",
        From::Builder => "Builder",
        From::Fixer => "Fixer",
        From::OlderTable => "older table",
    };
    let shown = pick.choice.as_ref().map(Choice::shown).unwrap_or_default();
    format!("{from}: {shown}")
}

fn show_text(show: &Show) -> String {
    let mut out = String::new();
    for role in Role::ALL {
        out.push_str(&format!(
            "{}: {}\n",
            role.row(),
            role_text(show.roles.get(role))
        ));
    }
    for family in Family::BOTH {
        let f = family.shown();
        out.push_str(&format!(
            "Review of {f}-built work: {}\n",
            pick_text(show.reviews.get(family))
        ));
        out.push_str(&format!(
            "Fix round for a {f} builder: {}\n",
            pick_text(show.fixers.get(family))
        ));
    }
    for warning in &show.warnings {
        out.push_str(&format!("{}\n", warning.text()));
    }
    clean_lines(&out)
}

fn harness_lines(harnesses: &[Value]) -> String {
    let mut out = String::new();
    for h in harnesses {
        out.push_str(&format!(
            "{} (spawn provider {})\n",
            h["harness"].as_str().unwrap_or_default(),
            h["provider"].as_str().unwrap_or_default()
        ));
        for m in h["models"].as_array().into_iter().flatten() {
            let efforts: Vec<&str> = m["efforts"]
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(Value::as_str)
                .collect();
            out.push_str(&format!(
                "  {}: {}\n",
                m["model"].as_str().unwrap_or_default(),
                efforts.join(", ")
            ));
        }
    }
    clean_lines(&out)
}

fn clean_lines(text: &str) -> String {
    text.lines().map(|l| format!("{}\n", clean(l))).collect()
}

fn document(value: &impl serde::Serialize) -> String {
    let mut out =
        serde_json::to_string_pretty(value).unwrap_or_else(|e| format!("{{\"error\": \"{e}\"}}"));
    out.push('\n');
    out
}

struct Checkout(File);

impl Checkout {
    fn open(root: &Path) -> Result<Self, String> {
        let flags = OFlags::RDONLY | OFlags::DIRECTORY | OFlags::CLOEXEC;
        rustix::fs::openat(CWD, root, flags, Mode::empty())
            .map(|fd| Checkout(File::from(fd)))
            .map_err(|e| format!("cannot open the checkout: {e}; nothing was written"))
    }
}

struct Agents<'a>(File, Option<AclCheck<'a>>);

impl<'a> Agents<'a> {
    fn open(checkout: &Checkout, acl: Option<AclCheck<'a>>) -> Result<Self, String> {
        let flags = OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC;
        let refused = |dir: &str| {
            format!(
                "{dir} is not a directory of this checkout (missing or a link); nothing was written"
            )
        };
        let docs = rustix::fs::openat(&checkout.0, "docs", flags, Mode::empty())
            .map_err(|_| refused("docs"))?;
        rustix::fs::openat(&docs, "agents", flags, Mode::empty())
            .map(|fd| Agents(File::from(fd), acl))
            .map_err(|_| refused("docs/agents"))
    }

    fn read(&self, rel: &str) -> Result<String, String> {
        let flags = OFlags::RDONLY | OFlags::NOFOLLOW | OFlags::CLOEXEC;
        let mut text = String::new();
        rustix::fs::openat(&self.0, name(rel), flags, Mode::empty())
            .map_err(std::io::Error::from)
            .and_then(|fd| File::from(fd).read_to_string(&mut text))
            .map_err(|e| format!("cannot read {rel}: {e}"))?;
        Ok(text)
    }

    fn keep_acl(&self, rel: &str, fd: Option<&OwnedFd>) -> Result<(), String> {
        let (Some(check), Some(fd)) = (&self.1, fd) else {
            return Ok(());
        };
        let unchecked = |why: String| {
            format!(
                "cannot write {rel}: cannot check its macOS extended ACL ({why}); nothing was written"
            )
        };
        let path = check.dir.join(name(rel));
        let unmoved = || {
            let open = rustix::fs::fstat(fd).map_err(|e| unchecked(e.to_string()))?;
            let here = rustix::fs::lstat(&path).map_err(|e| unchecked(e.to_string()))?;
            match (open.st_dev, open.st_ino) == (here.st_dev, here.st_ino) {
                true => Ok(()),
                false => Err(unchecked("it moved while it was checked".to_owned())),
            }
        };
        unmoved()?;
        let listed = (check.lister)(&path).map_err(|e| unchecked(format!("cannot run ls: {e}")))?;
        unmoved()?;
        if !listed.status.success() {
            return Err(unchecked(format!("ls failed: {}", listed.status)));
        }
        if !listed.stderr.is_empty() {
            return Err(unchecked("ls warned while it listed the file".to_owned()));
        }
        match String::from_utf8(listed.stdout)
            .ok()
            .and_then(|l| extended_acl(&l))
        {
            Some(false) => Ok(()),
            Some(true) => Err(format!(
                "cannot write {rel}: it has a macOS extended ACL, which openwiz cannot keep; nothing was written"
            )),
            None => Err(unchecked("ls printed no listing openwiz reads".to_owned())),
        }
    }

    fn lock(&self) -> Result<(), String> {
        self.0
            .lock()
            .map_err(|e| format!("cannot lock docs/agents: {e}"))
    }
}

fn name(rel: &str) -> &str {
    rel.rsplit('/').next().unwrap_or(rel)
}

struct Staged<'r> {
    rel: &'r str,
    temporary: String,
    existing: Option<OwnedFd>,
}

fn put_all(agents: &Agents, files: &[(&str, &str)]) -> Result<(), String> {
    let mut staged = Vec::new();
    let mut result = Ok(());
    for &(rel, text) in files {
        match stage(agents, rel, text) {
            Ok(one) => staged.push(one),
            Err(e) => {
                result = Err(e);
                break;
            }
        }
    }
    let result = result
        .and_then(|()| staged.iter().try_for_each(|one| unchanged(agents, one)))
        .and_then(|()| {
            staged.iter().try_for_each(|one| {
                rustix::fs::renameat(&agents.0, &one.temporary, &agents.0, name(one.rel))
                    .map_err(|e| format!("cannot write {}: {e}", one.rel))
            })
        });
    if result.is_err() {
        for one in &staged {
            let _ = rustix::fs::unlinkat(&agents.0, &one.temporary, AtFlags::empty());
        }
    }
    result
}

fn unchanged(agents: &Agents, one: &Staged) -> Result<(), String> {
    let rel = one.rel;
    let changed =
        || format!("cannot write {rel}: it changed while openwiz wrote it; nothing was written");
    let here = rustix::fs::statat(&agents.0, name(rel), AtFlags::SYMLINK_NOFOLLOW);
    match (&one.existing, here) {
        (None, Err(Errno::NOENT)) => Ok(()),
        (Some(fd), Ok(here)) => {
            let open = rustix::fs::fstat(fd).map_err(|_| changed())?;
            if (open.st_dev, open.st_ino) != (here.st_dev, here.st_ino) {
                return Err(changed());
            }
            agents.keep_acl(rel, Some(fd))
        }
        _ => Err(changed()),
    }
}

fn stage<'r>(agents: &Agents, rel: &'r str, text: &str) -> Result<Staged<'r>, String> {
    static NEXT: AtomicU64 = AtomicU64::new(0);
    let fail = |e: std::io::Error| format!("cannot write {rel}: {e}");
    let dir = &agents.0;
    let target = name(rel);
    let read = OFlags::RDONLY | OFlags::NOFOLLOW | OFlags::NONBLOCK | OFlags::CLOEXEC;
    let existing = match rustix::fs::openat(dir, target, read, Mode::empty()) {
        Ok(fd) => Some(fd),
        Err(Errno::NOENT) => None,
        Err(Errno::LOOP) => return Err(format!("cannot write {rel}: it is not a regular file")),
        Err(e) => return Err(fail(e.into())),
    };
    if let Some(fd) = &existing {
        let st = rustix::fs::fstat(fd).map_err(|e| fail(e.into()))?;
        if FileType::from_raw_mode(st.st_mode) != FileType::RegularFile {
            return Err(format!("cannot write {rel}: it is not a regular file"));
        }
    }
    agents.keep_acl(rel, existing.as_ref())?;
    let n = NEXT.fetch_add(1, Ordering::Relaxed);
    let temporary = format!(".{target}.openwiz-{}-{n}", std::process::id());
    let create =
        OFlags::WRONLY | OFlags::CREATE | OFlags::EXCL | OFlags::NOFOLLOW | OFlags::CLOEXEC;
    let mode = match existing {
        Some(_) => Mode::RUSR | Mode::WUSR,
        None => Mode::RUSR | Mode::WUSR | Mode::RGRP | Mode::WGRP | Mode::ROTH | Mode::WOTH,
    };
    let fd = rustix::fs::openat(dir, &temporary, create, mode).map_err(|e| fail(e.into()))?;
    let written = match &existing {
        Some(target) => access_like(&fd, target),
        None => Ok(()),
    }
    .and_then(|()| {
        let mut file = File::from(fd);
        file.write_all(text.as_bytes())?;
        file.sync_all()
    });
    match written {
        Ok(()) => Ok(Staged {
            rel,
            temporary,
            existing,
        }),
        Err(e) => {
            let _ = rustix::fs::unlinkat(dir, &temporary, AtFlags::empty());
            Err(fail(e))
        }
    }
}

const ACCESS_ACL: &str = "system.posix_acl_access";
pub type AclLister<'a> = &'a dyn Fn(&Path) -> std::io::Result<std::process::Output>;

struct AclCheck<'a> {
    lister: AclLister<'a>,
    dir: PathBuf,
}

fn macos_ls(path: &Path) -> std::io::Result<std::process::Output> {
    std::process::Command::new("/bin/ls")
        .arg("-lde")
        .arg(path)
        .env_clear()
        .stdin(std::process::Stdio::null())
        .output()
}

fn access_like(staged: impl AsFd, target: impl AsFd) -> std::io::Result<()> {
    let want = rustix::fs::fstat(&target)?;
    let have = rustix::fs::fstat(&staged)?;
    if (want.st_uid, want.st_gid) != (have.st_uid, have.st_gid) {
        let owner = Uid::from_raw(want.st_uid);
        let group = Gid::from_raw(want.st_gid);
        rustix::fs::fchown(&staged, Some(owner), Some(group))?;
    }
    rustix::fs::fchmod(&staged, Mode::from_raw_mode(want.st_mode))?;
    match (access_acl(&target)?, access_acl(&staged)?) {
        (Some(acl), _) => rustix::fs::fsetxattr(&staged, ACCESS_ACL, &acl, XattrFlags::empty())?,
        (None, Some(_)) => rustix::fs::fremovexattr(&staged, ACCESS_ACL)?,
        (None, None) => {}
    }
    Ok(())
}

fn access_acl(fd: impl AsFd) -> std::io::Result<Option<Vec<u8>>> {
    let mut names = match rustix::fs::flistxattr_query(&fd) {
        Ok(size) => vec![0; size],
        Err(e) if e == Errno::NOTSUP || e == Errno::OPNOTSUPP => return Ok(None),
        Err(e) => return Err(e.into()),
    };
    let size = rustix::fs::flistxattr(&fd, &mut names[..])?;
    names.truncate(size);
    if !names.split(|b| *b == 0).any(|n| n == ACCESS_ACL.as_bytes()) {
        return Ok(None);
    }
    let mut acl = vec![0; rustix::fs::fgetxattr_query(&fd, ACCESS_ACL)?];
    let size = rustix::fs::fgetxattr(&fd, ACCESS_ACL, &mut acl[..])?;
    acl.truncate(size);
    Ok(Some(acl))
}

fn extended_acl(listing: &str) -> Option<bool> {
    let mut lines = listing.lines();
    let mode = lines.next()?.split(' ').next()?;
    if !mode.starts_with('-') || !(10..=11).contains(&mode.len()) {
        return None;
    }
    let mut entries = 0;
    for line in lines {
        let (at, _) = line.trim_start().split_once(": ")?;
        at.parse::<u32>().ok()?;
        entries += 1;
    }
    match (mode.ends_with('+'), entries) {
        (true, 0) => None,
        (_, n) => Some(n > 0),
    }
}

fn emit(stdout: &mut dyn Write, stderr: &mut dyn Write, (code, text): (i32, String)) -> i32 {
    match stdout
        .write_all(text.as_bytes())
        .and_then(|()| stdout.flush())
    {
        Ok(()) => code,
        Err(e) => {
            let _ = writeln!(stderr, "openwiz: models: cannot write the output: {e}");
            EXIT_READ_FAILED
        }
    }
}
