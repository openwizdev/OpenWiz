use std::borrow::Cow;
use std::fmt;

use openwiz_core::fleet::fleets::{IssueRow, Link, Links, PrFacts, PrRow, StockPr};
use openwiz_core::fleet::model::{
    Check, CheckResult, Commit, IssueState, Milestone, NonEmpty, Number,
};
use openwiz_core::model::{Fact, Timestamp};
use serde::de::{self, Deserialize, Deserializer, MapAccess, SeqAccess, Visitor};

macro_rules! fast_seq {
    ($list:ident, $item:ident, $elem:ty) => {
        struct $list(Vec<$elem>);
        impl<'de> Deserialize<'de> for $list {
            fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
                struct V;
                impl<'de> Visitor<'de> for V {
                    type Value = $list;
                    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                        f.write_str("a JSON array")
                    }
                    fn visit_seq<A: SeqAccess<'de>>(
                        self,
                        mut seq: A,
                    ) -> Result<Self::Value, A::Error> {
                        let mut out = Vec::new();
                        while let Some($item(v)) = seq.next_element()? {
                            out.push(v);
                        }
                        Ok($list(out))
                    }
                }
                d.deserialize_seq(V)
            }
        }
    };
}

pub(crate) struct Text<'de>(pub(crate) Cow<'de, str>);

impl<'de> Text<'de> {
    pub(crate) fn as_str(&self) -> &str {
        &self.0
    }

    pub(crate) fn into_owned(self) -> String {
        self.0.into_owned()
    }
}

impl<'de> Deserialize<'de> for Text<'de> {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        struct V;
        impl<'de> Visitor<'de> for V {
            type Value = Text<'de>;
            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("a string")
            }
            fn visit_borrowed_str<E: de::Error>(self, s: &'de str) -> Result<Self::Value, E> {
                Ok(Text(Cow::Borrowed(s)))
            }
            fn visit_str<E: de::Error>(self, s: &str) -> Result<Self::Value, E> {
                Ok(Text(Cow::Owned(s.to_owned())))
            }
            fn visit_string<E: de::Error>(self, s: String) -> Result<Self::Value, E> {
                Ok(Text(Cow::Owned(s)))
            }
        }
        d.deserialize_str(V)
    }
}

pub(crate) struct DiscardedText;

impl<'de> Deserialize<'de> for DiscardedText {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        struct V;
        impl<'de> Visitor<'de> for V {
            type Value = DiscardedText;
            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("a string")
            }
            fn visit_str<E: de::Error>(self, _: &str) -> Result<Self::Value, E> {
                Ok(DiscardedText)
            }
        }
        d.deserialize_str(V)
    }
}

struct NullOrDiscardedText;

impl<'de> Deserialize<'de> for NullOrDiscardedText {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        struct V;
        impl<'de> Visitor<'de> for V {
            type Value = NullOrDiscardedText;
            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("null or a string")
            }
            fn visit_none<E: de::Error>(self) -> Result<Self::Value, E> {
                Ok(NullOrDiscardedText)
            }
            fn visit_some<D: Deserializer<'de>>(self, d: D) -> Result<Self::Value, D::Error> {
                let _ = DiscardedText::deserialize(d)?;
                Ok(NullOrDiscardedText)
            }
        }
        d.deserialize_option(V)
    }
}

pub(crate) struct FastCount(pub(crate) u64);

impl<'de> Deserialize<'de> for FastCount {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        struct V;
        impl<'de> Visitor<'de> for V {
            type Value = FastCount;
            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("a whole number")
            }
            fn visit_u64<E: de::Error>(self, n: u64) -> Result<Self::Value, E> {
                Ok(FastCount(n))
            }
            fn visit_i64<E: de::Error>(self, n: i64) -> Result<Self::Value, E> {
                u64::try_from(n)
                    .map(FastCount)
                    .map_err(|_| de::Error::custom("below zero"))
            }
        }
        d.deserialize_any(V)
    }
}

pub(crate) struct FastNumber(pub(crate) Number);

impl<'de> Deserialize<'de> for FastNumber {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        let FastCount(n) = FastCount::deserialize(d)?;
        Number::new(n)
            .map(FastNumber)
            .ok_or_else(|| de::Error::custom("not 1 or more"))
    }
}

pub(crate) struct FastNonEmpty(pub(crate) NonEmpty);

