# Runbook: email

The study sends two kinds of email, from two subdomains, so that one never affects whether
the other arrives:

| What | From | Sent by | Resend plan |
|---|---|---|---|
| Sign-in links | `signin@mail.thedefinitivesanjeevexperience.com` | the server, one at a time | transactional |
| Invitations and game nights ([recruitment.md](../recruitment.md)) | `fish@news.thedefinitivesanjeevexperience.com` | you, with `scripts/broadcast.py` | marketing (Broadcasts) |

All times below are Eastern; from 1 November to 13 March that is UTC−5, so `-05:00`.

## 1. Before Mon 16 Nov: the invitation domain, the lists, the key

**The domain.** In Resend, **Domains → Add domain**: `news.thedefinitivesanjeevexperience.com`,
in the same region as `mail.`. Add the records Resend lists where you added the `mail.` ones
(an `MX` and a `TXT` for bounces, and a `TXT` for the signature), then **Verify**. The free
plan allows three domains; this is the second.

**The lists.** In Resend, under **Audience**, make the segments, named exactly as
[recruitment.md](../recruitment.md) §4 names them (the script finds them by name):

| Segment | What goes in | When |
|---|---|---|
| `Test` | your own addresses, for trying each message first | now |
| `Gov School` | the Gov School group: import a CSV with an `email` column | now |
| `Pool` | everyone else willing to play | by Mon 7 Dec, after the upgrade in §2 |
| `Players: group 1`, `Players: group 2` | copied from the study database (T4.1 subtask 4) | before each Monday |

Delete each CSV from your computer once it is imported. A list never goes in the repository.

**The key.** `scripts/broadcast.py` needs a key with **Full access** (Broadcasts and segments
need it; the server's own key stays sending-only). In Resend, **API Keys → Create**, name it
`broadcasts (laptop)`, and keep it in your macOS keychain rather than a file:

```bash
security add-generic-password -a "$USER" -s fish-resend-broadcast -w   # paste the key when asked
```

and each time you send, in that terminal:

```bash
export RESEND_BROADCAST_KEY="$(security find-generic-password -a "$USER" -s fish-resend-broadcast -w)"
```

## 2. Before Tue 8 Dec: plans that can take the launch

- **Sign-in links.** The free transactional plan stops at 100 emails a day, and the server
  stops itself at 90 (`FISH_SIGNIN_DAILY_LIMIT`). On launch day more people than that will
  ask for links. Move to **Pro** (50,000 a month, no daily limit) and give the production
  service `FISH_SIGNIN_DAILY_LIMIT=1500` in `render.yaml` (T4.3). Staging keeps 90: the pilot
  is small.
- **Invitations.** The free marketing plan holds 1,000 contacts, enough for `Test`, `Gov
  School` and the pilot. Before importing `Pool`, move to the marketing plan for its size
  (5,000 contacts at the time of writing). It is needed until the last invitation, M6 on
  9 February.

Check the prices on Resend's pricing page when you upgrade; they change.

## 3. Sending a message

Every message is sent the same way: preview it, send it to yourself, then make the real one.

```bash
uv run python scripts/broadcast.py M1 --segment "Gov School"             # 1. read it
uv run python scripts/broadcast.py M1 --segment Test --create            # 2. a draft to Test
```

For step 2, open the draft in Resend (**Broadcasts**), press **Send**, and read the email on
your phone: the links, the unsubscribe link, and that nothing reads oddly. Then:

```bash
uv run python scripts/broadcast.py M1 --segment "Gov School" --create \
    --send-at 2026-11-16T09:00:00-05:00                                  # 3. scheduled
```

or leave out `--send-at` and send the draft from the dashboard when you are ready. Every
message goes at 9:00 am Eastern on its day:

| Message | Command (after `uv run python scripts/broadcast.py`) |
|---|---|
| M1, Mon 16 Nov | `M1 --segment "Gov School" --create --send-at 2026-11-16T09:00:00-05:00` |
| M2, Mon 30 Nov | `M2 --segment "Gov School" --create --send-at 2026-11-30T09:00:00-05:00` |
| M3, Tue 8 Dec | `M3 --segment "Gov School" --fill N=<minutes> --create --send-at 2026-12-08T09:00:00-05:00`, then the same with `--segment Pool` |
| M4, each Monday | `M4 --segment "Players: group 1" --week <that Monday> --create --send-at <that Monday>T09:00:00-05:00`, then the same with `"Players: group 2"` |
| M5, Tue 12 Jan | `M5 --segment "Gov School" ...`, then `--segment Pool` |
| M6, Tue 9 Feb | `M6 --segment "Gov School" ...`, then `--segment Pool` |
| M7, Mon 15 Feb | `M7 --segment "Players: group 1" ...`, then `"Players: group 2"` |

M3's `<minutes>` is the pilot's median game length, rounded to five minutes. Before each M4,
copy the players into their segments (T4.1 subtask 4) and check the week's pace
([recruitment.md](../recruitment.md) §3).

The script takes the words from `docs/recruitment.md` and nowhere else, and refuses a
message for a list its heading does not name, a placeholder left unfilled, a `--week` that is
not a Monday, or a time already past. To change a message, change the page (a pull request,
as for any change), then send.

## 4. After 31 March 2027

The email list is deleted that day (Research Plan §6), and Resend's copy with it: in Resend,
delete every contact and segment, then revoke the `broadcasts (laptop)` key and remove it from
your keychain (`security delete-generic-password -s fish-resend-broadcast`). Move both plans
back to free.
