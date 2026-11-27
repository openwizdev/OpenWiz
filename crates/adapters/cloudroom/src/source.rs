use std::path::PathBuf;
use std::time::Instant;

use openwiz_core::envelope::{Gap, GapKind};
use openwiz_core::model::{Fact, ProjectId, SessionId, Timestamp};
use openwiz_core::ops::{VERSION_NOT_RECOGNISED, is_version_text};
use openwiz_core::source::{
    MachineRecord, OutputRecord, Placement, ProjectRecord, Read, Rows, SessionDetailRecord,
    SessionRecord, SessionScope, SessionSource, SourceError,
};
use serde::de::{self, MapAccess, SeqAccess, Visitor};
use serde::{Deserialize, Deserializer};
use serde_json::error::Category;
use serde_json::{Map, Value};

use crate::allowlist::{Invocation, ThreadId};
use crate::{PROGRAM, TESTED_VERSION, process};

pub fn lower_read_timeout_for_fixtures(timeout: std::time::Duration) {
    process::lower_read_timeout(timeout);
}

pub fn use_fast_polling_for_fixtures() {
    process::use_fast_polling_for_fixtures();
}

#[derive(Clone, Debug)]
pub struct CloudRoomSource {
    program: PathBuf,
    read_timeout: std::time::Duration,
}

impl CloudRoomSource {
    pub fn new(program: impl Into<PathBuf>) -> Self {
        Self {
            program: program.into(),
            read_timeout: openwiz_core::limits::READ_TIMEOUT,
        }
    }

    pub fn from_path() -> Self {
        Self::new(PROGRAM)
    }

    pub fn program(&self) -> &PathBuf {
        &self.program
    }

    fn json(&self, invocation: &Invocation, deadline: Instant) -> Result<Value, SourceError> {
        let out =
            process::run_with_read_timeout(&self.program, invocation, deadline, self.read_timeout)?;
        serde_json::from_slice::<UniqueKeys>(&out)
            .map(|UniqueKeys(value)| value)
            .map_err(|e| SourceError::Malformed {
                detail: not_json(&e),
            })
    }

    fn array(&self, invocation: &Invocation, deadline: Instant) -> Result<Vec<Value>, SourceError> {
        match self.json(invocation, deadline)? {
            Value::Array(rows) => Ok(rows),
            other => Err(shape("a JSON array", &other)),
        }
    }

    fn object(
        &self,
        invocation: &Invocation,
        deadline: Instant,
    ) -> Result<Map<String, Value>, SourceError> {
        match self.json(invocation, deadline)? {
            Value::Object(object) => Ok(object),
            other => Err(shape("a JSON object", &other)),
        }
    }

    fn projects(
        &self,
        hidden: bool,
        deadline: Instant,
        rows: &mut Rows<ProjectRecord>,
    ) -> Result<(), SourceError> {
        let read = self.read_name(Read::Projects);
        for (i, row) in self
            .array(&Invocation::ProjectList { hidden }, deadline)?
            .iter()
            .enumerate()
        {
            let Some((id, mut fields)) = identify(row, i, read, &mut rows.unreadable) else {
                continue;
            };
            let name = fields.string("name");
            rows.unreadable.extend(fields.problems);
            rows.records.push(ProjectRecord {
                id: ProjectId(id),
                name,
            });
        }
        Ok(())
    }

    fn detail_read(
        &self,
        id: &SessionId,
        invocation: impl FnOnce(ThreadId) -> Invocation,
        deadline: Instant,
    ) -> Result<Map<String, Value>, SourceError> {
        let thread_id = ThreadId::parse(&id.0).map_err(|_| SourceError::InvalidId {
            id: id.0.clone(),
            detail: "an id is 1 to 128 ASCII letters, digits, _ or -, not starting with -"
                .to_owned(),
        })?;
        self.object(&invocation(thread_id), deadline)
            .map_err(|e| match e {
                SourceError::CommandFailed { ref detail, .. }
                    if detail.starts_with(process::NOT_FOUND_LINE) =>
                {
                    SourceError::NotFound {
                        subject: id.0.clone(),
                    }
                }
                other => other,
            })
    }
}

