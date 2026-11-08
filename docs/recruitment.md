# Recruitment

How people are invited to play (T4.1; Research Plan §3): when each message goes out and to
whom, the game nights it announces, and every message word for word. The datasheet (T7.1)
describes recruitment from this page, so a message is never sent without being here first.

## 1. Principles

- **Voluntary.** Every invitation says that taking part is voluntary and unpaid, that it can
  be ignored with no consequence, and who may take part: people who live in the United States
  and are legal adults where they live (18 or older; 19 in Alabama or Nebraska; 21 in
  Mississippi). Nothing is offered for playing.
- **Few messages.** People who have not signed up get at most three emails in all (five for
  the Gov School group, who are also asked to the pilot). Signed-up players get one short
  email a week with their game nights, and a thank-you at the end.
- **Easy to stop.** Every bulk email carries an unsubscribe link, and replies go to the
  researcher. Unsubscribing never affects anyone's games; withdrawing from the study is done
  on the site's account page or by email, as the study information says.
- **Nothing beyond the study information.** The messages describe the study only in words the
  approved consent text already uses (Consent Screen §1, §4), and never tell anyone which
  group they are in (§4 below).

All times are Eastern. 8:00 pm Eastern is 5:00 pm Pacific.

## 2. Timeline

| When | What | To | Site |
|---|---|---|---|
| Mon 16 Nov 2026 | M1: pilot invitation | Invited (the Gov School group only, until 7 Dec) | pilot |
| Mon 30 Nov | M2: pilot reminder | Invited (the Gov School group only) | pilot |
| Tue 1, Thu 3, Sat 5 Dec | Pilot nights (T4.2) | | pilot |
| Mon 7 Dec | The rest of the pool joins Invited | | |
| Tue 8 Dec | M3: launch invitation | Invited | study |
| Sun 13 Dec | Opening night; collection begins | | study |
| Every Monday, 14 Dec – 8 Feb | M4: this week's game nights | Players: group 1, Players: group 2 (each its own dates) | study |
| Tue 12 Jan 2027 | M5: five weeks left | Invited | study |
| Tue 9 Feb | M6: last week | Invited | study |
| Sun 14 Feb | Last game night; collection and website withdrawal close | | study |
| Mon 15 Feb | M7: thank you | Players: group 1, Players: group 2 | study |

The launch invitation goes out after the pilot, once game length is known (M3 says it) and
anything the pilot found is fixed. M5 and M6 go out on Tuesdays so that signed-up players,
who are in the pool too, never get two emails on one day.

**Sites.** The study: https://fish.thedefinitivesanjeevexperience.com. The pilot (staging,
which shows the pilot text): https://fish-pilot.thedefinitivesanjeevexperience.com. Both are
set up in T4.1 subtask 2.

**Sender.** `Sanjeev Kumar (Fish study) <fish@news.thedefinitivesanjeevexperience.com>`, replies
to 821sanjeevkumar@gmail.com. Bulk email goes from its own subdomain so that it never affects
the delivery of sign-in links. Messages are sent with `scripts/broadcast.py`, which takes their
words from this page ([runbooks/email.md](runbooks/email.md)).

## 3. Game nights

Anyone signed up can play at any time; a game night is when enough people are on at once
that a table of six fills within a minute or two. Games are only played on the website.

**Pilot (staging site, Gov School group):**

| Night | Time |
|---|---|
| Tue 1 Dec 2026 | 8:00 – 10:00 pm |
| Thu 3 Dec | 8:00 – 10:00 pm |
| Sat 5 Dec | 3:00 – 5:00 pm |

**Study:**

| Night | Time | For |
|---|---|---|
| Sun 13 Dec 2026 (opening night) | 8:00 – 10:00 pm | everyone |
| Wed 16 Dec | 8:00 – 10:00 pm | group 2 |
| Sun 20 Dec | 8:00 – 10:00 pm | everyone |
| Sun 27 Dec | 8:00 – 10:00 pm | everyone |
| Wed 30 Dec | 8:00 – 10:00 pm | group 1 |
| Sun 3 Jan 2027 | 8:00 – 10:00 pm | everyone |
| Wed 6 Jan | 8:00 – 10:00 pm | group 2 |
| Sun 10 Jan | 8:00 – 10:00 pm | everyone |
| Wed 13 Jan | 8:00 – 10:00 pm | group 1 |
| Sun 17 Jan | 8:00 – 10:00 pm | everyone |
| Wed 20 Jan | 8:00 – 10:00 pm | group 2 |
| Sun 24 Jan | 8:00 – 10:00 pm | everyone |
| Wed 27 Jan | 8:00 – 10:00 pm | group 1 |
| Sun 31 Jan | 8:00 – 10:00 pm | everyone |
| Wed 3 Feb | 8:00 – 10:00 pm | group 2 |
| Sun 7 Feb | 8:00 – 10:00 pm | everyone |
| Wed 10 Feb | 8:00 – 10:00 pm | group 1 |
| Sun 14 Feb (last night) | 8:00 – 10:00 pm | everyone |

