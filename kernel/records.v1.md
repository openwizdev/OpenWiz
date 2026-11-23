# OpenWiz records, version 1 (`openwiz:records v1`)

A factory keeps its state on GitHub: the issues, their labels, their comments and the links between them. These are the notebook's rules. Any tool (an agent, a bot, the app, a driver, a script) that follows them can read and write a factory's state correctly. The rules are versioned: a later version adds rules beside these and never changes a v1 rule's meaning.

Its test kit is [`records-kit/`](records-kit/README.md). It reads a tracker, either a fixture or a real repository, and reports every record that breaks a rule below, one line per break, naming the rule.

## 1. Labels

People set five labels. They are gates, never an agent's progress:

| Label | Means |
| --- | --- |
| `spec` | The issue is a spec |
| `ready-for-agent` | Approved: an agent can take it once its blockers are done |
| `ready-for-human` | Approved: a person has to do it |
| `needs-info` | Waiting on the user. The status section below says when an agent adds or clears it |
| `held` | Held: it waits for the user's approval of a changed plan or contract |

- **L1.** No label says what an agent is doing. `building`, `in-review`, `in review`, `needs-you`, `needs you`, `in-progress`, `in progress` and `merged` are never set. Building, in review and merged are read from GitHub (section 5).
- **L2.** A held issue has no ready label: `held` never sits beside `ready-for-agent` or `ready-for-human`.
- **L3.** A spec carries `spec`, and a ticket never does.

A project may keep other labels of its own (for example `polish`). Records v1 gives them no meaning, and no tool may read state from them.

## 2. The status note

Each agent says what it is doing in one status note per ticket, edited in place. The status note is the [OpenWiz agent status contract, version 1 (`openwiz:status v1`)](https://github.com/openwizdev/WizSkills/blob/a2993f47b8fd3d7853ee45e6c21feea708c70c02/contracts/agent-status.v1.md) from WizSkills: this section is that contract, unchanged. It fixes the note's marker, its fields (with the skills and versions the agent ran in its `skills` line), which authors count, when a note is live, which live note holds a claim, when `needs-info` is added and cleared, and what a note never holds. Records v1 adds nothing to it.

The kit checks two of its rules on every open issue:

- **S1.** At most one live note of each kind (`agent`) per issue.
- **S2.** A comment from a record author that starts with the v1 marker reads as a v1 note: its keys in order, each once, the required ones present, `agent` and `state` among their values.

The contract's own checker (`status.py check`) covers the rest.

## 3. Templates

Every spec and ticket is an issue whose body has the sections below, each as a `## ` heading on its own line, outside code blocks. Other sections may be added.

**A spec** has `## Problem Statement`, `## Solution`, `## Changelog headline`, `## User Stories`, `## Implementation Decisions`, `## Testing Decisions`, `## Proof`, `## Out of Scope` and `## Further Notes`. It may also have `## Live check`, when it touches the user's machine or account.

**A ticket** is a sub-issue of its spec. It has `## Parent`, `## What to build`, `## Owned paths`, `## Links`, `## Acceptance criteria` and `## Proof`, and one line starting `**Relies on:**`. A ticket for a person (`ready-for-human`) also has `## Done by`.

- **T1.** Every open spec and every open ticket has its template's sections.

## 4. Blockers

- **B1.** A ticket waits for another issue only through GitHub's native "blocked by" link. Text in a body never blocks. Each native blocker gets one reason line in `## Links`, as the [plan links contract](https://github.com/openwizdev/WizSkills/blob/8fea52a934492272e3d138c79602f93c9e2d45e0/contracts/plan-links.v1.md) says, in its short form (`- #<n>`) or its long form naming this repository (`- <owner>/<repo>#<n>`, in any case).
- **B2.** A blocker is done only when it is closed as completed. A blocker closed as not planned or as a duplicate is not done, and never will be. An open issue that has such a blocker is a break, and its plan must change: drop the link, or replace the blocker.

## 5. Everything else is read from GitHub

Nothing else is stored. A tool reads the rest from GitHub itself:

| What | Read from |
| --- | --- |
| Approved | A ready label (section 1) |
| Can start | Approved, not held, and every native blocker done (B2) |
| Building | A live `working` note from a builder (section 2) |
| In review | An open pull request that closes the ticket |
| Merged | The ticket's closing pull request has merged |
| Waiting on the user | `needs-info`, or a live `asking` note |
| A ticket's spec | Its parent issue |
| Done | Closed as completed |

## 6. The host setting

A project says where its agents run in one file on its default branch, `docs/agents/host.md`. It holds one setting line, `Host: <name>`, where `<name>` is a driver's folder in OpenWiz's `adapters/` (such as `local`, `cloudroom` or `boat`): lowercase letters, digits and single hyphens, at most 40 characters, as a [driver v1](driver.v1.md) names itself. The rest of the file is prose for people.

- **H1.** Onboarding asks once and writes the file. The person changes it by asking their agent, which edits that one line; nothing else changes.
- **H2.** A start reads the setting on the default branch as it is then, and calls that host's driver. A wake or a stop uses the run's saved driver, the one that started it, even after the setting changes.
- **H3.** A file without exactly one valid setting line starts nothing: the tool says what is wrong. A project with no file has chosen no host, and its tools keep their own default.
- **H4.** The setting names a host and nothing more: never a login, token, key, machine or account.

The kit doesn't check the setting: it reads the tracker, not the repository's files.

## The kit's checks

| Rule | The kit reports |
| --- | --- |
| L1 | An open issue with an agent-state label |
| L2 | An open issue with `held` and a ready label |
| L3 | An open ticket whose open parent lacks `spec`, or an open ticket that carries `spec` |
| S1 | Two or more live notes of one kind on one open issue |
| S2 | A record author's v1-marked comment that doesn't read as a v1 note |
| T1 | An open spec or ticket missing a template section, each missing part on its own line |
| B1 | An open ticket's native blocker with no reason line or more than one in `## Links`, or a malformed `## Links` section, as the plan links contract reads them |
| B2 | An open issue with a native blocker closed as anything but completed |

B1 is checked in part: the kit reports a ticket's native blocker with no reason line or more than one, and a malformed `## Links` section, as the plan links contract reads them; it is narrower than that contract's checker, never reporting a line that names no native blocker, a reason line's wording or a text "blocked by", which need a reader's judgement. Rules on closed issues are not checked: their records are history.
