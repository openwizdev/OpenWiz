//! The direct route and #694's check-in client use this same public store/key.
//! All clients/providers here are synthetic; no production tick is exercised.
use super::support::*;
use openwiz_core::messaging::send::{SendResult, Status, TellReply, UncertainReason};
use openwiz_core::model::SessionId;
use openwiz_service::events::{RelayKey, RelayKind, RelayStore, RouteResult};

fn key(kind: RelayKind) -> RelayKey {
    RelayKey::new(repository(), n(1901), commit('a'), kind)
}
fn message() -> String {
    format!(
        "CI failed for pull request #1901 at {} (rust). Read the failed job log, fix it, and hand back a new green head.",
        "a".repeat(40)
    )
}

#[test]
fn r2_direct_route_and_reopened_checkin_client_share_one_durable_record() {
    let fixture = Fixture::new();
    let fake = Fake::new(snapshot());
    let shared = RelayStore::open(&fixture.0).unwrap();
    let RouteResult::Send(first) = router(&fake, shared.records()).route_pr(n(1901)) else {
        panic!("direct send")
    };
    let key = key(RelayKind::CiFailed);
    assert_eq!(first.op_id, key.op_id());
    drop(shared);
    let checkin = RelayStore::open(&fixture.0).unwrap();
    let path = fixture
        .0
        .join("sends")
        .join(format!("{}.json", key.op_id()));
    let before = std::fs::read(&path).unwrap();
    let record = checkin.inspect(&key, &Fixed).unwrap().unwrap();
    assert_eq!(record.op_id, first.op_id);
    assert_eq!(record.binding.target.0, "thr_syn_builder");
    assert_eq!(
        std::fs::read(&path).unwrap(),
        before,
        "inspection never writes"
    );
    let replay = checkin
        .relay(
            &key,
            &fake,
            &Fixed,
            SessionId("thr_syn_builder".into()),
            &message(),
        )
        .unwrap();
    assert_eq!(replay.status, Status::Accepted);
    assert!(matches!(
        replay.result,
        SendResult::Outcome { replayed: true, .. }
    ));
    assert_eq!(fake.calls().len(), 1);
}

#[test]
fn r2_checkin_first_is_replayed_by_the_direct_route() {
    let fixture = Fixture::new();
    let fake = Fake::new(snapshot());
    let checkin = RelayStore::open(&fixture.0).unwrap();
    let first = checkin
        .relay(
            &key(RelayKind::CiFailed),
            &fake,
            &Fixed,
            SessionId("thr_syn_builder".into()),
            &message(),
        )
        .unwrap();
    assert_eq!(first.status, Status::Accepted);
    drop(checkin);
    let direct = RelayStore::open(&fixture.0).unwrap();
    let RouteResult::Send(replay) = router(&fake, direct.records()).route_pr(n(1901)) else {
        panic!("direct replay")
    };
    assert_eq!(replay.op_id, first.op_id);
    assert_eq!(replay.status, Status::Accepted);
    assert!(matches!(
        replay.result,
        SendResult::Outcome { replayed: true, .. }
    ));
    assert_eq!(fake.calls().len(), 1);
}

#[test]
fn r2_live_direct_claim_is_visible_to_an_independent_checkin_client() {
    let fixture = Fixture::new();
    let fake = Fake::new(snapshot());
    let direct = RelayStore::open(&fixture.0).unwrap();
    let checkin = RelayStore::open(&fixture.0).unwrap();
    let (started, waiting) = std::sync::mpsc::channel();
    let (release, held) = std::sync::mpsc::channel();
    *fake.hold.lock().unwrap() = Some((started, held));
    std::thread::scope(|scope| {
        let first = scope.spawn(|| router(&fake, direct.records()).route_pr(n(1901)));
        waiting
            .recv_timeout(std::time::Duration::from_secs(5))
            .unwrap();
        let replay = checkin
            .relay(
                &key(RelayKind::CiFailed),
                &fake,
                &Fixed,
                SessionId("thr_syn_builder".into()),
                &message(),
            )
            .unwrap();
        release.send(()).unwrap();
        first.join().unwrap();
        assert_eq!(replay.status, Status::InProgress);
        assert!(matches!(replay.result, SendResult::InProgress { .. }));
    });
    assert_eq!(fake.calls().len(), 1);
}

#[test]
fn r2_uncertain_shared_record_survives_both_clients_and_changed_text() {
    let fixture = Fixture::new();
    let fake = Fake::new(snapshot());
    *fake.reply.lock().unwrap() = TellReply::Unclear {
        reason: UncertainReason::TimedOut,
        gaps: vec![],
    };
    let shared = RelayStore::open(&fixture.0).unwrap();
    let first = shared
        .relay(
            &key(RelayKind::CiFailed),
            &fake,
            &Fixed,
            SessionId("thr_syn_builder".into()),
            &message(),
        )
        .unwrap();
    assert_eq!(first.status, Status::Uncertain);
    drop(shared);
    *fake.reply.lock().unwrap() = TellReply::Sent;
    let reopened = RelayStore::open(&fixture.0).unwrap();
    let replay = reopened
        .relay(
            &key(RelayKind::CiFailed),
            &fake,
            &Fixed,
            SessionId("thr_syn_builder".into()),
            "Changed check-in details",
        )
        .unwrap();
    assert_eq!(replay.status, Status::Uncertain);
    assert!(matches!(
        replay.result,
        SendResult::Outcome { replayed: true, .. }
    ));
    let RouteResult::Send(direct) = router(&fake, reopened.records()).route_pr(n(1901)) else {
        panic!("uncertain direct replay")
    };
    assert_eq!(direct.status, Status::Uncertain);
    assert_eq!(direct.op_id, first.op_id);
    assert_eq!(fake.calls().len(), 1);
}

#[test]
fn r2_shared_key_scopes_repository_pr_head_and_kind() {
    let original = key(RelayKind::CiFailed);
    let canonical = RelayKey::new(
        openwiz_core::fleet::starts::Repository::parse("Synthetic/Project").unwrap(),
        n(1901),
        commit('a'),
        RelayKind::CiFailed,
    );
    assert_eq!(original.op_id(), canonical.op_id());
    let other = [
        RelayKey::new(
            openwiz_core::fleet::starts::Repository::parse("synthetic/other").unwrap(),
            n(1901),
            commit('a'),
            RelayKind::CiFailed,
        ),
        RelayKey::new(repository(), n(1902), commit('a'), RelayKind::CiFailed),
        RelayKey::new(repository(), n(1901), commit('b'), RelayKind::CiFailed),
        key(RelayKind::ReviewFindings),
        key(RelayKind::ReCheck),
    ];
    let ids = std::iter::once(original.op_id())
        .chain(other.iter().map(RelayKey::op_id))
        .collect::<std::collections::BTreeSet<_>>();
    assert_eq!(ids.len(), 6);
}

#[test]
fn r2_operative_contract_requires_shared_record_and_once_per_key() {
    let contract = include_str!("../../contracts/fleet-tick.v1.md");
    let clause = contract
        .lines()
        .find(|line| line.starts_with("**Shared relay record (#546):**"))
        .expect("the ruling's operative relay clause");
    for required in [
        "at most once per key",
        "uncertain",
        "RelayStore",
        "RelayKey",
        "#694",
    ] {
        assert!(clause.contains(required), "missing {required}");
    }
    assert!(!contract.contains("A `send` repeated after an interruption reaches its agent twice"));
}
