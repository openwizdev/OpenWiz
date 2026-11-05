//! The only `gh` invocations OpenWiz may make (OpenWiz 0.0.6, spec #107).
//!
//! **Per module** (#111): each module declares its own part of the
//! allowlist in its own file, as a [`Module`], and [`MODULES`] collects
//! them, so A4, A5 and spec 2's B3 each add entries in their own file and
//! never edit this one. An [`Invocation`] is built only from an argument
//! list that some module allows exactly. Fail closed: what no module
//! recognises is refused.
//!
//! **Every part is empty** (A3): nothing is allowed, so no [`Invocation`]
//! can be built, and OpenWiz runs no `gh`.

use crate::{decisions, fleets, plan, tick, tickets, writes};

/// One module's part of the allowlist, declared in that module's file.
#[derive(Clone, Copy, Debug)]
pub struct Module {
    /// The module's name: its file's.
    pub name: &'static str,
    /// Whether `argv`, the arguments after `gh`, is exactly one of this
    /// module's forms.
    pub allows: fn(&[&str]) -> bool,
}

/// Every module's part of the allowlist.
pub const MODULES: &[Module] = &[
    fleets::ALLOWLIST,
    tickets::ALLOWLIST,
    writes::ALLOWLIST,
    plan::ALLOWLIST,
    decisions::ALLOWLIST,
    tick::ALLOWLIST,
    crate::events::ALLOWLIST,
];

/// Whether some module allows exactly `argv`, the arguments after `gh`.
pub fn allowed(argv: &[&str]) -> bool {
    allowed_by(MODULES, argv)
}

fn allowed_by(modules: &[Module], argv: &[&str]) -> bool {
    modules.iter().any(|module| (module.allows)(argv))
}

/// One `gh` call on the allowlist: exactly these arguments after `gh`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Invocation(Vec<String>);

impl Invocation {
    /// `gh <argv>`, only when some module allows exactly `argv`.
    pub fn new(argv: &[&str]) -> Option<Self> {
        Self::from_modules(MODULES, argv)
    }

    /// [`Invocation::new`] over `modules`, so the rule can be proven with
    /// planted ones.
    fn from_modules(modules: &[Module], argv: &[&str]) -> Option<Self> {
        allowed_by(modules, argv).then(|| Self(argv.iter().map(|&a| a.to_owned()).collect()))
    }

    /// The arguments after `gh`, exactly as allowed.
    pub fn argv(&self) -> &[String] {
        &self.0
    }
}

#[cfg(test)]
impl Invocation {
    /// Any arguments, for the runner's own proofs in this crate: never in a
    /// build.
    pub(crate) fn for_test(argv: &[&str]) -> Self {
        Self(argv.iter().map(|&a| a.to_owned()).collect())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A planted module that allows exactly `gh synthetic read`.
    fn planted(argv: &[&str]) -> bool {
        argv == ["synthetic", "read"]
    }

    const PLANTED: Module = Module {
        name: "planted",
        allows: planted,
    };

    fn never(_argv: &[&str]) -> bool {
        false
    }

    const EMPTY: Module = Module {
        name: "empty",
        allows: never,
    };

    #[test]
    fn the_registry_is_one_module_per_seam_file() {
        let names: Vec<&str> = MODULES.iter().map(|m| m.name).collect();
        assert_eq!(
            names,
            [
                "fleets",
                "tickets",
                "writes",
                "plan",
                "decisions",
                "tick",
                "events"
            ]
        );
        for name in names {
            let file = concat!(env!("CARGO_MANIFEST_DIR"), "/src/").to_owned() + name + ".rs";
            assert!(std::path::Path::new(&file).is_file(), "{file}");
        }
    }

    #[test]
    fn an_invocation_is_built_only_from_an_argv_a_module_allows_exactly() {
        let built = Invocation::from_modules(&[EMPTY, PLANTED], &["synthetic", "read"]);
        assert_eq!(
            built.as_ref().map(Invocation::argv),
            Some(&["synthetic".to_owned(), "read".to_owned()][..])
        );
        for refused in [
            &[][..],
            &["synthetic"],
            &["synthetic", "read", "--extra"],
            &["read", "synthetic"],
            &["Synthetic", "read"],
            &["synthetic", "read "],
        ] {
            assert_eq!(
                Invocation::from_modules(&[EMPTY, PLANTED], refused),
                None,
                "{refused:?}"
            );
        }
        // No module, or only modules that allow nothing: nothing at all.
        assert_eq!(Invocation::from_modules(&[], &["synthetic", "read"]), None);
        assert_eq!(
            Invocation::from_modules(&[EMPTY], &["synthetic", "read"]),
            None
        );
    }

    #[test]
    fn the_registry_allows_exactly_what_its_modules_allow() {
        for argv in [
            &[][..],
            &["--version"],
            &["issue", "view", "1", "--json", "title"],
            &["synthetic", "read"],
        ] {
            let any = MODULES.iter().any(|m| (m.allows)(argv));
            assert_eq!(allowed(argv), any, "{argv:?}");
            assert_eq!(Invocation::new(argv).is_some(), any, "{argv:?}");
        }
    }
}
