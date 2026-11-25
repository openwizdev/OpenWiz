use std::fs;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use openwiz_adapter_github::fleets::GitHubFleets;
use openwiz_core::fleet::fleets::{FleetsSource, IssueRow};
use openwiz_core::fleet::model::IssueState;

use super::protocol::{
    ContextPack, ConversationContext, GlossaryEntry, GrillEntry, OpenWork, SCHEMA_ID, SkillContext,
    SpecEntry, TicketEntry, Turn,
};
use super::recall::RecallIndex;

const RECORDS_READ_BUDGET: Duration = Duration::from_secs(10);

pub struct ContextStore {
    pack: ContextPack,
    recall: RecallIndex,
    revision_seq: u64,
    sent_messages: Vec<String>,
    github: Option<GitHubFleets>,
    glossary_path: Option<PathBuf>,
    skill_path: Option<PathBuf>,
    rebuild_count: u64,
}

impl ContextStore {
    pub fn from_pack(pack: ContextPack) -> Self {
        let recall = RecallIndex::build(&pack, &[]);
        Self {
            pack,
            recall,
            revision_seq: 1,
            sent_messages: Vec::new(),
            github: None,
            glossary_path: None,
            skill_path: None,
            rebuild_count: 1,
        }
    }

    pub fn from_sources(
        github: Option<GitHubFleets>,
        glossary_path: Option<PathBuf>,
        skill_path: Option<PathBuf>,
        sent_messages: Vec<String>,
    ) -> Self {
        let mut store = Self {
            pack: ContextPack::empty("ctx-0001"),
            recall: RecallIndex::default(),
            revision_seq: 0,
            sent_messages,
            github,
            glossary_path,
            skill_path,
            rebuild_count: 0,
        };
        store.rebuild_from_sources();
        store
    }

    pub fn system_default() -> Self {
        let var = |name: &str| std::env::var_os(name);
        let skill_path = crate::state::default_state_dir(&var)
            .ok()
            .map(|dir| dir.join("ghost").join("skill.json"));
        let glossary_path = PathBuf::from("GLOSSARY.md");
        let glossary_opt = glossary_path.exists().then_some(glossary_path);
        Self::from_sources(
            Some(GitHubFleets::from_path()),
            glossary_opt,
            skill_path,
            Vec::new(),
        )
    }

    pub fn pack(&self) -> &ContextPack {
        &self.pack
    }

    pub fn recall(&self) -> &RecallIndex {
        &self.recall
    }

    pub fn revision(&self) -> &str {
        &self.pack.revision
    }

    pub fn rebuild_count(&self) -> u64 {
        self.rebuild_count
    }

    pub fn refresh_records(&mut self) -> &str {
        self.rebuild_from_sources();
        self.revision()
    }

    pub fn update_turns(
        &mut self,
        session_id: String,
        agent: String,
        mut turns: Vec<Turn>,
    ) -> &str {
        if turns.len() > 3 {
            let start = turns.len() - 3;
            turns = turns.split_off(start);
        }
        self.revision_seq += 1;
        let rev = format!("ctx-{:04}", self.revision_seq);
        self.pack.revision = rev;
        self.pack.conversation = ConversationContext {
            session_id,
            agent,
            turns,
        };
        self.recall = RecallIndex::build(&self.pack, &self.sent_messages);
        self.rebuild_count += 1;
        self.revision()
    }

    pub fn record_sent_message(&mut self, text: String) -> &str {
        let trimmed = text.trim().to_owned();
        if !trimmed.is_empty() {
            if !self.sent_messages.contains(&trimmed) {
                self.sent_messages.push(trimmed.clone());
            }
            if trimmed.len() <= 120
                && !self
                    .pack
                    .skill
                    .phrases
                    .iter()
                    .any(|p| p.eq_ignore_ascii_case(&trimmed))
            {
                self.pack.skill.phrases.push(trimmed);
            }
        }
        self.revision_seq += 1;
        self.pack.revision = format!("ctx-{:04}", self.revision_seq);
        self.recall = RecallIndex::build(&self.pack, &self.sent_messages);
        self.rebuild_count += 1;
        self.revision()
    }

    fn rebuild_from_sources(&mut self) {
        self.revision_seq += 1;
        let revision = format!("ctx-{:04}", self.revision_seq);

        let mut skill = self
            .skill_path
            .as_deref()
            .and_then(load_skill_file)
            .unwrap_or_default();
        for msg in &self.sent_messages {
            let trimmed = msg.trim();
            if !trimmed.is_empty()
                && trimmed.len() <= 120
                && !skill
                    .phrases
                    .iter()
                    .any(|p| p.eq_ignore_ascii_case(trimmed))
            {
                skill.phrases.push(trimmed.to_owned());
            }
        }

        let glossary = self
            .glossary_path
            .as_deref()
            .and_then(load_glossary_file)
            .unwrap_or_default();

        let open_work = self.github.as_ref().map(read_open_work).unwrap_or_default();

        self.pack = ContextPack {
            schema: SCHEMA_ID.to_owned(),
            kind: "context_pack".to_owned(),
            revision,
            skill,
            glossary,
            open_work,
            conversation: self.pack.conversation.clone(),
        };
        self.recall = RecallIndex::build(&self.pack, &self.sent_messages);
        self.rebuild_count += 1;
    }
}