impl<'de> Deserialize<'de> for FastNonEmpty {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        struct V;
        impl<'de> Visitor<'de> for V {
            type Value = FastNonEmpty;
            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("a non-empty string")
            }
            fn visit_str<E: de::Error>(self, s: &str) -> Result<Self::Value, E> {
                if s.is_empty() {
                    return Err(de::Error::custom("empty"));
                }
                Ok(FastNonEmpty(NonEmpty::new(s).expect("non-empty")))
            }
            fn visit_string<E: de::Error>(self, s: String) -> Result<Self::Value, E> {
                NonEmpty::new(s)
                    .map(FastNonEmpty)
                    .ok_or_else(|| de::Error::custom("empty"))
            }
        }
        d.deserialize_str(V)
    }
}

pub(crate) struct FastCommit(pub(crate) Commit);

impl<'de> Deserialize<'de> for FastCommit {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        struct V;
        impl<'de> Visitor<'de> for V {
            type Value = FastCommit;
            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("a 40-char commit")
            }
            fn visit_str<E: de::Error>(self, s: &str) -> Result<Self::Value, E> {
                Commit::parse(s)
                    .map(FastCommit)
                    .ok_or_else(|| de::Error::custom("not a commit"))
            }
        }
        d.deserialize_str(V)
    }
}

pub(crate) struct FastOptMergeCommit(pub(crate) Option<Commit>);

impl<'de> Deserialize<'de> for FastOptMergeCommit {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        struct MergeObj(Commit);
        impl<'de> Deserialize<'de> for MergeObj {
            fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
                struct V;
                impl<'de> Visitor<'de> for V {
                    type Value = MergeObj;
                    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                        f.write_str("a mergeCommit object")
                    }
                    fn visit_map<A: MapAccess<'de>>(
                        self,
                        mut map: A,
                    ) -> Result<Self::Value, A::Error> {
                        let mut oid = None;
                        while let Some(key) = map.next_key::<Text<'de>>()? {
                            if key.as_str() != "oid" || oid.is_some() {
                                return Err(de::Error::custom("bad mergeCommit"));
                            }
                            oid = Some(map.next_value::<FastCommit>()?.0);
                        }
                        oid.map(MergeObj)
                            .ok_or_else(|| de::Error::custom("missing oid"))
                    }
                }
                d.deserialize_map(V)
            }
        }
        struct OptV;
        impl<'de> Visitor<'de> for OptV {
            type Value = FastOptMergeCommit;
            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("null or mergeCommit")
            }
            fn visit_none<E: de::Error>(self) -> Result<Self::Value, E> {
                Ok(FastOptMergeCommit(None))
            }
            fn visit_some<D: Deserializer<'de>>(self, d: D) -> Result<Self::Value, D::Error> {
                MergeObj::deserialize(d).map(|m| FastOptMergeCommit(Some(m.0)))
            }
        }
        d.deserialize_option(OptV)
    }
}

pub(crate) struct FastClosingRepo;

impl<'de> Deserialize<'de> for FastClosingRepo {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        struct Owner;
        impl<'de> Deserialize<'de> for Owner {
            fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
                struct V;
                impl<'de> Visitor<'de> for V {
                    type Value = Owner;
                    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                        f.write_str("an owner object")
                    }
                    fn visit_map<A: MapAccess<'de>>(
                        self,
                        mut map: A,
                    ) -> Result<Self::Value, A::Error> {
                        let mut seen = 0u8;
                        while let Some(key) = map.next_key::<Text<'de>>()? {
                            let bit = match key.as_str() {
                                "id" => 1 << 0,
                                "login" => 1 << 1,
                                _ => return Err(de::Error::custom("extra key")),
                            };
                            if seen & bit != 0 {
                                return Err(de::Error::custom("duplicate key"));
                            }
                            seen |= bit;
                            let _ = map.next_value::<DiscardedText>()?;
                        }
                        if seen != 0b11 {
                            return Err(de::Error::custom("missing key"));
                        }
                        Ok(Owner)
                    }
                }
                d.deserialize_map(V)
            }
        }
        struct V;
        impl<'de> Visitor<'de> for V {
            type Value = FastClosingRepo;
            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("a repository object")
            }
            fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Self::Value, A::Error> {
                let mut seen = 0u8;
                while let Some(key) = map.next_key::<Text<'de>>()? {
                    match key.as_str() {
                        "id" if seen & 1 == 0 => {
                            seen |= 1;
                            let _ = map.next_value::<DiscardedText>()?;
                        }
                        "name" if seen & 2 == 0 => {
                            seen |= 2;
                            let _ = map.next_value::<DiscardedText>()?;
                        }
                        "owner" if seen & 4 == 0 => {
                            seen |= 4;
                            let _ = map.next_value::<Owner>()?;
                        }
                        _ => return Err(de::Error::custom("bad repository")),
                    }
                }
                if seen != 0b111 {
                    return Err(de::Error::custom("missing key"));
                }
                Ok(FastClosingRepo)
            }
        }
        d.deserialize_map(V)
    }
}

