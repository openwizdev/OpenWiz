use std::collections::BTreeSet;

use serde::Serialize;

use crate::models::{self, Choice, Pick, Show, SpawnFlags};

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct AgentRule {
    pub harness: String,
    pub model: String,
    pub effort: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct RequiredCheck {
    pub name: String,
    pub required_on: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Rules {
    pub(crate) builder: AgentRule,
    pub(crate) builder_small: AgentRule,
    pub(crate) reviewer_claude: Option<AgentRule>,
    pub(crate) reviewer_gpt: Option<AgentRule>,
    pub(crate) ci_checks: Vec<RequiredCheck>,
    pub(crate) merge: MergeRule,
    #[serde(skip)]
    pub(crate) fixers: [Option<AgentRule>; 2],
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MergeRule {
    #[serde(rename = "adr_0008")]
    Adr0008,
    None,
}

struct Agents {
    builder: AgentRule,
    builder_small: AgentRule,
    reviews: [Option<AgentRule>; 2],
    fixers: [Option<AgentRule>; 2],
}

fn setting(c: &Choice) -> Result<AgentRule, &'static str> {
    let ids = [&c.provider, &c.model, &c.effort];
    if ids.iter().any(|id| id.len() > 128)
        || !(models::is_id(&c.provider)
            && models::is_model_id(&c.model)
            && models::is_id(&c.effort))
    {
        return Err("invalid agent setting");
    }
    Ok(AgentRule {
        harness: c.provider.clone(),
        model: c.model.clone(),
        effort: c.effort.clone(),
    })
}

fn from_show(show: &Show) -> Result<Agents, &'static str> {
    let pick = |p: &Pick| p.choice.as_ref().map(setting).transpose();
    Ok(Agents {
        builder: setting(&show.roles.builder.choice)?,
        builder_small: setting(&show.roles.small_builder.choice)?,
        reviews: [pick(&show.reviews.claude)?, pick(&show.reviews.gpt)?],
        fixers: [pick(&show.fixers.claude)?, pick(&show.fixers.gpt)?],
    })
}

fn older(text: &str, f: &SpawnFlags) -> Result<Agents, &'static str> {
    let read = |heading| {
        agent(
            table(
                text,
                heading,
                &["Setting", "Value", "`room-cli thread spawn` flag"],
            )?,
            f,
        )
    };
    Ok(Agents {
        builder: read("## Builder")?,
        builder_small: read("## Builder for small tickets")?,
        reviews: [
            Some(read("## Reviewer for Claude-built")?),
            Some(read("## Reviewer for GPT-built")?),
        ],
        fixers: [None, None],
    })
}

impl Rules {
    pub fn parse(text: &str, flags: &SpawnFlags) -> Result<Self, &'static str> {
        let has_models = text.lines().any(|l| l == "## Models");
        let agents = if has_models {
            from_show(&models::read(text, flags).map_err(|_| "models table refused")?)?
        } else {
            let mut agents = older(text, flags)?;
            if let Some(read) = models::read(text, flags)
                .ok()
                .and_then(|s| from_show(&s).ok())
            {
                agents.fixers = read.fixers;
            }
            agents
        };
        if !has_models
            && agents
                .reviews
                .each_ref()
                .map(|r| r.as_ref().map(|r| r.harness.as_str()))
                != [Some("codex"), Some("claude-code")]
        {
            return Err("reviewer must be the other family");
        }
        let rows = table(text, "## CI checks", &["Check", "Runs", "Required on"])?;
        let mut ci_checks = Vec::new();
        for row in rows {
            let name = quoted(row[0])?;
            if !name_form(name, false) {
                return Err("invalid check name");
            }
            let required_on = row[2]
                .split(", ")
                .map(|s| {
                    let branch = quoted(s)?;
                    if !branch_pattern(branch) {
                        return Err("invalid branch pattern");
                    }
                    Ok(branch.to_owned())
                })
                .collect::<Result<Vec<_>, _>>()?;
            if !unique(&required_on) {
                return Err("duplicate required branch");
            }
            ci_checks.push(RequiredCheck {
                name: name.to_owned(),
                required_on,
            });
        }
        if ci_checks.is_empty() || !unique(&ci_checks.iter().map(|c| &c.name).collect::<Vec<_>>()) {
            return Err("missing or duplicate check");
        }
        let rows = table(
            text,
            "## Standing merge rules",
            &["Pull request", "Review", "Merged by, and when"],
        )?;
        let matching = rows
            .iter()
            .filter(|r| {
                r[0].starts_with("A ticket in an approved plan graph")
                    && r[2].starts_with(
                        "The loop, as soon as the reviewer's APPROVE names that exact commit",
                    )
            })
            .collect::<Vec<_>>();
        let merge = match matching.as_slice() {
            [] => MergeRule::None,
            [_] => MergeRule::Adr0008,
            _ => return Err("ambiguous merge rule"),
        };
        let [reviewer_claude, reviewer_gpt] = agents.reviews;
        Ok(Self {
            builder: agents.builder,
            builder_small: agents.builder_small,
            reviewer_claude,
            reviewer_gpt,
            ci_checks,
            merge,
            fixers: agents.fixers,
        })
    }

    pub fn builder(&self) -> &AgentRule {
        &self.builder
    }
    pub fn builder_for(&self, labels: &[super::super::model::NonEmpty]) -> &AgentRule {
        if labels
            .iter()
            .any(|l| matches!(l.as_str(), "polish" | "huntr" | "proposal"))
        {
            &self.builder_small
        } else {
            &self.builder
        }
    }
    pub fn small_builder(&self) -> &AgentRule {
        &self.builder_small
    }
    pub fn reviewer_for(&self, family: super::BuilderFamily) -> Option<&AgentRule> {
        match family {
            super::BuilderFamily::Claude => self.reviewer_claude.as_ref(),
            super::BuilderFamily::Gpt => self.reviewer_gpt.as_ref(),
        }
    }
    pub fn fixer(&self, family: super::BuilderFamily) -> Option<&AgentRule> {
        match family {
            super::BuilderFamily::Claude => self.fixers[0].as_ref(),
            super::BuilderFamily::Gpt => self.fixers[1].as_ref(),
        }
    }
}

