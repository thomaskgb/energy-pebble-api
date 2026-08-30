# Energy Pebble, content review

A review of **what the site says**, not how it looks. The design system landed in
`8ed443f` and is treated here as settled. Nothing in this document has been
applied: it is a proposal to argue with before any string moves.

Everything below was checked against `main.py`, `static/i18n-strings.js` and
`tests/test_i18n.py` on branch `thomaskgb/content-review`.

---

## 1. The one-line diagnosis

**The site is written as documentation for an API, and the product it actually
sells is a lamp.**

Every symptom traces back to that. The H1 is `Energy Pebble API`. The most
prominent block below the fold is a list of HTTP endpoints. The one genuinely
sophisticated thing the product does (reshaping the signal around your
contract, your panels and your battery, from a live radiation forecast) is
described nowhere on the public site, while a card on the dashboard promises
that same capability is "Coming Soon". Meanwhile a visitor who wants the device
cannot find out what it costs, how to get one, what they need to run it, or
what happens to their data.

The site knows a great deal about the pebble and almost nothing about the
person holding it.

### The three readers, and how each is served today

| Reader | Wants | Gets today |
| --- | --- | --- |
| **Prospective buyer**, arrives from a link, has never seen the thing | What is it, does it help me, what does it cost, how do I get one | An API reference and a clip-art illustration with English text baked in |
| **New owner**, box in one hand, phone in the other | Plug it in, join Wi‑Fi, link it, understand the lights | `/setup/`, genuinely good, the best page on the site |
| **Existing owner**, wants it tuned to their house | What is my pebble doing and why | A dashboard where half the cards advertise absence, and the real controls hide behind a menu |

The proposal below serves all three, in that order of neglect.

---

## 2. The five leads: confirmed, extended, or challenged

### Lead 1, Solar is shipped, the dashboard says "Coming Soon", **CONFIRMED, and worse than stated**

`main.py` does not merely "have a solar mode". It:

- fetches an hourly shortwave-radiation forecast for Belgium from Open-Meteo
  (`SOLAR_FORECAST_URL`, `get_solar_boost_hours`, `main.py:1364`);
- **commits** each hour's boost decision to `solar_boost.json` the first time it
  sees it, so a shifting forecast can never flip a colour a user has already
  seen: the same discipline as the price commitment;
- falls back to a fixed 10:00–16:00 window when the forecast is unreachable;
- promotes each producing hour one step greener, `R→Y`, `Y→G`
  (`apply_signal_source`, `main.py:1338`);
- and, for solar + battery households, tracks which *days* actually charged
  (`_battery_charged_days`, ≥3 production hours before 17:00) and softens the
  17:00–22:00 evening peak only on those days.

That is a better solar story than most energy apps ship, and it is invisible.
`static/dashboard.html` instead offers a disabled **"Connect Enode"** button
under **"Solar Data Integration, Coming Soon"**.

Beyond undersell, there is a factual problem: the card describes a *different*
feature (reading live production from an inverter via Enode) than the one that
ships (forecast-driven, no hardware integration, no account linking). Removing
the card is not enough: the shipped behaviour has to be described somewhere,
because a user who ticks "Solar panels" in Settings currently gets no
explanation of what changed.

**Recommendation:** delete the card; describe the real mechanism on the home
page and echo it on the dashboard (§4.1, §4.2).

### Lead 2, Half the dashboard is "Coming Soon", **CONFIRMED, and there is a third dead tile**

Two of four feature cards are Coming Soon. There is also a **third** piece of
dead furniture nobody flagged: the **"Unclaimed Devices"** stat tile. It is
hardcoded:

```js
unclaimedElement.textContent = 0; // No unclaimed devices in simplified version
```

It will read `0` forever. Three of the dashboard's seven surfaces are inert.

"Energy Analytics" is a different case from Solar: it genuinely does not exist,
and there is no usage data in the system to build it from: the device sends
requests, not consumption. So it is not just unbuilt, it is not obviously
buildable without new hardware or a meter integration. A card promising it is a
promise the product may never keep.

