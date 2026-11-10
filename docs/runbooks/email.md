# Runbook: email

The study sends two kinds of email, from two subdomains, so that one never affects whether
the other arrives:

| What | From | Sent by | Resend plan |
|---|---|---|---|
| Sign-in links | `signin@mail.thedefinitivesanjeevexperience.com` | the server, one at a time | transactional |
| Invitations and game nights ([recruitment.md](../recruitment.md)) | `fish@news.thedefinitivesanjeevexperience.com` | you, with `scripts/broadcast.py` | marketing (Broadcasts) |

All times below are Eastern; from 1 November to 13 March that is UTC−5, so `-05:00`.

**Every Monday, 14 December to 8 February**, in this order:

1. In the production service's **Shell**: `python -m fish_server.stats`, checked against
   [collection.md](collection.md) §3. If it says two full weeks in a row were short, add a
   Friday night ([recruitment.md](../recruitment.md) §3) first.
2. In the same Shell: `python -m fish_server.integrity`. It prints PASS, or faults to deal
   with the same day ([collection.md](collection.md) §4). Then `python -m fish_server.audience`
   (§4).
3. On your computer: M4 for `Players: group 1`, then for `Players: group 2` (§3), for 9:00 am.
4. The weekly corpus copy ([backups.md](backups.md) §2): export in the Shell, copy it to your
   laptop, check it, and delete last week's. It goes on one more Monday, 15 February.

## 1. Before Mon 16 Nov: the invitation domain, the lists, the key

**The domain.** In Resend, **Domains → Add domain**: `news.thedefinitivesanjeevexperience.com`,
in the same region as `mail.`. Add the records Resend lists where you added the `mail.` ones
(an `MX` and a `TXT` for bounces, and a `TXT` for the signature), then **Verify**. The free
plan allows three domains; this is the second.

**The lists.** In Resend, under **Audience**, make three segments, named exactly as
[recruitment.md](../recruitment.md) §4 names them (the script finds them by name). Three is
the most the free marketing plan allows:

| Segment | What goes in | When |
|---|---|---|
| `Invited` | the Gov School group, from a CSV with one column, `email` | now |
| `Invited` | the rest of those invited, imported into the same segment: about 950 people in all, Gov School included | Mon 7 Dec |
| `Players: group 1`, `Players: group 2` | make them empty now; they are filled from the study database (§4) | before each Monday |

Someone on both of your lists becomes one contact, since Resend keeps one per address. Delete
each CSV from your computer once it is imported. A list never goes in the repository.

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
  ask for links. Move to **Pro** (50,000 a month, no daily limit). `render.yaml` gives the
  production service `FISH_SIGNIN_DAILY_LIMIT=1500` (T4.3). Staging keeps 90: the pilot is
  small.
- **Invitations stay on the free plan.** It holds 1,000 contacts and three segments, and
  every contact counts once, whichever segments it is in. About 950 are invited, which leaves
  room for players who sign up with another address: `fish_server.audience` adds them as new
  contacts. If Resend ever refuses a contact for the limit, the copy stops and says so (§4).
  Never delete a contact who unsubscribed to make room: Resend would forget that they did.

Check the price on Resend's pricing page when you upgrade; it changes.

## 3. Sending a message

Every message is sent the same way: preview it, make a draft and read a test copy of it, then
send the draft.

```bash
uv run python scripts/broadcast.py M1 --segment Invited                  # 1. read it
uv run python scripts/broadcast.py M1 --segment Invited --create         # 2. a draft
```

For step 2, open the draft in Resend (**Broadcasts**) and use **Send test email** to send a
copy to your own address. Read it on your phone: the links, the footer's privacy policy (the
pilot site's for M1 and M2, the study site's after) and unsubscribe links, and that nothing
reads oddly.

Before it makes anything, `--create` checks that Resend tracks neither opens nor clicks on
`news.` and `mail.thedefinitivesanjeevexperience.com`, because the privacy policy says we
never do (T3.8). Both are off unless someone turns them on. If it refuses, turn tracking off
in Resend (**Domains**, the domain, **Configuration**), then run it again. Then schedule the draft in the dashboard for 9:00 am Eastern on its
day, or delete it and make it scheduled in one step:

```bash
uv run python scripts/broadcast.py M1 --segment Invited --create \
    --send-at 2026-11-16T09:00:00-05:00                                  # 3. scheduled
```

Every message goes at 9:00 am Eastern on its day:

| Message | Command (after `uv run python scripts/broadcast.py`) |
|---|---|
| M1, Mon 16 Nov | `M1 --segment Invited --create --send-at 2026-11-16T09:00:00-05:00` |
| M2, Mon 30 Nov | `M2 --segment Invited --create --send-at 2026-11-30T09:00:00-05:00` |
| M3, Tue 8 Dec | `M3 --segment Invited --fill N=<minutes> --create --send-at 2026-12-08T09:00:00-05:00` |
| M4, each Monday | `M4 --segment "Players: group 1" --week <that Monday> --create --send-at <that Monday>T09:00:00-05:00`, then the same with `"Players: group 2"` |
| M5, Tue 12 Jan | `M5 --segment Invited --create --send-at 2027-01-12T09:00:00-05:00` |
| M6, Tue 9 Feb | `M6 --segment Invited --create --send-at 2027-02-09T09:00:00-05:00` |
| M7, Mon 15 Feb | `M7 --segment "Players: group 1" ...`, then `"Players: group 2"` |

M3's `<minutes>` is the pilot's median game length, rounded to five minutes: "M3's {N}" in
the pilot report ([pilot.md](pilot.md) §4). Before each M4, copy
the players into their segments (§4) and check the week's pace with `python -m
fish_server.stats` ([recruitment.md](../recruitment.md) §3).

The script takes the words from `docs/recruitment.md` and nowhere else, and refuses a
message for a list its heading does not name, a placeholder left unfilled, a `--week` that is
not a Monday, or a time already past. To change a message, change the page (a pull request,
as for any change), then send.

## 4. Before each Monday's M4: copying the players

The two Players segments hold everyone who has accepted the study information and not
withdrawn, by group. Only the study database knows who that is, and it is reachable only
inside Render, so the copy runs in the production service's **Shell** (from 14 December; the
pilot site refuses, since pilot players get no game-night emails):

```bash
python -m fish_server.audience --dry-run     # what would change
python -m fish_server.audience
```

It asks for the full-access key (paste it from your keychain; it is not shown and not
stored) and prints counts only, for example:

```
Players: group 1: added 41, removed 0, kept 212, 3 unsubscribed
Players: group 2: added 6, removed 0, kept 37
Invited: added 0, removed 1, kept 4928
(97 calls to Resend)
```

Each player goes into their own group's segment and is taken out of the other; anyone who
has withdrawn is taken out of every segment above, so no invitation reaches someone who can
no longer play. Nobody's subscription is changed: someone who unsubscribed stays unsubscribed,
and Resend skips them. Running it twice changes nothing the second time, so after an error,
run it again.

## 5. After 31 March 2027

The email list is deleted that day (Research Plan §6): in the database with
`python -m fish_server.contacts forget-everyone --yes` ([requests.md](requests.md) §6), and
Resend's copy with it: in Resend,
delete every contact and segment, then revoke the `broadcasts (laptop)` key and remove it from
your keychain (`security delete-generic-password -s fish-resend-broadcast`). Move both plans
back to free.
