# PlayMetrics Admin Reference (Region 58)

> Internal admin/registrar knowledge. Not parent-facing. No screenshots may be published publicly.

## Program Context
- Program name: **2026 Fall Core** · Program ID **101848** · League ID (coaching requests) **11427**. [VERIFY]
- 17 packages; no 4U. Region tax ID **95-6205398**. Covers Van Nuys / Sherman Oaks.
- Key roles: Sara Zaldivar = Regional Commissioner; Steve(n) Davis = Registrar/tech lead; Kristen Gillespie = Treasurer/Controller; Jay Spillane = CVPA; Ben Hauser = Game Scheduler; Mike Lauer = Referee Admin.

## Programs, Seasons & Packages
- Hierarchy: **Season → Program → Package**. "Package" = Sports Connect "Division."
- Packages display in **creation order** and **cannot be reordered** — build them in the order parents should see them.
- Programs/seasons can be deleted or archived (archived → Archived Programs tab → delete). Programs can be **duplicated year-to-year**.
- A season spanning Fall→Spring keeps volunteers visible across both.
- **"Set Registration Schedule"** (open/close dates, program- or per-package level) unlocks only **after PlayMetrics approves the program review**.
- Birth-date/age ranges are set in package settings or at the age-group level; PlayMetrics auto-filters so only age-eligible packages appear to a parent (why a too-young child sees "no programs available"). PlayMetrics added a **U19** age classification (older versions required a birth-date-range workaround above 18U). [VERIFY]

## Player vs Program Questions
- **Player Questions** = once per child (3 kids → answered 3×): photo, preferred name, uniform size, medical, per-player emergency contact.
- **Program Questions** = once per registration session: volunteer interest, donations, household emergency contact.
- An **Optional Subscription Fee can only be linked to a Player Question** (e.g., a background-check donation tied to an auto-add fee must be a player question).

## Package-Specific Questions
- Build a **Dropdown** element with Dropdown Options = "Program Packages" (auto-loads all packages). Use **"Linked Elements"** to attach package-specific questions; only those linked appear for that package. Name the dropdown **"Division"** so it reads cleanly.
- Conditional links do **NOT** copy when copying sections between programs — re-link manually.

## File Upload (Player Photo)
- Minimum Required = 0 (optional); Maximum = 1; turn ON "Add to Player Resources on Form Completion"; "Reuse existing resources" OFF. Must fill Section Title and File-Upload Label to publish.

## Medical Question Pattern
- Yes/No radio + conditional text field shown only on "Yes," mapped to the player's **medical notes**. (A plain optional text box saves "none"/"no" as a medical note — avoid.)

## Settings & Toggles
- "Allow player contact to edit registration responses": parents can edit post-submission with **no admin notification** — for uniform sizing, export before ordering or lock after a cutoff.
- "Collect financial aid requests" = two-gate (club + program level). Toggle off at program level to handle aid offline (Region 58 collects aid in PlayMetrics).
- Volunteer roles must be toggled ON **and** each position's "collect sign ups / contacts can apply" checkbox checked, or volunteer questions won't appear.
- Do **NOT** enable the volunteer discount.
- Once registration is open you can only **hide** questions, not delete them — finalize structure first.

## Fees
- **Club Fee (NPF):** player-oriented, once per player per season; must be aligned/attached to **ALL packages** (select in bulk) or those players won't be charged. PlayMetrics may pre-create the NPF for regions with a merchant account.
- **Credit card processing fee (~2.8%):** admin toggle — Region 58 leaves OFF (absorbs).
- **Order/service fee ($3.50):** NOT admin-controllable; enabled only by PlayMetrics; once enabled can't self-disable. Region 58 does not pass it through.

## Merchant Account
- Managed by the **Controller** role (Treasurer), under Financials → Merchant Account.
- **Entity (KYC) address and customer-service address must both be physical addresses, NOT PO boxes.** Receipt shows a physical address.
- Refund policy text lives here as **text** (not a link). Verify receipts: customer service name (region name, not a person), physical address, tax ID, clean refund text (no leftover SC references).

## Leagues & Coaching Requests
- A **League** is separate from the Program. Build the Program first, create an **In-House League**, then connect it to the Program.
- Enable Coach Requests in **League Settings** (pencil icon). Coaching request questions: **Leagues → Coaching Requests → More Actions → Set Coaching Request Questions**.

## Viewing & Editing Registration Data
- Individual responses: **Programs → 2026 Fall Core → Subscriptions list → click subscription → "View Program Responses"**; **"Edit Responses"** to change (admin side). There is **no separate "Subscriptions tab"** — the list is within Program Details (older help articles are wrong).
- Players do NOT appear under Leagues until assigned to teams (expected, not a bug).
- **Active subscriptions** = completed registrations with an active payment obligation (registered, not canceled). Canceling prompts whether to remove the player from rosters.