impl SessionSource for CloudRoomSource {
    fn name(&self) -> &str {
        PROGRAM
    }

    fn tested_version(&self) -> &str {
        TESTED_VERSION
    }

    fn read_name(&self, read: Read) -> &str {
        match read {
            Read::Version => "room-cli --version",
            Read::Sessions => "thread list",
            Read::Projects => "project list",
            Read::Machines => "machine list",
            Read::SessionDetail => "thread show",
            Read::SessionOutput => "thread output",
        }
    }

    fn version(&self, deadline: Instant) -> Result<String, SourceError> {
        let out = process::run_with_read_timeout(
            &self.program,
            &Invocation::Version,
            deadline,
            self.read_timeout,
        )?;
        let version = String::from_utf8_lossy(&out).trim().to_owned();
        if version.is_empty() {
            return Err(SourceError::Malformed {
                detail: "printed no version".to_owned(),
            });
        }
        if !is_version_text(&version) {
            return Err(SourceError::Malformed {
                detail: VERSION_NOT_RECOGNISED.to_owned(),
            });
        }
        Ok(version)
    }

    fn list_sessions(
        &self,
        scope: SessionScope,
        deadline: Instant,
    ) -> Result<Rows<SessionRecord>, SourceError> {
        let invocation = Invocation::ThreadList {
            include_hidden: scope.include_hidden,
            include_archived: scope.include_archived,
        };
        let read = self.read_name(Read::Sessions);
        let mut rows = Rows {
            records: vec![],
            unreadable: vec![],
        };
        for (i, row) in self.array(&invocation, deadline)?.iter().enumerate() {
            let Some((id, mut fields)) = identify(row, i, read, &mut rows.unreadable) else {
                continue;
            };
            if ThreadId::parse(&id).is_err() {
                rows.unreadable.push(Gap {
                    kind: GapKind::WrongType,
                    subject: Some(format!("{read} row {}", i + 1)),
                    detail: format!(
                        "schema drift: {read} id (not 1 to 128 ASCII letters, digits, _ or -)"
                    ),
                });
                continue;
            }
            let placement = fields.list_placement();
            rows.records.push(fields.session(SessionId(id), placement));
        }
        Ok(rows)
    }

    fn list_projects(
        &self,
        include_hidden: bool,
        deadline: Instant,
    ) -> Result<Rows<ProjectRecord>, SourceError> {
        let mut rows = Rows {
            records: vec![],
            unreadable: vec![],
        };
        self.projects(false, deadline, &mut rows)?;
        if include_hidden {
            self.projects(true, deadline, &mut rows)?;
        }
        Ok(rows)
    }

    fn list_machines(&self, deadline: Instant) -> Result<Rows<MachineRecord>, SourceError> {
        let read = self.read_name(Read::Machines);
        let mut rows = Rows {
            records: vec![],
            unreadable: vec![],
        };
        for (i, row) in self
            .array(&Invocation::MachineList, deadline)?
            .iter()
            .enumerate()
        {
            let Some((id, mut fields)) = identify(row, i, read, &mut rows.unreadable) else {
                continue;
            };
            let name = fields.string("name");
            rows.unreadable.extend(fields.problems);
            rows.records.push(MachineRecord { id, name });
        }
        Ok(rows)
    }

