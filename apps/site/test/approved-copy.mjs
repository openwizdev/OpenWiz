// Independent literals from the approved copy and the release claim sources.
// #1352 (Jake, landing grill LR1-LR6, LP4-LP6): headline "User decides, agents do." and the
// approved lead; the main button copies a prompt for your agent; Works today is one plain line per
// published version (#1190's lines); Building next is one plain line per planned version, from the
// version specs, 0.0.6 to 0.0.14. The changelog copy is #1199's: one entry per version.
// #1109 (0.0.13 T7): the one install line, the confirmed grill's I1 order at the public address.
// An agent resolves it through the packaged install skill (skills/install/SKILL.md).
export const setupPrompt = 'Install OpenWiz from github.com/openwizdev/openwiz';
// #2293 (reconciling #1109's upgrade line, contracts/public-offer.v1.md): OpenWiz is free now and
// paid plans come later; CloudRoom and model charges are separate, never an OpenWiz upgrade. No
// owner-supplied referral is verified, so the link is CloudRoom's own pricing page with none, and
// the page says verification is unavailable.
export const costLine = 'OpenWiz is free now. Paid plans come later. CloudRoom and model charges are separate and not included. Referral verification is unavailable. No referral is applied. CloudRoom plans ↗';
export const cloudroomHref = 'https://cloudroom.dev/pricing';
// #2293: no OpenWiz upgrade, price, trial, subscription or checkout anywhere on the landing.
export const notOffered = /upgrad|\btrial|\$\s?[0-9]|per month|checkout|subscri/i;
export const landing = [
  'User decides, agents do.',
  'Approve one plan. A fleet of coding agents builds it.',
  'Paste into your agent to install OpenWiz',
  setupPrompt,
  'Copy the prompt Star on GitHub',
  costLine,
  'Building now: where OpenWiz is going, not released yet.',
  'Works today',
  '0.0.1 List and inspect your CloudRoom threads from the terminal.',
  '0.0.2 View your threads in a private web page on your phone or computer.',
  '0.0.3 Queue a message or steer a thread from the terminal or web page.',
  '0.0.4 Start a Cloud thread in an existing project, with files or images attached.',
  '0.0.5 Use eight fleet skills to plan, build and review work with coding agents.',
  'Changelog →',
  'Building next',
  '0.0.6 Run fleets inside OpenWiz and watch them on a fleets screen.',
  '0.0.7 Helper agents that speed up building and reviewing.',
  '0.0.8 OpenWiz runs on an always-on machine, so fleets keep going without you.',
  '0.0.9 OpenWiz runs your loops and sends each event to the agent that owns it.',
  '0.0.10 The cockpit: what needs you, every running agent, and a command bar.',
  '0.0.11 Decide from the cockpit, with a live plan graph and decision cards.',
  '0.0.12 A visual app in your terminal, and every command ready for agents.',
  '0.0.13 Ask your agent to install OpenWiz, then launch your first fleet.',
  '0.0.14 Run threads on your own server, with overflow to Cloud when it is full.',
].join(' ');
export const worksToday = ["0.0.1", "0.0.2", "0.0.3", "0.0.4", "0.0.5"];
export const buildingNext = ["0.0.6", "0.0.7", "0.0.8", "0.0.9", "0.0.10", "0.0.11", "0.0.12", "0.0.13", "0.0.14"];

// The intro is one labelled illustration (role="img"): its synthetic text is checked on its own,
// apart from the page's claims, and says it is not released (its label and the caption above).
export const stage = "OpenWiz New ideaDark mode · 5 ticketsAdd a dark mode toggle to Settings0/5 merged1/5 merged2/5 merged3/5 merged4/5 merged5/5 merged #101Theme tokensOpuswaitingbuildingPR #212 merged #102Settings toggleSolwaitingbuildingPR #213 merged #104Charts in darkHaikuwaitingbuildingPR #214 merged #103Remember the choiceSolwaitingbuildingPR #215 merged #105Check it on a phoneOpuswaitingbuildingPR #216 merged 1 approval · 5 pull requests mergedApprove planApproved by you you type one idea you approve once agents build side by side you watch the board";
export const stageLabel = 'Building now, not released yet. Illustration: you type one idea, Add a dark mode toggle to Settings; it becomes a plan of five tickets; you approve it once; three agents build side by side; their pull requests merge; the board shows all five merged.';

