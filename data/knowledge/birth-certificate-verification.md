# Birth Certificate (BC) Verification

## Parent-Facing Summary
- Most **returning players already have a verified birth certificate on file**; verified status **carries over** from Sports Connect/Affinity, so those players **skip the BC upload** automatically at registration.
- **New / unverified players** are automatically **prompted to upload** a birth certificate during registration.
- The conditional **"have you played before / provided a BC?"** question was **removed**; the BC **upload element is kept** with **"skip players with a verified date of birth" toggled ON**. The system auto-skips verified players and prompts everyone else — handling both cases with no conditional question.
- Birth certificate upload **can be set as required** in PlayMetrics.
- Going forward, BC **review/validation is done at the Region level**.

## Divorce / Cannot Produce a Birth Certificate
- For families who cannot readily produce a BC (e.g., divorce situations where obtaining one may take months), direct the parent to talk to their **AD/SD (Area Director / Section Director)** rather than the registrar making a unilateral decision. Do not deny play unilaterally.

## How Verification Carries Over
- When a player who exists in Sports Connect registers on PlayMetrics, the **embedded registration workflow** looks them up, migrates them, and **preserves verified status**. **Age verification does NOT have to be restarted.**
- If an imported family creates a NEW account instead of using their invitation link, they orphan the imported record and must **re-upload** the BC (see invitation-links.md).

## BC Status — Definitive Source (Admin/Migration)
- Definitive BC status comes from **Sports Affinity's "Player Photo BC Info" report** (Reports → Player Reports), which contains per-player **upload dates** and **verification dates**.
- The **"Media=B" flag** from player applications is **NOT a reliable BC indicator** — every player defaults to B. **Do not use it.**

## BC Modes (Import Tool)
- **Default mode:** a player is treated as having a BC on file if the certificate was **uploaded OR verified**.
- **Strict BC mode:** only players with a **verification date** count as having a BC on file (uploaded-but-unverified does not qualify). Strict mode yields far fewer verified players (e.g., a ~1,400-player dataset yielded ~476 verified in strict vs ~933+ non-verified).
- A player with a BC in **any merged season** is flagged verified.

## BC Import Split & Handoff
- The import tool produces a **BC-verified CSV** and a **non-verified CSV**.
- **BC-verified players** must be imported **by PlayMetrics** — email the BC-verified file to `success@playmetrics.com` (subject e.g., "BC-Verified Player Import — Region 58"). PlayMetrics flags them as verified on load.
- **Non-verified players** are imported **by the Region itself** (Players → More Actions → Import Players).
- After PM imports the verified batch, any registering player matching an imported record auto-skips the BC upload; new players are prompted to upload.
- PlayMetrics can optionally be set to **delete the BC file after verification**.
