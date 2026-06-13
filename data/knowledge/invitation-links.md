# PlayMetrics Invitations & Account Setup

## Invitation Emails (Returning/Imported Families)
- Imported families receive a PlayMetrics invitation email from **`noreply@playmetrics.com`** with subject **"Sign Up For Player Access to AYSO Region 58."**
- The email contains a **unique Sign Up link** tied to their pre-loaded account; clicking it pre-populates their account info from the import.
- **Critical guidance:** Returning/imported families must use the invitation link to finish registering. If a family ignores the link and **creates a brand-new account**, they **orphan their imported record** and must **re-upload the birth certificate**. Always emphasize using the invitation link; never tell imported families to create a new account.

## Invitation Link Mechanics
- Each invitation link is **unique per contact**. Token format: `Login.V2-{contact_id}-{org_id}-{timestamp}|{signature}`. It uses the PlayMetrics **`contact_id`** (from the Player Contacts export), not the player_id.
- The cryptographic signature means links **cannot be reconstructed or forged externally** — only PlayMetrics can generate valid links.
- Each **contact** (primary AND secondary guardian) has their own `contact_id` and gets their own unique link; non-primary contacts can be invited and register independently.
- Invitations can be **resent unlimited times** in bulk to anyone in "not invited" or "unverified" status.
- Invitation/contact counts are **per-contact, not per-family** (e.g., ~3,900 contacts vs ~2,874 players vs ~2,152 unique primary-parent emails).

## "I Didn't Get the Invitation" — Diagnostic & Resolution
1. **Check the family's status** (registered vs imported-not-registered) and whether the pre-launch heads-up email was delivered.
2. **Resend the invitation.**
3. Tell them to **check spam** for `noreply@playmetrics.com`.
4. Provide the **direct registration link** as a second path.
- Many parents register successfully shortly after emailing.

### Email Already Verified/Registered Elsewhere
- If a parent's email shows as already verified/registered in PlayMetrics (sometimes from **another club's** PlayMetrics account), they will **NOT receive an invitation**. Direct them to:
  1. Log in at `https://playmetrics.com/login`
  2. Use **"Forgot your password?"** if needed
  3. Navigate to **Programs**
  - Also give them the Region 58 direct registration link as a second path.

### Account Missed in Import (Date Cutoff)
- Some interest-list/inactive accounts were missed in the initial import due to a date cutoff. When a parent reports not seeing registration, their account can be **imported individually**; they will then receive an invite.
- Pattern reply: confirm registration is open, explain the account was missed due to a date cutoff, tell them an invitation email is coming, and instruct them to click the link — their info will already be there.

### Wrong/Changed Email on an Imported Contact
- Parents can change their own account email from account settings (this makes that address the account's username).
- For an unverified imported contact, an admin can **edit the contact's email**, OR **delete and re-import** the record with the corrected email, then **resend** the invitation.

## Invitations Dashboard (Admin)
- Located at **Players → All Players**. Status counts:
  - **Total Players**
  - **Not Verified** = invited, no account yet (the follow-up list)
  - **Not Invited** = in system, no invite sent
  - **Delivery Failed** = bounced (needs an alternate contact)
  - **No Contacts** = no email on file
- **Bulk resend:** Players → All Players → **Manage Invitations** → **Send Invitations**.
- **Individual resend:** Players → All Players → search player → **Contacts** tab → "..." menu → **Edit Contact** → **Send / Resend Invitation**.
- **KEY DIAGNOSTIC:** If Edit Contact shows a **"Resend Invitation"** option, the contact is **unverified** (not yet registered). If absent, the contact has **already registered**. An **orange dot** on a contact indicates unverified.
- **Manage Invitations "Primary Contacts" toggle:** ON = only primary contacts get invitations; OFF = all contacts (primary + secondary).