// #1190, W1: none of these may appear anywhere on the landing, visible,
// hidden or in an attribute. Labels from the ticket and the copy it replaces.
export const bannedLanding = [/staged/i, /pending/i, /fixture/i, /live observation/i, /live[- ]test/i, /LIVE-/, /\bgaps?\b/i, /PACP/i, /evidence/i];
// The landing's visible main text before #1190 (normalized, in characters):
// the #1114 approved copy at 6b8649e8. The new landing must be shorter.
export const landingCharsBefore1190 = 3594;

// #1199: Jake approved one section per version, 2026-11-06.
// Private record: https://github.com/jparker2006/ClosedWiz/issues/1277#issuecomment-6705218593
// Each section has a huge numeral and its date,
// then the headline, 3 to 6 numbered lines and one small link. Words from the public CHANGELOG.md.
const notes = 'https://github.com/openwizdev/openwiz/blob/main/CHANGELOG.md';
export const changelogEntries = [
  // [id, version, datetime, shown date, headline, lines, link]
  ['v0.0.5', '0.0.5', '2026-11-05', 'Nov 5, 2026', 'Fleets of agents build for you', [
    'Eight fleet skills for coding agents: grill you on an idea, plan it into tickets, then build, review and merge each one.',
    'They ship as a Claude Code plugin, and as skill folders Codex reads from the repo.',
    'Every merge needs an independent review of the exact commit and green CI.',
  ], `${notes}#005--2026-11-05`],
  ['v0.0.4', '0.0.4', '2026-11-05', 'Nov 5, 2026', 'Start new threads, with files', [
    'openwiz new starts a Cloud thread in one of your projects. It shows exactly what it will do, and only creates it with --yes.',
    'Attach files and images to a new thread or a queued message, from the terminal or the web page.',
    'One thread per create: if the result is unclear, it tells you instead of trying again.',
  ], `${notes}#004--2026-11-05`],
  ['v0.0.3', '0.0.3', '2026-11-05', 'Nov 5, 2026', 'Message your threads', [
    'openwiz send sends one message to a thread, as Queue or Steer.',
    'Or send from the web page on your phone.',
    "If a send's result is unclear, OpenWiz says so instead of sending twice.",
  ], `${notes}#003--2026-11-05`],
  ['v0.0.2', '0.0.2', '2026-10-30', 'Oct 30, 2026', 'Your threads on your phone', [
    'A private web page served from your own computer: threads by project, with status and age; tap one for details.',
    'Reach it from anywhere through a Cloudflare Tunnel and a login for your email only.',
    "Read-only, and it tells you when data is stale or you're signed out.",
  ], `${notes}#002--2026-10-30`],
  ['v0.0.1', '0.0.1', '2026-10-30', 'Oct 30, 2026', 'Your CloudRoom threads in the terminal', [
    'openwiz ls lists your threads with status, project and age; -l adds a recap, model and effort.',
    'openwiz show <id> shows one thread and its final output.',
    '--json for scripts. Read-only: it never changes a thread.',
  ], `${notes}#001--2026-10-30`],
  ['v0.0.0', '0.0.0', '2026-10-22', 'Oct 22, 2026', 'The design', [
    'Published first as OpenFleet.',
    'The design, architecture and release rules, no code yet.',
    'Renamed to OpenWiz before 0.0.1.',
  ], `${notes}#000--2026-10-22`],
];
export const changelog = [
  'Changelog.',
  "What's tested and what isn't ↗",
  ...changelogEntries.flatMap(([, version, , shown, headline, lines]) => [`${version} ${shown} ${headline}`, ...lines, `${version} on GitHub ↗`]),
].join(' ');
const published = 'https://github.com/openwizdev/openwiz/blob/54a96ddddddc80b41ce129485fa31fc2b67da5bf/';
// These public destinations receive the staged release on Jake's publish step.
// Keep the old releases pinned to their historical evidence.
const release = 'https://github.com/openwizdev/openwiz/blob/main/';
export const landingLinks = [
  'https://github.com/openwizdev/openwiz', cloudroomHref, ...Array(6).fill('/changelog/'),
];
export const changelogLinks = [`${release}docs/testing.md`, ...changelogEntries.map(entry => entry[6])];
