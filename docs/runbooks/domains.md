# Runbook: the site's addresses

Each Render service is reached at one address of our own, never at `*.onrender.com`
(T4.1): invitations link to it, sign-in links point at it, and its session cookie belongs to
it. A second address for the same site would split people's sessions between the two.

| Site | Address | Render service | When |
|---|---|---|---|
| Pilot (staging) | https://fish-pilot.thedefinitivesanjeevexperience.com | `fish-staging` | now |
| Study (production) | https://fish.thedefinitivesanjeevexperience.com | `fish-production` | when production is created (T4.3), by 7 December |

Render's Hobby workspace includes two custom domains, which is exactly these two.

## Adding a site's address

Do the DNS step first, so that Render can verify the address as soon as it learns of it.

1. **Find the service's Render host.** In the Render dashboard, open the service. Its address
   is under its name: something like `fish-staging.onrender.com` (sometimes with a suffix, as
   in `fish-staging-a1b2.onrender.com`). Copy it exactly.
2. **Add the DNS record** wherever `thedefinitivesanjeevexperience.com`'s DNS is managed (the
   same place as the Resend records):

   | Type | Name (host) | Value (target) | TTL |
   |---|---|---|---|
   | `CNAME` | `fish-pilot` (or `fish` for the study) | the Render host from step 1 | automatic, or 300 |

   Some providers want the full name (`fish-pilot.thedefinitivesanjeevexperience.com`) and
   some only the part before the domain; the provider's own examples show which. If DNS is on
   Cloudflare, set the record to **DNS only** (grey cloud). Make sure no `A` or `AAAA` record
   exists for the same name.
3. **Check it has spread** (a few minutes, rarely an hour):

   ```bash
   dig +short CNAME fish-pilot.thedefinitivesanjeevexperience.com
   ```

   It should print the Render host from step 1, with a dot at the end.
4. **Let Render know.** The service's `domains` in `render.yaml` lists the address, and
   `renderSubdomainPolicy: disabled` switches the `onrender.com` address off; `FISH_PUBLIC_URL`
   points sign-in links at the address. Merge the change; when the Blueprint syncs, Render
   adds the address and issues its certificate. If the service's **Settings → Custom
   Domains** shows the address as unverified, press **Verify**.
5. **Check the site** as a player would:

   ```bash
   curl -sI https://fish-pilot.thedefinitivesanjeevexperience.com/health | head -1   # HTTP/2 200
   curl -sI https://fish-staging.onrender.com/health | head -1                        # HTTP/2 404
   ```

   Then open the address in a browser, ask for a sign-in link, and check that the link in the
   email starts with the same address. Finish with `scripts/try_server.py` against it
   ([server.md](../server.md) §7).

## If something goes wrong

| Symptom | Cause and fix |
|---|---|
| The Blueprint sync fails on `renderSubdomainPolicy` | Render will not switch the old address off before the new one exists. Remove that line, merge, wait until the address shows as verified, then put the line back in a second change. |
| Render says the address is not verified | DNS has not spread yet, or the record's name or value has a typo: compare `dig` with step 1, wait a few minutes, press **Verify** again. |
| `502 Bad Gateway` just after verifying | Render is still updating its routing. Wait a few minutes. |
| The site works but sign-in links point elsewhere | `FISH_PUBLIC_URL` in `render.yaml` is missing or different. Correct it and merge; Render restarts the service with the new value. |
| Signed in on one address but not the other | Expected: a session belongs to one address. With the `onrender.com` address switched off there is only one. |
