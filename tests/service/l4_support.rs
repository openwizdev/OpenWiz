#![allow(dead_code)]
use openwiz_core::fleet::model::{
    Check, CheckResult, Commit, Issue, IssueState, NonEmpty, Number, PrFields,
};
use openwiz_core::fleet::starts::Repository;
use openwiz_core::fleet::tick::*;
use openwiz_core::messaging::effects::{Activity, QueuedWork, TargetRecord};
use openwiz_core::messaging::send::{Messenger, TellReply};
use openwiz_core::messaging::{InvalidRequest, Mode};
use openwiz_core::model::{Fact, SessionId, Timestamp};
use openwiz_core::ops::Clock;
use openwiz_core::source::{Placement, SourceError};
use openwiz_service::events::*;
use openwiz_store::FileStore;
use std::collections::{BTreeMap, VecDeque};
use std::fs::{self, DirBuilder};
use std::os::unix::fs::DirBuilderExt;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::mpsc::{Receiver, Sender};
use std::sync::{Mutex, OnceLock};
use std::time::Instant;

pub fn n(value: u64) -> Number {
    Number::new(value).unwrap()
}
pub fn text(value: &str) -> NonEmpty {
    NonEmpty::new(value).unwrap()
}
pub fn commit(value: char) -> Commit {
    Commit::parse(&value.to_string().repeat(40)).unwrap()
}
pub fn repository() -> Repository {
    Repository::parse("synthetic/project").unwrap()
}
pub fn agent(value: &str) -> Agent {
    Agent {
        thread: text(value),
        archived: false,
    }
}
pub struct Fixed;
impl Clock for Fixed {
    fn now(&self) -> Timestamp {
        Timestamp(2_000_000)
    }
    fn monotonic(&self) -> Instant {
        Instant::now()
    }
}
pub fn issue() -> Issue {
    Issue {
        title: "Synthetic ticket".into(),
        state: IssueState::Open,
        milestone: None,
        labels: vec![text("ready-for-agent")],
        owned_paths: None,
        relies_on: None,
        pending_question: None,
    }
}
pub fn snapshot() -> Snapshot {
    let fingerprint = Fingerprint::parse(&"d".repeat(64)).unwrap();
    Snapshot {
        default_branch: Observed::Complete(text("main")),
        fleets: Observed::Complete(vec![FleetInput {
            spec: n(900),
            facts: Observed::Complete(FleetFacts {
                issue: issue(),
                approval: Some(PlanApproval {
                    approval: Approval {
                        comment: n(5000),
                        revision: n(1),
                        fingerprint: fingerprint.clone(),
                    },
                    rows: BTreeMap::from([(n(901), Ready::Agent)]),
                    approved_at: 0,
                }),
                fingerprint_now: fingerprint,
                tickets: vec![TicketInput {
                    number: n(901),
                    facts: Observed::Complete(TicketFacts {
                        issue: issue(),
                        blockers: vec![],
                        builder: Some(agent("thr_syn_builder")),
                        builder_source: Some(BuilderSource {
                            thread: text("thr_syn_builder"),
                            branch: text("room/synthetic"),
                            family: BuilderFamily::Gpt,
                            plan_limit: false,
                        }),
                        reviewers: vec![],
                        starts: vec![],
                        relies_on: vec![],
                        holds: vec![],
                        held_label_comment: None,
                        question: None,
                        records: TicketRecords::default(),
                        pr: Some(PrInput::Open(Box::new(OpenPr {
                            fields: PrFields {
                                number: n(1901),
                                draft: false,
                                head_branch: text("room/synthetic"),
                                head_commit: commit('a'),
                                base_branch: text("main"),
                                closes: vec![n(901)],
                            },
                            subject: "Synthetic green".into(),
                            ci: Some(CheckRun {
                                head_commit: commit('a'),
                                base_commit: commit('b'),
                                checks: ["web-build", "ci", "web-test"]
                                    .into_iter()
                                    .map(|name| Check {
                                        name: text(name),
                                        result: if name == "ci" {
                                            CheckResult::Fail
                                        } else {
                                            CheckResult::Pass
                                        },
                                    })
                                    .collect(),
                            }),
                            base_now: Some(commit('b')),
                            reports: vec![],
                            starts: vec![],
                            records: PrRecords::default(),
                        }))),
                    }),
                }],
                changes: vec![],
                follow_ups: vec![],
                records: SpecRecords::default(),
            }),
        }]),
    }
}
pub fn fleet(snapshot: &mut Snapshot) -> &mut FleetFacts {
    let Observed::Complete(fleets) = &mut snapshot.fleets else {
        panic!("fleets")
    };
    let Observed::Complete(fleet) = &mut fleets[0].facts else {
        panic!("fleet")
    };
    fleet
}
pub fn ticket(snapshot: &mut Snapshot) -> &mut TicketFacts {
    let Observed::Complete(ticket) = &mut fleet(snapshot).tickets[0].facts else {
        panic!("ticket")
    };
    ticket
}
pub fn pr(snapshot: &mut Snapshot) -> &mut OpenPr {
    let Some(PrInput::Open(pr)) = &mut ticket(snapshot).pr else {
        panic!("PR")
    };
    pr
}
pub fn event(kind: EventKind, id: &str) -> Event {
    Event {
        repository: repository(),
        event_id: id.into(),
        kind,
        pull_requests: vec![n(1901)],
    }
}
pub struct Source(pub VecDeque<Event>);
impl Source {
    pub fn new(event: Event) -> Self {
        Self(VecDeque::from([event]))
    }
}
impl EventSource for Source {
    fn next(&mut self) -> Result<Option<Event>, EventError> {
        Ok(self.0.pop_front())
    }
}
pub struct Fake {
    pub current: Mutex<Snapshot>,
    pub trace: Mutex<Vec<&'static str>>,
    pub sent: Mutex<Vec<(String, String)>>,
    pub reply: Mutex<TellReply>,
    pub unread: Mutex<bool>,
    pub crash: Option<(String, PathBuf)>,
    pub returned_repository: Mutex<Repository>,
    pub hold: Mutex<Option<(Sender<()>, Receiver<()>)>>,
}
impl Fake {
    pub fn new(current: Snapshot) -> Self {
        Self {
            current: Mutex::new(current),
            trace: Mutex::new(vec![]),
            sent: Mutex::new(vec![]),
            reply: Mutex::new(TellReply::Sent),
            unread: Mutex::new(false),
            crash: None,
            returned_repository: Mutex::new(repository()),
            hold: Mutex::new(None),
        }
    }
    pub fn calls(&self) -> Vec<(String, String)> {
        self.sent.lock().unwrap().clone()
    }
}
impl FleetReader for Fake {
    fn read_current(&self, repo: &Repository, number: Number) -> Result<Current, ReadError> {
        assert_eq!(repo, &repository());
        assert!([n(1901), n(1902)].contains(&number));
        self.trace.lock().unwrap().push("facts");
        if *self.unread.lock().unwrap() {
            return Err(ReadError);
        }
        Ok(Current {
            repository: self.returned_repository.lock().unwrap().clone(),
            snapshot: self.current.lock().unwrap().clone(),
        })
    }
}
impl Messenger for Fake {
    fn name(&self) -> &str {
        "fake-room-cli"
    }
    fn tested_version(&self) -> &str {
        "0.43.1"
    }
    fn check_target_id(&self, id: &SessionId) -> Result<(), InvalidRequest> {
        openwiz_adapter_cloudroom::allowlist::ThreadId::parse(&id.0)
            .map(|_| ())
            .map_err(|_| InvalidRequest("bad synthetic target".into()))
    }
    fn version(&self, _: Instant) -> Result<String, SourceError> {
        if self
            .crash
            .as_ref()
            .is_some_and(|(stage, _)| stage == "claim")
        {
            std::process::exit(73);
        }
        Ok("0.43.1".into())
    }
    fn read_target(&self, id: &SessionId, _: Instant) -> Result<TargetRecord, SourceError> {
        Ok(TargetRecord {
            id: id.clone(),
            title: Fact::Known("Synthetic thread".into()),
            activity: Fact::Known(Activity::Idle),
            hidden: Fact::Known(false),
            archived: Fact::Known(false),
            placement: Fact::Known(Placement::Cloud),
            host_connected: None,
            queued_work: Fact::Known(QueuedWork::None),
            queued_message_count: Fact::Known(0),
            pending_interaction: Fact::Known(false),
            problems: vec![],
        })
    }
    fn tell(&self, id: &SessionId, mode: Mode, message: &str, _: Instant) -> TellReply {
        assert_eq!(mode, Mode::Queue);
        if let Some((stage, marker)) = &self.crash {
            if stage == "dispatch" {
                std::process::exit(73);
            }
            fs::write(marker, "synthetic provider call\n").unwrap();
            std::process::exit(73);
        }
        self.trace.lock().unwrap().push("tell");
        self.sent
            .lock()
            .unwrap()
            .push((id.0.clone(), message.into()));
        let hold = self.hold.lock().unwrap().take();
        if let Some((started, release)) = hold {
            started.send(()).unwrap();
            release
                .recv_timeout(std::time::Duration::from_secs(5))
                .unwrap();
        }
        self.reply.lock().unwrap().clone()
    }
}
pub fn router<'a>(
    fake: &'a Fake,
    sends: &'a dyn openwiz_core::messaging::record::SendStore,
) -> Router<'a> {
    static RULES: OnceLock<Rules> = OnceLock::new();
    static REPO: OnceLock<Repository> = OnceLock::new();
    Router {
        repository: REPO.get_or_init(repository),
        rules: RULES
            .get_or_init(|| Rules::parse(include_str!("../../docs/agents/fleet.md")).unwrap()),
        facts: fake,
        messenger: fake,
        sends,
        clock: &Fixed,
    }
}
pub struct Fixture(pub PathBuf);
impl Fixture {
    pub fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let dir = std::env::temp_dir().join(format!(
            "openwiz-l4-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        DirBuilder::new().mode(0o700).create(&dir).unwrap();
        Self(dir)
    }
    pub fn store(&self) -> FileStore {
        FileStore::open(&self.0).unwrap()
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}
