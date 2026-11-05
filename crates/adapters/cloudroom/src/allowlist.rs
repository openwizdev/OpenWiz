//! The only `room-cli` invocations OpenWiz may make. All of them are reads,
//! except two writes: `thread tell`, for `send` (OpenWiz 0.0.3,
//! ClosedWiz#8), and `thread spawn`, for `new` (OpenWiz 0.0.4, ClosedWiz#11,
//! sheet A-2, in exactly the shape spike run 3 recorded).
//!
//! **Attachments (B2, ClosedWiz#15, sheet B-7):** both writes may carry
//! `--file <path>` and `--image <path>`, and only with a staged absolute
//! path ([`StagedPath`](openwiz_core::attachment::StagedPath), a type nothing
//! else can build). One function,
//! [`attachment_args`], builds that tail for both, and nothing else here
//! spells either flag. The flags are observed in spike run 3's help
//! (repeatable, "an absolute path … from this CLI machine"); a call with
//! them never ran.
//!
//! **Archive (OpenWiz 0.0.6, B4, ClosedWiz#120):** `thread archive <id>
//! --json`, for finished agents ([`Invocation::ThreadArchive`]): spec #116's
//! "New writes: CloudRoom `thread archive`".
//!
//! Never `--work-status`, `--git-diff`, `thread log`, `thread queue`, or any
//! other mutating subcommand. Ticket 2's runner must start `room-cli` only
//! from an [`Invocation`] and its [`Invocation::argv`]. P8(a) checks the
//! sources for that as a tripwire; it is not a proof.

use openwiz_core::attachment::{Kind, StagedAttachment};
use openwiz_core::messaging::{Mode, validate_text};
use openwiz_core::prompt::attachment_allowance;

use crate::new_thread::{CLI_REASONING_LEVELS, HARNESS_PROVIDERS};

/// The PC's bundled CLI pattern, observed in #267's read-only PC check:
/// `/tmp/.mount_*/resources/app.asar.unpacked/node_modules/bb-app/host-daemon/dist/room-cli`.
pub const PC_BUNDLE_ROOT: &str = "/tmp";
pub const PC_BUNDLE_PREFIX: &str = ".mount_";
pub const PC_BUNDLE_CLI: &str =
    "resources/app.asar.unpacked/node_modules/bb-app/host-daemon/dist/room-cli";

/// The fixed bundled launcher on the Mac (CloudRoom's room-cli skill).
pub const MAC_BUNDLE_CLI: &str = "/Applications/Cloudroom.app/Contents/Resources/app.asar.unpacked/node_modules/bb-app/host-daemon/dist/room-cli";

/// #2201 (Jake J30; pinned in `contracts/public-cloudroom-setup.v1.md`):
/// setup's CloudRoom tool (`tools/install/cloudroom/cloudroom.py`) runs
/// exactly these two `room-cli` calls, from CloudRoom's fixed launcher under
/// the user's home directory (never `PATH`), and no other: the login read
/// and the sign-in link. The Rust adapter never runs them; the tool's own
/// test proves it can build nothing else.
pub const SETUP_LAUNCHER: &str = ".local/bin/room-cli";
pub const SETUP_CALLS: [&[&str]; 2] = [
    &["cloud", "status", "--json"],
    &["cloud", "sign-in", "--json"],
];

/// A session id that is safe to pass as one argument: it cannot be read as
/// a flag or split into several arguments.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct ThreadId(String);

/// The longest id accepted.
pub const THREAD_ID_MAX_LEN: usize = 128;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct InvalidThreadId(pub String);

