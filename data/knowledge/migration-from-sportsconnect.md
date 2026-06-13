# Migration from SportsConnect to PlayMetrics — Region 58

## Status & Scope
- Region 58 is migrating from **SportsConnect (Blue Sombrero) / Sports Affinity** to **PlayMetrics** for **Fall 2026**, as part of an **AYSO national pilot**.
- SportsConnect and the Association Platform are scheduled to be **sunset in 2027**. [VERIFY]
- Historical player data (~1,100+ records) was imported via the migration tool. Migration was ~92% complete as of early May 2026. [VERIFY]
- **Note on location:** Some documents say Region 58 covers **Burbank, CA**; the authoritative parent-facing description is **Van Nuys / Sherman Oaks**. [VERIFY]

## PlayMetrics Platform Architecture (for context)
- Two connected products: **Governing System** (AYSO National — compliance, purple interface) and **Club System** (region day-to-day registration, blue interface).
- Hierarchy: **Season → Programs & Leagues → Packages (≈ Divisions) → Teams**.
- **Embedded Registration** connects Club → Governing, injecting AYSO national requirements (waivers, NPF, birth-certificate verification) into every region's workflow. National configures a default season with these; regions layer their own programs, packages, pricing, and custom questions on top.

## Terminology Map (SportsConnect/AYSO → PlayMetrics)
| SportsConnect / AYSO | PlayMetrics |
|---|---|
| Division | **Package** |
| Order / Registration | **Subscription** (overdue order = Overdue Subscription) |
| Parent Account / User | **Player Contact** / Account Owner |
| Division Coordinator | **Director** |
| Volunteer roles | **Staff** types (Admin, Director, Coach, Team Staff) |
| National Player Fee (NPF) | **Club Fee** |
| Evaluation Ratings | **Tryout Evaluations** |
| Saved Reports | **Exports** (More Actions menu) |
| Game Schedules | **League Schedules** |
| Buddy/Coach Requests | **Player Questions** / built-in Coaching Requests |
- SC hierarchy was **Organization > Program > Division > Team**; PlayMetrics reverses to **Season > Program > Package > Team**. The Season/Program/Package nesting is the #1 source of admin confusion.

## Data Import Approach
- PlayMetrics officially **recommends AGAINST bulk-importing from Sports Connect** (parents should make fresh accounts so contact info is current). Region 58 **did** import historical players because **post-import invites are tied to the email on record**, eliminating the account-mismatch concern the recommendation is based on.
- Import templates exist for **players and staff** (not parents).
- **Hard sequencing rule:** ALL imports must finish **BEFORE registration opens**. Importing on top of newly-registered accounts causes conflicts.
- **Correct sequence:** (1) PlayMetrics approves the program → (2) import historical players (PM imports the BC-verified batch; region imports the non-verified batch) → (3) send invites to imported families → (4) open registration → (5) email the generic registration link to non-imported families.

## Source Data (Sports Affinity)
- Two reports from the **Sports Affinity Association site** (`ayso.sportsaffinity.com`, same login as Sports Connect; reachable via Sports Connect → profile → "Go to AYSO"):
  - **"Player Detail | upload format"** (`playerUpload.xlsx`) — primary source: pre-split player/parent names, gender (M/F), DOB, parent1+parent2 contacts, addresses, team assignments. From Players/Admins → Player Lookup → Report dropdown.
  - **"Player Photo BC Info"** (`Player_Photo_BC_Info.xlsx`) — definitive BC status (upload + verification dates). From Reports → Player Reports.
- **Filters in Player Lookup:** Season = current membership year; Region = your region; Age Group = "Multiple" (all checked); other filters at defaults.
- **"Father"/"Mother" columns are NOT gendered** — they are simply **Parent 1 / Parent 2** (many "Father" entries have female names). Map as-is to parent1/parent2.
- **Inactive Participants Report** (Sports Connect) captures interest signups (Most Recent Division = "N/A") — a separate/third import batch, often youngest age groups. ("N/A" reads as null/empty in tools — handle both the literal string and null.)