fn load_skill_file(path: &Path) -> Option<SkillContext> {
    let text = fs::read_to_string(path).ok()?;
    serde_json::from_str::<SkillContext>(&text).ok()
}

fn load_glossary_file(path: &Path) -> Option<Vec<GlossaryEntry>> {
    let text = fs::read_to_string(path).ok()?;
    let mut entries = Vec::new();
    let mut current_term: Option<String> = None;

    for raw_line in text.lines() {
        let line = raw_line.trim();
        if let Some(heading) = line.strip_prefix("## ") {
            let term = heading.trim();
            if !term.is_empty() {
                current_term = Some(term.to_owned());
            }
            continue;
        }
        if line.starts_with('|') && line.ends_with('|') {
            let cells: Vec<&str> = line.trim_matches('|').split('|').map(str::trim).collect();
            if cells.len() >= 2 {
                let term = cells[0].trim_matches('`').trim_matches('*').trim();
                let meaning = cells[1].trim();
                if !term.is_empty()
                    && !meaning.is_empty()
                    && !term.eq_ignore_ascii_case("term")
                    && !term.eq_ignore_ascii_case("word")
                    && !term.chars().all(|c| c == '-' || c == ':')
                {
                    entries.push(GlossaryEntry {
                        term: term.to_owned(),
                        meaning: meaning.to_owned(),
                    });
                }
            }
            continue;
        }
        if let Some(term) = current_term.as_ref()
            && !line.is_empty()
            && !line.starts_with('#')
            && !line.starts_with('>')
        {
            entries.push(GlossaryEntry {
                term: term.clone(),
                meaning: line.to_owned(),
            });
            current_term = None;
        }
    }

    Some(entries)
}

fn read_open_work(github: &GitHubFleets) -> OpenWork {
    let deadline = Instant::now() + RECORDS_READ_BUDGET;
    let Ok(listed) = github.issues(deadline) else {
        return OpenWork::default();
    };
    open_work_from_issues(&listed.rows)
}

fn open_work_from_issues(rows: &[IssueRow]) -> OpenWork {
    let mut specs = Vec::new();
    let mut tickets = Vec::new();
    let mut grills = Vec::new();

    for row in rows {
        if row.state != IssueState::Open {
            continue;
        }
        let number = row.number.get();
        let title = row.title.trim();
        if title.is_empty() {
            continue;
        }
        extract_grills(&row.body, &mut grills);

        let is_spec = row.sub_issues.total > 0 || title.to_ascii_lowercase().contains("spec:");
        if is_spec {
            specs.push(SpecEntry {
                number,
                title: title.to_owned(),
            });
        } else {
            let action = format!("approve #{number} and merge");
            tickets.push(TicketEntry {
                number,
                title: title.to_owned(),
                action,
            });
        }
    }

    OpenWork {
        specs,
        tickets,
        grills,
    }
}

fn extract_grills(body: &str, out: &mut Vec<GrillEntry>) {
    for raw_line in body.lines() {
        let line = raw_line.trim();
        // Table format: | J1 | Question text? | all recs |
        if line.starts_with('|') && line.ends_with('|') {
            let cells: Vec<&str> = line.trim_matches('|').split('|').map(str::trim).collect();
            if cells.len() >= 3 {
                let code = cells[0].trim_matches('`').trim_matches('*').trim();
                let question = cells[1].trim();
                let recommended = cells[2].trim_matches('`').trim();
                if is_grill_code(code) && !question.is_empty() && !recommended.is_empty() {
                    push_unique_grill(out, code, question, recommended);
                }
            }
        }
    }
}

fn is_grill_code(code: &str) -> bool {
    let mut chars = code.chars();
    let Some(first) = chars.next() else {
        return false;
    };
    first.is_ascii_uppercase()
        && code.len() >= 2
        && code.len() <= 8
        && chars.all(|c| c.is_ascii_digit())
}

fn push_unique_grill(out: &mut Vec<GrillEntry>, code: &str, question: &str, recommended: &str) {
    if !out.iter().any(|g| g.code == code) {
        out.push(GrillEntry {
            code: code.to_owned(),
            question: question.to_owned(),
            recommended: recommended.to_owned(),
        });
    }
}