    fn session_detail(
        &self,
        id: &SessionId,
        deadline: Instant,
    ) -> Result<SessionDetailRecord, SourceError> {
        let read = self.read_name(Read::SessionDetail);
        let doc = self.detail_read(id, Invocation::ThreadShow, deadline)?;
        let Some(Value::Object(thread)) = doc.get("thread") else {
            return Err(SourceError::Malformed {
                detail: "no thread object".to_owned(),
            });
        };
        let mut fields = Fields::new(thread, read, "thread.", &id.0);
        match fields.string("id") {
            Fact::Known(reported) if reported != id.0 => {
                return Err(SourceError::Malformed {
                    detail: format!(
                        "it describes a different session (id withheld), not {}",
                        id.0
                    ),
                });
            }
            _ => {}
        }
        let placement = fields.show_placement(&doc);
        let mut session = fields.session(id.clone(), placement);

        let mut doc_fields = Fields::new(&doc, read, "", &id.0);
        let (model, effort) = match doc_fields.get("execution") {
            Some(Value::Object(execution)) => {
                let mut f = Fields::new(execution, read, "execution.", &id.0);
                let pair = (f.string("model"), f.string("reasoningLevel"));
                session.problems.extend(f.problems);
                pair
            }
            Some(_) => {
                let why = doc_fields.wrong("execution");
                (Fact::Unknown(why.clone()), Fact::Unknown(why))
            }
            None => {
                let why = doc_fields.missing("execution");
                (Fact::Unknown(why.clone()), Fact::Unknown(why))
            }
        };
        session.problems.extend(doc_fields.problems);
        Ok(SessionDetailRecord {
            session,
            model,
            effort,
        })
    }

    fn session_output(
        &self,
        id: &SessionId,
        deadline: Instant,
    ) -> Result<OutputRecord, SourceError> {
        let read = self.read_name(Read::SessionOutput);
        let doc = self.detail_read(id, Invocation::ThreadOutput, deadline)?;
        let mut fields = Fields::new(&doc, read, "", &id.0);
        let output = fields.nullable_string("output");
        let error = fields.nullable_string("error");
        Ok(OutputRecord {
            output,
            error,
            problems: fields.problems,
        })
    }
}

struct UniqueKeys(Value);

impl<'de> Deserialize<'de> for UniqueKeys {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        d.deserialize_any(UniqueKeysVisitor).map(UniqueKeys)
    }
}

struct UniqueKeysVisitor;

impl<'de> Visitor<'de> for UniqueKeysVisitor {
    type Value = Value;

    fn expecting(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("JSON with unique object keys")
    }

    fn visit_unit<E: de::Error>(self) -> Result<Value, E> {
        Ok(Value::Null)
    }

    fn visit_bool<E: de::Error>(self, value: bool) -> Result<Value, E> {
        Ok(Value::Bool(value))
    }

    fn visit_i64<E: de::Error>(self, value: i64) -> Result<Value, E> {
        Ok(Value::Number(value.into()))
    }

    fn visit_u64<E: de::Error>(self, value: u64) -> Result<Value, E> {
        Ok(Value::Number(value.into()))
    }

    fn visit_f64<E: de::Error>(self, value: f64) -> Result<Value, E> {
        serde_json::Number::from_f64(value)
            .map(Value::Number)
            .ok_or_else(|| E::custom("not a JSON number"))
    }

    fn visit_str<E: de::Error>(self, value: &str) -> Result<Value, E> {
        Ok(Value::String(value.to_owned()))
    }

    fn visit_string<E: de::Error>(self, value: String) -> Result<Value, E> {
        Ok(Value::String(value))
    }

    fn visit_seq<A: SeqAccess<'de>>(self, mut sequence: A) -> Result<Value, A::Error> {
        let mut values = Vec::new();
        while let Some(UniqueKeys(value)) = sequence.next_element()? {
            values.push(value);
        }
        Ok(Value::Array(values))
    }

    fn visit_map<A: MapAccess<'de>>(self, mut object: A) -> Result<Value, A::Error> {
        let mut fields = Map::new();
        while let Some(key) = object.next_key::<String>()? {
            if fields.contains_key(&key) {
                return Err(de::Error::custom("a repeated object key"));
            }
            let UniqueKeys(value) = object.next_value()?;
            fields.insert(key, value);
        }
        Ok(Value::Object(fields))
    }
}

fn not_json(error: &serde_json::Error) -> String {
    let what = match error.classify() {
        Category::Io => "a read error",
        Category::Syntax => "a syntax error",
        Category::Data => "unexpected data",
        Category::Eof => "an early end",
    };
    format!(
        "not JSON ({what} at line {} column {})",
        error.line(),
        error.column()
    )
}

