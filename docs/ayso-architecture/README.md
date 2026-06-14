# AYSO Temporal Data Architecture Project

**Created:** 2025-08-30T14:53:32

This project captures a temporal-first data model for AYSO registrations and volunteers, plus REST API outlines and a relationship diagram.

## Contents
- `schema.sql` — PostgreSQL DDL using range types and GiST exclusions.
- `endpoints.md` — REST endpoints and payload shapes (JSON).
- `diagram.png` — Entity relationship diagram.
- `README.md` — This file.

## Highlights
- Canonical **Person** with temporal **PersonRole** (PLAYER, VOLUNTEER, etc.).
- **Season → Program → Division/Team/AgeGroup** temporal hierarchy.
- **Enrollment** with temporal **EnrollmentStatus** and **TeamPlacement**.
- **VolunteerAssignment** scoped to Program with **VolunteerType** taxonomy.
- **CertificationType**, **PersonCertification**, **VolunteerRequirement**, and **CertificationEquivalency** for derived compliance.
- All validity windows as half‑open ranges `[begin, end)`.

## Next Steps
- Import `schema.sql` into PostgreSQL.
- Populate lookup tables (`role_type`, `volunteer_type`, `certification_type`, `enrollment_status_type`).
- Use queries in `endpoints.md` to implement API handlers.
