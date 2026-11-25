use std::collections::BTreeMap;

use super::protocol::{ContextPack, TurnRole};

pub const CONFIDENCE_THRESHOLD: f64 = 0.30;
const MAX_SUGGESTION_WORDS: usize = 8;

#[derive(Clone, Debug)]
struct Candidate {
    text: String,
    lower: String,
    base_weight: f64,
    frequency: u32,
}

#[derive(Default, Clone, Debug)]
struct TrieNode {
    children: BTreeMap<char, TrieNode>,
    candidate_indices: Vec<usize>,
}

impl TrieNode {
    fn insert(&mut self, key: &str, idx: usize) {
        let mut node = self;
        for ch in key.chars() {
            node = node.children.entry(ch).or_default();
            if !node.candidate_indices.contains(&idx) {
                node.candidate_indices.push(idx);
            }
        }
    }

    fn lookup(&self, prefix: &str) -> Option<&[usize]> {
        let mut node = self;
        for ch in prefix.chars() {
            node = node.children.get(&ch)?;
        }
        Some(&node.candidate_indices)
    }
}

#[derive(Clone, Debug)]
pub struct RecallMatch {
    pub text: String,
    pub full_text: String,
    pub confidence: f64,
}

#[derive(Clone, Debug, Default)]
pub struct RecallIndex {
    candidates: Vec<Candidate>,
    trie: TrieNode,
    ngrams: BTreeMap<String, Vec<(String, u32)>>,
    never_suggest_lower: Vec<String>,
}

impl RecallIndex {
    pub fn build(pack: &ContextPack, sent_messages: &[String]) -> Self {
        let never_suggest_lower: Vec<String> = pack
            .skill
            .never_suggest
            .iter()
            .map(|s| s.trim().to_ascii_lowercase())
            .filter(|s| !s.is_empty())
            .collect();

        let mut index = Self {
            candidates: Vec::new(),
            trie: TrieNode::default(),
            ngrams: BTreeMap::new(),
            never_suggest_lower,
        };

        // 1. Grills (highest entity priority: exact grill code -> recommended answer)
        for grill in &pack.open_work.grills {
            let code = grill.code.trim();
            let rec = grill.recommended.trim();
            if !code.is_empty() && !rec.is_empty() {
                index.add_candidate(format!("{code} {rec}"), 0.96);
            }
        }

        // 2. Tickets (action, approve #N, ship <title>, #N <title>)
        for ticket in &pack.open_work.tickets {
            let action = ticket.action.trim();
            if !action.is_empty() {
                index.add_candidate(action.to_owned(), 0.94);
            } else {
                index.add_candidate(format!("approve #{}", ticket.number), 0.84);
            }
            let title = ticket.title.trim();
            if !title.is_empty() {
                index.add_candidate(format!("ship {title}"), 0.90);
                index.add_candidate(format!("#{} {title}", ticket.number), 0.85);
            }
        }

        // 3. Specs (title and #N <title>)
        for spec in &pack.open_work.specs {
            let title = spec.title.trim();
            if !title.is_empty() {
                index.add_candidate(title.to_owned(), 0.90);
                index.add_candidate(format!("#{} {title}", spec.number), 0.82);
            }
        }

        // 4. Skill phrases
        for phrase in &pack.skill.phrases {
            let p = phrase.trim();
            if !p.is_empty() {
                index.add_candidate(p.to_owned(), 0.92);
            }
        }

        // 5. Glossary terms
        for entry in &pack.glossary {
            let term = entry.term.trim();
            if !term.is_empty() {
                index.add_candidate(term.to_owned(), 0.72);
            }
        }

        // 6. Sent messages and user turns -> phrases + n-grams
        for msg in sent_messages {
            let m = msg.trim();
            if !m.is_empty() {
                index.add_candidate(m.to_owned(), 0.80);
                index.index_ngrams(m);
            }
        }
        for turn in &pack.conversation.turns {
            if turn.role == TurnRole::User {
                let t = turn.text.trim();
                if !t.is_empty() {
                    index.index_ngrams(t);
                }
            }
        }

        index
    }

    fn is_forbidden(&self, text: &str) -> bool {
        let lower = text.to_ascii_lowercase();
        self.never_suggest_lower
            .iter()
            .any(|banned| lower.contains(banned))
    }

    fn add_candidate(&mut self, text: String, base_weight: f64) {
        if text.is_empty() || self.is_forbidden(&text) {
            return;
        }
        let lower = text.to_ascii_lowercase();
        if let Some(existing) = self.candidates.iter_mut().find(|c| c.lower == lower) {
            existing.frequency = existing.frequency.saturating_add(1);
            if base_weight > existing.base_weight {
                existing.base_weight = base_weight;
                existing.text = text;
            }
            return;
        }
        let idx = self.candidates.len();
        self.trie.insert(&lower, idx);
        self.candidates.push(Candidate {
            text,
            lower,
            base_weight,
            frequency: 1,
        });
    }

    fn index_ngrams(&mut self, text: &str) {
        let words: Vec<&str> = text.split_whitespace().collect();
        if words.len() < 2 {
            return;
        }
        // Index 1-word and 2-word contexts predicting up to 4 following words
        for i in 0..words.len().saturating_sub(1) {
            let end = (i + 1 + 4).min(words.len());
            let continuation = words[i + 1..end].join(" ");
            if !self.is_forbidden(&continuation) {
                let key1 = words[i].to_ascii_lowercase();
                push_ngram(&mut self.ngrams, key1, continuation.clone());
                if i > 0 {
                    let key2 = format!(
                        "{} {}",
                        words[i - 1].to_ascii_lowercase(),
                        words[i].to_ascii_lowercase()
                    );
                    push_ngram(&mut self.ngrams, key2, continuation);
                }
            }
        }
    }

