//! Structure: every label and shape the core serializes for send is in the
//! published messaging schema.

use serde_json::Value;

use crate::support::*;

/// Haiku A1: every label the core can serialize is in the schema's enums.
#[test]
fn every_serialized_label_is_in_the_schema() {
    use openwiz_core::messaging::send::{FailReason, Status, UncertainReason, WaitingOn};
    let schema = messaging_schema();
    let enums = |path: &str| -> Vec<Value> {
        schema
            .pointer(path)
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_else(|| panic!("no enum at {path}"))
    };
    let fail = enums("/$defs/fail_reason/enum");
    for reason in [
        FailReason::NotFound,
        FailReason::InvalidInput,
        FailReason::UnsupportedMode,
        FailReason::InterruptedBeforeDispatch,
        FailReason::UntestedVersion,
        FailReason::TargetNotRead,
        FailReason::TargetArchived,
        FailReason::TargetHidden,
        FailReason::TargetVisibilityUnknown,
        FailReason::PausedQueueNotAcknowledged,
        FailReason::RecordNotWritten,
        FailReason::BudgetExhausted,
        FailReason::CallNotStarted,
    ] {
        let label = serde_json::to_value(reason).unwrap();
        assert!(fail.contains(&label), "{label} is not in the schema");
    }
    let uncertain = enums("/$defs/delivery/oneOf/3/properties/reason/enum");
    for reason in [
        UncertainReason::TimedOut,
        UncertainReason::EndedWithoutExitCode,
        UncertainReason::NotJson,
        UncertainReason::UnexpectedReceipt,
        UncertainReason::UndocumentedError,
        UncertainReason::CallNotConfirmed,
        UncertainReason::InterruptedAfterDispatchMark,
    ] {
        let label = serde_json::to_value(reason).unwrap();
        assert!(uncertain.contains(&label), "{label} is not in the schema");
    }
    let waiting = enums("/$defs/delivery/oneOf/0/properties/waiting_on/enum");
    for kind in [
        WaitingOn::Time,
        WaitingOn::ThreadBusy,
        WaitingOn::TurnStarting,
        WaitingOn::Provisioning,
        WaitingOn::HostOffline,
        WaitingOn::Interaction,
        WaitingOn::Plugin,
    ] {
        let label = serde_json::to_value(kind).unwrap();
        assert!(waiting.contains(&label), "{label} is not in the schema");
    }
    let status = enums("/$defs/report/properties/status/enum");
    for s in [
        Status::Queued,
        Status::Accepted,
        Status::Failed,
        Status::Uncertain,
        Status::InProgress,
        Status::ConflictingReuse,
        Status::PossibleDuplicateRefused,
    ] {
        let label = serde_json::to_value(s).unwrap();
        assert!(status.contains(&label), "{label} is not in the schema");
    }
    // A label added to the core without a schema entry fails to compile here.
    fn _exhaustive(r: FailReason) {
        match r {
            FailReason::NotFound
            | FailReason::InvalidInput
            | FailReason::UnsupportedMode
            | FailReason::InterruptedBeforeDispatch
            | FailReason::UntestedVersion
            | FailReason::TargetNotRead
            | FailReason::TargetArchived
            | FailReason::TargetHidden
            | FailReason::TargetVisibilityUnknown
            | FailReason::PausedQueueNotAcknowledged
            | FailReason::RecordNotWritten
            | FailReason::BudgetExhausted
            | FailReason::CallNotStarted => {}
        }
    }
}

/// #79: the preview shape is in the schema, with every label the core can
/// serialize, and an earlier send says whether it is in flight. (Its lookup
/// half went with `messaging::lookup` in #1264.)
#[test]
fn the_preview_shape_is_in_the_schema() {
    use openwiz_core::messaging::preview::{PREVIEW_SCHEMA_ID, PreviewStatus};
    let schema = messaging_schema();
    for def in ["preview", "refusal"] {
        assert!(schema["$defs"][def].is_object(), "no $defs/{def}");
    }
    assert_eq!(
        schema["$defs"]["preview"]["properties"]["schema"]["const"],
        PREVIEW_SCHEMA_ID
    );
    let statuses = schema["$defs"]["preview"]["properties"]["status"]["enum"]
        .as_array()
        .cloned()
        .unwrap_or_default();
    for s in [
        PreviewStatus::Ready,
        PreviewStatus::NeedsAcknowledgement,
        PreviewStatus::Refused,
    ] {
        let label = serde_json::to_value(s).unwrap();
        assert!(statuses.contains(&label), "{label} is not in the schema");
    }
    fn _exhaustive(s: PreviewStatus) {
        match s {
            PreviewStatus::Ready | PreviewStatus::NeedsAcknowledgement | PreviewStatus::Refused => {
            }
        }
    }
    let earlier = &schema["$defs"]["earlier_send"];
    assert!(
        earlier["required"]
            .as_array()
            .is_some_and(|r| r.contains(&"in_flight".into())),
        "{earlier}"
    );
}
