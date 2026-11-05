//! Shared durable relay records for direct events and the fleet check-in.
//! The record is the existing strict send record, not a second copy of it.
use openwiz_core::fleet::model::{Commit, Number};
use openwiz_core::fleet::starts::Repository;
use openwiz_core::messaging::lookup::{self, LookupResult};
use openwiz_core::messaging::record::{SendRecord, SendStore, StoreError};
use openwiz_core::messaging::send::{self, Messenger, SendError, SendReport, SendRequest};
use openwiz_core::messaging::{OpId, sha256_hex};
use openwiz_core::model::SessionId;
use openwiz_core::ops::Clock;
use openwiz_store::FileStore;
use std::path::Path;

/// The relay kind is part of the key: one kind never consumes another's send.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RelayKind {
    CiFailed,
    ReviewFindings,
    ReCheck,
}

impl RelayKind {
    fn key(self) -> &'static str {
        match self {
            Self::CiFailed => "ci_failed",
            Self::ReviewFindings => "review_findings",
            Self::ReCheck => "re_check",
        }
    }
}

/// Repository-scoped (PR, head, kind), independent of webhook delivery IDs.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RelayKey {
    repository: Repository,
    pr: Number,
    head: Commit,
    kind: RelayKind,
}

impl RelayKey {
    pub fn new(repository: Repository, pr: Number, head: Commit, kind: RelayKind) -> Self {
        Self {
            repository,
            pr,
            head,
            kind,
        }
    }

    /// Stable shared ID; Repository already canonicalizes case. The domain,
    /// separators and typed components make the mapping unambiguous.
    pub fn op_id(&self) -> OpId {
        let identity = format!(
            "openwiz.fleet-relay.v1\n{}\n{}\n{}\n{}",
            self.repository.as_str(),
            self.pr,
            self.head.as_str(),
            self.kind.key()
        );
        OpId::parse(&sha256_hex(identity.as_bytes())).expect("SHA-256 is a valid op ID")
    }
}

/// Both clients open the same OpenWiz state root. Each key maps to the single
/// `sends/<key.op_id()>.json` SendRecord and its existing atomic lock. FileStore
/// supplies private permissions, strict parsing, sync-before-send and crash
/// recovery. GitHub's post-send comments are notifications, not these records.
pub struct RelayStore {
    records: FileStore,
}

impl RelayStore {
    pub fn open(state_root: &Path) -> Result<Self, StoreError> {
        Ok(Self {
            records: FileStore::open(state_root)?,
        })
    }

    /// Supply this backing store to Router; #694's client uses the same root.
    pub fn records(&self) -> &dyn SendStore {
        &self.records
    }

    /// Read only, including in-memory recovery of a stopped sender's record.
    pub fn inspect(
        &self,
        key: &RelayKey,
        clock: &dyn Clock,
    ) -> Result<Option<SendRecord>, StoreError> {
        self.records.inspect(&key.op_id(), clock.now())
    }

    /// Consult the shared record before relaying. The existing send operation
    /// rechecks under its claim lock, so concurrent clients make one call.
    /// An uncertain result is returned as uncertain, never automatically
    /// retried; the contract's exception permits only an explicit resolution
    /// of that uncertain record, not a new ID caused by a repeated hint.
    pub fn relay(
        &self,
        key: &RelayKey,
        messenger: &dyn Messenger,
        clock: &dyn Clock,
        target: SessionId,
        message: &str,
    ) -> Result<SendReport, SendError> {
        let op_id = key.op_id();
        if let Some(record) = self.inspect(key, clock).map_err(SendError::Store)? {
            let saved = lookup::lookup(
                Some(self.records()),
                clock,
                &record.binding.target,
                &op_id,
                messenger.tested_version(),
            )
            .map_err(SendError::Store)?;
            match saved.result {
                LookupResult::Recorded { report } => return Ok(*report),
                LookupResult::OtherTarget => {
                    return Err(SendError::Store(StoreError(
                        "relay binding changed while reading its record".into(),
                    )));
                }
                LookupResult::NoRecord => {}
            }
        }
        send::send(
            messenger,
            self.records(),
            clock,
            &SendRequest::new(target, message, op_id),
        )
    }
}
