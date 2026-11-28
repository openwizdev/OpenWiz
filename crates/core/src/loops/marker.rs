pub fn is_id(s: &str) -> bool {
    let b = s.as_bytes();
    (1..=64).contains(&b.len())
        && (b[0].is_ascii_lowercase() || b[0].is_ascii_digit())
        && b.iter()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || *c == b'-')
}

pub fn marker(id: &str) -> String {
    format!("[wizloop:{id}]")
}

pub fn split_marker(name: &str) -> Option<(&str, &str)> {
    let rest = name.strip_suffix(']')?;
    let at = rest.rfind(" [wizloop:")?;
    let id = &rest[at + " [wizloop:".len()..];
    is_id(id).then_some((id, &name[..at]))
}

#[cfg(test)]
mod tests {
    use super::{marker, split_marker};

    #[test]
    fn formats_the_marker() {
        assert_eq!(marker("synthetic-7"), "[wizloop:synthetic-7]");
    }

    #[test]
    fn splits_only_the_final_marker_and_preserves_the_display_name() {
        assert_eq!(
            split_marker("Café [wizloop:earlier]  [wizloop:synthetic-7]"),
            Some(("synthetic-7", "Café [wizloop:earlier] "))
        );
        assert_eq!(split_marker(" [wizloop:0]"), Some(("0", "")));
    }

    #[test]
    fn accepts_ids_at_both_length_bounds() {
        let longest = format!("{}-", "a".repeat(63));
        for id in ["z", longest.as_str()] {
            let name = format!("Synthetic [wizloop:{id}]");
            assert_eq!(split_marker(&name), Some((id, "Synthetic")));
        }
    }

    #[test]
    fn refuses_names_without_a_terminal_marker() {
        for name in [
            "Synthetic",
            "[wizloop:synthetic]",
            "Synthetic[wizloop:synthetic]",
            "Synthetic [wizloop:synthetic",
            "Synthetic [wizloop:synthetic] later",
            "Synthetic [wizloop:synthetic] ",
            "Synthetic [wizloop:synthetic] [wizloop:Invalid]",
        ] {
            assert_eq!(split_marker(name), None, "{name:?}");
        }
    }

    #[test]
    fn refuses_markers_with_invalid_ids() {
        let too_long = "a".repeat(65);
        for id in [
            "",
            "-leading",
            "Upper",
            "under_score",
            "a b",
            "café",
            &too_long,
        ] {
            let name = format!("Synthetic [wizloop:{id}]");
            assert_eq!(split_marker(&name), None, "{name:?}");
        }
    }
}