pub(crate) enum FastPrState {
    Open,
    Merged,
    Closed,
}

impl<'de> Deserialize<'de> for FastPrState {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        struct V;
        impl<'de> Visitor<'de> for V {
            type Value = FastPrState;
            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("OPEN, MERGED or CLOSED")
            }
            fn visit_str<E: de::Error>(self, s: &str) -> Result<Self::Value, E> {
                match s {
                    "OPEN" => Ok(FastPrState::Open),
                    "MERGED" => Ok(FastPrState::Merged),
                    "CLOSED" => Ok(FastPrState::Closed),
                    _ => Err(de::Error::custom("bad state")),
                }
            }
        }
        d.deserialize_str(V)
    }
}

struct FastIssueState(IssueState);

impl<'de> Deserialize<'de> for FastIssueState {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        struct V;
        impl<'de> Visitor<'de> for V {
            type Value = FastIssueState;
            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("OPEN or CLOSED")
            }
            fn visit_str<E: de::Error>(self, s: &str) -> Result<Self::Value, E> {
                match s {
                    "OPEN" => Ok(FastIssueState(IssueState::Open)),
                    "CLOSED" => Ok(FastIssueState(IssueState::Closed)),
                    _ => Err(de::Error::custom("bad state")),
                }
            }
        }
        d.deserialize_str(V)
    }
}

struct FastOptMilestone(Option<Milestone>);

impl<'de> Deserialize<'de> for FastOptMilestone {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        struct M(Milestone);
        impl<'de> Deserialize<'de> for M {
            fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
                struct V;
                impl<'de> Visitor<'de> for V {
                    type Value = M;
                    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                        f.write_str("a milestone object")
                    }
                    fn visit_map<A: MapAccess<'de>>(
                        self,
                        mut map: A,
                    ) -> Result<Self::Value, A::Error> {
                        let mut seen = 0u8;
                        let mut number = None;
                        let mut title = None;
                        while let Some(key) = map.next_key::<Text<'de>>()? {
                            match key.as_str() {
                                "description" if seen & 1 == 0 => {
                                    seen |= 1;
                                    let _ = map.next_value::<DiscardedText>()?;
                                }
                                "dueOn" if seen & 2 == 0 => {
                                    seen |= 2;
                                    let _ = map.next_value::<NullOrDiscardedText>()?;
                                }
                                "number" if seen & 4 == 0 => {
                                    seen |= 4;
                                    number = Some(map.next_value::<FastNumber>()?.0);
                                }
                                "title" if seen & 8 == 0 => {
                                    seen |= 8;
                                    title = Some(map.next_value::<String>()?);
                                }
                                _ => return Err(de::Error::custom("bad milestone")),
                            }
                        }
                        if seen != 0b1111 {
                            return Err(de::Error::custom("missing milestone field"));
                        }
                        Ok(M(Milestone {
                            number: number.expect("seen"),
                            title: title.expect("seen"),
                        }))
                    }
                }
                d.deserialize_map(V)
            }
        }
        struct OptV;
        impl<'de> Visitor<'de> for OptV {
            type Value = FastOptMilestone;
            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("null or milestone")
            }
            fn visit_none<E: de::Error>(self) -> Result<Self::Value, E> {
                Ok(FastOptMilestone(None))
            }
            fn visit_some<D: Deserializer<'de>>(self, d: D) -> Result<Self::Value, D::Error> {
                M::deserialize(d).map(|m| FastOptMilestone(Some(m.0)))
            }
        }
        d.deserialize_option(OptV)
    }
}

struct FastLabel(NonEmpty);