Group 2 is the held-out cohort, matched only with each other (Research Plan §3); group 1 is
everyone else. The cohort is about 15% of sign-ups, so its tables fill only if its players
come at the same time: it gets Wednesday nights of its own, and so does group 1, so that
every player is invited to "your group's game nights" and nobody can tell which group is held
out. Every Sunday is for everyone: the two groups play at separate tables on the same night.
There are no nights on 24–25 December or 31 December – 1 January.

**Pace.** At least 1,000 completed games by 14 February is about 110 a week. Every Monday,
before M4 goes out, run `python -m fish_server.stats` in the study service's Shell: it counts
each week's corpus games and says when two full weeks in a row fall short. Then add a Friday
night, 8:00 – 10:00 pm, for everyone, record it in the table above, and include it in that
week's M4.

## 4. Lists

| List (Resend segment) | Who | Where it comes from |
|---|---|---|
| Invited | Until 7 December, the Gov School group (all adults); from then on, also the rest of those invited, chosen from everyone who has said they are willing to play (mainly Lake Braddock alumni): about 950 people in all | The researcher's lists, imported into Resend |
| Players: group 1 | Signed-up players outside the held-out cohort who have not withdrawn | Copied from the study database before each Monday's M4 (`python -m fish_server.audience`, [runbooks/email.md](runbooks/email.md) §4) |
| Players: group 2 | Signed-up players in the held-out cohort who have not withdrawn | The same |

Three lists and at most 1,000 contacts, the most Resend's free marketing plan allows. About
950 are invited, so that players who sign up with an address other than the one invited still
fit when they are copied into their Players list. M1 and M2 go to Invited while it
holds only the Gov School group; the rest of the pool is added on 7 December, before M3. One
list for every invitation also means nobody on both of the researcher's lists is sent the
same message twice. Each message is read first as a test copy sent from its draft (Resend's
"Send test email").

The lists live only in Resend and in the study database's email table; none of them is ever
in this repository. Resend's contacts are deleted on 31 March 2027, with the email table
(Research Plan §6).

## 5. Messages

`[unsubscribe]` stands for the footer every bulk email carries: a link to the privacy policy
of the message's site (§2's Site column: the pilot site's for M1 and M2, the study site's for
the rest; T3.8) and Resend's unsubscribe link. Text in `{braces}` is filled in when the message is sent.

### M1 · Pilot invitation · Mon 16 Nov · Invited

**Subject:** Help me test Fish before it opens: 1, 3 or 5 December

> Hi,
>
> I'm Sanjeev Kumar. For a research project supervised by Dr. Hany Eldeib, I've built a
> website where six people play Fish, the card game, in two teams of three. In December it
> opens as a research study.
>
> Before it opens, I need a few full tables for pilot games, so I can time games and check
> that the site works. Pilot games are never published, and they are deleted on 31 March 2027.
>
> Pilot nights, Eastern time. Come to any of them, for as long as you like:
>
> - Tuesday 1 December, 8:00 – 10:00 pm
> - Thursday 3 December, 8:00 – 10:00 pm
> - Saturday 5 December, 3:00 – 5:00 pm
>
> To take part you need to live in the United States and be a legal adult where you live
> (18 or older; 19 in Alabama or Nebraska; 21 in Mississippi). It's voluntary and unpaid,
> you can stop at any time, even in the middle of a game, and it's completely fine to
> ignore this email.
>
> On the night, open https://fish-pilot.thedefinitivesanjeevexperience.com, read the study
> information, confirm three things, and enter your email for a sign-in link (there's no
> password). During a game, please don't talk to your teammates about it outside the game:
> no texts, calls or voice chat, even if you know each other.
>
> If you think you'll come, a one-word reply ("Tuesday", "Thursday" or "Saturday") tells
> me whether tables will fill. Questions: just reply.
>
> Thanks,
> Sanjeev
>
> [unsubscribe]

### M2 · Pilot reminder · Mon 30 Nov · Invited

**Subject:** Fish pilot: tomorrow at 8 pm, then Thursday and Saturday

> Hi,
>
> A reminder that the Fish pilot starts tomorrow. Eastern time:
>
> - Tuesday 1 December, 8:00 – 10:00 pm
> - Thursday 3 December, 8:00 – 10:00 pm
> - Saturday 5 December, 3:00 – 5:00 pm
>
> Play at https://fish-pilot.thedefinitivesanjeevexperience.com. It's voluntary and unpaid,
> for US residents who are legal adults where they live, and you can stop at any time. No
> need to reply if you can't make it.
>
> Thanks,
> Sanjeev
>
> [unsubscribe]

