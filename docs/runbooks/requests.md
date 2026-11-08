# Runbook: requests about personal data, and 31 March

T3.8. The privacy policy (Terms and Privacy §2, "What you can do") lets a person ask what we
hold about them, have their email address corrected, or have it deleted before 31 March 2027,
and it promises an answer **within 30 days**. It also promises that every address is deleted
on 31 March 2027. This runbook is how each one is done. Withdrawals by email have their own
command (`python -m fish_server.withdraw`, [server.md](../server.md) §2).

Every command here is `python -m fish_server.contacts …`, run from the service's **Shell** in
Render: `fish-production` for study players, `fish-staging` for pilot players. If you can't
tell which, run `show` on both. The commands connect as the database's owner, because the
server's own login can't change these tables, and they never touch games or acceptances.

## 1. Before answering any request

- **It must come from the address it is about.** Act on a request only when it was sent from
  that address, or when the address has confirmed it by replying to you. Anyone can type
  someone else's address into an email.
- **Reply to that address**, never to another one the message asks you to use.
- Note the date it arrived. The 30 days start then.

## 2. "What do you hold about me?"

```bash
python -m fish_server.contacts show someone@example.org
```

It prints their address, random player ID, when they signed up and into which group, each
acceptance (text and terms versions, and the date), any withdrawal, how many games they
played and when, their note-taking answers and their sign-ins. Paste it into your reply, under
a line saying it is everything the study database holds about them. Then record it in §7.

## 3. "Please change my address"

Ask the new address to confirm too: reply to it and wait for its answer. Then:

```bash
python -m fish_server.contacts correct old@example.org new@example.org
```

It refuses if the new address belongs to another player. Sign-in links to the old address are
deleted. In Resend, open **Audience**, find the old address, and change it to the new one, so
the weekly copy of the lists (email.md §4) doesn't keep the old one. Record it in §7.

## 4. "Please delete my address"

First tell them what it means, as the policy does: they can no longer sign in or hear from the
study, and a withdrawal can no longer be linked to their games. So if they also want to
withdraw, that comes first. Then:

```bash
python -m fish_server.withdraw someone@example.org          # only if they want to withdraw
python -m fish_server.contacts forget someone@example.org
```

`forget` deletes the address and every sign-in link to it, and signs them out everywhere.
Their games and acceptances stay, unlinked to any address from then on. In Resend, open
**Audience**, find the address and **Delete contact**. Reply to say it's done, and record it
in §7.

## 5. A player found to be under age

The policy says their games are removed as if they had withdrawn, and their address is
deleted. On the site they played on:

```bash
python -m fish_server.withdraw someone@example.org
python -m fish_server.contacts forget someone@example.org
```

Then delete their Resend contact as in §4, tell Dr. Hany, and record it in §7.

## 6. 31 March 2027: deleting the email list

On 31 March 2027, after any cross-play withdrawals are done:

1. **The study's addresses.** In `fish-production`'s Shell:

   ```bash
   python -m fish_server.contacts forget-everyone --yes
   ```

   It deletes every address and every sign-in record, and prints how many. Nobody can sign in
   after this.
2. **Resend's copy:** [email.md](email.md) §5 (every contact and segment, then the key).
3. **The pilot.** Pilot games and the pilot's email list are both deleted that day (Consent
   Screen §4). Delete the whole pilot database: in Render, `fish-staging-db` → **Settings** →
   **Delete Database**. Then suspend `fish-staging`, which can't run without it.
4. Record it in §7, with the counts `forget-everyone` printed.

The study database itself, with the withdrawn games, is deleted on 30 June 2027 (Research Plan
§6), and so is the laptop copy ([backups.md](backups.md) §4).

## 7. Record

One row per request or deletion. Don't write anyone's address here.

| Arrived | What | Site | Answered | By |
|---|---|---|---|---|