impl<'de> Deserialize<'de> for FastLabel {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        struct V;
        impl<'de> Visitor<'de> for V {
            type Value = FastLabel;
            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("a label object")
            }
            fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Self::Value, A::Error> {
                let mut seen = 0u8;
                let mut name = None;
                while let Some(key) = map.next_key::<Text<'de>>()? {
                    match key.as_str() {
                        "color" if seen & 1 == 0 => {
                            seen |= 1;
                            let _ = map.next_value::<DiscardedText>()?;
                        }
                        "description" if seen & 2 == 0 => {
                            seen |= 2;
                            let _ = map.next_value::<DiscardedText>()?;
                        }
                        "id" if seen & 4 == 0 => {
                            seen |= 4;
                            let _ = map.next_value::<DiscardedText>()?;
                        }
                        "name" if seen & 8 == 0 => {
                            seen |= 8;
                            name = Some(map.next_value::<FastNonEmpty>()?.0);
                        }
                        _ => return Err(de::Error::custom("bad label")),
                    }
                }
                if seen != 0b1111 {
                    return Err(de::Error::custom("missing label field"));
                }
                Ok(FastLabel(name.expect("seen")))
            }
        }
        d.deserialize_map(V)
    }
}

fast_seq!(FastLabels, FastLabel, NonEmpty);

struct FastLink(Link);

impl<'de> Deserialize<'de> for FastLink {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        struct V;
        impl<'de> Visitor<'de> for V {
            type Value = FastLink;
            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("a link object")
            }
            fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Self::Value, A::Error> {
                let mut seen = 0u8;
                let mut id = None;
                let mut number = None;
                while let Some(key) = map.next_key::<Text<'de>>()? {
                    match key.as_str() {
                        "id" if seen & 1 == 0 => {
                            seen |= 1;
                            id = Some(map.next_value::<FastNonEmpty>()?.0);
                        }
                        "number" if seen & 2 == 0 => {
                            seen |= 2;
                            number = Some(map.next_value::<FastNumber>()?.0);
                        }
                        "state" if seen & 4 == 0 => {
                            seen |= 4;
                            let _ = map.next_value::<DiscardedText>()?;
                        }
                        "title" if seen & 8 == 0 => {
                            seen |= 8;
                            let _ = map.next_value::<DiscardedText>()?;
                        }
                        "url" if seen & 16 == 0 => {
                            seen |= 16;
                            let _ = map.next_value::<DiscardedText>()?;
                        }
                        _ => return Err(de::Error::custom("bad link")),
                    }
                }
                if seen != 0b11111 {
                    return Err(de::Error::custom("missing link field"));
                }
                Ok(FastLink(Link {
                    number: number.expect("seen"),
                    id: id.expect("seen"),
                }))
            }
        }
        d.deserialize_map(V)
    }
}

fast_seq!(FastLinkVec, FastLink, Link);

struct FastLinks(Links);

impl<'de> Deserialize<'de> for FastLinks {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        struct V;
        impl<'de> Visitor<'de> for V {
            type Value = FastLinks;
            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("a links object")
            }
            fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Self::Value, A::Error> {
                let mut seen = 0u8;
                let mut nodes = None;
                let mut total = None;
                while let Some(key) = map.next_key::<Text<'de>>()? {
                    match key.as_str() {
                        "nodes" if seen & 1 == 0 => {
                            seen |= 1;
                            nodes = Some(map.next_value::<FastLinkVec>()?.0);
                        }
                        "totalCount" if seen & 2 == 0 => {
                            seen |= 2;
                            total = Some(map.next_value::<FastCount>()?.0);
                        }
                        _ => return Err(de::Error::custom("bad links")),
                    }
                }
                if seen != 0b11 {
                    return Err(de::Error::custom("missing links field"));
                }
                Ok(FastLinks(Links {
                    nodes: nodes.expect("seen"),
                    total: total.expect("seen"),
                }))
            }
        }
        d.deserialize_map(V)
    }
}

struct FastIssueRow(IssueRow);

