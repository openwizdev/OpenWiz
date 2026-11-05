//! Project names (Sol round 1, finding 1): a name resolves to one project
//! only when no other project answers to it, whether by its literal name or
//! by the inventory's qualified `name~<last 6 of the id>`. Otherwise it is
//! refused as ambiguous, so a create can never land in another project.

use openwiz_core::model::Fact;
use openwiz_core::new_thread::ProjectRef;
use openwiz_core::new_thread::effects::{ProjectCandidate, resolve_project};
use openwiz_core::new_thread::outcome::RefusalReason;

fn project(id: &str, name: &str) -> ProjectCandidate {
    ProjectCandidate {
        id: id.to_owned(),
        name: Fact::Known(name.to_owned()),
        kind: Fact::Known("standard".to_owned()),
        github_remote: Fact::Known(true),
    }
}

/// Sol's scenario: two projects named `Synthetic` (ids ending `111111` and
/// `222222`) and a third literally named `Synthetic~111111`.
fn collision() -> Vec<ProjectCandidate> {
    vec![
        project("prj_syn_111111", "Synthetic"),
        project("prj_syn_222222", "Synthetic"),
        project("prj_syn_333333", "Synthetic~111111"),
    ]
}

fn by_name(name: &str, projects: &[ProjectCandidate]) -> Result<String, RefusalReason> {
    resolve_project(&ProjectRef::Name(name.to_owned()), projects).map(|p| p.id)
}

#[test]
fn project_names_contracts_preserve_all_original_cases() {
    let cases: [(&str, fn()); 3] = [
        (
            "a_literal_name_that_equals_another_projects_qualified_name_is_ambiguous",
            a_literal_name_that_equals_another_projects_qualified_name_is_ambiguous,
        ),
        (
            "a_unique_name_resolves_by_either_form",
            a_unique_name_resolves_by_either_form,
        ),
        (
            "every_project_is_reachable_by_its_id",
            every_project_is_reachable_by_its_id,
        ),
    ];
    for (name, proof) in cases {
        eprintln!("TA2 case: project_names::{name}");
        proof();
    }
}

fn a_literal_name_that_equals_another_projects_qualified_name_is_ambiguous() {
    let projects = collision();
    assert_eq!(
        by_name("Synthetic~111111", &projects),
        Err(RefusalReason::ProjectAmbiguous)
    );
    assert_eq!(
        by_name("Synthetic", &projects),
        Err(RefusalReason::ProjectAmbiguous)
    );
    assert_eq!(
        by_name("Synthetic~222222", &projects),
        Ok("prj_syn_222222".to_owned())
    );
}

fn every_project_is_reachable_by_its_id() {
    let projects = collision();
    for p in &projects {
        assert_eq!(
            resolve_project(&ProjectRef::Id(p.id.clone()), &projects).map(|v| v.id),
            Ok(p.id.clone())
        );
    }
}

fn a_unique_name_resolves_by_either_form() {
    let projects = vec![
        project("prj_syn_aaaaaa", "Synthetic alpha"),
        project("prj_syn_bbbbbb", "Synthetic beta"),
    ];
    for name in ["Synthetic alpha", "Synthetic alpha~aaaaaa"] {
        assert_eq!(by_name(name, &projects), Ok("prj_syn_aaaaaa".to_owned()));
    }
    assert_eq!(
        by_name("Synthetic alpha~bbbbbb", &projects),
        Err(RefusalReason::ProjectNotFound)
    );
}
