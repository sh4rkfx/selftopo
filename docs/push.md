# Push notifications

On days with a Today card (see [recommendations.md](recommendations.md)), the daily workflow can
send it to the installed dashboard as a notification. There is no selftopo server: the workflow
in your data repository sends the message itself through the push service of the browser (Apple,
Google or Mozilla), encrypted with keys only your device knows.

## Setup

1. **Make a key pair once** (needs Python with the requirements installed):

   ```bash
   python -m selftopo push-keys
   ```

   It prints a public and a private key.
2. **Private key → secret.** In the data repository, *Settings → Secrets and variables → Actions →
   New repository secret*: name `VAPID_PRIVATE_KEY`, value the private key.
3. **Workflow.** Data repositories made before this feature need the step *Push notification*
   and the input `push_test` from
   [templates/data-repo/.github/workflows/sync.yml](../templates/data-repo/.github/workflows/sync.yml).
   Copy the template over `.github/workflows/sync.yml` in the data repository.
4. **On each device.** Open the installed app, gear icon → *App* → *Push notifications*, paste the
   public key, *Turn on for this device* and allow notifications. Then save `settings.json`
   (*Go to saving*) the usual way. On the iPhone and iPad this only works in the app added to the
   Home Screen (iOS/iPadOS 16.4 or later), not in Safari.
5. **Check.** *Actions → Sync → Run workflow* with `push_test` = `yes` sends a test message to
   every device.

From then on, the workflow sends the Today card after the analysis, in the language the device had
when it was turned on. Without a Today card for the day, nothing is sent.

## settings.json

```json
{
  "push": {
    "public_key": "BP…",
    "subscriptions": [
      { "endpoint": "https://web.push.apple.com/…", "keys": { "p256dh": "B…", "auth": "…" }, "lang": "de", "added": "2026-11-10" }
    ]
  }
}
```

The dashboard writes both. The public key is not secret. A subscription only lets someone with the
private key send to that device.

## When something does not arrive

| Log line of the workflow | Meaning |
|---|---|
| `subscriptions exist, but the secret VAPID_PRIVATE_KEY is not set` | Step 2 is missing |
| `no device has turned notifications on` | No subscription in `settings.json`: turn on and save |
| `a subscription has expired (HTTP 410)` | The browser dropped the subscription (app removed, data cleared). Turn on again on that device and save |
| `no Today card for …, nothing sent` | Normal on good days |

A new key pair makes every saved subscription useless: turn notifications on again on each device.

## Privacy

The message body is encrypted for the device; the push service only sees that a message of a
certain size goes to a device at a certain time. The text appears on the lock screen like any
notification, so it can name readiness or resting heart rate. Turning off on the device and saving
removes the subscription; deleting the secret stops all sending.