fn is_label(value: &str) -> bool {
    let b = value.as_bytes();
    (1..=32).contains(&b.len())
        && b[0].is_ascii_lowercase()
        && b.iter()
            .all(|&c| c.is_ascii_lowercase() || c == b'-' || c == b'_')
}

fn shape(expected: &str, got: &Value) -> SourceError {
    let kind = match got {
        Value::Null => "null",
        Value::Bool(_) => "a boolean",
        Value::Number(_) => "a number",
        Value::String(_) => "a string",
        Value::Array(_) => "an array",
        Value::Object(_) => "an object",
    };
    SourceError::Malformed {
        detail: format!("expected {expected}, got {kind}"),
    }
}

fn identify<'a>(
    row: &'a Value,
    i: usize,
    read: &'a str,
    unreadable: &mut Vec<Gap>,
) -> Option<(String, Fields<'a>)> {
    let subject = Some(format!("{read} row {}", i + 1));
    let Value::Object(object) = row else {
        unreadable.push(Gap {
            kind: GapKind::WrongType,
            subject,
            detail: format!("schema drift: {read} row (not an object)"),
        });
        return None;
    };
    let kind = match object.get("id") {
        Some(Value::String(id)) => {
            return Some((id.clone(), Fields::new(object, read, "", id)));
        }
        Some(_) => GapKind::WrongType,
        None => GapKind::MissingField,
    };
    unreadable.push(Gap {
        kind,
        subject,
        detail: format!("schema drift: {read} id"),
    });
    None
}

struct Fields<'a> {
    object: &'a Map<String, Value>,
    read: &'a str,
    prefix: &'a str,
    subject: String,
    problems: Vec<Gap>,
}

impl<'a> Fields<'a> {
    fn new(object: &'a Map<String, Value>, read: &'a str, prefix: &'a str, subject: &str) -> Self {
        Self {
            object,
            read,
            prefix,
            subject: subject.to_owned(),
            problems: vec![],
        }
    }

