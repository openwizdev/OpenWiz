# Grills

**Private.** Each grill is saved exactly, question by question, after every round (the `grill` skill's rules). One file per grill; one PR per grill, merged once Jake confirms its summary, or parks the grill.

The index is printed from the files, never written here, so no grill's PR edits this file and none conflicts with another (#317). From the repository's root:

```sh
sh skills/grill/scripts/index.sh
```

It prints one row per grill file, in file-name order: its topic, its status (**open**, **parked** or **confirmed**, with the date) and what it feeds, all read from the file's status paragraph. A grill still open on its own branch shows only there, in its PR.