impl ThreadId {
    /// Accepts 1 to [`THREAD_ID_MAX_LEN`] ASCII letters, digits, `_` and `-`,
    /// not starting with `-`.
    pub fn parse(id: &str) -> Result<Self, InvalidThreadId> {
        let valid = !id.is_empty()
            && id.len() <= THREAD_ID_MAX_LEN
            && !id.starts_with('-')
            && id
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-');
        if valid {
            Ok(Self(id.to_owned()))
        } else {
            Err(InvalidThreadId(id.to_owned()))
        }
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// Why a `thread spawn` could not be built: in OpenWiz's words, never the
/// value.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct InvalidSpawn(pub String);

/// The arguments of one `thread spawn`, each checked when it is built, so
/// an [`Invocation::ThreadSpawn`] can only carry safe ones:
/// - the project id: a [`ThreadId`]-shaped id;
/// - the provider: one of the verified `spawn --provider` ids
///   ([`HARNESS_PROVIDERS`]);
/// - the model: 1 to 128 printable ASCII characters, no space, not
///   starting with `-`;
/// - the effort: one of the levels `thread spawn --help` lists
///   ([`CLI_REASONING_LEVELS`]);
/// - the request id: `ow1-` and 40 lowercase hex digits, as OpenWiz derives
///   it;
/// - the prompt: `send`'s text rules (not empty or only whitespace, no NUL,
///   at most 16 KiB);
/// - the attachments (B2): staged attachments only, in the order passed
///   (the core's dispatch order), through [`attachment_args`].
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SpawnArgs {
    project: ThreadId,
    provider: String,
    model: String,
    effort: String,
    request_id: String,
    prompt: String,
    attachments: Vec<StagedAttachment>,
}

impl SpawnArgs {
    pub fn new(
        project_id: &str,
        provider: &str,
        model: &str,
        effort: &str,
        request_id: &str,
        prompt: &str,
    ) -> Result<Self, InvalidSpawn> {
        let refuse = |why: &str| Err(InvalidSpawn(why.to_owned()));
        let Ok(project) = ThreadId::parse(project_id) else {
            return refuse("the project id is not safe to pass as one argument");
        };
        if !HARNESS_PROVIDERS.iter().any(|(_, p)| *p == provider) {
            return refuse("the provider is not a verified spawn provider");
        }
        let model_ok = !model.is_empty()
            && model.len() <= MODEL_MAX_LEN
            && !model.starts_with('-')
            && model.bytes().all(|b| b.is_ascii_graphic());
        if !model_ok {
            return refuse("the model is not safe to pass as one argument");
        }
        if !CLI_REASONING_LEVELS.contains(&effort) {
            return refuse("the effort is not a level thread spawn lists");
        }
        let request_id_ok = request_id.strip_prefix("ow1-").is_some_and(|hex| {
            hex.len() == 40 && hex.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
        });
        if !request_id_ok {
            return refuse("the request id is not ow1- and 40 lowercase hex digits");
        }
        if validate_text(prompt).is_err() {
            return refuse("the prompt does not follow the text rules");
        }
        Ok(Self {
            project,
            provider: provider.to_owned(),
            model: model.to_owned(),
            effort: effort.to_owned(),
            request_id: request_id.to_owned(),
            prompt: prompt.to_owned(),
            attachments: vec![],
        })
    }

    /// The same arguments, carrying `attachments`, in this order.
    pub fn with_attachments(self, attachments: Vec<StagedAttachment>) -> Self {
        Self {
            attachments,
            ..self
        }
    }
}

/// **The one place** that builds `--file` and `--image` (B2, AD11): for each
/// staged attachment, in the order given (the core's dispatch order: files,
/// then images), `--file <path>` or `--image <path>`, the flag by its kind
/// and the path its
/// [`StagedPath`](openwiz_core::attachment::StagedPath). `tell` and `spawn` append the same
/// tail; each keeps its own text placement (`tell`'s `--` and positional
/// text, `spawn`'s `--prompt`), after it.
pub fn attachment_args(staged: &[StagedAttachment]) -> Vec<String> {
    let mut tail = Vec::with_capacity(2 * staged.len());
    for a in staged {
        let flag = match a.attachment.kind {
            Kind::File => "--file",
            Kind::Image => "--image",
        };
        tail.push(flag.to_owned());
        tail.push(a.path.as_str().to_owned());
    }
    tail
}

/// The extra time a call carrying `staged` may take (B2's proposed
/// [`attachment_allowance`]).
fn allowance_of(staged: &[StagedAttachment]) -> std::time::Duration {
    let total = staged
        .iter()
        .map(|a| a.attachment.size_bytes)
        .fold(0, u64::saturating_add);
    attachment_allowance(total)
}

/// The longest model passed.
const MODEL_MAX_LEN: usize = 128;

/// One allowed `room-cli` invocation: a read, or one of the two writes.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Invocation {
    /// `room-cli --version`
    Version,
    /// `room-cli thread list --json`, with `--include-hidden` and
    /// `--include-archived` only on request.
    ThreadList {
        include_hidden: bool,
        include_archived: bool,
    },
    /// `room-cli project list --json --include-personal`, with `--hidden`
    /// only on request.
    ProjectList { hidden: bool },
    /// `room-cli machine list --json`
    MachineList,
    /// `room-cli thread show <id> --json`
    ThreadShow(ThreadId),
    /// `room-cli thread output <id> --json`
    ThreadOutput(ThreadId),
    /// The one write: `room-cli thread tell <id> --mode <queue|steer> --json
    /// -- <text>`, with the text as one argument, byte for byte.
    ///
    /// **Documented, not observed; the argument shape must be rechecked on
    /// the owner's endpoint before any live send.** It follows the
    /// `room-cli` 0.43.1 help and guide as read during planning
    /// (2026-10-23): `thread tell <id> <message>`, `--mode
    /// steer|queue|auto`, `--json`. OpenWiz always passes `--mode` (never
    /// `auto`, never the location default) and none of `tell`'s other
    /// flags. The `--` before the text is OpenWiz's choice, so that text
    /// starting with `-` can never be read as a flag; whether 0.43.1 honours
    /// `--` as the end of options is undocumented, and is the first item of
    /// the pre-live recheck.
    ///
    /// **With attachments (B2, sheet B-7):** `room-cli thread tell <id>
    /// --mode queue --json [--file|--image <staged path>]… -- <text>`, the
    /// tail from [`attachment_args`] before the `--`. Never with steer: the
    /// core refuses Steer with attachments before anything (B-11).
    ThreadTell {
        id: ThreadId,
        mode: Mode,
        text: String,
        attachments: Vec<StagedAttachment>,
    },
    /// `room-cli cloud status --json`: the Cloud catalogue. The adapter keeps
    /// only the catalogue keys and drops the account and everything else
    /// before anything reads it (sheet A-2). Observed in spike run 3 (v131).
    CloudStatus,
    /// The second write (OpenWiz 0.0.4, `new`): `room-cli thread spawn
    /// --project <id> --machine cloud --provider <p> --model <m>
    /// --reasoning-level <l> --request-id <rid> --json --prompt <text>`,
    /// every setting explicit and the text one argument, byte for byte, last.
    ///
    /// **The flags are observed in `thread spawn --help` (spike run 3,
    /// v131); the call itself never ran.** `--provider` is required with
    /// `--machine cloud`, and spawn's own defaults (remembered project
    /// settings, then the catalogue's) are never relied on. No other flag is
    /// ever passed: no title, branch, permission, parent or schedule.
    ///
    /// **With attachments (B2, sheet B-7):** `[--file|--image <staged
    /// path>]…` from [`attachment_args`], after `--json` and before
    /// `--prompt`, so the text stays the last argument.
    ThreadSpawn(SpawnArgs),
    /// `room-cli cloud thread-workspace <id> --json`: one Cloud thread's
    /// current checkout and branch, for `openwiz fleet <spec>`'s verified
    /// chain (OpenWiz 0.0.6, A6, ClosedWiz#114). A read. Jake approved this
    /// one entry on #107, 2026-10-31
    /// ([private record](https://github.com/jparker2006/ClosedWiz/issues/1277#issuecomment-6704800036)). Observed: one call in
    /// A1's spike (`room-cli` v132, a flat `{branch, head, path}`), and its
    /// help on 0.43.1 (`Usage: room-cli cloud thread-workspace [options]
    /// <thread-id>`, `--json`); its error shapes are not.
    CloudThreadWorkspace(ThreadId),
    /// The third write (OpenWiz 0.0.6, B4, ClosedWiz#120, for finished
    /// agents): `room-cli thread archive <id> --json`, the id one argument
    /// ([`ThreadId`]), no other flag: never `--self`.
    ///
    /// **Observed in help (0.43.1), the call never run:** `Usage: room-cli
    /// thread archive [options] [id]`, with `--self`, `--json` and `-h` (the
    /// orchestrator's read-only `thread archive --help`, 2026-11-01, on
    /// #120). What it prints is not observed, so nothing reads it: the
    /// adapter reads `thread show <id> --json` before and after instead
    /// ([`archive`](crate::archive)). B6 (#122) runs it once live.
    ThreadArchive(ThreadId),
    /// T5: full loop inventory. Synthetic response shape, not live verified.
    LoopList,
    /// T5: resume one owned loop, verified before and after by the adapter.
    LoopResume(ThreadId),
    /// TK1: pause only the exact old fleet loop named by its ownership record.
    /// The adapter requires repository ownership and confirms paused readback.
    LoopPause(ThreadId),
}

impl Invocation {
    /// The staged attachments this call carries: none for a read.
    fn staged(&self) -> &[StagedAttachment] {
        match self {
            Invocation::ThreadTell { attachments, .. } => attachments,
            Invocation::ThreadSpawn(args) => &args.attachments,
            _ => &[],
        }
    }

