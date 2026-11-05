# The OpenWiz GitHub App: the person's checklist

GI4 of spec #2537 (#2546), for GI6 (#2548). The agent prepares the one OpenWiz
App with GitHub's manifest flow; the person clicks twice: **Create**, then
**Install**. Everything else is the agent's. The App, its installations and its
secret are pinned in [the identity contract](../../contracts/github-identity.v1.md).

**Assumption A1: the agent-side secret store.** With `--secret-store <program>`,
the setup puts the converted key straight into the Cloudroom secret: the program
gets the secret's name as its only argument and its value on stdin. Cloudroom
does not offer such a store yet (`room-cli` has only `secret request`, which the
person fills in). If it still does not by GI6, the setup runs with no
`--secret-store`, discards GitHub's converted key, and the person adds a fourth
step: one paste into Cloudroom's own secret prompt (Jake, 2026-11-13, J27;
private record: spec #2537, revision 5).

## Before: the agent

1. Checks the secret. If `OPENWIZ_GITHUB_APP_KEY` is delivered, the App already
   exists: the agent reconciles it (as in Click 2 below) and never registers
   another one.
2. Previews, then confirms, the one registration, for Jake's account. Add
   `--secret-store <A1 store>` to both commands only if Cloudroom offers one:

   ```sh
   python3 -I tools/github-app/setup.py --agent-for jparker2006
   python3 -I tools/github-app/setup.py --agent-for jparker2006 --yes --operation <the id it printed>
   ```

3. Gives the person the local page the second command announces, through
   Cloudroom's preview (`room-cli preview <port>`), never a public address.

## Click 1: Create

Open the link the agent gives you. It goes on to GitHub by itself, with the
App already filled in: OpenWiz, public, Metadata read, Contents, Issues and
Pull requests write, Checks and Actions read, no webhook.

- **Click "Create GitHub App".** Change nothing on the page.

GitHub returns to the setup, which converts GitHub's one-hour code and records
the public App id on this host. With a store, the key goes straight into the
Cloudroom secret `OPENWIZ_GITHUB_APP_KEY` and the id beside it as
`OPENWIZ_GITHUB_APP_ID`. Without one, the key is discarded. Either way it is
never shown, logged, put in an argument or URL, or left on disk. You are sent
on to GitHub's install page.

## Click 2: Install, on selected repositories only

On GitHub's install page:

- Choose **Only select repositories** and select exactly `jparker2006/ClosedWiz`.
- **Click "Install".**

The App is installed per account, so `openwizdev` gets the same click. Once the
key is in the secret (after step 4 if there is no store), the agent previews and
confirms the organisation's run, which reconciles the App from the secret and
registers nothing:

```sh
python3 -I tools/github-app/setup.py --agent-for openwizdev --organization
python3 -I tools/github-app/setup.py --agent-for openwizdev --organization --yes --operation <its id>
```

The agent gives you that run's announced local page. It goes straight to
GitHub's install page. Choose `openwizdev`, then **Only select repositories**:
exactly `openwizdev/openwiz` and `openwizdev/wizplugins`. **Click "Install".**

Never choose "All repositories": the setup refuses that installation.

## Step 4, only without an agent-side store (J27): paste the key once

1. On GitHub, open the App's settings (Settings, Developer settings, GitHub
   Apps, OpenWiz) and click **Generate a private key**. GitHub downloads one
   `.pem` file.
2. The agent opens Cloudroom's own secret prompt:
   `room-cli secret request OPENWIZ_GITHUB_APP_KEY`. Paste the file's base64,
   on one line (`base64 -w0 <file>.pem`, or `base64 -i <file>.pem` on a Mac),
   into that prompt only, never the chat. Then delete the downloaded file.

The key goes from GitHub's download into Cloudroom's prompt and never passes
through the setup. The App id is public; the agent gives it to the token
command as `OPENWIZ_GITHUB_APP_ID` (GI5, #2547).

## After: the agent

1. With the key delivered, the agent reruns the setup for each account. Each
   run reads the App from GitHub again, offers the install again if it is
   missing, and reads the installation back: this App's, on the named account,
   with selected repositories only. It prints
   `Installation <id> read back: <account>, selected repositories only.`
2. GI6 reads back each installation's exact repositories and writes C9's
   receipt (`docs/evidence/ci2-app-installation.md`).

## When something stops

- **Stopped after the page opened, before the App id was recorded:** the
  registration stays uncertain, because GitHub may have created the App. The
  setup never offers Create again until someone checks GitHub's App settings
  and names that operation with `--after-uncertain`. Delete any App it left
  there first.
- **The App id is recorded but the key never reached the secret:** the setup
  refuses to register again, for any account. Recover the key with step 4.
- **The key reached the secret but its id did not:** a run with the key
  delivered, and the store, writes the id only. It never converts or replaces
  the key again.
