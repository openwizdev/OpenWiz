use serde::Serialize;

use super::{
    Choice, MODELS_HEADER, OLDER, OLDER_ROWS, Older, Role, RoleRead, Show, SpawnFlags, Warning,
    older_form, parse, resolve, section,
};

pub enum Asked {
    Choice(Choice),
    Follows,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RowOutcome {
    Changed,
    Unchanged,
    Kept,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct OlderRow {
    pub table: &'static str,
    pub outcome: RowOutcome,
}

pub struct Set {
    pub before: RoleRead,
    pub after: RoleRead,
    pub text: Option<String>,
    pub models_table_added: bool,
    pub older_tables: Vec<OlderRow>,
    pub warnings: Vec<Warning>,
}

pub fn set(text: &str, role: Role, asked: &Asked, f: &SpawnFlags) -> Result<Set, String> {
    let p = parse(text, f)?;
    if p.older_present && p.older.is_none() {
        return Err(
            "the older model tables are present but broken, so set can't keep them in step".into(),
        );
    }
    let show = resolve(&p);
    let before = show.roles.get(role).clone();
    let was = p.older.as_ref().map(Older::rows);
    let unchanged = match asked {
        Asked::Follows => before.follows.is_some(),
        Asked::Choice(c) => before.follows.is_none() && before.choice.same_spawn(c),
    };
    if unchanged {
        let older_tables = match &was {
            Some(rows) if p.models.is_some() => outcomes(&show, rows, rows),
            _ => vec![],
        };
        return Ok(Set {
            after: before.clone(),
            before,
            text: None,
            models_table_added: false,
            older_tables,
            warnings: show.warnings,
        });
    }
    let mut lines: Vec<String> = text.split_inclusive('\n').map(str::to_owned).collect();
    let asked = match asked {
        Asked::Choice(c) => Some(c),
        Asked::Follows => None,
    };
    match &p.models {
        Some(table) => {
            let mut block = Vec::new();
            for r in Role::ALL {
                let kept = table.rows.iter().find(|row| row.0 == r && r != role);
                block.push(match kept {
                    Some((_, at, _)) => ended(&lines[*at]),
                    None => row_line(r, if r == role { asked } else { None }, f),
                });
            }
            lines.splice(table.rows[0].1..table.end, block);
        }
        None => {
            let first = OLDER
                .iter()
                .filter_map(|name| section(&p.lines, name).ok().flatten())
                .map(|(at, _)| at)
                .min()
                .unwrap_or(lines.len());
            let mut block = vec![
                "## Models\n".to_owned(),
                "\n".to_owned(),
                format!("| {} |\n", MODELS_HEADER.join(" | ")),
                format!("|{}\n", " --- |".repeat(5)),
            ];
            for r in Role::ALL {
                let c = if r == role {
                    asked
                } else {
                    Some(&show.roles.get(r).choice)
                };
                block.push(row_line(r, c, f));
            }
            block.push("\n".to_owned());
            lines.splice(first..first, block);
        }
    }
    let mut text = lines.concat();
    let p2 = parse(&text, f)?;
    if let Some(older) = &p2.older {
        let want = resolve(&p2).older_rows();
        let have = older.rows();
        for (i, c) in want.iter().enumerate() {
            let Some(c) = c.as_ref().filter(|c| older_form(c) && **c != have[i]) else {
                continue;
            };
            if i < 4 {
                let at = older.tables[i].1;
                let cells = [
                    ("Harness", &c.names.harness, &f.provider, &c.provider),
                    ("Model", &c.names.model, &f.model, &c.model),
                    ("Effort", &c.names.effort, &f.effort, &c.effort),
                ];
                for (k, (setting, name, flag, id)) in cells.into_iter().enumerate() {
                    put(
                        &mut lines,
                        at[k],
                        &format!("| {setting} | {name} | `{flag} {id}` |"),
                    );
                }
            } else {
                let family = ["Claude", "GPT"][i - 4];
                let row = format!(
                    "| {family} | {} | {} | {} | {} |",
                    c.names.harness,
                    c.names.model,
                    c.names.effort,
                    c.flags(f)
                );
                put(&mut lines, older.fixers[i - 4].1, &row);
            }
        }
        text = lines.concat();
    }
    let p3 = parse(&text, f)?;
    let show = resolve(&p3);
    let older_tables = match (&p3.older, show.older_tables_present) {
        (Some(older), true) => {
            let in_file = older.rows();
            outcomes(&show, was.as_ref().unwrap_or(&in_file), &in_file)
        }
        _ => vec![],
    };
    Ok(Set {
        before,
        after: show.roles.get(role).clone(),
        text: Some(text),
        models_table_added: p.models.is_none(),
        older_tables,
        warnings: show.warnings,
    })
}

fn outcomes(show: &Show, was: &[Choice; 6], in_file: &[Choice; 6]) -> Vec<OlderRow> {
    let want = show.older_rows();
    (0..6)
        .map(|i| OlderRow {
            table: OLDER_ROWS[i],
            outcome: if want[i].as_ref() != Some(&in_file[i]) {
                RowOutcome::Kept
            } else if was[i] == in_file[i] {
                RowOutcome::Unchanged
            } else {
                RowOutcome::Changed
            },
        })
        .collect()
}

fn row_line(role: Role, c: Option<&Choice>, f: &SpawnFlags) -> String {
    match c {
        Some(c) => format!(
            "| {} | {} | {} | {} | {} |\n",
            role.row(),
            c.names.harness,
            c.names.model,
            c.names.effort,
            c.flags(f)
        ),
        None => format!("| {} | follows Builder | | | |\n", role.row()),
    }
}

fn ended(line: &str) -> String {
    if line.ends_with('\n') {
        line.to_owned()
    } else {
        format!("{line}\n")
    }
}

fn put(lines: &mut [String], at: usize, content: &str) {
    let line = &lines[at];
    let ending = &line[line.trim_end_matches(['\r', '\n']).len()..];
    lines[at] = format!("{content}{ending}");
}