    pub fn complete(&self, prefix: &str, threshold: f64) -> Option<RecallMatch> {
        if prefix.trim().len() < 2 {
            return None;
        }

        // 1. Direct full-prefix lookup in entity/phrase trie
        if let Some(m) = self.lookup_trie_prefix(prefix, prefix, 1.0, threshold) {
            return Some(m);
        }

        // 2. Suffix-clause lookup in entity/phrase trie (up to last 4 word starts)
        let mut word_starts: Vec<usize> = Vec::new();
        let mut prev_ws = true;
        for (idx, ch) in prefix.char_indices() {
            if ch.is_whitespace() {
                prev_ws = true;
            } else if prev_ws {
                word_starts.push(idx);
                prev_ws = false;
            }
        }
        if word_starts.len() > 1 {
            let skip = word_starts.len().saturating_sub(4);
            for &start in &word_starts[skip..] {
                if start == 0 {
                    continue;
                }
                let sub = &prefix[start..];
                if sub.trim().len() < 2 {
                    continue;
                }
                if let Some(m) = self.lookup_trie_prefix(prefix, sub, 0.90, threshold) {
                    return Some(m);
                }
            }
        }

        // 3. N-gram continuation when prefix ends with whitespace
        if prefix.ends_with(char::is_whitespace) {
            let words: Vec<&str> = prefix.split_whitespace().collect();
            if let Some(m) = self.lookup_ngram(prefix, &words, threshold) {
                return Some(m);
            }
        }

        None
    }

    fn lookup_trie_prefix(
        &self,
        full_prefix: &str,
        matched_prefix: &str,
        scope_factor: f64,
        threshold: f64,
    ) -> Option<RecallMatch> {
        let lower_prefix = matched_prefix.to_ascii_lowercase();
        let indices = self.trie.lookup(&lower_prefix)?;

        let mut best: Option<RecallMatch> = None;
        let prefix_chars = matched_prefix.chars().count();

        for &idx in indices {
            let cand = &self.candidates[idx];
            if cand.lower.len() <= lower_prefix.len() {
                continue;
            }
            let suffix_raw: String = cand.text.chars().skip(prefix_chars).collect();
            let suffix = clamp_suggestion(&suffix_raw);
            if suffix.is_empty() || self.is_forbidden(&format!("{full_prefix}{suffix}")) {
                continue;
            }

            let cand_chars = cand.text.chars().count().max(1);
            let match_ratio = (prefix_chars as f64 / cand_chars as f64).clamp(0.0, 1.0);
            let freq_boost = ((cand.frequency.saturating_sub(1)) as f64 * 0.02).min(0.06);
            let confidence = (cand.base_weight * scope_factor * (0.70 + 0.30 * match_ratio)
                + freq_boost)
                .clamp(0.0, 0.99);

            if confidence < threshold {
                continue;
            }

            let replace = best
                .as_ref()
                .is_none_or(|prev| confidence > prev.confidence);
            if replace {
                let full_text = format!("{full_prefix}{suffix}");
                best = Some(RecallMatch {
                    text: suffix,
                    full_text,
                    confidence,
                });
            }
        }

        best
    }

    fn lookup_ngram(
        &self,
        full_prefix: &str,
        words: &[&str],
        threshold: f64,
    ) -> Option<RecallMatch> {
        if words.is_empty() {
            return None;
        }
        let keys: Vec<(String, f64)> = if words.len() >= 2 {
            vec![
                (
                    format!(
                        "{} {}",
                        words[words.len() - 2].to_ascii_lowercase(),
                        words[words.len() - 1].to_ascii_lowercase()
                    ),
                    0.78,
                ),
                (words[words.len() - 1].to_ascii_lowercase(), 0.52),
            ]
        } else {
            vec![(words[0].to_ascii_lowercase(), 0.52)]
        };

        for (key, base) in keys {
            if let Some(entries) = self.ngrams.get(&key)
                && let Some((cont, freq)) = entries.iter().max_by_key(|(_, f)| *f)
            {
                let suffix = clamp_suggestion(cont);
                if suffix.is_empty() || self.is_forbidden(&format!("{full_prefix}{suffix}")) {
                    continue;
                }
                let confidence =
                    (base + ((*freq).saturating_sub(1) as f64 * 0.05).min(0.15)).clamp(0.0, 0.95);
                if confidence >= threshold {
                    return Some(RecallMatch {
                        full_text: format!("{full_prefix}{suffix}"),
                        text: suffix,
                        confidence,
                    });
                }
            }
        }
        None
    }
}

fn push_ngram(map: &mut BTreeMap<String, Vec<(String, u32)>>, key: String, cont: String) {
    let list = map.entry(key).or_default();
    if let Some((_, count)) = list.iter_mut().find(|(c, _)| *c == cont) {
        *count = count.saturating_add(1);
    } else {
        list.push((cont, 1));
    }
}

fn clamp_suggestion(raw: &str) -> String {
    let trimmed_end = raw.trim_end();
    if trimmed_end.is_empty() {
        return String::new();
    }
    // Preserve a single leading space if present (e.g. " all recs" after "J1").
    let leading_space = trimmed_end.starts_with(' ');
    let body = trimmed_end.trim_start();
    let mut out = String::new();
    if leading_space {
        out.push(' ');
    }
    for (words_taken, word) in body.split_whitespace().enumerate() {
        if words_taken >= MAX_SUGGESTION_WORDS {
            break;
        }
        if words_taken > 0 {
            out.push(' ');
        }
        out.push_str(word);
        if word.ends_with(['.', '?', '!']) {
            break;
        }
    }
    out
}
