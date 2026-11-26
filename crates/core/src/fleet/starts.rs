use std::time::Duration;

use serde::Serialize;

use crate::messaging::record::StoreError;
use crate::messaging::{InvalidRequest, OpId, sha256_hex};
use crate::model::Timestamp;
use crate::new_thread::{NEW_THREAD_BUDGET, NewThreadRequest, ProjectRef, Settings};
use crate::prompt::PromptPayload;

use super::model::{Commit, Number};

pub const START_RECORD_SCHEMA_ID: &str = "openwiz.start-record.v1";

pub const START_ID_DOMAIN: &str = "openwiz.start.v1:";

pub const START_ID_PREFIX: &str = "start-";

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Role {
    Builder,
    Reviewer,
}

impl Role {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Builder => "builder",
            Self::Reviewer => "reviewer",
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(transparent)]
pub struct Repository(String);

impl Repository {
    pub fn parse(text: &str) -> Result<Self, InvalidRequest> {
        let valid = text.split_once('/').is_some_and(|(owner, name)| {
            (1..=39).contains(&owner.len())
                && !owner.starts_with('-')
                && owner
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b == b'-')
                && (1..=100).contains(&name.len())
                && name != "."
                && name != ".."
                && name
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b'-'))
        });
        if valid {
            Ok(Self(text.to_ascii_lowercase()))
        } else {
            Err(InvalidRequest(
                "a repository is owner/name, as GitHub names them".to_owned(),
            ))
        }
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct StartKey {
    repository: Repository,
    role: Role,
    number: Number,
    commit: Option<Commit>,
}

impl StartKey {
    pub fn builder(repository: Repository, ticket: Number) -> Self {
        Self {
            repository,
            role: Role::Builder,
            number: ticket,
            commit: None,
        }
    }

    pub fn reviewer(repository: Repository, pull_request: Number, commit: Commit) -> Self {
        Self {
            repository,
            role: Role::Reviewer,
            number: pull_request,
            commit: Some(commit),
        }
    }

    pub fn repository(&self) -> &Repository {
        &self.repository
    }

    pub fn role(&self) -> Role {
        self.role
    }

    pub fn number(&self) -> Number {
        self.number
    }

    pub fn commit(&self) -> Option<&Commit> {
        self.commit.as_ref()
    }

    pub fn id(&self) -> OpId {
        let key = match &self.commit {
            None => format!(
                "{}:{}#{}",
                self.role.as_str(),
                self.repository.0,
                self.number
            ),
            Some(commit) => format!(
                "{}:{}#{}@{}",
                self.role.as_str(),
                self.repository.0,
                self.number,
                commit.as_str()
            ),
        };
        let digest = sha256_hex(format!("{START_ID_DOMAIN}{key}").as_bytes());
        OpId::parse(&format!("{START_ID_PREFIX}{}", &digest[..40]))
            .expect("a prefix and hex digits make an op id")
    }
}

pub fn brief(key: &StartKey) -> String {
    match &key.commit {
        None => format!(
            "You are the builder for #{}. Read skills/build-ticket/SKILL.md and follow it.",
            key.number
        ),
        Some(commit) => format!(
            "You are the reviewer for pull request #{} at {}. Read skills/review-ticket/SKILL.md \
             and follow it.",
            key.number,
            commit.as_str()
        ),
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum AttemptOutcome {
    Pending,
    Created { thread_id: String },
    NotCreated { status: NotCreated, words: String },
    Uncertain { words: String },
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NotCreated {
    Refused,
    Failed,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Attempt {
    pub op_id: OpId,
    pub at: Timestamp,
    pub outcome: AttemptOutcome,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct StartRecord {
    schema: String,
    id: OpId,
    key: StartKey,
    project_id: String,
    settings: Settings,
    attempts: Vec<Attempt>,
}

impl StartRecord {
    pub fn id(&self) -> &OpId {
        &self.id
    }

    pub fn key(&self) -> &StartKey {
        &self.key
    }

    pub fn project_id(&self) -> &str {
        &self.project_id
    }

    pub fn settings(&self) -> &Settings {
        &self.settings
    }

    pub fn attempts(&self) -> &[Attempt] {
        &self.attempts
    }

    pub fn from_parts(
        id: OpId,
        key: StartKey,
        project_id: String,
        settings: Settings,
        attempts: Vec<Attempt>,
    ) -> Result<Self, String> {
        if id != key.id() {
            return Err("its id is not its key's".to_owned());
        }
        StartRequest::new(key.clone(), project_id.clone(), settings.clone())
            .validate()
            .map_err(|e| e.0)?;
        if attempts.is_empty() {
            return Err("it has no attempt".to_owned());
        }
        for (i, attempt) in attempts.iter().enumerate() {
            if attempts[..i].iter().any(|a| a.op_id == attempt.op_id) {
                return Err(format!("attempt {i}'s op id is given twice"));
            }
            if attempt.at.0 < 0 {
                return Err(format!("attempt {i}'s time is before 1970"));
            }
            let created_nothing = matches!(attempt.outcome, AttemptOutcome::NotCreated { .. });
            if i + 1 < attempts.len() && !created_nothing {
                return Err(format!(
                    "attempt {i} is not the last, so it must have created nothing"
                ));
            }
            if let AttemptOutcome::Created { thread_id } = &attempt.outcome
                && !safe_id(thread_id)
            {
                return Err(format!("attempt {i}'s thread id is not safe to pass"));
            }
        }
        Ok(Self {
            schema: START_RECORD_SCHEMA_ID.to_owned(),
            id,
            key,
            project_id,
            settings,
            attempts,
        })
    }
}

pub fn safe_id(id: &str) -> bool {
    (1..=128).contains(&id.len())
        && !id.starts_with('-')
        && id
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Locked {
    Mine(Option<Box<StartRecord>>),
    Busy,
}

pub trait StartStore: Send + Sync {
    fn lock(&self, key: &StartKey) -> Result<Locked, StoreError>;

    fn write(&self, record: &StartRecord) -> Result<(), StoreError>;

    fn unlock(&self, key: &StartKey);

    fn inspect(&self, key: &StartKey) -> Result<Option<StartRecord>, StoreError>;
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StartRequest {
    pub key: StartKey,
    pub project_id: String,
    pub settings: Settings,
    pub budget: Duration,
}

impl StartRequest {
    pub fn new(key: StartKey, project_id: impl Into<String>, settings: Settings) -> Self {
        Self {
            key,
            project_id: project_id.into(),
            settings,
            budget: NEW_THREAD_BUDGET,
        }
    }

    pub fn validate(&self) -> Result<(), InvalidRequest> {
        if !safe_id(&self.project_id) {
            return Err(InvalidRequest(
                "the project id is 1 to 128 ASCII letters, digits, _ or -, not starting with -"
                    .to_owned(),
            ));
        }
        self.new_thread(self.key.id()).validate()
    }

    fn new_thread(&self, op_id: OpId) -> NewThreadRequest {
        let mut request = NewThreadRequest::new(
            ProjectRef::Id(self.project_id.clone()),
            self.settings.clone(),
            PromptPayload::text(brief(&self.key)),
            op_id,
        );
        request.budget = self.budget;
        request
    }
}
