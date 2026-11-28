use serde::Serialize;

use crate::limits::cap_field;
use crate::messaging::send::read_failure;
use crate::model::{Fact, Timestamp};
use crate::source::SourceError;

use super::outcome::Gap;

pub const REPORTED_LABEL: &str =
    "reported configuration: what CloudRoom reports, never the serving model";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ShownThread {
    pub status: Fact<String>,
    pub last_error: Fact<Option<String>>,
    pub provider: Fact<String>,
    pub model: Fact<String>,
    pub effort: Fact<String>,
    pub problems: Vec<Gap>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum StartStage {
    WaitingToStart {
        text: String,
    },
    Started {
        text: String,
    },
    IdleAsReported {
        text: String,
    },
    StartFailed {
        last_error: Fact<String>,
        text: String,
    },
    Unknown {
        reason: String,
        text: String,
    },
}

impl StartStage {
    pub fn from_shown(shown: &ShownThread) -> Self {
        let status = match &shown.status {
            Fact::Known(status) => status.as_str(),
            Fact::Unknown(why) => return Self::unknown(why),
        };
        match status {
            "pending" | "starting" => Self::WaitingToStart {
                text: "waiting to start".to_owned(),
            },
            "active" => Self::Started {
                text: "started: its first turn is running, as reported".to_owned(),
            },
            "idle" => Self::IdleAsReported {
                text: "idle, as reported: whether the first prompt ran is not confirmed".to_owned(),
            },
            "error" => {
                let last_error = match &shown.last_error {
                    Fact::Known(Some(error)) => Fact::Known(cap_field(error)),
                    Fact::Known(None) => Fact::Unknown("not reported by CloudRoom".to_owned()),
                    Fact::Unknown(why) => Fact::Unknown(why.clone()),
                };
                Self::StartFailed {
                    last_error,
                    text: "start failed, in CloudRoom's words below; the prompt stays saved in \
                           CloudRoom"
                        .to_owned(),
                }
            }
            _ => Self::unknown("the status is not one OpenWiz knows"),
        }
    }

    pub fn unknown(reason: &str) -> Self {
        Self::Unknown {
            reason: reason.to_owned(),
            text: format!("unknown ({reason})"),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct ReportedSetting {
    pub requested: String,
    pub reported: Fact<String>,
    pub differs_from_requested: Fact<bool>,
    pub text: String,
}

impl ReportedSetting {
    fn new(name: &str, requested: &str, reported: &Fact<String>) -> Self {
        let (differs, text) = match reported {
            Fact::Known(value) if value == requested => {
                (Fact::Known(false), format!("{name} {value}, as requested"))
            }
            Fact::Known(value) => (
                Fact::Known(true),
                format!("{name} {value}: differs from requested ({requested})"),
            ),
            Fact::Unknown(why) => (
                Fact::Unknown(why.clone()),
                format!("{name} unknown ({why}); requested {requested}"),
            ),
        };
        Self {
            requested: requested.to_owned(),
            reported: reported.clone(),
            differs_from_requested: differs,
            text,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct ReportedConfiguration {
    pub label: String,
    pub provider: ReportedSetting,
    pub model: ReportedSetting,
    pub effort: ReportedSetting,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct StartView {
    pub thread_id: String,
    pub read_at: Timestamp,
    pub stage: StartStage,
    pub reported: Option<ReportedConfiguration>,
    pub gaps: Vec<Gap>,
}

pub fn start_view(
    thread_id: &str,
    requested: (&str, &str, &str),
    read: Result<ShownThread, SourceError>,
    read_at: Timestamp,
) -> StartView {
    let (provider, model, effort) = requested;
    match read {
        Ok(shown) => StartView {
            thread_id: thread_id.to_owned(),
            read_at,
            stage: StartStage::from_shown(&shown),
            reported: Some(ReportedConfiguration {
                label: REPORTED_LABEL.to_owned(),
                provider: ReportedSetting::new("provider", provider, &shown.provider),
                model: ReportedSetting::new("model", model, &shown.model),
                effort: ReportedSetting::new("effort", effort, &shown.effort),
            }),
            gaps: shown.problems,
        },
        Err(e) => {
            let why = read_failure("thread show", &e);
            StartView {
                thread_id: thread_id.to_owned(),
                read_at,
                stage: StartStage::unknown(&why),
                reported: None,
                gaps: vec![Gap {
                    subject: "thread show".to_owned(),
                    detail: why,
                }],
            }
        }
    }
}
