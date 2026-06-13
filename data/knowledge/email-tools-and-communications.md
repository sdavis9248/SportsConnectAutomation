# Email Tools & Communications — Region 58 (Internal)

> Internal tooling/process. Not parent-facing.

## Sending Channels
- **PlayMetrics built-in email** sends from `noreply@reg.playmetrics.com`; replies route to PlayMetrics' internal message center (no custom reply-to).
- **Custom Python framework** (Gmail OAuth2, Google Workspace) sends from `registrar@ayso58.org`. Google Workspace caps **2,000 recipients/day per user** — large sends (~2,152 unique families) must be split across two days; the framework dedupes across runs.

## PlayMetrics ↔ Mailchimp Integration
- Native integration is **Beta**, enabled by PlayMetrics Success; a **Marketer-role** feature. PlayMetrics connects to **one** external email provider at a time (Mailchimp or Constant Contact). [VERIFY]
- The synced audience = **one contact per player: the account owner of every REGISTERED AND VERIFIED player** (secondary guardians never synced). Auto-syncs as players register.
- Because it's "registered + verified" only, it **cannot** be used for pre-launch email and does **not** include imported-but-not-registered families.
- PM custom tagging can segment only on Age/Gender/Level/Program/Team — **never registration status** — so there's no native "unregistered" segment.

## "Invited but Not Registered" Audience
- Built as **(all imported families) − (synced/registered audience)**. The synced audience is the authoritative "registered" set.
- **Player-level logic (correct):** a player is "registered" if ANY linked guardian email is in the registered set. The not-registered audience = all distinct guardian emails of players with NO registered guardian (avoids missing second-parent emails and avoids nagging families who registered under the other parent). Region 58 chose **maximum reach** (email all guardians of unregistered players).
- Use the **Player Contacts export** (`contact_email` + `player_id`) as the universe. Normalize emails (lowercase/trim). Collapse to one contact per email.
- Kept as a **separate, manually-managed audience**: "Region 58 - Invited but not yet registered Fall 2026" — separate from the synced audience so the PM sync doesn't reconcile manual contacts out.
- Region 58 audience IDs: synced = `2be4ba6a13`; not-registered = `eb403808cf`. Not-registered merge tags: **MMERGE5 = Players, MMERGE6 = Player Count** (always confirm auto-generated merge tags after a manual import). "Players" values may contain commas — quote them in CSV.
- The list **drifts**: MailChimp does not auto-remove families as they register — refresh/suppress periodically. **Archiving** removes from active count/campaigns, is reversible, preserves data.
- **Dual-audience send:** a campaign targets exactly ONE audience. Build once, **Replicate**, point the copy at the second audience. Run the suppression sync **immediately before** sending so no one gets it twice.

## Email Configuration (PlayMetrics)
- "Email Name" is an internal label (parents never see it). "Email Type" = registration confirmation vs waitlist confirmation. Select all applicable packages; emails do NOT auto-attach to packages created later. Body supports merge variables (`$$PlayerName$$`, `$$ProgramName$$`, `$$PackageName$$`).

## Drafting Conventions (Registrar Email Assistant)
- **Tone:** warm, welcoming, enthusiastic about new players, professional, patient.
- **Greetings:** "Hi [Name]," / "Hello [Name],". **Sign-off:** "Best regards, Steve Davis, Registrar, AYSO Region 58" (note: the Registrar is also referred to as **Steven Davis**).
- Use **bold** for key details, bullet points for organization, include relevant ayso58.org links, always offer further help at the end.
- Common phrases: "Thanks for reaching out," "we'd be happy to have [player] join us!", "Everyone who registers plays — there are no tryouts," "No prior experience is required."
- **Never suggest calling the registrar; never provide a phone number** — all registrar communication is by email.
- Emphasize **Open Registration** (no boundaries, any region welcome), **"Everyone Plays"** (no tryouts), and no prior experience required.
- **Only state a player's specific division, balance, team, or waitlist status if it is actually found in a registration-data lookup — never guess.** Do not guess a division from a stated age.