    fn get(&self, key: &str) -> Option<&'a Value> {
        self.object.get(key)
    }

    fn drift(&mut self, kind: GapKind, key: &str) -> String {
        let field = format!("{}{key}", self.prefix);
        self.problems.push(Gap {
            kind,
            subject: Some(self.subject.clone()),
            detail: format!("schema drift: {} {field}", self.read),
        });
        format!("schema: {field}")
    }

    fn missing(&mut self, key: &str) -> String {
        self.drift(GapKind::MissingField, key)
    }

    fn wrong(&mut self, key: &str) -> String {
        self.drift(GapKind::WrongType, key)
    }

    fn unrecognised(&mut self, key: &str, value: &str) -> String {
        let field = format!("{}{key}", self.prefix);
        self.problems.push(Gap {
            kind: GapKind::WrongType,
            subject: Some(self.subject.clone()),
            detail: format!(
                "schema drift: {} {field} (a value 0.43.1 did not have)",
                self.read
            ),
        });
        if is_label(value) {
            format!("schema: {field} is {value}, which is not recognised")
        } else {
            format!("schema: {field} has a value that is not recognised (value withheld)")
        }
    }

    fn string(&mut self, key: &str) -> Fact<String> {
        match self.get(key) {
            Some(Value::String(s)) => Fact::Known(s.clone()),
            Some(_) => Fact::Unknown(self.wrong(key)),
            None => Fact::Unknown(self.missing(key)),
        }
    }

    fn int(&mut self, key: &str) -> Fact<i64> {
        match self.get(key).map(|v| (v, v.as_i64())) {
            Some((_, Some(n))) => Fact::Known(n),
            Some((_, None)) => Fact::Unknown(self.wrong(key)),
            None => Fact::Unknown(self.missing(key)),
        }
    }

    fn nullable_string(&mut self, key: &str) -> Fact<Option<String>> {
        match self.get(key) {
            Some(Value::String(s)) => Fact::Known(Some(s.clone())),
            Some(Value::Null) => Fact::Known(None),
            Some(_) => Fact::Unknown(self.wrong(key)),
            None => Fact::Unknown(self.missing(key)),
        }
    }

    fn nullable_int(&mut self, key: &str) -> Fact<Option<i64>> {
        match self.get(key) {
            Some(Value::Null) => Fact::Known(None),
            Some(v) => match v.as_i64() {
                Some(n) => Fact::Known(Some(n)),
                None => Fact::Unknown(self.wrong(key)),
            },
            None => Fact::Unknown(self.missing(key)),
        }
    }

    fn session(mut self, id: SessionId, placement: Fact<Placement>) -> SessionRecord {
        let hidden = match self.string("visibility") {
            Fact::Known(v) if v == "hidden" => Fact::Known(true),
            Fact::Known(v) if v == "visible" => Fact::Known(false),
            Fact::Known(v) => Fact::Unknown(self.unrecognised("visibility", &v)),
            Fact::Unknown(why) => Fact::Unknown(why),
        };
        SessionRecord {
            project_id: self.string("projectId").map(ProjectId),
            title: self.string("title"),
            provider: self.string("providerId"),
            status: self.string("status"),
            hidden,
            archived: self.nullable_int("archivedAt").map(|at| at.is_some()),
            parent: self
                .nullable_string("parentThreadId")
                .map(|p| p.map(SessionId)),
            purpose_text: self.purpose(),
            updated_at: self.int("updatedAt").map(Timestamp),
            started_at: self.started_at(),
            placement,
            id,
            problems: self.problems,
        }
    }

    fn started_at(&self) -> Fact<Timestamp> {
        match self.get("startedAt") {
            None => Fact::Unknown("room-cli did not report a start time".to_owned()),
            Some(v) => match v.as_i64() {
                Some(at) if at >= 0 => Fact::Known(Timestamp(at)),
                _ => Fact::Unknown(
                    "room-cli reported startedAt, but not as a nonnegative integer".to_owned(),
                ),
            },
        }
    }

    fn purpose(&mut self) -> Fact<Option<String>> {
        match self.get("purpose") {
            None => Fact::Known(None),
            Some(Value::Object(purpose)) => match purpose.get("text") {
                Some(Value::String(text)) => Fact::Known(Some(text.clone())),
                Some(_) => Fact::Unknown(self.wrong("purpose.text")),
                None => Fact::Unknown(self.missing("purpose.text")),
            },
            Some(_) => Fact::Unknown(self.wrong("purpose")),
        }
    }

    fn execution_target(&mut self) -> Option<Fact<Placement>> {
        Some(match self.get("executionTarget")? {
            Value::String(target) if target == "cloud" => Fact::Known(Placement::Cloud),
            Value::String(target) => Fact::Unknown(self.unrecognised("executionTarget", target)),
            _ => Fact::Unknown(self.wrong("executionTarget")),
        })
    }

    fn list_placement(&mut self) -> Fact<Placement> {
        if let Some(placement) = self.execution_target() {
            return placement;
        }
        match self.nullable_string("environmentHostId") {
            Fact::Known(Some(host)) => Fact::Known(Placement::Host(host)),
            Fact::Known(None) => {
                Fact::Unknown("no executionTarget and no environmentHostId".to_owned())
            }
            Fact::Unknown(why) => Fact::Unknown(why),
        }
    }

    fn show_placement(&mut self, doc: &Map<String, Value>) -> Fact<Placement> {
        if let Some(placement) = self.execution_target() {
            return placement;
        }
        let mut top = Fields::new(doc, self.read, "", &self.subject);
        let placement = match top.get("environment") {
            Some(Value::Object(environment)) => {
                let mut env = Fields::new(environment, self.read, "environment.", &self.subject);
                let host = env.string("hostId").map(Placement::Host);
                top.problems.extend(env.problems);
                host
            }
            Some(Value::Null) => {
                Fact::Unknown("no thread.executionTarget and no environment".to_owned())
            }
            Some(_) => Fact::Unknown(top.wrong("environment")),
            None => Fact::Unknown(top.missing("environment")),
        };
        self.problems.extend(top.problems);
        placement
    }
}
