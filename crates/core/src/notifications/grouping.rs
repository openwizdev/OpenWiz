//! Canonical, domain-separated tuple identity. No clock or transport identity.
use super::{model::*, policy};

pub fn key(fact: &SourceFact) -> Vec<u8> {
    let mut key = b"openwiz.notification-group.v1".to_vec();
    fn part(key: &mut Vec<u8>, value: &[u8]) {
        key.extend_from_slice(&(value.len() as u64).to_be_bytes());
        key.extend_from_slice(value);
    }
    match policy::reference(fact) {
        Reference::Decision(d) => {
            key.push(0);
            part(&mut key, d.repository.as_str().as_bytes());
            key.push(match d.subject.kind {
                SubjectKind::Issue => 0,
                SubjectKind::PullRequest => 1,
            });
            part(&mut key, &d.subject.number.get().to_be_bytes());
            part(&mut key, d.request_id.as_str().as_bytes());
            part(&mut key, d.fingerprint.as_str().as_bytes());
        }
        Reference::Incident(i) => {
            key.push(1);
            part(&mut key, i.repository.as_str().as_bytes());
            part(&mut key, i.owner.as_str().as_bytes());
            key.push(match i.source {
                RecoverySource::ServiceHealth => 0,
                RecoverySource::LoopWatchdog => 1,
            });
            part(&mut key, i.subject.as_str().as_bytes());
            part(&mut key, i.incident.as_str().as_bytes());
        }
        Reference::Event(e) => {
            key.push(2);
            // ALL is the pinned catalogue's explicit stable order.
            key.push(
                Category::ALL
                    .iter()
                    .position(|c| *c == policy::category(fact))
                    .unwrap() as u8,
            );
            part(&mut key, e.repository.as_str().as_bytes());
            key.push(match e.source {
                SourceOwner::Decisions => 0,
                SourceOwner::ServiceHealth => 1,
                SourceOwner::LoopWatchdog => 2,
                SourceOwner::EventRouter => 3,
                SourceOwner::Fleet => 4,
                SourceOwner::Inventory => 5,
                SourceOwner::Plan => 6,
                SourceOwner::Loops => 7,
                SourceOwner::ServiceUpdate => 8,
            });
            part(&mut key, e.subject.as_str().as_bytes());
            part(&mut key, e.event_id.as_str().as_bytes());
            part(&mut key, e.revision.as_str().as_bytes());
        }
    }
    key
}
