#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Tier {
    Recall,
    SmallModel,
}

impl Tier {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Recall => "recall",
            Self::SmallModel => "small_model",
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct RecallHit {
    pub text: String,
    pub confidence: f64,
    pub fixed_code: bool,
}

#[derive(Clone, Debug, PartialEq)]
pub struct ModelDraft {
    pub text: String,
    pub mean_logprob: f64,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Blended {
    pub text: String,
    pub tier: Tier,
    pub confidence: f64,
}

pub fn confidence(mean_logprob: f64) -> f64 {
    if !mean_logprob.is_finite() {
        return 0.0;
    }
    mean_logprob.exp().clamp(0.0, 1.0)
}

pub fn blend(
    model: Option<&ModelDraft>,
    recall: Option<&RecallHit>,
    threshold: f64,
    logprob_gate: f64,
    never_suggest: &[String],
) -> Option<Blended> {
    let model = model.filter(|draft| model_passes(draft, threshold, logprob_gate, never_suggest));
    let recall = recall.filter(|hit| recall_passes(hit, threshold, never_suggest));
    match (model, recall) {
        (_, Some(hit)) if hit.fixed_code => Some(from_recall(hit)),
        (Some(draft), Some(hit)) if same_suggestion(&draft.text, &hit.text) => Some(Blended {
            text: draft.text.clone(),
            tier: Tier::SmallModel,
            confidence: confidence(draft.mean_logprob).max(hit.confidence),
        }),
        (Some(draft), _) => Some(Blended {
            text: draft.text.clone(),
            tier: Tier::SmallModel,
            confidence: confidence(draft.mean_logprob),
        }),
        (None, Some(hit)) => Some(from_recall(hit)),
        (None, None) => None,
    }
}

fn from_recall(hit: &RecallHit) -> Blended {
    Blended {
        text: hit.text.clone(),
        tier: Tier::Recall,
        confidence: hit.confidence,
    }
}

fn model_passes(draft: &ModelDraft, threshold: f64, logprob_gate: f64, never: &[String]) -> bool {
    draft.mean_logprob.is_finite()
        && draft.mean_logprob >= logprob_gate
        && confidence(draft.mean_logprob) >= threshold
        && !draft.text.is_empty()
        && !forbidden(&draft.text, never)
}

fn recall_passes(hit: &RecallHit, threshold: f64, never: &[String]) -> bool {
    hit.confidence.is_finite()
        && (0.0..=1.0).contains(&hit.confidence)
        && hit.confidence >= threshold
        && !hit.text.is_empty()
        && !forbidden(&hit.text, never)
}

fn forbidden(text: &str, never: &[String]) -> bool {
    never
        .iter()
        .any(|phrase| !phrase.is_empty() && text.contains(phrase))
}

fn same_suggestion(model: &str, recall: &str) -> bool {
    model.trim() == recall.trim()
}
