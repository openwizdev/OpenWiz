# Factory settings in 0.2.0

This walkthrough is a **0.2.0 preview** until the [owner’s live check in #3383](https://github.com/openwizdev/OpenWiz/issues/3383) passes on the home machine and phone. See the [factory settings spec in #3375](https://github.com/openwizdev/OpenWiz/issues/3375) for the planned behavior.

## Open Settings

- **On T3 desktop**, open the WizBar board preview and select **Settings** on its side rail.
- **On your phone**, connect through T3 Connect, open the board yourself in T3’s Browser tab, then select **Settings** on the same rail.

## On first open

Settings fills the role rows from the tools and accounts already signed in on your home machine, using each tool’s current model and effort. Only the **local** driver starts enabled. Optional services start off. If nothing is signed in, the rows show **Not set** and Settings shows how to sign in. With two model families signed in, the reviewer uses the family other than the builder’s. If there is only one family available, the reviewer **Waits**.

## Try a role change and undo it

In this synthetic example, the Builder and Reviewer already use different model families. The Reviewer’s model offers **low**, **medium** and **high** effort and starts at **medium**.

1. On desktop, tell Wiz “Set reviewer effort to high” in the Wiz chat. You can also send those words from **Ask Wiz to change anything** in Settings. Wiz tells you what changed from **medium** to **high** and how to undo it.
2. On your phone, open Settings and tap the **Reviewer** row. Choose **low** effort in the dropdown. The row changes from **high** to **low**.
3. On your phone, say “Undo” in the Wiz chat. The row returns to **high**, the value just before the phone change.

## Accounts and proposed changes

Mark an account **Reserved** if you want to keep it to yourself. It disappears from every role dropdown, and the factory excludes it from launches, including fallback choices. In the Reviewer dropdown, choices from the builder’s model family are disabled with an explanation.

If an agent suggests changing a setting, the proposal appears in **Needs-you**. Check the proposed change and confirm it if you want it applied. Wiz applies it only after your confirmation.

To set up a key, choose **Set key** in **Accounts and keys** or ask Wiz to open the key setup. Enter the value only in T3’s secret card. The value goes to the configured secret store. Settings shows the key’s status and where it’s stored. See the [keys and sign-ins spec in #3420](https://github.com/openwizdev/OpenWiz/issues/3420).

## Where changes go

The Settings tab and Wiz chat save each change immediately to one settings file in your home project on your home machine. It keeps the last 10 earlier versions for undo. Each change also gets its own backup commit on the `openwiz/settings` branch of your home repository.

Only new launches read the updated setting. A running job keeps the setting it started with, including when it wakes again.