impl<'de> Deserialize<'de> for FastIssueRow {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        struct V;
        impl<'de> Visitor<'de> for V {
            type Value = FastIssueRow;
            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("an issue row")
            }
            fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Self::Value, A::Error> {
                let mut seen = 0u16;
                let mut blocked_by = None;
                let mut body = None;
                let mut id = None;
                let mut labels = None;
                let mut milestone = None;
                let mut number = None;
                let mut state = None;
                let mut sub_issues = None;
                let mut title = None;
                while let Some(key) = map.next_key::<Text<'de>>()? {
                    match key.as_str() {
                        "blockedBy" if seen & (1 << 0) == 0 => {
                            seen |= 1 << 0;
                            blocked_by = Some(map.next_value::<FastLinks>()?.0);
                        }
                        "body" if seen & (1 << 1) == 0 => {
                            seen |= 1 << 1;
                            body = Some(map.next_value::<String>()?);
                        }
                        "id" if seen & (1 << 2) == 0 => {
                            seen |= 1 << 2;
                            id = Some(map.next_value::<FastNonEmpty>()?.0);
                        }
                        "labels" if seen & (1 << 3) == 0 => {
                            seen |= 1 << 3;
                            labels = Some(map.next_value::<FastLabels>()?.0);
                        }
                        "milestone" if seen & (1 << 4) == 0 => {
                            seen |= 1 << 4;
                            milestone = Some(map.next_value::<FastOptMilestone>()?.0);
                        }
                        "number" if seen & (1 << 5) == 0 => {
                            seen |= 1 << 5;
                            number = Some(map.next_value::<FastNumber>()?.0);
                        }
                        "state" if seen & (1 << 6) == 0 => {
                            seen |= 1 << 6;
                            state = Some(map.next_value::<FastIssueState>()?.0);
                        }
                        "subIssues" if seen & (1 << 7) == 0 => {
                            seen |= 1 << 7;
                            sub_issues = Some(map.next_value::<FastLinks>()?.0);
                        }
                        "title" if seen & (1 << 8) == 0 => {
                            seen |= 1 << 8;
                            title = Some(map.next_value::<String>()?);
                        }
                        _ => return Err(de::Error::custom("bad issue row")),
                    }
                }
                if seen != (1 << 9) - 1 {
                    return Err(de::Error::custom("missing issue field"));
                }
                Ok(FastIssueRow(IssueRow {
                    number: number.expect("seen"),
                    id: id.expect("seen"),
                    title: title.expect("seen"),
                    state: state.expect("seen"),
                    milestone: milestone.expect("seen"),
                    labels: labels.expect("seen"),
                    body: body.expect("seen"),
                    sub_issues: sub_issues.expect("seen"),
                    blocked_by: blocked_by.expect("seen"),
                }))
            }
        }
        d.deserialize_map(V)
    }
}

fast_seq!(FastIssueList, FastIssueRow, IssueRow);

struct FastClosingRef(Link);

impl<'de> Deserialize<'de> for FastClosingRef {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        struct V;
        impl<'de> Visitor<'de> for V {
            type Value = FastClosingRef;
            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("a closing reference")
            }
            fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Self::Value, A::Error> {
                let mut seen = 0u8;
                let mut id = None;
                let mut number = None;
                while let Some(key) = map.next_key::<Text<'de>>()? {
                    match key.as_str() {
                        "id" if seen & 1 == 0 => {
                            seen |= 1;
                            id = Some(map.next_value::<FastNonEmpty>()?.0);
                        }
                        "number" if seen & 2 == 0 => {
                            seen |= 2;
                            number = Some(map.next_value::<FastNumber>()?.0);
                        }
                        "repository" if seen & 4 == 0 => {
                            seen |= 4;
                            let _ = map.next_value::<FastClosingRepo>()?;
                        }
                        "url" if seen & 8 == 0 => {
                            seen |= 8;
                            let _ = map.next_value::<DiscardedText>()?;
                        }
                        _ => return Err(de::Error::custom("bad closing ref")),
                    }
                }
                if seen != 0b1111 {
                    return Err(de::Error::custom("missing closing ref field"));
                }
                Ok(FastClosingRef(Link {
                    number: number.expect("seen"),
                    id: id.expect("seen"),
                }))
            }
        }
        d.deserialize_map(V)
    }
}

fast_seq!(FastClosingRefs, FastClosingRef, Link);

struct FastOptFleetTime(Option<Timestamp>);

