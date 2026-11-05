# Live checks run as soon as a version is built; publishing stays in version order

Live checks used to wait for the previous version to be published, which stacked days of waiting behind slow gates such as 0.0.8's full day with the Mac shut. Jake decided on 2026-11-07 that each version's live checks run as soon as its tickets are done, in parallel with earlier versions, while publishing stays strictly in version order, and that 0.0.6 and 0.0.7 publish together as one update once 0.0.6 passes, each keeping its own changelog section.

Source: Jake, 2026-11-07: run live checks when each version is built, publish in version order, and combine 0.0.6 with 0.0.7 after 0.0.6 passes, retaining separate changelog sections ([private record](https://github.com/jparker2006/ClosedWiz/issues/1276#issuecomment-6704797460)).
