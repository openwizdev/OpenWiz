use std::collections::{BTreeMap, BTreeSet};

use serde::Serialize;

use crate::messaging::send::read_failure;
use crate::model::Timestamp;
use crate::source::SourceError;

use super::{OPTIONS_SCHEMA_ID, Settings};

pub const J255_CLAUDE_MODEL: &str = "claude-opus-5-5";
pub const J255_CODEX_MODEL: &str = "gpt-6.2-sol";
pub const J255_EFFORT: &str = "medium";

const LOCAL_LABEL: &str = "Installed local harnesses with OpenWiz's current choices";

pub const SAVED_COPY_LABEL: &str = "as reported by CloudRoom; it may answer from a saved copy";

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub struct AttachmentSupport {
    pub files: bool,
    pub images: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CatalogueModel {
    pub model: String,
    pub reasoning_levels: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CatalogueHarness {
    pub id: String,
    pub provider: Option<String>,
    pub models: Option<Vec<CatalogueModel>>,
    pub attachments: Option<AttachmentSupport>,
    pub steer: Option<bool>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Catalogue {
    pub ready: bool,
    pub harnesses: Option<Vec<CatalogueHarness>>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct ModelOption {
    pub model: String,
    pub efforts: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct HarnessOption {
    pub harness: String,
    pub provider: String,
    pub models: Vec<ModelOption>,
    pub attachments: Option<AttachmentSupport>,
    pub steer: Option<bool>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum UnavailableReason {
    CatalogueNotReported,
    IdMappingNotVerified,
    NoOfferedEffort,
}

impl UnavailableReason {
    pub fn words(self) -> &'static str {
        match self {
            Self::CatalogueNotReported => "unavailable (catalogue not reported)",
            Self::IdMappingNotVerified => "unavailable (its id mapping is not verified)",
            Self::NoOfferedEffort => {
                "unavailable (no effort is in both the catalogue and the CLI's levels)"
            }
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct UnavailableHarness {
    pub harness: String,
    pub reason: UnavailableReason,
    pub text: String,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NoOptionsReason {
    NotReady,
    HarnessesNotReported,
    ReadFailed,
    UnexpectedShape,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum OptionsState {
    Offered,
    NoOptions {
        reason: NoOptionsReason,
        text: String,
    },
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct CloudOptions {
    pub schema: String,
    pub read_at: Timestamp,
    pub label: String,
    pub state: OptionsState,
    pub harnesses: Vec<HarnessOption>,
    pub unavailable: Vec<UnavailableHarness>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source: Option<OptionsSource>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum OptionsSource {
    Local,
}

pub fn local_options(
    claude_installed: bool,
    codex_installed: bool,
    read_at: Timestamp,
) -> CloudOptions {
    let harnesses: Vec<_> = [
        (claude_installed, "claude-code", J255_CLAUDE_MODEL),
        (codex_installed, "codex", J255_CODEX_MODEL),
    ]
    .into_iter()
    .filter(|(installed, _, _)| *installed)
    .map(|(_, provider, model)| HarnessOption {
        harness: provider.to_owned(),
        provider: provider.to_owned(),
        models: vec![ModelOption {
            model: model.to_owned(),
            efforts: vec![J255_EFFORT.to_owned()],
        }],
        attachments: None,
        steer: None,
    })
    .collect();
    let state = if harnesses.is_empty() {
        OptionsState::NoOptions {
            reason: NoOptionsReason::HarnessesNotReported,
            text: "neither claude nor codex was found on PATH".to_owned(),
        }
    } else {
        OptionsState::Offered
    };
    CloudOptions {
        schema: OPTIONS_SCHEMA_ID.to_owned(),
        read_at,
        label: LOCAL_LABEL.to_owned(),
        state,
        harnesses,
        unavailable: vec![],
        source: Some(OptionsSource::Local),
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NotOfferedField {
    Options,
    Harness,
    Model,
    Effort,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct NotOffered {
    pub field: NotOfferedField,
    pub offered: Vec<String>,
    pub text: String,
}

impl CloudOptions {
    pub fn offered(&self, settings: &Settings) -> Result<String, NotOffered> {
        if let OptionsState::NoOptions { text, .. } = &self.state {
            return Err(NotOffered {
                field: NotOfferedField::Options,
                offered: vec![],
                text: format!("not offered: no Cloud options ({text})"),
            });
        }
        let Some(harness) = self
            .harnesses
            .iter()
            .find(|h| h.harness == settings.harness)
        else {
            return Err(not_offered(
                NotOfferedField::Harness,
                &settings.harness,
                self.harnesses.iter().map(|h| h.harness.clone()).collect(),
            ));
        };
        let Some(model) = harness.models.iter().find(|m| m.model == settings.model) else {
            return Err(not_offered(
                NotOfferedField::Model,
                &settings.model,
                harness.models.iter().map(|m| m.model.clone()).collect(),
            ));
        };
        if !model.efforts.contains(&settings.effort) {
            return Err(not_offered(
                NotOfferedField::Effort,
                &settings.effort,
                model.efforts.clone(),
            ));
        }
        Ok(harness.provider.clone())
    }
}

fn not_offered(field: NotOfferedField, chosen: &str, offered: Vec<String>) -> NotOffered {
    let what = match field {
        NotOfferedField::Options => "option",
        NotOfferedField::Harness => "harness",
        NotOfferedField::Model => "model",
        NotOfferedField::Effort => "effort",
    };
    NotOffered {
        field,
        text: format!(
            "not offered: the {what} {chosen} is not in CloudRoom's options; offered: {}. \
             Nothing was substituted",
            if offered.is_empty() {
                "none".to_owned()
            } else {
                offered.join(", ")
            }
        ),
        offered,
    }
}

pub fn cloud_options(
    read: Result<Catalogue, SourceError>,
    cli_levels: &[&str],
    read_at: Timestamp,
) -> CloudOptions {
    let none = |reason: NoOptionsReason, text: String| CloudOptions {
        schema: OPTIONS_SCHEMA_ID.to_owned(),
        read_at,
        label: SAVED_COPY_LABEL.to_owned(),
        state: OptionsState::NoOptions { reason, text },
        harnesses: vec![],
        unavailable: vec![],
        source: None,
    };
    let catalogue = match read {
        Ok(catalogue) => catalogue,
        Err(SourceError::Malformed { .. }) => {
            return none(
                NoOptionsReason::UnexpectedShape,
                "cloud status returned a shape OpenWiz does not recognise".to_owned(),
            );
        }
        Err(e) => {
            return none(
                NoOptionsReason::ReadFailed,
                read_failure("cloud status", &e),
            );
        }
    };
    if !catalogue.ready {
        return none(
            NoOptionsReason::NotReady,
            "CloudRoom reports that Cloud is not ready".to_owned(),
        );
    }
    let Some(rows) = catalogue.harnesses else {
        return none(
            NoOptionsReason::HarnessesNotReported,
            "CloudRoom reports no harness catalogue".to_owned(),
        );
    };
    let mut harnesses = Vec::new();
    let mut unavailable = Vec::new();
    let mut by_id = BTreeMap::new();
    for row in &rows {
        let entry = by_id.entry(row.id.as_str()).or_insert((row, false));
        entry.1 |= entry.0 != row;
    }
    for row in &rows {
        let Some((_, conflicting_harness)) = by_id.remove(row.id.as_str()) else {
            continue;
        };
        let refuse = |reason: UnavailableReason| UnavailableHarness {
            harness: row.id.clone(),
            reason,
            text: reason.words().to_owned(),
        };
        let mut models_by_id = BTreeMap::new();
        let conflicting_models = row.models.as_ref().is_some_and(|models| {
            models.iter().any(|model| {
                models_by_id
                    .insert(model.model.as_str(), model)
                    .is_some_and(|previous| previous != model)
            })
        });
        if conflicting_harness || conflicting_models {
            unavailable.push(UnavailableHarness {
                text: "unavailable (conflicting catalogue rows)".to_owned(),
                ..refuse(UnavailableReason::CatalogueNotReported)
            });
            continue;
        }
        let Some(models) = &row.models else {
            unavailable.push(refuse(UnavailableReason::CatalogueNotReported));
            continue;
        };
        let Some(provider) = &row.provider else {
            unavailable.push(refuse(UnavailableReason::IdMappingNotVerified));
            continue;
        };
        let mut seen_models = BTreeSet::new();
        let models: Vec<ModelOption> = models
            .iter()
            .filter(|m| seen_models.insert(m.model.as_str()))
            .filter_map(|m| {
                let efforts: Vec<String> = m
                    .reasoning_levels
                    .iter()
                    .filter(|l| cli_levels.contains(&l.as_str()))
                    .cloned()
                    .collect();
                (!efforts.is_empty()).then(|| ModelOption {
                    model: m.model.clone(),
                    efforts,
                })
            })
            .collect();
        if models.is_empty() {
            unavailable.push(refuse(UnavailableReason::NoOfferedEffort));
            continue;
        }
        harnesses.push(HarnessOption {
            harness: row.id.clone(),
            provider: provider.clone(),
            models,
            attachments: row.attachments,
            steer: row.steer,
        });
    }
    if harnesses.is_empty() {
        return CloudOptions {
            unavailable,
            ..none(
                NoOptionsReason::HarnessesNotReported,
                "no harness in CloudRoom's catalogue can be offered".to_owned(),
            )
        };
    }
    CloudOptions {
        schema: OPTIONS_SCHEMA_ID.to_owned(),
        read_at,
        label: SAVED_COPY_LABEL.to_owned(),
        state: OptionsState::Offered,
        harnesses,
        unavailable,
        source: None,
    }
}