impl<'de> Deserialize<'de> for FastOptFleetTime {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        struct TimeStr(Timestamp);
        impl<'de> Deserialize<'de> for TimeStr {
            fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
                struct V;
                impl<'de> Visitor<'de> for V {
                    type Value = TimeStr;
                    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                        f.write_str("a UTC timestamp")
                    }
                    fn visit_str<E: de::Error>(self, s: &str) -> Result<Self::Value, E> {
                        super::time(s)
                            .map(TimeStr)
                            .ok_or_else(|| de::Error::custom("bad time"))
                    }
                }
                d.deserialize_str(V)
            }
        }
        struct OptV;
        impl<'de> Visitor<'de> for OptV {
            type Value = FastOptFleetTime;
            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("null or UTC timestamp")
            }
            fn visit_none<E: de::Error>(self) -> Result<Self::Value, E> {
                Ok(FastOptFleetTime(None))
            }
            fn visit_some<D: Deserializer<'de>>(self, d: D) -> Result<Self::Value, D::Error> {
                TimeStr::deserialize(d).map(|t| FastOptFleetTime(Some(t.0)))
            }
        }
        d.deserialize_option(OptV)
    }
}

struct FastStockPr(StockPr);

impl<'de> Deserialize<'de> for FastStockPr {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        struct V;
        impl<'de> Visitor<'de> for V {
            type Value = FastStockPr;
            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("a pull request row")
            }
            fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Self::Value, A::Error> {
                let mut seen = 0u16;
                let mut base_ref: Option<Text<'de>> = None;
                let mut closes = None;
                let mut head_ref: Option<Text<'de>> = None;
                let mut head_oid: Option<Text<'de>> = None;
                let mut draft = None;
                let mut merge_commit = None;
                let mut merged_at = None;
                let mut number = None;
                let mut state = None;
                let mut title = None;
                while let Some(key) = map.next_key::<Text<'de>>()? {
                    match key.as_str() {
                        "baseRefName" if seen & (1 << 0) == 0 => {
                            seen |= 1 << 0;
                            base_ref = Some(map.next_value::<Text<'de>>()?);
                        }
                        "closingIssuesReferences" if seen & (1 << 1) == 0 => {
                            seen |= 1 << 1;
                            closes = Some(map.next_value::<FastClosingRefs>()?.0);
                        }
                        "headRefName" if seen & (1 << 2) == 0 => {
                            seen |= 1 << 2;
                            head_ref = Some(map.next_value::<Text<'de>>()?);
                        }
                        "headRefOid" if seen & (1 << 3) == 0 => {
                            seen |= 1 << 3;
                            head_oid = Some(map.next_value::<Text<'de>>()?);
                        }
                        "isDraft" if seen & (1 << 4) == 0 => {
                            seen |= 1 << 4;
                            draft = Some(map.next_value::<bool>()?);
                        }
                        "mergeCommit" if seen & (1 << 5) == 0 => {
                            seen |= 1 << 5;
                            merge_commit = Some(map.next_value::<FastOptMergeCommit>()?.0);
                        }
                        "mergedAt" if seen & (1 << 6) == 0 => {
                            seen |= 1 << 6;
                            merged_at = Some(map.next_value::<FastOptFleetTime>()?.0);
                        }
                        "number" if seen & (1 << 7) == 0 => {
                            seen |= 1 << 7;
                            number = Some(map.next_value::<FastNumber>()?.0);
                        }
                        "state" if seen & (1 << 8) == 0 => {
                            seen |= 1 << 8;
                            state = Some(map.next_value::<FastPrState>()?);
                        }
                        "title" if seen & (1 << 9) == 0 => {
                            seen |= 1 << 9;
                            title = Some(map.next_value::<FastNonEmpty>()?.0);
                        }
                        _ => return Err(de::Error::custom("bad pr row")),
                    }
                }
                if seen != (1 << 10) - 1 {
                    return Err(de::Error::custom("missing pr field"));
                }
                let number = number.expect("seen");
                let title = Fact::Known(title.expect("seen"));
                let merge_commit = merge_commit.expect("seen");
                let merged_at = merged_at.expect("seen");
                match state.expect("seen") {
                    FastPrState::Closed => {
                        if merge_commit.is_some() || merged_at.is_some() {
                            return Err(de::Error::custom("closed with merge"));
                        }
                        Ok(FastStockPr(StockPr {
                            pr: PrRow::Closed { number },
                            title,
                        }))
                    }
                    FastPrState::Open => {
                        if merge_commit.is_some() || merged_at.is_some() {
                            return Err(de::Error::custom("open with merge"));
                        }
                        let facts = PrFacts {
                            number,
                            draft: draft.expect("seen"),
                            head_branch: NonEmpty::new(head_ref.expect("seen").into_owned())
                                .ok_or_else(|| de::Error::custom("empty head"))?,
                            head_commit: Commit::parse(head_oid.expect("seen").as_str())
                                .ok_or_else(|| de::Error::custom("bad head commit"))?,
                            base_branch: NonEmpty::new(base_ref.expect("seen").into_owned())
                                .ok_or_else(|| de::Error::custom("empty base"))?,
                            closes: closes.expect("seen"),
                        };
                        Ok(FastStockPr(StockPr {
                            pr: PrRow::Open(facts),
                            title,
                        }))
                    }
                    FastPrState::Merged => {
                        let (Some(merge_commit), Some(merged_at)) = (merge_commit, merged_at)
                        else {
                            return Err(de::Error::custom("merged without merge"));
                        };
                        let facts = PrFacts {
                            number,
                            draft: draft.expect("seen"),
                            head_branch: NonEmpty::new(head_ref.expect("seen").into_owned())
                                .ok_or_else(|| de::Error::custom("empty head"))?,
                            head_commit: Commit::parse(head_oid.expect("seen").as_str())
                                .ok_or_else(|| de::Error::custom("bad head commit"))?,
                            base_branch: NonEmpty::new(base_ref.expect("seen").into_owned())
                                .ok_or_else(|| de::Error::custom("empty base"))?,
                            closes: closes.expect("seen"),
                        };
                        Ok(FastStockPr(StockPr {
                            pr: PrRow::Merged {
                                facts,
                                merge_commit,
                                merged_at,
                            },
                            title,
                        }))
                    }
                }
            }
        }
        d.deserialize_map(V)
    }
}