### M3 · Launch invitation · Tue 8 Dec · Invited

**Subject:** Play Fish for a research study, from Sunday 13 December

> Hi,
>
> I'm Sanjeev Kumar. For a research project supervised by Dr. Hany Eldeib, I've built a
> website where six people play Fish, the card game, in two teams of three. In Fish, every
> signal you send your teammates is also seen by your opponents; this study measures how
> much players' actions reveal about hidden cards, and whether players signal on purpose.
> The games are recorded and, once anonymised, published for anyone to use; they will also be
> used to build and test AI agents that play Fish.
>
> The site opens on Sunday 13 December and stays open until 14 February. A game takes about
> {N} minutes, and you can play as many or as few as you like. You can play at any time, but
> tables fill fastest on game nights, Eastern time:
>
> - Opening night: Sunday 13 December, 8:00 – 10:00 pm
> - Then every Sunday, 8:00 – 10:00 pm, until 14 February
>
> To take part you need to live in the United States and be a legal adult where you live
> (18 or older; 19 in Alabama or Nebraska; 21 in Mississippi). It's voluntary and unpaid,
> you can stop at any time, even in the middle of a game, and you can withdraw until
> 14 February. It's completely fine to ignore this email.
>
> To join, open https://fish.thedefinitivesanjeevexperience.com, read the study information,
> confirm three things, and enter your email for a sign-in link (there's no password). One
> rule: during a game, don't talk to your teammates about it outside the game, even if you
> know each other. Once you've signed up, you'll get a short email each Monday with that
> week's game nights.
>
> If you played in the pilot: the study site is separate, so you'll read and accept the study
> information there too.
>
> Questions: just reply. To raise a concern with someone other than me, you can contact
> Dr. Hany Eldeib at hkeldeib@fcps.edu.
>
> Thanks,
> Sanjeev
>
> [unsubscribe]

`{N}` is the median game length from the pilot (T4.2), rounded to five minutes: the pilot
report's median, from games started on or after 1 December ([runbooks/pilot.md](runbooks/pilot.md) §4).

### M4 · This week's game nights · every Monday, 14 Dec – 8 Feb · each Players segment

Sent separately to each group, with that group's nights for the week (§3).

**Subject:** Fish this week: {days}

> Hi,
>
> Your group's game nights this week, Eastern time:
>
> - {Wednesday 16 December, 8:00 – 10:00 pm}
> - {Sunday 20 December, 8:00 – 10:00 pm}
>
> Play at https://fish.thedefinitivesanjeevexperience.com. You can play at any time; on game
> nights, tables fill fastest.
>
> You're getting this because you signed up for the Fish study. Unsubscribing stops these
> emails and doesn't affect your games. To withdraw from the study (until 14 February), use
> "Your account" on the site, or reply to this email.
>
> Thanks,
> Sanjeev
>
> [unsubscribe]

For the week of 8 February, the first line reads: "This is the study's last week. Your
group's game nights, Eastern time:" and the list ends with "Sunday 14 February, 8:00 –
10:00 pm (the last night)".

### M5 · Five weeks left · Tue 12 Jan · Invited

**Subject:** Fish study: five weeks left to play

> Hi,
>
> The Fish research study is open until Sunday 14 February. If you've been meaning to try
> it, game nights are every Sunday, 8:00 – 10:00 pm Eastern, at
> https://fish.thedefinitivesanjeevexperience.com. If you've already played: thank you, and
> you'll keep getting your weekly game nights.
>
> It's for US residents who are legal adults where they live, voluntary and unpaid, and
> fine to ignore.
>
> Thanks,
> Sanjeev
>
> [unsubscribe]

### M6 · Last week · Tue 9 Feb · Invited

**Subject:** Fish study: last week to play

> Hi,
>
> The Fish research study closes on Sunday 14 February; the last game night is that
> evening, 8:00 – 10:00 pm Eastern, at https://fish.thedefinitivesanjeevexperience.com.
> 14 February is also the last day to withdraw, through the site or by replying to this
> email.
>
> It's for US residents who are legal adults where they live, voluntary and unpaid, and
> fine to ignore. This is the last invitation you'll get from me about it.
>
> Thanks,
> Sanjeev
>
> [unsubscribe]

### M7 · Thank you · Mon 15 Feb · each Players segment

**Subject:** Fish study: thank you

> Hi,
>
> The Fish study closed last night. Thank you for playing.
>
> What happens next, as the study information said: the games are now frozen and
> anonymised, so they can no longer be removed, and in March they're published as a dataset
> under the Creative Commons Attribution 4.0 licence. The email list, including your address, is deleted on
> 31 March 2027.
>
> If one of the study's AI agents passes its test at the end of February, I may invite you
> to play some extra games with it in March. Otherwise, this is the last email you'll get
> from me about Fish.
>
> Thanks again,
> Sanjeev
>
> [unsubscribe]
