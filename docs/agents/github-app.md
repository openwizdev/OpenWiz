# The OpenWiz GitHub App: the person's checklist

**Status (legacy route):** today the App identity is off for everyone (#2394), and spec #1837 replaced this CloudRoom-secret route with the owner-side token service ([`docs/github-app.md`](../github-app.md#the-token-service-ga2)); put no App key in a CloudRoom secret or prompt. This page documents `tools/github-app/setup.py --agent-for`, kept as the legacy record.

GI4 of spec #2537 (#2546), revised for 0.0.16 by T3 (#606). The agent prepares
an OpenWiz App with GitHub's manifest flow; the person clicks twice: **Create**,
then **Install**. Everything else is the agent's. The factory's App and the
secret are pinned in [the identity contract](../../contracts/github-identity.v1.md);
each user's own App and the key routes in
[setup-onboard.v1](../../contracts/setup-onboard.v1.md).

## Two Apps, never inferred (J48)

- **Your own App (the default).** Private, named `OpenWiz <your login>` (GitHub
  App names are unique, and `OpenWiz` is the factory's), installable only on
  the account that owns it, on selected repositories only. Its tokens mint
  only for an installation on that owner's account and a repository it owns.
  A repository elsewhere is refused. It never switches to a public App.
- **The factory's App.** Public, because one App installs on the factory's two
  accounts. It is used only through the explicit factory setting: `--factory`
  for `setup.py`, and `OPENWIZ_GITHUB_APP_MODE=factory` (a public, non-secret
  variable) for `openwiz github token` and `mint-token.py`. In that mode only the
  installations the identity contract names are accepted. Unset, or `user`,
  means your own App. Any other value is refused.

Both use the same fixed permissions: Metadata read; Contents, Issues and Pull
requests write; Checks and Actions read; no webhook. Commits stay authored and
committed as the person.

## Where the key goes

The key lives once, as the CloudRoom secret `OPENWIZ_GITHUB_APP_KEY` (base64 of
the PEM, one line), with the public App id as `OPENWIZ_GITHUB_APP_ID`. It never
enters chat, output, an argument, a URL, a log, a prompt or Git.

- **No paste (not available yet).** GitHub's converted key would go straight
  to the secret through the **CloudRoom agent-side save-secret contribution**,
  leaving no key file. That contribution has not shipped and has not been
  observed. `--secret-store <program>` is only the seam it will use: the
  program gets the secret's name as its only argument and its value on stdin.
  A test stand-in proves the seam, never that CloudRoom offers it.
- **One protected paste (the supported route today).** With no
  `--secret-store`, the setup discards GitHub's converted key and keeps the
  App's id. The person then provisions a fresh key once, as in "Step 4" below.
  That costs six more owner actions, each counted: open the App's settings,
  generate a key, GitHub's browser download, encode it to one line, paste it
  into CloudRoom's own protected prompt, and delete the download. The download
  is the one temporary key file on this route. It is the owner's, outside any
  OpenWiz component and Git tree, and deleted after the paste. This is not a
  no-download route.

`python3 -I tools/github-app/setup.py --agent-for <login> --capability
[--secret-store <program>]` prints this host's setup-onboard.v1
`secret_capability` document. It needs no network and writes nothing. Delivery
is `verified` only when the delivered key decodes and its delivered App id agrees
with the one recorded here. The owner's steps and the download's deletion are
the documented route's; the setup never observes them.

## Before: the agent

1. Checks the secret. If `OPENWIZ_GITHUB_APP_KEY` is delivered, the App already
   exists: the agent reconciles it (as in "After" below) and never registers
   another one.
2. Previews, then confirms, the one registration, for the person's own account
   (add `--organization` for an organisation they own):

   ```sh
   python3 -I tools/github-app/setup.py --agent-for <login>
   python3 -I tools/github-app/setup.py --agent-for <login> --yes --operation <the id it printed>
   ```

   Add `--secret-store <program>` only once the save-secret contribution is
   observed. Add `--factory` only for the factory's own App.
3. Gives the person the local page the second command announces, through
   CloudRoom's preview (`room-cli preview <port>`), never a public address.

## Click 1: Create

Open the link the agent gives you. It goes on to GitHub by itself, with the
App already filled in: `OpenWiz <your login>`, private, the permissions above,
no webhook. Be signed in to GitHub as that same account.

- **Click "Create GitHub App".** Change nothing on the page.

GitHub returns to the setup. It converts GitHub's one-hour code, checks that
the new App is owned by the named account and records the public App id on
this host. With an observed save-secret store, the key goes straight into the
secret and the id beside it; without one, the key is discarded. Either way it
is never shown, logged, put in an argument or URL, or left on disk. You are
sent on to GitHub's install page.

## Click 2: Install, on selected repositories only

On GitHub's install page:

- Choose **Only select repositories** and select the repositories you were given.
- **Click "Install".**

Never choose "All repositories": the setup refuses that installation, and one
on another account.

## Step 4, only without an observed save-secret store: paste the key once

1. On GitHub, open the App's settings (Settings, Developer settings, GitHub
   Apps, your App) and click **Generate a private key**. GitHub downloads one
   `.pem` file.
2. The agent opens CloudRoom's own secret prompt:
   `room-cli secret request OPENWIZ_GITHUB_APP_KEY`. Paste the file's base64,
   on one line (`base64 -w0 <file>.pem`, or `base64 -i <file>.pem` on a Mac),
   into that prompt only, never the chat. Then delete the downloaded file.

The key goes from GitHub's download into CloudRoom's prompt and never passes
through the setup. The agent gives the token command the public App id as
`OPENWIZ_GITHUB_APP_ID`.

## After: the agent

1. With the key delivered, the agent reruns the setup. Each run reads the App
   from GitHub again: it must be this App, with the fixed permissions, owned by
   the named account (or, with `--factory`, on one of the factory's named
   accounts). It offers the install again if it is missing, and reads the
   installation back: this App's, on the named account, with selected
   repositories only. It prints
   `Installation <id> read back: <account>, selected repositories only.`
2. Later runs reuse the same App and secret. Nothing is registered again and
   no key is entered again.

## Rotation and revocation

- **Rotate:** generate a new private key in the App's settings and provision
  it as in Step 4. The next run reconciles the same App with the new key.
  Then delete the old key in the App's settings. Nothing is registered.
- **Revoked or deleted key:** GitHub refuses the App's JWT. The setup and every
  token command refuse, with no token printed and no other identity used.
  Provision a new key as in Step 4.

## When something stops

- **Stopped after the page opened, before the App id was recorded:** the
  registration stays uncertain, because GitHub may have created the App. The
  setup never offers Create again until someone checks GitHub's App settings
  and names that operation with `--after-uncertain`. Delete any App it left
  there first.
- **The App id is recorded but the key never reached the secret:** the setup
  refuses to register again, for any account. Recover the key with Step 4.
- **The key reached the secret but its id did not:** a run with the key
  delivered, and the store, writes the id only. It never converts or replaces
  the key again.
- **The App was created by another account** (the browser was signed in as
  someone else): the setup refuses it. No key is kept and nothing is offered
  for install. Its id stays recorded, so nothing is registered blindly. Delete
  that App in that account's GitHub App settings, then remove the recorded id
  (`<state>/service/app/app.json`) and preview again.
- **A token for a repository outside the owner's account:** refused (exit 5).
  Use the personal-login path for it only if the owner explicitly chooses that
  path in setup. Nothing switches identity on its own.