fast_seq!(FastStockPrList, FastStockPr, StockPr);

struct FastBucket(CheckResult);

impl<'de> Deserialize<'de> for FastBucket {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        struct V;
        impl<'de> Visitor<'de> for V {
            type Value = FastBucket;
            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("a check bucket")
            }
            fn visit_str<E: de::Error>(self, s: &str) -> Result<Self::Value, E> {
                match s {
                    "pass" => Ok(FastBucket(CheckResult::Pass)),
                    "fail" => Ok(FastBucket(CheckResult::Fail)),
                    "pending" => Ok(FastBucket(CheckResult::Pending)),
                    "skipping" => Ok(FastBucket(CheckResult::Skipping)),
                    "cancel" => Ok(FastBucket(CheckResult::Cancel)),
                    _ => Err(de::Error::custom("bad bucket")),
                }
            }
        }
        d.deserialize_str(V)
    }
}

struct FastCheck(Check);

impl<'de> Deserialize<'de> for FastCheck {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        struct V;
        impl<'de> Visitor<'de> for V {
            type Value = FastCheck;
            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("a check row")
            }
            fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Self::Value, A::Error> {
                let mut seen = 0u8;
                let mut bucket = None;
                let mut name = None;
                while let Some(key) = map.next_key::<Text<'de>>()? {
                    match key.as_str() {
                        "bucket" if seen & 1 == 0 => {
                            seen |= 1;
                            bucket = Some(map.next_value::<FastBucket>()?.0);
                        }
                        "name" if seen & 2 == 0 => {
                            seen |= 2;
                            name = Some(map.next_value::<FastNonEmpty>()?.0);
                        }
                        _ => return Err(de::Error::custom("bad check")),
                    }
                }
                if seen != 0b11 {
                    return Err(de::Error::custom("missing check field"));
                }
                Ok(FastCheck(Check {
                    name: name.expect("seen"),
                    result: bucket.expect("seen"),
                }))
            }
        }
        d.deserialize_map(V)
    }
}

fast_seq!(FastCheckList, FastCheck, Check);

pub(crate) fn parse_issues(out: &[u8]) -> Result<Vec<IssueRow>, ()> {
    serde_json::from_slice::<FastIssueList>(out)
        .map(|x| x.0)
        .map_err(|_| ())
}

pub(crate) fn parse_stock_prs(out: &[u8]) -> Result<Vec<StockPr>, ()> {
    serde_json::from_slice::<FastStockPrList>(out)
        .map(|x| x.0)
        .map_err(|_| ())
}

pub(crate) fn parse_checks(out: &[u8]) -> Result<Vec<Check>, ()> {
    serde_json::from_slice::<FastCheckList>(out)
        .map(|x| x.0)
        .map_err(|_| ())
}
