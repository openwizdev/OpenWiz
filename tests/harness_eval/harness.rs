use std::fs;
use std::io::Write;
use std::path::{Component, Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::Duration;

use serde_json::Value;

pub const CORRECTION_CAP: u32 = 3;
pub const TOOL_OUTPUT_MAX_BYTES: usize = 8 * 1024;
pub const CONTEXT_FILE_MAX_BYTES: usize = 2 * 1024;
pub const HANDOFF_MAX_BYTES: usize = 400;
pub const SAME_FAILURE_STALL: u32 = 2;
pub const SAFETY_TURNS: u32 = 10_000;

#[derive(Clone, Debug)]
pub struct Config {
    pub check: bool,
    pub max_reds: u32,
    pub stall_same_evidence: bool,
    pub tool_output_max_bytes: Option<usize>,
    pub compact_at_bytes: Option<usize>,
    pub compact_tail: usize,
    pub just_in_time_context: bool,
    pub preload_all: bool,
    pub context_file_max_bytes: Option<usize>,
    pub condense_handoff: bool,
    pub handoff_max_bytes: usize,
    pub max_identical_tool_failures: Option<u32>,
    pub max_turns: Option<u32>,
    pub hooks: Vec<Hook>,
    pub blast_radius: bool,
    pub learn: bool,
    pub measurement_ceiling: Option<u32>,
}

pub fn baseline() -> Config {
    Config {
        check: false,
        max_reds: CORRECTION_CAP,
        stall_same_evidence: false,
        tool_output_max_bytes: None,
        compact_at_bytes: None,
        compact_tail: 4,
        just_in_time_context: false,
        preload_all: false,
        context_file_max_bytes: None,
        condense_handoff: false,
        handoff_max_bytes: usize::MAX,
        max_identical_tool_failures: None,
        max_turns: None,
        hooks: vec![],
        blast_radius: false,
        learn: false,
        measurement_ceiling: None,
    }
}

pub fn gated() -> Config {
    Config {
        check: true,
        max_reds: CORRECTION_CAP,
        stall_same_evidence: true,
        tool_output_max_bytes: Some(TOOL_OUTPUT_MAX_BYTES),
        compact_at_bytes: Some(16 * 1024),
        compact_tail: 4,
        just_in_time_context: true,
        preload_all: false,
        context_file_max_bytes: Some(CONTEXT_FILE_MAX_BYTES),
        condense_handoff: true,
        handoff_max_bytes: HANDOFF_MAX_BYTES,
        max_identical_tool_failures: Some(SAME_FAILURE_STALL),
        max_turns: Some(32),
        hooks: vec![],
        blast_radius: true,
        learn: true,
        measurement_ceiling: None,
    }
}

pub fn preloaded() -> Config {
    let mut config = baseline();
    config.preload_all = true;
    config
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum HookEvent {
    PreTool,
    PostTool,
    Stop,
}

#[derive(Clone, Debug)]
pub struct Hook {
    pub event: HookEvent,
    pub program: String,
    pub args: Vec<String>,
}

#[derive(Clone, Debug)]
pub struct Unit {
    pub id: String,
    pub scope: String,
}

#[derive(Clone, Debug)]
pub struct Scenario {
    pub instruction: String,
    pub units: Vec<Unit>,
    pub check: Vec<String>,
    pub workspace: PathBuf,
    pub constraints_file: PathBuf,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Brief {
    pub instruction: String,
    pub constraints: Vec<String>,
    pub context: String,
    pub corrections: Vec<String>,
    pub observations: Vec<String>,
}

pub fn brief_bytes(brief: &Brief) -> usize {
    brief.instruction.len()
        + brief.constraints.iter().map(String::len).sum::<usize>()
        + brief.context.len()
        + brief.corrections.iter().map(String::len).sum::<usize>()
        + brief.observations.iter().map(String::len).sum::<usize>()
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Reply {
    pub text: String,
    pub calls: Vec<Call>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Call {
    pub op: String,
    pub input: String,
}

pub trait Model {
    fn complete(&mut self, brief: &Brief) -> Reply;
}

impl<F> Model for F
where
    F: FnMut(&Brief) -> Reply,
{
    fn complete(&mut self, brief: &Brief) -> Reply {
        self(brief)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Stop {
    Green,
    Escalated,
    Stall,
    Budget,
    ClosedLane,
    Ceiling,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Outcome {
    pub stop: Stop,
    pub turns: u32,
    pub checks: u32,
    pub reds: u32,
    pub corrections_sent: u32,
    pub correction_bytes: usize,
    pub correction_text: String,
    pub tool_calls: u32,
    pub tool_calls_blocked: u32,
    pub raw_tool_bytes: usize,
    pub kept_tool_bytes: usize,
    pub truncated: u32,
    pub compactions: u32,
    pub context_files: u32,
    pub context_file_bytes: usize,
    pub final_brief_bytes: usize,
    pub peak_brief_bytes: usize,
    pub constraints_seen: Vec<String>,
    pub constraints_written: Vec<String>,
    pub hard_applied: u32,
    pub hard_refused: u32,
    pub contained_applied: u32,
    pub handoff_bytes: usize,
    pub handoff_text: String,
    pub wall: Duration,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Radius {
    Contained,
    Wide,
    Hard,
}

#[derive(Clone, Debug)]
enum Op {
    Write { path: String, body: String },
    Delete { path: String },
    Bash { argv: Vec<String> },
    Bad,
}

pub fn radius_of(op: &str, input: &str) -> Radius {
    match parse_op(op, input) {
        Op::Delete { .. } => Radius::Hard,
        Op::Write { path, .. } if closed_path(&path) => Radius::Hard,
        Op::Bash { argv } if argv.iter().any(|arg| arg == "rm" || closed_path(arg)) => Radius::Hard,
        Op::Write { path, .. } if wide_path(&path) => Radius::Wide,
        Op::Bash { argv } if argv.len() > 4 => Radius::Wide,
        _ => Radius::Contained,
    }
}

pub fn run(config: &Config, scenario: &Scenario, model: &mut dyn Model) -> Outcome {
    let started = std::time::Instant::now();
    let mut outcome = Outcome {
        stop: Stop::Ceiling,
        turns: 0,
        checks: 0,
        reds: 0,
        corrections_sent: 0,
        correction_bytes: 0,
        correction_text: String::new(),
        tool_calls: 0,
        tool_calls_blocked: 0,
        raw_tool_bytes: 0,
        kept_tool_bytes: 0,
        truncated: 0,
        compactions: 0,
        context_files: 0,
        context_file_bytes: 0,
        final_brief_bytes: 0,
        peak_brief_bytes: 0,
        constraints_seen: vec![],
        constraints_written: vec![],
        hard_applied: 0,
        hard_refused: 0,
        contained_applied: 0,
        handoff_bytes: 0,
        handoff_text: String::new(),
        wall: Duration::ZERO,
    };
    let mut constraints = if config.learn {
        read_lines(&scenario.constraints_file)
    } else {
        vec![]
    };
    let mut loaded = Vec::new();
    let mut context = String::new();
    if config.preload_all {
        preload_all(
            &scenario.workspace,
            &mut loaded,
            &mut context,
            config,
            &mut outcome,
        );
    }
    let mut corrections = Vec::new();
    let mut observations = Vec::new();
    let mut previous_evidence: Option<String> = None;
    let mut fail_key: Option<String> = None;
    let mut fail_streak = 0u32;

    loop {
        if outcome.turns >= SAFETY_TURNS {
            outcome.stop = Stop::Ceiling;
            break;
        }
        if config.max_turns.is_some_and(|max| outcome.turns >= max) {
            outcome.stop = Stop::Budget;
            break;
        }
        if config
            .measurement_ceiling
            .is_some_and(|max| outcome.turns >= max)
        {
            outcome.stop = Stop::Ceiling;
            break;
        }
        compact(&mut observations, config, &mut outcome);
        let brief = Brief {
            instruction: scenario.instruction.clone(),
            constraints: constraints.clone(),
            context: context.clone(),
            corrections: corrections.clone(),
            observations: observations.clone(),
        };
        let bytes = brief_bytes(&brief);
        outcome.final_brief_bytes = bytes;
        outcome.peak_brief_bytes = outcome.peak_brief_bytes.max(bytes);
        if outcome.turns == 0 {
            outcome.constraints_seen = constraints.clone();
        }
        let reply = model.complete(&brief);
        outcome.turns += 1;

        if reply.calls.is_empty() {
            if !config.check {
                outcome.stop = Stop::Green;
                break;
            }
            match gate(
                config,
                scenario,
                &mut outcome,
                &mut corrections,
                &mut constraints,
                &mut previous_evidence,
            ) {
                Gate::Stop => break,
                Gate::Again => continue,
            }
        }

        let mut closed = false;
        for call in &reply.calls {
            if config.just_in_time_context
                && let Some(dir) = mentioned_dir(&call.input)
            {
                attach_chain(
                    &scenario.workspace,
                    &dir,
                    &mut loaded,
                    &mut context,
                    config,
                    &mut outcome,
                );
            }
            match step_tool(
                config,
                scenario,
                call,
                &mut observations,
                &mut outcome,
                &mut fail_key,
                &mut fail_streak,
            ) {
                ToolStep::Closed => {
                    closed = true;
                    break;
                }
                ToolStep::Stalled => {
                    closed = true;
                    break;
                }
                ToolStep::Done => {}
            }
        }
        if closed {
            break;
        }
    }
    let handoff = handoff_text(
        config,
        scenario,
        &outcome,
        &context,
        &corrections,
        &observations,
    );
    outcome.handoff_bytes = handoff.len();
    outcome.handoff_text = handoff;
    outcome.wall = started.elapsed();
    outcome
}

enum Gate {
    Stop,
    Again,
}

fn gate(
    config: &Config,
    scenario: &Scenario,
    outcome: &mut Outcome,
    corrections: &mut Vec<String>,
    constraints: &mut Vec<String>,
    previous_evidence: &mut Option<String>,
) -> Gate {
    let hook = run_hooks(
        config,
        &scenario.workspace,
        HookEvent::Stop,
        &format!(
            "{{\"event\":\"Stop\",\"stop_hook_active\":{}}}",
            if outcome.reds > 0 { "true" } else { "false" }
        ),
    );
    let check = run_argv(&scenario.check, &scenario.workspace);
    outcome.checks += 1;
    let program_ok = check.ok;
    if program_ok && hook.block.is_none() {
        if config.learn {
            let fresh = learn_from(&check.stdout, constraints, &scenario.constraints_file);
            outcome.constraints_written.extend(fresh);
        }
        outcome.stop = Stop::Green;
        return Gate::Stop;
    }

    let failures = if !program_ok {
        parse_failures(&check.stdout, &check.stderr, scenario)
    } else {
        vec![Failure {
            id: first_id(scenario),
            reason: hook
                .block
                .clone()
                .unwrap_or_else(|| "stop hook blocked".to_owned()),
            evidence: "hook:1".to_owned(),
            scope: first_scope(scenario),
        }]
    };
    let evidence_key = failures
        .iter()
        .map(|failure| failure.evidence.as_str())
        .collect::<Vec<_>>()
        .join("\n");
    let text = failures
        .iter()
        .map(Failure::render)
        .collect::<Vec<_>>()
        .join("\n");
    outcome.correction_text = text.clone();
    outcome.reds += 1;
    if config.stall_same_evidence && previous_evidence.as_deref() == Some(evidence_key.as_str()) {
        outcome.stop = Stop::Stall;
        return Gate::Stop;
    }
    if outcome.reds >= config.max_reds {
        outcome.stop = Stop::Escalated;
        return Gate::Stop;
    }
    *previous_evidence = Some(evidence_key);
    outcome.corrections_sent += 1;
    outcome.correction_bytes += text.len();
    corrections.push(text);
    Gate::Again
}

enum ToolStep {
    Done,
    Closed,
    Stalled,
}

fn step_tool(
    config: &Config,
    scenario: &Scenario,
    call: &Call,
    observations: &mut Vec<String>,
    outcome: &mut Outcome,
    fail_key: &mut Option<String>,
    fail_streak: &mut u32,
) -> ToolStep {
    let radius = radius_of(&call.op, &call.input);
    if config.blast_radius && radius == Radius::Hard {
        outcome.hard_refused += 1;
        outcome.stop = Stop::ClosedLane;
        observations.push(format!(
            "blocked: hard to reverse, not applied ({})",
            call.op
        ));
        return ToolStep::Closed;
    }
    let pre = run_hooks(
        config,
        &scenario.workspace,
        HookEvent::PreTool,
        &hook_payload("PreToolUse", &call.op, &call.input),
    );
    if let Some(reason) = pre.block {
        outcome.tool_calls_blocked += 1;
        observations.push(format!("blocked: {reason}"));
        return ToolStep::Done;
    }

    let ran = execute(&scenario.workspace, &call.op, &call.input);
    match radius {
        Radius::Hard => outcome.hard_applied += 1,
        Radius::Contained | Radius::Wide => outcome.contained_applied += 1,
    }
    outcome.tool_calls += 1;
    outcome.raw_tool_bytes += ran.raw.len();
    let (mut kept, truncated) = clip(&ran.raw, config.tool_output_max_bytes);
    if truncated {
        outcome.truncated += 1;
    }
    outcome.kept_tool_bytes += kept.len();
    let post = run_hooks(
        config,
        &scenario.workspace,
        HookEvent::PostTool,
        &hook_payload("PostToolUse", &call.op, &call.input),
    );
    if let Some(reason) = post.block {
        kept.push('\n');
        kept.push_str(&reason);
    }
    let failed = !ran.ok;
    observations.push(kept);
    if failed {
        let key = format!("{}:{}", call.op, call.input);
        if fail_key.as_deref() == Some(key.as_str()) {
            *fail_streak += 1;
        } else {
            *fail_key = Some(key);
            *fail_streak = 1;
        }
        if config
            .max_identical_tool_failures
            .is_some_and(|max| *fail_streak >= max)
        {
            outcome.stop = Stop::Stall;
            return ToolStep::Stalled;
        }
    } else {
        *fail_key = None;
        *fail_streak = 0;
    }
    ToolStep::Done
}

struct Ran {
    ok: bool,
    raw: String,
}

fn execute(workspace: &Path, op: &str, input: &str) -> Ran {
    match parse_op(op, input) {
        Op::Write { path, body } => match place(workspace, &path) {
            Some(full) => match write_file(&full, &body) {
                Ok(()) => Ran {
                    ok: true,
                    raw: format!("wrote {path}"),
                },
                Err(err) => Ran {
                    ok: false,
                    raw: format!("write failed: {err}"),
                },
            },
            None => Ran {
                ok: false,
                raw: format!("write refused: {path}"),
            },
        },
        Op::Delete { path } => match place(workspace, &path) {
            Some(full) => match fs::remove_file(&full) {
                Ok(()) => Ran {
                    ok: true,
                    raw: format!("deleted {path}"),
                },
                Err(err) => Ran {
                    ok: false,
                    raw: format!("delete failed: {err}"),
                },
            },
            None => Ran {
                ok: false,
                raw: format!("delete refused: {path}"),
            },
        },
        Op::Bash { argv } => {
            if argv.is_empty() {
                return Ran {
                    ok: false,
                    raw: "bash refused: empty argv".to_owned(),
                };
            }
            let mut command = Command::new(&argv[0]);
            command
                .args(&argv[1..])
                .current_dir(workspace)
                .stdin(Stdio::null())
                .stdout(Stdio::piped())
                .stderr(Stdio::piped());
            match command.output() {
                Ok(out) => {
                    let mut raw = String::from_utf8_lossy(&out.stdout).into_owned();
                    if !out.stderr.is_empty() {
                        if !raw.is_empty() && !raw.ends_with('\n') {
                            raw.push('\n');
                        }
                        raw.push_str(&String::from_utf8_lossy(&out.stderr));
                    }
                    Ran {
                        ok: out.status.success(),
                        raw,
                    }
                }
                Err(err) => Ran {
                    ok: false,
                    raw: format!("bash failed: {err}"),
                },
            }
        }
        Op::Bad => Ran {
            ok: false,
            raw: "tool input is not a known operation".to_owned(),
        },
    }
}

fn parse_op(op: &str, input: &str) -> Op {
    let Ok(value) = serde_json::from_str::<Value>(input) else {
        return Op::Bad;
    };
    match op {
        "write" => {
            let Some(path) = value.get("path").and_then(Value::as_str) else {
                return Op::Bad;
            };
            let body = value.get("body").and_then(Value::as_str).unwrap_or("");
            Op::Write {
                path: path.to_owned(),
                body: body.to_owned(),
            }
        }
        "delete" => {
            let Some(path) = value.get("path").and_then(Value::as_str) else {
                return Op::Bad;
            };
            Op::Delete {
                path: path.to_owned(),
            }
        }
        "bash" => {
            let Some(argv) = value.get("argv").and_then(Value::as_array) else {
                return Op::Bad;
            };
            let args = argv
                .iter()
                .filter_map(Value::as_str)
                .map(str::to_owned)
                .collect::<Vec<_>>();
            if args.len() != argv.len() {
                return Op::Bad;
            }
            Op::Bash { argv: args }
        }
        _ => Op::Bad,
    }
}

fn closed_path(path: &str) -> bool {
    Path::new(path)
        .components()
        .any(|part| matches!(part, Component::Normal(name) if name == "migrations"))
}

fn wide_path(path: &str) -> bool {
    Path::new(path)
        .components()
        .any(|part| matches!(part, Component::Normal(name) if name == "shared"))
}

fn safe_rel(path: &str) -> bool {
    let path = Path::new(path);
    !path.is_absolute()
        && path
            .components()
            .all(|part| matches!(part, Component::Normal(_)))
}

fn place(workspace: &Path, rel: &str) -> Option<PathBuf> {
    if !safe_rel(rel) {
        return None;
    }
    let full = workspace.join(rel);
    let parent = full.parent()?.to_path_buf();
    fs::create_dir_all(&parent).ok()?;
    let root = workspace.canonicalize().ok()?;
    let parent = parent.canonicalize().ok()?;
    if parent.starts_with(&root) {
        Some(full)
    } else {
        None
    }
}

fn write_file(path: &Path, body: &str) -> std::io::Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let mut file = fs::File::create(path)?;
    file.write_all(body.as_bytes())
}

fn clip(text: &str, cap: Option<usize>) -> (String, bool) {
    let Some(cap) = cap else {
        return (text.to_owned(), false);
    };
    if text.len() <= cap {
        return (text.to_owned(), false);
    }
    let mut end = cap;
    while end > 0 && !text.is_char_boundary(end) {
        end -= 1;
    }
    let dropped = text.len() - end;
    let mut kept = text[..end].to_owned();
    kept.push_str(&format!("\n[truncated {dropped} bytes]"));
    (kept, true)
}

struct HookRun {
    block: Option<String>,
}

fn run_hooks(config: &Config, workspace: &Path, event: HookEvent, payload: &str) -> HookRun {
    let mut block = None;
    for hook in config.hooks.iter().filter(|hook| hook.event == event) {
        let mut command = Command::new(&hook.program);
        command
            .args(&hook.args)
            .current_dir(workspace)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        let Ok(mut child) = command.spawn() else {
            continue;
        };
        if let Some(mut stdin) = child.stdin.take() {
            let _ = stdin.write_all(payload.as_bytes());
        }
        let Ok(out) = child.wait_with_output() else {
            continue;
        };
        if out.status.code() == Some(2) {
            let reason = String::from_utf8_lossy(&out.stderr).trim().to_owned();
            block = Some(if reason.is_empty() {
                "hook exited 2".to_owned()
            } else {
                reason
            });
        }
    }
    HookRun { block }
}

fn hook_payload(event: &str, tool: &str, input: &str) -> String {
    serde_json::json!({"event": event, "tool": tool, "input": input}).to_string()
}

struct Program {
    ok: bool,
    stdout: String,
    stderr: String,
}

fn run_argv(argv: &[String], workspace: &Path) -> Program {
    if argv.is_empty() {
        return Program {
            ok: false,
            stdout: String::new(),
            stderr: "check could not run".to_owned(),
        };
    }
    match Command::new(&argv[0])
        .args(&argv[1..])
        .current_dir(workspace)
        .stdin(Stdio::null())
        .output()
    {
        Ok(out) => Program {
            ok: out.status.success(),
            stdout: String::from_utf8_lossy(&out.stdout).into_owned(),
            stderr: String::from_utf8_lossy(&out.stderr).into_owned(),
        },
        Err(err) => Program {
            ok: false,
            stdout: String::new(),
            stderr: format!("check could not run: {err}"),
        },
    }
}

struct Failure {
    id: String,
    reason: String,
    evidence: String,
    scope: String,
}

impl Failure {
    fn render(&self) -> String {
        format!(
            "UNIT: {}\nVERDICT: red\nREASON: {}\nEVIDENCE: {}\nSCOPE: {}",
            self.id, self.reason, self.evidence, self.scope
        )
    }
}

fn parse_failures(stdout: &str, stderr: &str, scenario: &Scenario) -> Vec<Failure> {
    let mut found = Vec::new();
    for line in stdout.lines() {
        let mut parts = line.split('\t');
        let Some(id) = parts.next() else { continue };
        let Some(reason) = parts.next() else { continue };
        let Some(evidence) = parts.next() else {
            continue;
        };
        if id.is_empty() || reason.is_empty() || evidence.is_empty() || parts.next().is_some() {
            continue;
        }
        if id.starts_with("CONSTRAINT:") {
            continue;
        }
        let scope = scenario
            .units
            .iter()
            .find(|unit| unit.id == id)
            .map(|unit| unit.scope.clone())
            .unwrap_or_else(|| format!("fix {id} only"));
        found.push(Failure {
            id: id.to_owned(),
            reason: reason.to_owned(),
            evidence: evidence.to_owned(),
            scope,
        });
    }
    if found.is_empty() {
        let reason = stdout
            .lines()
            .chain(stderr.lines())
            .find(|line| !line.trim().is_empty())
            .unwrap_or("check failed")
            .trim()
            .to_owned();
        found.push(Failure {
            id: first_id(scenario),
            reason,
            evidence: "check:1".to_owned(),
            scope: first_scope(scenario),
        });
    }
    found
}

fn first_id(scenario: &Scenario) -> String {
    scenario
        .units
        .first()
        .map(|unit| unit.id.clone())
        .unwrap_or_else(|| "task".to_owned())
}

fn first_scope(scenario: &Scenario) -> String {
    scenario
        .units
        .first()
        .map(|unit| unit.scope.clone())
        .unwrap_or_else(|| "fix this unit only".to_owned())
}

fn learn_from(stdout: &str, constraints: &mut Vec<String>, path: &Path) -> Vec<String> {
    let mut fresh = Vec::new();
    for line in stdout.lines() {
        let Some(rest) = line.strip_prefix("CONSTRAINT:") else {
            continue;
        };
        let text = rest.trim();
        if text.is_empty() || constraints.iter().any(|have| have == text) {
            continue;
        }
        constraints.push(text.to_owned());
        fresh.push(text.to_owned());
    }
    if !fresh.is_empty() {
        let _ = fs::write(path, constraints.join("\n") + "\n");
    }
    fresh
}

fn read_lines(path: &Path) -> Vec<String> {
    fs::read_to_string(path)
        .unwrap_or_default()
        .lines()
        .map(str::trim)
        .filter(|line| !line.is_empty())
        .map(str::to_owned)
        .collect()
}

fn compact(observations: &mut Vec<String>, config: &Config, outcome: &mut Outcome) {
    let Some(at) = config.compact_at_bytes else {
        return;
    };
    let tail = config.compact_tail.max(1);
    let before = observations.len();
    let mut dropped_bytes = 0usize;
    while observations.len() > tail && observations.iter().map(String::len).sum::<usize>() > at {
        dropped_bytes += observations.remove(0).len();
    }
    if observations.len() < before {
        observations.insert(
            0,
            format!(
                "compacted {} earlier tool results ({dropped_bytes} bytes) into this note",
                before - observations.len()
            ),
        );
        outcome.compactions += 1;
    }
}

const JIT_NAMES: &[&str] = &["AGENTS.md", "CLAUDE.md"];
const PRELOAD_NAMES: &[&str] = &["AGENTS.md", "CLAUDE.md", "SKILL.md"];

fn attach_chain(
    workspace: &Path,
    rel: &Path,
    loaded: &mut Vec<PathBuf>,
    context: &mut String,
    config: &Config,
    outcome: &mut Outcome,
) {
    let mut chain = vec![rel.to_path_buf()];
    let mut cursor = rel.to_path_buf();
    while cursor.pop() {
        chain.push(cursor.clone());
    }
    if !chain.iter().any(|dir| dir.as_os_str().is_empty()) {
        chain.push(PathBuf::new());
    }
    for dir in chain {
        consider_dir(
            workspace,
            &workspace.join(dir),
            JIT_NAMES,
            loaded,
            context,
            config,
            outcome,
        );
    }
}

fn preload_all(
    workspace: &Path,
    loaded: &mut Vec<PathBuf>,
    context: &mut String,
    config: &Config,
    outcome: &mut Outcome,
) {
    let mut stack = vec![workspace.to_path_buf()];
    let mut walked = 0u32;
    while let Some(dir) = stack.pop() {
        walked += 1;
        if walked > 200 {
            break;
        }
        let Ok(read) = fs::read_dir(&dir) else {
            continue;
        };
        for entry in read.flatten() {
            let path = entry.path();
            let Ok(meta) = fs::symlink_metadata(&path) else {
                continue;
            };
            if meta.file_type().is_symlink() {
                continue;
            }
            if meta.is_dir() {
                stack.push(path);
            }
        }
        consider_dir(
            workspace,
            &dir,
            PRELOAD_NAMES,
            loaded,
            context,
            config,
            outcome,
        );
    }
}

fn consider_dir(
    workspace: &Path,
    dir: &Path,
    names: &[&str],
    loaded: &mut Vec<PathBuf>,
    context: &mut String,
    config: &Config,
    outcome: &mut Outcome,
) {
    let Ok(root) = workspace.canonicalize() else {
        return;
    };
    let Ok(dir) = dir.canonicalize() else {
        return;
    };
    if !dir.starts_with(&root) {
        return;
    }
    for name in names {
        let path = dir.join(name);
        if !path.is_file() {
            continue;
        }
        let Ok(canon) = path.canonicalize() else {
            continue;
        };
        if !canon.starts_with(&root) || loaded.contains(&canon) {
            continue;
        }
        let Ok(text) = fs::read_to_string(&path) else {
            continue;
        };
        let (kept, _) = clip(&text, config.context_file_max_bytes);
        loaded.push(canon);
        outcome.context_files += 1;
        outcome.context_file_bytes += kept.len();
        context.push_str(name);
        context.push('\n');
        context.push_str(&kept);
        context.push('\n');
    }
}

fn handoff_text(
    config: &Config,
    scenario: &Scenario,
    outcome: &Outcome,
    context: &str,
    corrections: &[String],
    observations: &[String],
) -> String {
    if !config.condense_handoff {
        let mut full = String::new();
        full.push_str(context);
        for item in observations.iter().chain(corrections.iter()) {
            full.push_str(item);
            full.push('\n');
        }
        return full;
    }
    let evidence = outcome
        .correction_text
        .lines()
        .find_map(|line| line.strip_prefix("EVIDENCE: "))
        .unwrap_or("none");
    let summary = observations
        .last()
        .map(|text| text.lines().next().unwrap_or(""))
        .unwrap_or("");
    let text = format!(
        "UNIT: {}\nVERDICT: {}\nEVIDENCE: {evidence}\nSUMMARY: {summary}\n",
        first_id(scenario),
        handoff_verdict(outcome.stop),
    );
    within_budget(&text, config.handoff_max_bytes)
}

fn handoff_verdict(stop: Stop) -> &'static str {
    match stop {
        Stop::Green => "green",
        Stop::Escalated | Stop::Stall => "red",
        Stop::ClosedLane => "closed",
        Stop::Budget | Stop::Ceiling => "stopped",
    }
}

fn within_budget(text: &str, cap: usize) -> String {
    if text.len() <= cap {
        return text.to_owned();
    }
    let marker = "\n[truncated]";
    let room = cap.saturating_sub(marker.len());
    let mut end = room.min(text.len());
    while end > 0 && !text.is_char_boundary(end) {
        end -= 1;
    }
    let mut kept = text[..end].to_owned();
    if kept.len() + marker.len() <= cap {
        kept.push_str(marker);
    }
    kept
}

fn mentioned_dir(input: &str) -> Option<PathBuf> {
    let value = serde_json::from_str::<Value>(input).ok()?;
    let path = value.get("path")?.as_str()?;
    if !safe_rel(path) {
        return None;
    }
    Some(Path::new(path).parent()?.to_path_buf())
}