**Recommendation:** delete both Coming Soon cards and the Unclaimed tile. If
Analytics is a real roadmap commitment, one honest line in a footer ("Usage
insights are on the roadmap") costs nothing and promises nothing.

### Lead 3, Developer framing on a consumer page, **CONFIRMED. Move it to `/developers`, untranslated**

The home page currently spends two of its five sections on `API Endpoints` and
`Technical Details`. The H1 is literally `Energy Pebble API`.

The API is worth keeping public: it is a differentiator, `/docs` already
exists, there is a **Home Assistant integration** in `homeassistant/` that the
website never mentions, and users can mint API tokens in Settings → Account.
But it is a footer link, not a headline.

**Where it should live:** a new `static/developers.html` at `/developers`,
**deliberately untranslated**, exactly like the admin pages. This is not
laziness: it is the same call already made for `/admin/*`, and
`tests/test_i18n.py` supports it directly: `TRANSLATED_FILES` is an explicit
list, so a page not on it is legitimately English-only. Translating HTTP
endpoint descriptions into Dutch and French is pure cost with no reader.

The move also lets us **delete 11 keys × 3 catalogs** (`home.api.*`,
`home.tech.*`): a real reduction in translation surface.

The new page should carry what is currently missing entirely: the Home
Assistant custom component, and the API-token flow.

### Lead 4, Impact Circle reads as a conspiracy reveal, **CONFIRMED, and I want to go further: every factual claim on the page is wrong**

The tone is the smaller problem. The page is inaccurate, and it is inaccurate
in a way that **contradicts the product it is attached to**.

| Claim on the page | Problem |
| --- | --- |
| "Every night between **2 AM and 6 AM** … hidden green hours" | This is the *opposite* of the product's premise. The pebble exists because cheap hours are **not** a fixed window. The site's own simulator, one click away, shows a sunny day going **negative at midday** and a winter day where 2–6 AM is not green at all. We tell people to buy a device that finds the cheap hours, then hand them a fixed answer that makes the device pointless. |
| "solar panels have stored excess energy" | Solar panels do not store energy. And between 2 AM and 6 AM there is no sun anywhere in Belgium, in any season. |
| "**70%** Potential Savings" | No source, and not defensible. On a Belgian bill, network fees, levies and VAT are the majority of what you pay; the commodity component is the only part that moves with the hour. A number that large invites exactly one reaction from a sceptical reader, and it is not trust. |
| "the grid practically **pays you to use electricity**" | True only during negative prices, only on a dynamic contract, and only if the supplier passes them through. Stated unconditionally it is a promise the product cannot keep for the day/night and fixed-tariff users we explicitly support. |
| "crypto miners fire up their operations" | Cited approvingly, as a model to copy, on a product page that elsewhere sells reduced peak-plant emissions. |
| "the secret energy companies don't want you to know" | The register of a sidebar ad. For a product whose entire job is to be *believed about numbers*, this is expensive. |

**What is the page for?** Right now: nothing. It does not sell, does not teach
anything actionable, and does not configure anything. It is a reward for
logging in, and the reward is a paragraph of untruths.

**Recommendation, keep the URL, replace the content and drop the name.** A new
owner in week one has a real, unanswered question: *what do I actually do
differently now?* That is a page worth writing, and it is the honest version of
what this page was reaching for. Concrete copy in §4.3.

Dropping the name matters too. "Impact Circle" is currently the framing for the
**entire product**: it is the login page's subtitle *and* its submit button
("Enter Impact Circle"), and the home page's closing CTA. A members' club is
the wrong promise for a device you have already bought and plugged in.

### Lead 5, English text baked into the product image, **CONFIRMED, plus three problems the lead did not mention**

`static/energy-pebble-device.jpg`:

1. **It is untranslatable.** "See the power / Change the habit" is baked into
   pixels. Dutch and French visitors get English.
2. **It is invisible to assistive tech and to search.** `alt="Energy Pebble"`.
   The tagline: the only piece of positioning copy on the page, is not text.
3. **It is not a photo.** It is clip-art. A prospective buyer cannot tell what
   they would actually receive, which is the single most important job of the
   image on a hardware landing page.
4. **It contradicts the product.** The illustration shows roughly 16 ring
   segments. The real pebble shows **8 ring segments plus a centre dot**, the
   API returns exactly 9 hours (`display_colors = color_codes[:9]`,
   `main.py:1949`) and `pebble-sim.js` draws 8 (`for (let i = 0; i < 8; i++)`).
   The picture teaches the wrong mental model before the copy gets a chance.
5. **Its sky-blue background is outside the design system** and does not adapt
   to the dark theme.

**Recommendation:** replace with a plain photograph of the real device on a
neutral surface, no text, transparent or off-white background so it sits in
both themes. Move the tagline into an actual translated string next to it. If a
photo is not available yet, the second-best option is to crop the current
illustration to the device only, discarding the text and the blue field, that
is a one-command fix and removes four of the five problems today.

---

## 3. Defects found beyond the five leads

These are small, cheap, and two of them are live bugs the redesign left behind.

### 3.1 The home page's "How It Works" is an empty section, **live bug**

`static/index.html` renders a paragraph that ends in a colon, promising a list,
followed by nothing:

> "…and their pebble follows automatically**:**"

`git show dd534a6:static/index.html` shows why: the colour legend and the
green/yellow/red list used to sit right there and were moved into the hero
during the redesign. The trailing colon went with the paragraph and the list did
not. The section is now a dangling sentence next to a picture.

### 3.2 `setup.intro` styles the word "blue" with a token that does not exist, **live bug, all three languages**

```js
'setup.intro': '… slowly pulses <strong style="color:var(--blue)">blue</strong> …'
```

`--blue` is not defined in `base.css`; the token is `--info-500`. The markup in
`static/setup/index.html` was updated to `var(--info-500)` in the redesign, but
the catalog string, which is what `data-i18n-html` actually renders, was not.
An undefined custom property makes the declaration invalid at computed-value
time, so the word renders in ordinary body colour.

This is the **single most important instruction on the first-run page**: "wait
until it pulses blue". Present in `en`, `nl` and `fr`
(`i18n-strings.js:257`, `:538`, `:819`).

### 3.3 `simulator.legend` hard-codes a hex, in all three catalogs

```js
'… dashed <span style="color:#2980b9">blue outline</span> …'
```

`#2980b9` is a fixed mid-blue that ignores the dark theme and violates the
"never hard-code a hex" rule in CLAUDE.md. Should be `var(--info-500)`.
(`i18n-strings.js:240`, `:521`, `:802`.)

### 3.4 The product has three names

| Name | Where |
| --- | --- |
| **Energy Pebble** | brand, home page, setup page, `firmware/energy_pebble_v1.1.0.bin` |
| **Pebble** | setup page body, settings modal, simulator |
| **Energy Dot** | dashboard, 6 strings, and `device.defaultName`; `firmware/energy_dot_v1.0.0.bin` |

The firmware filenames date the rename: `energy_dot` is v1.0.0, `energy_pebble`
is v1.1.0. The dashboard was never brought along. A user who buys an "Energy
Pebble", sets up a "Pebble", and then logs in to manage their "Energy Dots" has
to work out on their own that these are the same object.

**Recommendation:** *Energy Pebble* on first mention, *pebble* thereafter.
Retire *Energy Dot* from all user-facing copy.

### 3.5 "Contact your administrator" is enterprise-IT language, and it is wrong

```js
'dashboard.devices.emptyList': 'No devices assigned to your account yet.
  Contact your administrator to have devices assigned to you.'
```

There is no administrator in a consumer's life, and it is not how claiming
works: users self-claim by scanning the sticker at `/setup/`
(`POST /api/user/devices/claim`). The string sends a stuck user to a person who
does not exist instead of to the page that solves it.

### 3.6 `/login` appears to be an orphan page

Nothing in `static/` links to `/login`. Every sign-in path in the codebase
redirects to Authelia at `auth.tdlx.nl`. The page is routed in the `Caddyfile`,
carries 11 translated keys × 3 catalogs, posts credentials cross-origin to
Authelia's `firstfactor` API, and frames the whole product as "Impact Circle".

I could not fully confirm it is dead, `authelia/` is not present in this
worktree, so an Authelia redirect to `/login` cannot be ruled out.
**Owner decision needed** (§7).

### 3.7 The language switcher exists on exactly one page

| Page | Switcher |
| --- | --- |
| `index.html` | yes |
| `dashboard.html` | no, account setting instead, which is correct |
| `setup/index.html` | **no** |
| `impact-circle.html` | no |
| `simulator.html` | no |
| `login.html` | no |

The dashboard is fine: signed-in users set language in Settings → Account. The
others are not, and **`/setup/` is the serious one**. It is the first thing a
brand-new buyer opens, often before they have an account, and language falls
back to the browser's. A French-speaking Belgian with an English-configured
phone gets English setup instructions for a physical device, with no way to
change them. That is the highest-stakes page on the site to get wrong.

### 3.8 The "Stable Color Promise" is worded as a stronger promise than it is

> "Once you see a color, **it won't change** for the next 8 hours."

Read literally that says one colour persists for eight hours. What the code
does is lock **each of the next 8 hours** to the colour first committed for it
(`commit_colors_for_window(... commitment_hours=8)`). Also unstated: changing
your household profile *does* recolour the display immediately, because
`apply_signal_source` runs after commitment. Worth rewording: the real promise
is good and clearly explainable.

### 3.9 `README.md` is stale (developer-facing, low priority)

Says the API analyses "the current hour and the next 11 hours": it is 9 hours
displayed, 8 committed, 48-hour reference window. No mention of
personalisation, homes, API tokens, or the Home Assistant component. Worth a
pass when `/developers` is written, since they should agree.

---

## 4. Page-by-page proposal

Suggested copy is English; §5 lists the exact catalog impact. Where tone
carries the brand, Dutch and French are given too.

### 4.1 Home page `/`

**Job:** convince a Belgian household this object is worth having, and tell them
how to get one. Nothing else.

**Structure, current vs proposed:**

| Now | Proposed |
| --- | --- |
| Hero: "Energy Pebble API" + colour legend + stability note + live pebble | Hero: consumer headline + colour legend + live pebble |
| How It Works (empty) + illustration | How it works, three real steps |
|, | **Tuned to your home** (the shipped personalisation, currently undocumented) |
|, | **What you need** |
| API Endpoints + Technical Details | *moved to `/developers`* |
| CTA: "Access Impact Circle" | **CTA: get a pebble** |
|, | Footer: privacy · contact · developers · Home Assistant |

**Hero.**

`home.title`, replace `Energy Pebble API`:

> **A light on your desk that knows when power is cheap**

- nl: *Een lampje op je bureau dat weet wanneer stroom goedkoop is*
- fr: *Une lampe sur votre bureau qui sait quand l'électricité est bon marché*

`home.subtitle`:

> Belgian electricity prices change every hour. Energy Pebble glows green when
> it is the cheapest time to run the washing machine, charge the car or heat the
> water: no app to open, no prices to read.

- nl: *Belgische stroomprijzen veranderen elk uur. Energy Pebble licht groen op
  wanneer het het goedkoopste moment is om de wasmachine te laten draaien, de
  auto te laden of water op te warmen, geen app, geen prijzen om te lezen.*
- fr: *Les prix belges de l'électricité changent chaque heure. Energy Pebble
  s'allume en vert au moment le moins cher pour lancer la machine à laver,
  charger la voiture ou chauffer l'eau, sans application, sans consulter les
  prix.*

**Colour legend**: the hints currently advise a posture; they should name an
action. `home.how.green` / `.yellow` / `.red`:

> **GREEN**, Cheapest hours today. Run what you can.
> **YELLOW**, Middle of the range. Fine, but green is better.
> **RED**, Peak prices. Postpone what can wait.

**Stability note** (§3.8). `home.stable.title` / `.body`:

> **The next 8 hours are locked in**
> Once your pebble shows a colour for an hour, that colour stays. You can plan
> tonight's laundry at breakfast and it will still be right.

`home.stable.scheduling` stands as written, dishwashers, washing machines and
EV charging are exactly the shiftable loads. Keep.

**How it works**, replaces the empty section (§3.1). Three steps, one new key
each:

> **1. We read the Belgian day-ahead market.** Elia publishes a price for every
> hour, a day ahead. Prices swing from negative on a sunny, windy afternoon to
> five times the average on a cold, still evening.
>
> **2. We split the range in three.** The cheapest third of the hours ahead is
> green, the middle yellow, the priciest red, then each hour is locked so it
> stops moving under you.
>
> **3. We fit it to your home.** Tell us your contract, and whether you have
> solar panels or a battery. Your pebble adjusts on its own.

**Tuned to your home**, new section. This is the shipped feature the site has
never described, and every line below is what `apply_signal_source` actually
does:

> **Your contract decides what the colours mean**
>
> **Dynamic prices**, you pay the hourly market rate, so your pebble shows the
> market. Green is genuinely the cheapest hour of your day.
>
> **Day & night tariff**, your cheap hours are fixed, not market-driven. Your
> pebble shows nights and weekends green and daytime yellow. It never shows
> red, because for you no hour is a peak.
>
> **Fixed price**, your rate does not move, so the market is not your signal.
> Your pebble goes green while your own panels are producing: self-consumption
> is the one lever a fixed contract leaves you.
>
> **Solar panels**, we read an hourly sunshine forecast for Belgium. During
> the hours your panels are actually producing, your pebble shifts one step
> greener than price alone would say. The forecast is locked in per hour, so a
> changing forecast never flips a colour you have already seen.
>
> **Home battery**, on days your battery filled up, your pebble softens the
> evening peak between 17:00 and 22:00. You are running on stored sunshine, not
> on the grid.

**What you need**, new section; today a buyer cannot find this anywhere:

> - An Energy Pebble and a free USB power socket
> - Home Wi‑Fi *(2.4 GHz, confirm against the firmware before publishing)*
> - Five minutes: plug it in, scan the sticker on the base, pick your network
> - A Belgian electricity connection, prices come from the Belgian day-ahead
>   market
>
> A dynamic contract gets the most out of it, but it works on a day/night or
> fixed tariff too, see above.

**Closing CTA**, currently "Ready for More? / Access Impact Circle". Replace
with the commercial ask. Copy depends on an owner decision (§7); assuming
direct sale:

> **Get an Energy Pebble**, €NN, delivered in Belgium. One pebble per home;
> add more later from your account.

If there is no sales channel yet, the honest interim is a waiting list, still
far better than pointing a prospective buyer at a members' page:

> **Not on sale yet.** Leave your e-mail and we will tell you when pebbles ship.

**Footer**, new, and the home for four things a first-time visitor currently
cannot find: **Privacy**, **Contact**, **For developers**, **Home Assistant**.

**Also on this page:** replace the image per §5 of Lead 5, and give it real alt
text, `alt` should describe the object ("An Energy Pebble showing a green
ring"), with the tagline as an adjacent translated string, not baked pixels.

---

### 4.2 Dashboard `/dashboard`

**Job:** show what my pebble is doing and let me change it. It is a control
panel for an owner, not a feature brochure.

**Remove:**
- **Solar Data Integration, Coming Soon** card (Lead 1). The feature ships; the
  card describes a different, unbuilt one.
- **Energy Analytics, Coming Soon** card (Lead 2).
- **Unclaimed Devices** stat tile (§3.2), permanently `0`.
- All six **"Energy Dot"** strings (§3.4).

**Add, "Your signal right now".** With the Coming Soon cards gone, the
dashboard should answer the question an owner actually has: *why is my pebble
that colour?* The data already exists, `GET /api/user/settings` returns
`derived_signal`, and `/api/color-code` returns `meta.signal_source`. No backend
work; the panel just says in words what the profile resolves to:

> **Dynamic contract, solar panels**, your pebble follows the market, and goes
> a step greener while your panels are producing. Change this in **Settings →
> Pebble**.

One line per `derived_signal` value (`price`, `day_night`, `fixed`, `solar`),
plus a battery clause. Four new keys, and it turns the dashboard's most inert
region into its most useful one.

**Rewrite:**

`dashboard.greetingSub`, "Ready to optimize your energy usage and manage your
connected devices?" is a rhetorical question with no answer. Replace:

> Your pebble, your homes and your settings.

`dashboard.stat.connected`, "Connected Energy Dots" → **"Pebbles"**.

`dashboard.devices.emptyList` (§3.5):

> No pebble linked yet. Plug one in and scan the sticker on its base to add it.

…with the existing **Add a Device** button beside it, relabelled **Add a
pebble**.

**Keep:** the "My Pebble" live-preview card (the best thing on this page), the
device list, and the Impact Circle card, relabelled to match §4.3.

---

### 4.3 `/impact-circle`, replace the content, keep the URL

**Proposed name:** **"Making the most of it"** (nl: *Haal er meer uit*, fr:
*En tirer le maximum*).

**Job:** the honest version of what this page was reaching for. A new owner's
real question is not "what is the secret", it is "what do I actually do
differently now?" Answer that, accurately, in about 300 words.

**Suggested copy:**

> ### Making the most of it
>
> Your pebble tells you *when*. This is the *what*.
>
> **Move the big things, ignore the small ones.**
> Fridges, lights, routers and the TV run all day and barely register. What is
> worth moving is what is both large and patient: charging an electric car,
> heating water, running a heat pump harder, the dishwasher, the washing
> machine, the tumble dryer. Shift those into green hours and you have captured
> nearly all of what there is to capture. Shifting anything else is effort for
> a rounding error.
>
> **The cheap hours are not where people expect.**
> The old advice, "run things at night", comes from a grid that no longer
> exists. On a sunny day, Belgian prices bottom out around midday and can go
> negative: so much solar is on the grid that consuming is worth money. On a
> still winter evening, prices can be five times the daily average at 19:00.
> Some days have no cheap hours at all. This is exactly why the pebble is an
> object on your desk and not a rule you memorise.
>
> **What you save depends on your contract.**
> On a dynamic contract you pay the hourly price, so moving a load from a red
> hour to a green one shows up directly on your bill. On a day/night tariff
> your cheap hours are fixed and the pebble shows those instead. On a fixed
> price the hourly market costs you nothing either way, but if you have solar
> panels, using your own production instead of exporting it is still real
> money, and that is what your pebble shows.
>
> Be realistic about the size of it: the energy itself is only part of a
> Belgian bill. Network fees, levies and VAT do not move with the hour. Shifting
> your flexible loads is worth doing, and it is not worth exaggerating.
>
> **It is not only about money.**
> The hours that are expensive are the hours the grid is leaning hardest on its
> dirtiest, most expensive plants. Every load you move out of a red hour is one
> the grid does not have to cover that way.

**On the three stat tiles** ("70% Potential Savings", "2-6AM Sweet Spot",
"Planet Helper"): all three should go. Two are false and the third is not a
statistic. If a three-tile strip is wanted for rhythm, replace the fake numbers
with the three loads actually worth moving, **EV charging · Hot water & heat
pump · Washing & drying**, which is information rather than decoration.

**Also:** the page currently has no way back except Dashboard, and a bare
`auth.tdlx.nl/logout` with no `rd=` parameter (the home page passes one). Worth
matching.

---

### 4.4 Simulator `/simulator.html`, keep, and promote it

This is the most honest and most persuasive thing on the site. It shows a sunny
day going negative at midday, a winter day with brutal evening peaks, and a
live view of today. It quietly proves the claim the rest of the site only
asserts. It also directly refutes the Impact Circle page, which is its own
argument for §4.3.

**Changes, all small:**
- **Link it from the header nav**, not only from one line mid-home-page. It is
  the best sales asset here.
- Fix the hard-coded `#2980b9` in `simulator.legend` → `var(--info-500)` (§3.3).
- Add the language switcher (§3.7).
- Add a way back to the home page beyond the brand mark, and a closing line
  pointing at the CTA: a visitor who has just watched a day go negative is the
  most persuaded they will ever be.

No copy changes otherwise. The scenario notes are well written and accurate.

---

### 4.5 Setup `/setup/`, nearly right, three fixes

This page understands its reader: short sentences, one instruction at a time, a
Bluetooth path and a captive-portal path, and an LED table that answers "why is
it red" before the user has to search. Leave the structure alone.

1. **Fix `setup.intro`'s `var(--blue)`** (§3.2), all three catalogs. The word
   "blue" is currently not blue, on the one instruction that matters most.
2. **Add the language switcher** (§3.7). Highest-stakes missing switcher on the
   site.
3. **Add one line about what happens next**, after the success banner. The
   footer currently says only "Once connected, prices update automatically."
   A first-time owner does not know how long "shortly" is, or that the pebble
   is dumb by design:

   > Your pebble now shows the current hour in the middle and the next 8 hours
   > around the ring. It has no buttons and needs no app, everything is set
   > from your account.

---

### 4.6 `/login`, decide, then delete or fix

If it is unreachable (§3.6), delete the page, the `Caddyfile` route and its 11
keys × 3 catalogs. If Authelia does route to it, it needs the "Impact Circle"
framing removed (`login.subtitle`, `login.submit`) and a language switcher.
Either way "Enter Impact Circle" should not be the button that signs a customer
into the product they bought.

---

### 4.7 New page: `/developers` (untranslated)

Holds what moves off the home page, plus what has never been documented:

- The four public endpoints and a link to `/docs`
- `X-Device-ID` personalisation and the `display` block
- **The Home Assistant custom component** in `homeassistant/`, currently
  invisible to every user
- **API tokens** (Settings → Account) and how to use them
- The colour algorithm, honestly: 48-hour reference window, thirds, 8-hour
  commitment, 9 hours returned
- Attribution: Elia day-ahead prices, Open-Meteo radiation forecast

Untranslated by design, like `/admin/*`. Not added to `TRANSLATED_FILES`.

### 4.8 New page: `/privacy`

Currently absent, and this is a networked device in someone's home that a
Belgian consumer is being asked to buy. `main.py` stores device IDs, client IP
addresses, user agents, request counts and fingerprints
(`log_device_request`). A one-page plain-language note on what is collected,
why, how long it is kept and how to delete an account is both the right thing
and, under GDPR, not optional for a consumer product sold in Belgium.

I have not drafted this copy: it should reflect actual retention and deletion
behaviour, which is an owner decision, not a writing one.

---

## 5. i18n impact

Constraints observed: every key must exist in `en`, `nl` and `fr`
(`test_translations_cover_every_english_key`); an unreferenced key fails
`test_catalog_has_no_unused_keys`, so **removing copy means removing its keys
from all three catalogs**; `{placeholders}` must match across languages; admin
pages are out of scope.

### Keys to delete (removal is mandatory, not optional)

| Keys | Why | × 3 catalogs |
| --- | --- | --- |
| `home.api.*` (6) | moves to untranslated `/developers` | 18 |
| `home.tech.*` (5) | same | 15 |
| `dashboard.solar.*` (3) | card deleted | 9 |
| `dashboard.analytics.*` (3) | card deleted | 9 |
| `dashboard.status.comingSoon` | no Coming Soon cards remain | 3 |
| `dashboard.stat.unclaimed` | dead tile | 3 |
| `impact.nightHours`, `impact.smartMoney`, `impact.bestPart`, `impact.stat.*` (3) | false claims | 18 |
| `login.*` (11) | **only if** `/login` is deleted (§3.6) | 33 |

Roughly **75 catalog entries removed**, or 108 if `/login` goes.

### Keys to add

| Keys | For |
| --- | --- |
| `home.how.step1` / `.step2` / `.step3` (+ 3 titles) | fixes the empty section (§3.1) |
| `home.tuned.title` + 5 bodies (`dynamic`, `dayNight`, `fixed`, `solar`, `battery`) | documents the shipped personalisation |
| `home.need.*` (~5) | "What you need" |
| `home.cta.*` (rewrite in place) | commercial CTA |
| `home.footer.*` (~4) | privacy · contact · developers · Home Assistant |
| `dashboard.signal.*` (4–5) | "Your signal right now" |
| `impact.*` (~8, replacing 6 deleted) | rewritten page |
| `setup.next` | what happens after setup |
| `nav.simulator` | simulator in the header |

Net movement is roughly flat, around 40 added against 75 removed, so this is
a **net reduction** in translation surface despite adding two sections and a
page. That is worth saying out loud: the site currently spends a lot of
translation budget on absent features and false claims.

### Keys to fix in place (no key changes, values only)

| Key | Fix |
| --- | --- |
| `setup.intro` (en/nl/fr) | `var(--blue)` → `var(--info-500)`, **live bug**, §3.2 |
| `simulator.legend` (en/nl/fr) | `#2980b9` → `var(--info-500)`, §3.3 |
| `home.how.intro` | drop the dangling colon, §3.1 |
| `home.stable.body` | reword the promise accurately, §3.8 |
| `dashboard.devices.emptyList` | remove "contact your administrator", §3.5 |
| `dashboard.stat.connected`, `dashboard.dots.*`, `dashboard.devices.summary.*`, `device.defaultName` | "Energy Dot" → "pebble", §3.4 |

### Sequencing

The two hard-coded-colour fixes (§3.2, §3.3) are value-only edits in existing
keys: no markup, no test movement. They are worth landing on their own,
immediately, ahead of any of this.

---

## 6. Claims audit, quick reference

| Claim | Where | Verdict |
| --- | --- | --- |
| "Solar Data Integration, Coming Soon", "Connect Enode" | dashboard | **False.** Solar ships, forecast-driven; Enode is not the mechanism |
| "Energy Analytics, Coming Soon" | dashboard | Not built, and no usage data exists to build it from |
| "Unclaimed Devices" | dashboard | Hardcoded `0` |
| "Contact your administrator" | dashboard | Wrong flow, users self-claim at `/setup/` |
| "Every night between 2 AM and 6 AM… green hours" | impact | **False**, and contradicts the product and the site's own simulator |
| "solar panels have stored excess energy" (at 2–6 AM) | impact | **False** twice over |
| "70% Potential Savings" | impact | Unsourced, not defensible on a Belgian bill |
| "the grid pays you to use electricity" | impact | Only on dynamic contracts, only at negative prices |
| "Once you see a color, it won't change for the next 8 hours" | home | Roughly right, worded stronger than the code, §3.8 |
| "devices pick up changes within 15 minutes" | dashboard, settings | **Unverifiable from this repo**: the poll interval lives in the esphome firmware. Confirm before keeping |
| "Elia Grid International (Belgian TSO)" | home | Correct, but Open-Meteo now also feeds the signal and is credited nowhere |
| "the 9 hours on the pebble" | simulator | Correct, matches `main.py` and `pebble-sim.js`; the *illustration* does not |
| "next 11 hours" | `README.md` | Stale, §3.9 |

---

## 7. Decisions I need from the owner

These change the copy materially and I did not want to guess.

1. **How does someone buy one, and for how much?** This is the single largest
   gap on the site. Direct sale, waiting list, or "not for sale yet"? The home
   page CTA cannot be written without it.
2. **Is `/login` reachable?** (§3.6) `authelia/` is not in this worktree.
   Delete, or fix and keep?
3. **Is "Energy Analytics" a real roadmap item?** If yes it gets one honest
   footer line; if no it disappears entirely.
4. **Retire "Impact Circle" as a name?** I recommend yes: it currently frames
   the login page and the home page CTA, which is the wrong promise for a
   device someone already owns.
5. **Is a real product photo available?** If not, cropping the current
   illustration to the device is a good same-day fallback.
6. **Confirm the two hardware facts** before they go on the page: 2.4 GHz Wi‑Fi
   only, and the firmware's settings-poll interval (the "15 minutes" claim).
7. **Privacy page content**, retention period and account-deletion behaviour
   are yours to state, not mine to invent.

---

## 8. Suggested order of work

1. **Today, standalone:** the two colour-token bugs (§3.2, §3.3) and the
   dangling colon (§3.1). Value-only edits, no structural risk.
2. **Truthfulness:** delete the Solar and Analytics cards, the Unclaimed tile
   and the false Impact Circle claims. This removes wrong information, which is
   worth more than adding right information.
3. **The home page rewrite:** H1, how-it-works, "Tuned to your home", "What you
   need", CTA, footer; move the API material to `/developers`.
4. **Naming:** Energy Dot → pebble, everywhere.
5. **The rest:** rewritten Impact Circle, dashboard signal panel, setup and
   simulator switchers, privacy page.

Run `python3 -m pytest tests/test_i18n.py` after each step: it catches a
half-finished catalog immediately, and steps 2 and 3 both delete keys, which is
where that test earns its keep.

---

# Appendix A, Decisions taken (owner review, session 2)

## A.1 The Impact Circle page becomes an insights page

Owner's framing: *"the device simplifies when to consume; people sometimes want
insight into what actually happened."* The page is the looking-back layer.

### What is and is not measurable

**Not measurable: "how your behaviour changed your bill."** The pebble reports
requests, not kWh. Nothing in the system knows whether anyone actually ran the
dishwasher at 13:00. Any "you saved €X" figure would be fabricated, which on a
page whose only job is to be believed is the one thing we cannot do. *(The path
that would unlock it is real meter data, Fluvius P1 port, or an inverter API.
Roadmap decision, not a content one.)*

**Measurable, and better: what the choice was worth.** The euro difference
between the cheapest and priciest hour, priced on a load people recognise.

Why the difference in euros rather than a ratio or an absolute cost:

- **An absolute cost needs their tariff.** We do not know it.
- **A ratio misleads, and sometimes explodes.** On 29 Aug the priciest hour was
  *890×* the cheapest, because the cheapest was €0.2/MWh. A ratio on the
  commodity alone also overstates what a bill does, since network fees and
  levies do not move.
- **The difference is exact and tariff-independent.** The fixed part of the
  bill is identical either way, so it cancels. "Running it at 13:00 instead of
  19:00 was worth 21 cents" is true for every household, with no assumptions.

### Decisions

| # | Decision | Choice |
| --- | --- | --- |
| 1 | Headline metric | **What the choice was worth**, euro difference on a recognisable load |
| 2 | Timeframe | **Last 7 days, per household.** Not annualised: one August week has unusually wide solar spreads, and a yearly figure needs a rolling 12-month calculation before it is defensible |
| 3 | Audience | **Public, deeper when signed in.** Market half needs no account; the personalised half appears underneath when it can. Visitors get the "get a pebble" CTA |
| 4 | Appliances | **Toggles on the page, not saved.** Tick what you have, the number updates. No account, no schema change, works logged-out, same pattern the simulator already uses |

Consequences: the page moves to **`/insights`** and stops requiring auth;
`impact.*` keys are replaced; the dashboard card and the home CTA are relabelled.

### Verified figures (Elia day-ahead, 23–29 Aug 2026)

Sum of the daily best-vs-worst gap over the 7 days: **€0.895/kWh**.

| Load | kWh per run | Worth over the week |
| --- | --- | --- |
| Dishwasher cycle | 1.2 | €1.07 |
| Washing machine | 0.9 | €0.81 |
| Tumble dryer | 2.5 | €2.24 |
| **Basket total** | **4.6** | **€4.12** |
| EV charge | 11.0 | €9.85 |
| **Basket + EV** | **15.6** | **€13.97** |

Single day, 29 Aug: cheapest hour 10:00 at €0.2/MWh, priciest 19:00 at
€178/MWh. A dishwasher cycle was worth **21 cents**, an EV charge **€1.96**.

These are ceilings, best hour versus worst hour, every day. The copy must say
**"up to"**.

### This also settles Lead 4 on the evidence

On 29 Aug the hourly price was **€101/MWh at 02:00** and **€0.2/MWh at 10:00**.
The current page's headline advice, "every night between 2 AM and 6 AM… hidden
green hours", would have had a reader pay roughly **500× the midday price**.
The page is not merely tacky; following it costs money. Full shape of that day:

```
00:135  01:114  02:101  03:094  04:093  05:097  06:098  07:102
08:061  09:006  10:000  11:000  12:002  13:001  14:000  15:010
16:022  17:097  18:141  19:178  20:176  21:169  22:156  23:144   EUR/MWh
```

Midday was free. The night was not cheap. This is the product's whole argument,
and it is sitting in our own data.

### Implementation note

Historical prices are available from Elia's existing per-date endpoint :
verified back at least a month, quarter-hourly, so a 7-day window needs no new
data source, just seven cached fetches behind a new `GET /api/insights`.

| 5 | Name | **Insights** (`nav.insights`, Inzichten / Aperçus). H1 says the value out loud. **"Impact Circle" retires site-wide**: login subtitle, login submit button, home CTA and dashboard card all change |

## A.2 Draft copy, `/insights`

English is the source. NL/FR given for the lines where tone carries the brand;
the rest follow once this is signed off.

### Header

> # What paying attention was worth
>
> Belgian electricity prices move every hour. Here is what last week's swings
> were actually worth, and when the cheap hours really fell.

- nl: *Wat het juiste moment waard is*, *Belgische stroomprijzen bewegen elk
  uur. Dit is wat de schommelingen van vorige week echt waard waren, en wanneer
  de goedkope uren vielen.*
- fr: *Ce que vaut le bon moment*, *Les prix belges de l'électricité bougent
  chaque heure. Voici ce que valaient réellement les écarts de la semaine
  dernière, et quand les heures creuses sont vraiment tombées.*

### The headline block

> **What have you got?**
> ☑ dishwasher ☑ washing machine ☑ tumble dryer
> ☐ electric car ☐ heat pump ☐ electric hot water
>
> Over the last 7 days, running these at the cheapest hour instead of the
> priciest was worth up to
>
> # €4.12
>
> That is the difference, not your bill. Network fees, levies and VAT are the
> same whichever hour you pick, this is the part that moves.

- nl headline: *was dat tot **€ 4,12** waard*
- fr headline: *cela valait jusqu'à **4,12 €***

### When the cheap hours fell

> [7 days × 24 hours, coloured green / yellow / red]
>
> The cheapest hour of the day fell **at midday on 7 of the last 7 days**.
>
> Cheapest, Sunday 23 August, 13:00, −€4.08/MWh.
> Priciest, Wednesday 26 August, 19:00, €212.28/MWh.
>
> The old advice was to run things overnight. That came from a grid that no
> longer exists: on a sunny day there is so much solar on the network that the
> middle of the day is the cheap part, and the night is not.

That last paragraph does real work. It replaces the deleted claim with the
evidence that refutes it, and it teaches the one thing the product depends on
people understanding.

### Signed in only, what your pebble did differently

> **Your pebble, last week**
>
> Your pebble showed green for **61 hours**. The price alone would have shown
> 41. Your panels turned 20 of those green, and your battery carried 2 evenings
> past the peak.

Degrades to nothing when signed out, and to a single line for a default
(dynamic, no solar) household: *"Your pebble followed the market directly last
week: no solar or battery to shift it."*

### What is worth moving

> Move the big things and ignore the small ones. Fridges, lights and the TV run
> all day and barely register. What is worth moving is what is both large and
> patient: charging a car, heating water, running a heat pump harder, the
> dishwasher, the washing machine, the dryer.
>
> **Be realistic about the size of it.** The energy itself is only part of a
> Belgian bill, and the numbers above are ceilings: they assume you hit the
> best hour every single day. Shifting your flexible loads is worth doing, and
> it is not worth exaggerating.

### Visitors only, closing CTA

> **Get an Energy Pebble.** It does the watching, so you don't have to.

Final wording waits on the sales-channel decision (§7.1).

## A.3 Implementation notes

- **New endpoint** `GET /api/insights`, seven cached Elia fetches, returns the
  daily best/worst hour, the per-kWh weekly spread, and the coloured week grid.
  Public. The signed-in block reads the existing profile and reuses
  `apply_signal_source` to count green hours with and without the profile
  applied: no new colour logic.
- **Number formatting is locale-specific and the site does not do it today.**
  `€4.12` is `€ 4,12` in Dutch and `4,12 €` in French. Use
  `Intl.NumberFormat(lang, {style:'currency', currency:'EUR'})` rather than
  putting formatted numbers in the catalogs; catalogs take a `{amount}`
  placeholder. Same for dates.
- **Route:** `/insights` in the `Caddyfile`, and **remove** `/impact-circle`'s
  auth requirement, or keep the old path as a redirect so existing links live.
- **`TRANSLATED_FILES`** in `tests/test_i18n.py` gains `static/insights.html`
  and loses `static/impact-circle.html`.
- Assumed kWh per run (dishwasher 1.2, washing machine 0.9, dryer 2.5, EV 11,
  hot water 4.0, heat pump TBD) should be stated on the page, not hidden.

## A.4 Built, status

`/insights` ships. What actually landed, against the plan above:

| Piece | Where |
| --- | --- |
| `GET /api/insights` (public; `personal` block when signed in) | `main.py:2092` |
| The page | `static/insights.html` (new) |
| Catalogs | `impact.*` (14 keys) → `insights.*` (41 keys), plus `nav.insights`, ×3 |
| Route + redirect | `Caddyfile`, and the dev mirror in `main.py` |
| Old page | `static/impact-circle.html` deleted |
| Test file list | `tests/test_i18n.py`, `impact-circle.html` → `insights.html` |

### Corrections to the plan, found by building it

- **The week's extremes are not the same as one day's.** The draft copy above
  used 29 Aug's numbers as though they were the week's. Corrected: the cheapest
  hour of the window was **Sunday 23 August 13:00 at −€4.08/MWh**, the priciest
  **Wednesday 26 August 19:00 at €212.28/MWh**.
- **Midday won 7 days out of 7**, not 5. The old page's "2 AM–6 AM" claim was
  wrong on every single day of the window.
- **A fixed-tariff household has no green hours at all** (`apply_signal_source`
  returns `Y` for every non-solar hour). So the personalised block cannot be
  one template with a number in it, each signal source gets its own sentence,
  and the fixed one says plainly that moving a load "costs you nothing and
  saves you nothing". Better to say it than to show them a zero.
- **The headline only holds on a dynamic contract.** Added
  `insights.worth.contract` under the figure to say so, rather than letting a
  day/night or fixed household read €4.12 as theirs.
- **Numbers had to go through `Intl`.** Verified in the browser: Dutch renders
  **€ 4,12** and **−4,08 €/MWh**, English **€4.12** and **-4.08 €/MWh**. Dates
  too, "zondag 23 augustus". Catalog strings carry `{amount}`/`{price}`
  placeholders and never a formatted number.
- **`nav.insights` was written before anything linked to it**, and
  `test_catalog_has_no_unused_keys` caught it. The Insights link now sits in the
  home page header, which the review wanted anyway, outside `#nav-buttons`,
  since `updateNavigation()` replaces that node wholesale.
- **Keys referenced through a JS lookup table are invisible to the test.** The
  loads now use the `labelKey:` convention `simulator.html` already established,
  and the personalised strings are `t('literal')` calls in a branch.

### Still open on this page

- **`insights.cta.*` says "Get an Energy Pebble" but the button reads "See how
  it works" and points at `/`**, there is nowhere to buy one yet (§7.1). The
  home page CTA is likewise pointed at `/insights` for now. Both become a real
  purchase link the moment there is a URL.
- **`heat_pump` is assumed at 6.0 kWh for a shiftable preheating block.** The
  least defensible of the six figures; worth a second opinion.
- The window is 7 days. A rolling 12-month figure would let us state a yearly
  number honestly, which is the more motivating frame (§A.1, decision 2).

---

# Appendix B, The call to action: a waitlist

## B.1 Decisions

The `/insights` CTA had been left pointing at `/`, because there is nowhere to
buy a pebble (§7.1). A waitlist resolves that, and it is the right answer
rather than a stopgap, because **it turns the unanswered pricing question into
the thing that answers it**: you can price the product after seeing how many
people put their hand up.

| # | Decision | Choice |
| --- | --- | --- |
| 1 | Where addresses go | **Stored in the database, read in admin.** Not mailed |
| 2 | Price on the page | **Promise to tell them**, "when the next batch is ready, and what it will cost" |

### Why not email them to energypebble@tdlx.nl

The owner's first instinct was to have the form send the address on by mail.
Three reasons not to, and none of them are about effort:

- **A public endpoint that triggers outbound mail is a spam relay.** Anyone
  could loop it and bury the inbox, and the only way to stop it would be to
  take the form down.
- **Mail fails silently.** A bounce or a greylist is a signup nobody ever knew
  about. A database row cannot go missing.
- **It is new infrastructure**, provider, credentials in compose,
  deliverability, SPF/DKIM, to reproduce what a table already does. There is
  no SMTP anywhere in this repo today.

`energypebble@tdlx.nl` still appears **on the page**, as the contact and
deletion address. Same address, no mail stack.

### On price

€5 is bill of materials, not cost. It excludes assembly, enclosure, USB supply,
packaging, shipping, payment fees and returns, plus the one that is easy to
miss, that **every pebble sold calls this API forever**. Small-batch hardware
commonly lands at 4–6× BOM, which would put it somewhere around €25–35, but
that is a guess and not a costing. The waitlist means it does not have to be
decided yet.

## B.2 Data protection

This is the first personal data the project collects from people who are not
users, so the table is deliberately thin (address, timestamp, reading
language), and the promise is made in plain words on the form itself:

> One message, nothing else. We don't pass your address on, and you can have it
> deleted any time, energypebble@tdlx.nl

The admin page carries the matching note, because a promise of deletion needs
somebody able to perform it:

> The signup form promises these addresses are never passed on and can be
> deleted on request. Deleting a row here is how that promise is kept.

This does not replace the privacy page (§4.8), which is still outstanding.

## B.3 What was built

| Piece | Where |
| --- | --- |
| `waitlist` table | `main.py`, `init_database()` |
| `POST /api/waitlist` | public, validated, rate limited 5/hour/IP |
| `GET /api/admin/waitlist` | list + counts per language, admin only |
| `DELETE /api/admin/waitlist/{id}` | the deletion route the form promises |
| `GET /api/admin/waitlist.csv` | export, admin only |
| Signup form | `static/insights.html`, replaces the placeholder CTA |
| Strings | `insights.cta.*`, 9 keys × 3 catalogs |
| Admin page | `static/admin-waitlist.html` (new, untranslated) |
| Navigation | linked from the dashboard admin menu and all four admin pages |
| Tests | `tests/test_waitlist.py`, 23 tests |

### Design notes

- **Signing up twice returns exactly the same response as signing up once**
  (`ON CONFLICT DO NOTHING`). Otherwise the endpoint is an oracle for whether a
  given address is on the list.
- **Addresses are lower-cased on the way in**, or `Nele@Example.be` and
  `nele@example.be` become two people.
- **The reading language is captured** from the UI, so you know which language
  to write back in. The browser test signed up through the Dutch page and the
  row landed with `language: "nl"`.
- **An unknown language is stored as NULL rather than rejected**: a signup is
  worth more than a tidy column.
- The new admin page is built on **`base.css`**, not the legacy
  `components.css` the other four still use. Its asset paths are absolute
  (`/base.css`), matching the existing admin convention, because Caddy serves
  `static/` at the web root (`docker-compose.yml:93`) while the page lives at
  `/admin/waitlist`. A relative path would resolve to `/admin/base.css`.

### Verified

- 23 unit tests: validation, normalisation, duplicate handling, rate limiting,
  language capture, admin-only access on all three read/delete routes, CSV
  shape, deletion.
- In the browser: an invalid address shows the Dutch error, a valid one hides
  the form and shows the Dutch confirmation, and the row appears in admin with
  `nl` recorded and the timestamp converted from stored UTC to local (19:05 →
  21:05 CEST).
- **Note for local development:** admin pages cannot be previewed properly
  through `uvicorn`, which mounts static at `/static`, so absolute asset paths
  404. This affects all five admin pages equally and is not new. Serving the
  `static/` directory at the web root reproduces Caddy correctly:
  `python3 -m http.server 8779 --directory static`.
