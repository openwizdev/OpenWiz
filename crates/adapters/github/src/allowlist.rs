use crate::{decisions, fleets, plan, tick, tickets, writes};

#[derive(Clone, Copy, Debug)]
pub struct Module {
    pub name: &'static str,
    pub allows: fn(&[&str]) -> bool,
}

pub const MODULES: &[Module] = &[
    fleets::ALLOWLIST,
    tickets::ALLOWLIST,
    writes::ALLOWLIST,
    plan::ALLOWLIST,
    decisions::ALLOWLIST,
    tick::ALLOWLIST,
];

pub fn allowed(argv: &[&str]) -> bool {
    allowed_by(MODULES, argv)
}

fn allowed_by(modules: &[Module], argv: &[&str]) -> bool {
    modules.iter().any(|module| (module.allows)(argv))
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Invocation(Vec<String>);

impl Invocation {
    pub fn new(argv: &[&str]) -> Option<Self> {
        Self::from_modules(MODULES, argv)
    }

    fn from_modules(modules: &[Module], argv: &[&str]) -> Option<Self> {
        allowed_by(modules, argv).then(|| Self(argv.iter().map(|&a| a.to_owned()).collect()))
    }

    pub fn argv(&self) -> &[String] {
        &self.0
    }
}

#[cfg(test)]
impl Invocation {
    pub(crate) fn for_test(argv: &[&str]) -> Self {
        Self(argv.iter().map(|&a| a.to_owned()).collect())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

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