## Import Tool Behavior (open-source `playmetrics-import`)
- Converts Sports Affinity / SportsConnect data into PlayMetrics Player Import CSV; produces a **BC-verified CSV** (to PlayMetrics), a **non-verified CSV** (region imports), an **all-players reference CSV**, and an **audit log**.
- **Strict BC mode** = GUI checkbox / `--strict-bc` flag (verified-only).
- **Multi-season merge** deduplicates by **player name + DOB** (NOT email — a child may appear under both mom's and dad's email; keep the more complete record). Recommendation: current year + 1 prior; 3+ years has diminishing returns.
- **Phone validation (NANP):** area codes starting with 0 or 1 are blanked; format `XXX-XXX-XXXX`. **ZIP** truncated to 5 digits.
- **Team column always blank** — prior-season teams don't exist in PlayMetrics; teams are built fresh after registration and draft.
- **Age-eligibility filter:** oldest eligible DOB cutoff **Aug 1, 2007** for Fall 2026; aged-out players (DOBs from early 2000s) are excluded (PlayMetrics rejects them with "birth_date not valid"). [VERIFY]
- **Jamboree/4U players** are included; they may age up to 5U and retain BC verification.
- Run modes: GUI (default drag-and-drop), batch (`--dir folder`), CLI (`--cli`). Windows `.exe` and Mac binary available from GitHub Releases (v1.0); first-launch SmartScreen/Gatekeeper warnings are normal for unsigned apps.

## PlayMetrics Player Import CSV Format
Columns in order: `team, season_id, season, player_first_name, player_last_name, gender, birth_date, age_group, position, number, Foot, parent1_email, parent1_first_name, parent1_last_name, parent1_mobile_number, parent2_email, parent2_first_name, parent2_last_name, parent2_mobile_number, street, city, state, zip`. [VERIFY]
- `gender` = single letter **M** or **F** (not Male/Female).
- `birth_date` = **YYYY-MM-DD** (note: some PM templates and exports use MM/DD/YYYY — **confirm the official template's exact format before importing**).
- Phones = `XXX-XXX-XXXX`.
- `season_id` optional; `team`, `age_group`, `number`, `position`, `Foot` may be blank.
- **Always download the official PlayMetrics CSV import template (behind the admin login) to confirm exact headers and formats before each import.** [VERIFY]

## Field Mapping (SportsConnect Enrollment Export → PlayMetrics)
- player_first/last_name ← Player First/Last Name
- gender ← derived from Division Name 4th char (B→M, G→F) or Player Gender (Male→M, Female→F)
- birth_date ← Player Birth Date
- parent1_email ← User Email; parent1_first/last ← Account First/Last Name; parent1_mobile ← Cellphone (fallback Telephone), stripped to 10 digits, leading '1' removed
- parent2_email ← Secondary/Additional Email; parent2_first/last ← Additional First/Last Name; parent2_mobile ← Additional Cellphone (fallback Additional Telephone)
- street ← Street Address + Unit; city/state/zip ← City/State (normalize to 2-letter)/Postal Code

## Data Cleanup Steps (pre-import)
- Deduplicate (NameKey = Player First + Last + Account First; sort newest-to-oldest; keep newest). Resolve split households (copy Parent 2 into the primary row rather than merging accounts in SC).
- Remove aged-out players; review unsubscribed emails (may re-register fresh); fix city/zip; review/remove clearly out-of-area registrations.

## Pilot Constraints
- **Governing System (compliance) is NOT accessible to pilot regions** — expected **summer 2026** (pending JDP background-check + AYSOU integrations). During the pilot, compliance data continues to live in **Sports Affinity / eTrainU**.
- **Contractual restriction:** **no PlayMetrics application screenshots** may be published on a public wiki/site. Text descriptions (field names, navigation paths, labels) are fine. AYSO-provided communication assets (rotator banners, email headers, social graphics) are OK to publish.
- Pilot regions open MY2026 on PlayMetrics in spring 2026; broader regions transition for MY2027. [VERIFY]

## Website & Go-Live
- The live website still runs on SportsConnect (Blue Sombrero) until the **Duda**-based PlayMetrics website builder is ready (a later project; assign the manager the Marketer role).
- **Domain names (e.g., ayso58.org) are owned/managed by AYSO National** — National handles the DNS switch; regions take no action but should confirm it's on National's rollout plan.
- The SportsConnect **"Register Now" redirect** is handled by **Sports Connect support** (ticket/chat), NOT PlayMetrics.
- **Program Review gate:** Email `success@playmetrics.com` (subject "AYSO Region [X] Program Review"). PlayMetrics reviews, then enables the Merchant Account.

## Resources
- Import tool repo: https://github.com/sdavis9248/playmetrics-import [VERIFY]
- Migration docs site (status dashboard, volunteer compliance guide, game scheduling guide, website migration, terminology reference, data import steps): https://sdavis9248.github.io/playmetrics-migration-region58/ [VERIFY]
- PlayMetrics support/onboarding: `success@playmetrics.com` (Region 58 contact: Heather Deist; rep referenced as Jason). Zendesk replies may go to a ticket-specific address and can drop CC'd people — re-add recipients as needed.