fn table<'a>(
    text: &'a str,
    heading: &str,
    header: &[&str; 3],
) -> Result<Vec<[&'a str; 3]>, &'static str> {
    let lines = text.lines().collect::<Vec<_>>();
    let starts = lines
        .iter()
        .enumerate()
        .filter(|(_, l)| **l == heading)
        .map(|(i, _)| i)
        .collect::<Vec<_>>();
    let [start] = starts.as_slice() else {
        return Err("missing or repeated section");
    };
    let section = &lines[start + 1..];
    let end = section
        .iter()
        .position(|l| l.starts_with("## "))
        .unwrap_or(section.len());
    let section = &section[..end];
    let blocks = section
        .iter()
        .enumerate()
        .filter(|(i, l)| l.starts_with('|') && (*i == 0 || !section[i - 1].starts_with('|')))
        .map(|(i, _)| i)
        .collect::<Vec<_>>();
    let [start] = blocks.as_slice() else {
        return Err("missing or repeated table");
    };
    let rows = section[*start..]
        .iter()
        .take_while(|l| l.starts_with('|'))
        .map(|l| {
            let row = l
                .strip_prefix('|')
                .and_then(|s| s.strip_suffix('|'))
                .ok_or("incomplete table row")?;
            let cells = row.split('|').map(str::trim).collect::<Vec<_>>();
            cells.try_into().map_err(|_| "wrong table width")
        })
        .collect::<Result<Vec<[&str; 3]>, _>>()?;
    if rows.len() < 2 || rows[0] != *header || rows[1] != ["---"; 3] {
        return Err("wrong table header or separator");
    }
    Ok(rows[2..].to_vec())
}

fn agent(rows: Vec<[&str; 3]>, f: &SpawnFlags) -> Result<AgentRule, &'static str> {
    if rows.len() != 3 {
        return Err("wrong agent row count");
    }
    let mut values = Vec::new();
    for (row, (key, flag)) in rows.iter().zip([
        ("Harness", &f.provider),
        ("Model", &f.model),
        ("Effort", &f.effort),
    ]) {
        if row[0] != key {
            return Err("wrong agent row");
        }
        let value = quoted(row[2])?
            .strip_prefix(flag.as_str())
            .and_then(|v| v.strip_prefix(' '))
            .ok_or("wrong agent flag")?;
        if value.len() > 128 || !name_form(value, true) {
            return Err("invalid agent setting");
        }
        values.push(value.to_owned());
    }
    Ok(AgentRule {
        harness: values[0].clone(),
        model: values[1].clone(),
        effort: values[2].clone(),
    })
}

fn quoted(s: &str) -> Result<&str, &'static str> {
    s.strip_prefix('`')
        .and_then(|s| s.strip_suffix('`'))
        .filter(|s| !s.contains('`'))
        .ok_or("expected one quoted value")
}

fn name_form(s: &str, lowercase: bool) -> bool {
    let letter = |b: u8| {
        b.is_ascii_lowercase() || (!lowercase && b.is_ascii_uppercase()) || b.is_ascii_digit()
    };
    s.as_bytes().first().is_some_and(|b| letter(*b))
        && s.bytes().all(|b| letter(b) || b"._-".contains(&b))
}

fn branch_pattern(s: &str) -> bool {
    if s.len() > 255 {
        return false;
    }
    let s = s.strip_suffix('*').unwrap_or(s);
    !s.is_empty()
        && s.len() <= 255
        && s.as_bytes()[0].is_ascii_alphanumeric()
        && s.bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"._-/".contains(&b))
}

pub(crate) fn unique<T: Ord>(values: &[T]) -> bool {
    values.iter().collect::<BTreeSet<_>>().len() == values.len()
}

pub(crate) fn branch_matches(pattern: &str, branch: &str) -> bool {
    pattern
        .strip_suffix('*')
        .map_or(pattern == branch, |prefix| branch.starts_with(prefix))
}
