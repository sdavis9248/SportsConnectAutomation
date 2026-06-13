# Waitlist — Region 58

## Parent-Facing Policy
- **AYSO's philosophy is "Everyone Plays."** If a parent mentions being waitlisted, reassure them — being permanently shut out is not how AYSO works. (Note: there can be capacity-driven exceptions like field caps or specific full divisions worth confirming case-by-case.)
- There is a **free waitlist**; families should register **promptly** as divisions can reach their cap (driven by number of players and available head coaches).
- **There are no waitlists or pre-registration lists for general/early registration before it opens** — to be notified when registration opens, a family should simply create an account at ayso58.org.
- **19U divisions are waitlist-only** by design (teams form only if enough players register).
- "NO PROGRAMS AVAILABLE" shown for a player can mean a division is **closed or full**.

## PlayMetrics Waitlist Mechanics (Admin)
- Waitlists are enabled per-package. The **Packages tab** shows live per-package **waitlist count** alongside "Active Registrations X of Y."
- A waitlisted player can be sent a **waitlist invitation** to register; admins manage the waitlist list and can **extend the expiration date** or **cancel** an expired invitation. An expired invitation does **not** auto-move the player back to the waitlist or auto-cancel.
- A separate **waitlist confirmation email** can be configured (e.g., a "you will not be charged" note for waitlisted families).

## Region 58 Waitlist Confirmation (Google Form — legacy/supplemental tooling)
- Region 58 uses a Google Form titled **"AYSO Region 58 - Waitlist Confirmation"** to ask waitlisted families whether they want to stay on the waitlist (**Yes** = stay, **No** = remove).
- The form is **anonymous** (Collect email OFF, Limit to 1 response OFF, Require sign-in OFF). Player info (name, division, order number) is passed via a **pre-filled URL parameter** so responses match to a player/order while staying anonymous.
- The "Sign in to Google to save your progress" message is a standard, **non-removable** Google Forms element — it is only a suggestion and does **not** force login. If parents are confused, add a note in the email/form description clarifying no sign-in is required.

## Waitlist Removal Procedure (Admin)
- Before removing anyone, **cross-check the removal list against a freshly downloaded current Waitlist report** — only remove order numbers still actually on the waitlist.
- **"Total Pending Responses"** = everyone notified who hasn't responded. **"Non-responders"** = the subset pending longer than a threshold (e.g., >3 days). A "No" response means remove; "Yes" means stay.
- Non-responder actions: **summary** (counts), **report** (detailed list of players still on the waitlist), **remove** (processes removal, with confirmation unless auto-confirm set).