## Exports (More Actions — appear only after real registrations exist)
- **Export Responses** → `registration-responses*.csv` (one row per player: player info, account, address, ALL question answers incl. waivers/emergency contact + per-role volunteer-interest flags). Opens an intermediary "Download as .CSV" page.
- **Export Volunteer Info** → `volunteers*.csv` (one row per volunteer position per player). Downloads immediately.
- **Export Subscriptions** (= Orders; player question/payment data), **Export Payments** (Order No, Amount, Paid, Balance — NOT in Responses), **Export Financial Aid Requests**.
- **Coaching Requests** export: **Leagues → Coaching Requests → More Actions → Export** → `*coaching-requests*.csv` (one row per coach-player pair).
- **Packages tab** (Programs → 2026 Fall Core → Packages): the **only** source for live per-package "Active Registrations X of Y," waitlist count, and financials. **Max spots are NOT in any export CSV.**
- NPF reconciliation: Financials → Additional Fees → Club Fees → select fee → More Actions → Export Subscriptions. Payouts: Merchant Account → Payouts (toggle "Split transaction by program").

### Key Export Columns
- `registration-responses` (snake_case): `account_email/first/last/phone`, `player_first/last_name`, `player_id`, `birth_date` (YYYY-MM-DD), `gender` (M/F), `package_name` (division), `status`, `registered_on`, `age_group`, address/city/state/zip. `account_phone` in E.164 (`+1##########`). `volunteer_head_coach` holds an email if interested (NOT Yes/No). ~30 extra question fields (photo, BC, teammate/coach request, school, experience, positions, uniform/jersey/short sizes, medical flag+note, waivers, emergency contact, per-role volunteer flags).
- `volunteers`: `volunteer_position` (Head Coach/Assistant Coach/Referee/etc.), `package_name`, `volunteer_email`, `volunteer_name`, `volunteer_mobile_number`.
- `coaching-requests`: `coach_email/first/last/phone`, `request_head_coach`, `request_asst_coach`, `coach_assigned_to_player_team`. **Division codes are gendered** (`08UB`, `08UG`) — match on the full gendered code, never the first 3 chars (substring matching merges Boys+Girls and inflates counts).

## Team Assignments / Scheduling
- **No automatic team building/balancing** — assignment is **drag-and-drop**. Pull player pools by age/gender (incl. both genders for coed). Ratings/evaluations use a separate **Tryout** tool (or a hidden admin question for ratings).
- Creating a Team Assignment and pulling players is a **sandbox** — nothing is sent to families until you assign players to teams and click **"Notify Players."**
- **Coaches are notified immediately** when assigned to a team; players only on "Notify."
- California **AB 506** requires fingerprinting to activate teams and print official rosters.

## Scheduling Capabilities (built-in) [VERIFY]
- Game scheduler (weekly matchups + locations, coaching-conflict detection, unscheduled-team highlighting, repeat-matchup tracking); league scheduling (cross-division matchups, public schedules/standings, change alerts); field/facility management (custom field plans, drag-and-drop moves, field closures with auto-notify); parent/family calendar (consolidated, week/month/list, Google/Apple sync). Game import via CSV. In-house vs imported games are treated as two different leagues (matters for divisions that travel).

## Test Tools
- **"Login as Test Parent"** (More Actions) walks the full registration flow (some features behave differently in test mode). **"Login as a User"** impersonates a real account. A draft shows **"Draft Not Validated"** until PlayMetrics approves (parents wouldn't see this in production).

## Player Photos
- Photo URL pattern: `https://playmetrics.com/subscription-file-upload-redirect/<id>/player/2.0` — a redirect-to-download endpoint requiring an **authenticated** session (anonymous fetches fail); serves `application/octet-stream` (don't gate on content-type). ~half of players have a photo.

## Platform Mechanics (automation)
- PlayMetrics is **Vue.js + Bulma** (not React); Firebase-based auth (`playmetrics-prod`); session JWTs expire ~60 min. **No public API/webhooks** — all extraction is manual CSV export via "More Actions."
- **Login:** go directly to `playmetrics.com/login` (the landing-page "Sign In" opens a new tab). Fields: `input#username`, `input#password`, `button#submit`. New/unknown devices trigger an **SMS MFA** challenge; a persistent profile retains device trust.
- Export URL pattern: `https://api.playmetrics.com/program_admin/programs/{program_id}/{export}.csv?...` (server-signed `access_key` cannot be built client-side). [VERIFY]