    /// How much longer than a read this call may take: the attachments'
    /// allowance (B2), zero for everything else.
    pub fn allowance(&self) -> std::time::Duration {
        allowance_of(self.staged())
    }

    /// The exact arguments passed to `room-cli`, after the program name.
    pub fn argv(&self) -> Vec<String> {
        let tail = attachment_args(self.staged());
        let words: Vec<&str> = match self {
            Self::Version => vec!["--version"],
            Self::LoopList => vec!["loop", "list", "--json"],
            Self::LoopResume(id) => vec!["loop", "resume", id.as_str(), "--json"],
            Self::LoopPause(id) => vec!["loop", "pause", id.as_str(), "--json"],
            Self::ThreadList {
                include_hidden,
                include_archived,
            } => {
                let mut w = vec!["thread", "list", "--json"];
                if *include_hidden {
                    w.push("--include-hidden");
                }
                if *include_archived {
                    w.push("--include-archived");
                }
                w
            }
            Self::ProjectList { hidden } => {
                let mut w = vec!["project", "list", "--json", "--include-personal"];
                if *hidden {
                    w.push("--hidden");
                }
                w
            }
            Self::MachineList => vec!["machine", "list", "--json"],
            Self::ThreadShow(id) => vec!["thread", "show", id.as_str(), "--json"],
            Self::ThreadOutput(id) => vec!["thread", "output", id.as_str(), "--json"],
            Self::ThreadTell { id, mode, text, .. } => {
                let mut w = vec![
                    "thread",
                    "tell",
                    id.as_str(),
                    "--mode",
                    mode.as_str(),
                    "--json",
                ];
                w.extend(tail.iter().map(String::as_str));
                w.extend(["--", text.as_str()]);
                w
            }
            Self::CloudStatus => vec!["cloud", "status", "--json"],
            Self::CloudThreadWorkspace(id) => {
                vec!["cloud", "thread-workspace", id.as_str(), "--json"]
            }
            Self::ThreadSpawn(a) => {
                let mut w = vec![
                    "thread",
                    "spawn",
                    "--project",
                    a.project.as_str(),
                    "--machine",
                    "cloud",
                    "--provider",
                    a.provider.as_str(),
                    "--model",
                    a.model.as_str(),
                    "--reasoning-level",
                    a.effort.as_str(),
                    "--request-id",
                    a.request_id.as_str(),
                    "--json",
                ];
                w.extend(tail.iter().map(String::as_str));
                w.extend(["--prompt", a.prompt.as_str()]);
                w
            }
            Self::ThreadArchive(id) => vec!["thread", "archive", id.as_str(), "--json"],
        };
        words.into_iter().map(str::to_owned).collect()
    }
}
