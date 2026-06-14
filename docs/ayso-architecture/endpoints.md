# REST Endpoints (JSON) — /api/v1

Use `?asOf=YYYY-MM-DD` on temporal GETs where relevant.

## People & Roles
- GET /people
- GET /people/{personId}
- POST /people
- PUT /people/{personId}
- DELETE /people/{personId}

- GET /role-types
- GET /role-types/{roleTypeCode}
- POST /role-types
- PUT /role-types/{roleTypeCode}
- DELETE /role-types/{roleTypeCode}

- GET /person-roles
- GET /person-roles/{personRoleId}
- POST /person-roles
- PUT /person-roles/{personRoleId}
- DELETE /person-roles/{personRoleId}

## Seasons / Programs / Divisions / Teams / Age Groups
- GET /seasons
- GET /seasons/{seasonId}
- POST /seasons
- PUT /seasons/{seasonId}
- DELETE /seasons/{seasonId}

- GET /programs
- GET /programs/{programId}
- POST /programs
- PUT /programs/{programId}
- DELETE /programs/{programId}

- GET /divisions
- GET /divisions/{divisionId}
- POST /divisions
- PUT /divisions/{divisionId}
- DELETE /divisions/{divisionId}

- GET /teams
- GET /teams/{teamId}
- POST /teams
- PUT /teams/{teamId}
- DELETE /teams/{teamId}
- GET /teams/{teamId}/roster?asOf=YYYY-MM-DD

- GET /age-groups
- GET /age-groups/{ageGroupId}
- POST /age-groups
- PUT /age-groups/{ageGroupId}
- DELETE /age-groups/{ageGroupId}

## Enrollment & Placement
- GET /enrollments
- GET /enrollments/{enrollmentId}
- POST /enrollments
- PUT /enrollments/{enrollmentId}
- DELETE /enrollments/{enrollmentId}

- GET /enrollments/{enrollmentId}/status
- POST /enrollments/{enrollmentId}/status
- PUT /enrollment-status/{statusId}
- DELETE /enrollment-status/{statusId}

- GET /team-placements
- GET /team-placements/{teamPlacementId}
- POST /team-placements
- PUT /team-placements/{teamPlacementId}
- DELETE /team-placements/{teamPlacementId}

## Volunteers & Certifications
- GET /volunteer-assignments
- GET /volunteer-assignments/{volunteerAssignmentId}
- POST /volunteer-assignments
- PUT /volunteer-assignments/{volunteerAssignmentId}
- DELETE /volunteer-assignments/{volunteerAssignmentId}

- GET /certification-types
- GET /certification-types/{code}
- POST /certification-types
- PUT /certification-types/{code}
- DELETE /certification-types/{code}

- GET /person-certifications
- GET /person-certifications/{personCertificationId}
- POST /person-certifications
- PUT /person-certifications/{personCertificationId}
- DELETE /person-certifications/{personCertificationId}

- GET /volunteer-requirements
- GET /volunteer-requirements/{id}
- POST /volunteer-requirements
- PUT /volunteer-requirements/{id}
- DELETE /volunteer-requirements/{id}

## Derived
- GET /programs/{programId}/volunteers/{volunteerType}/compliance?asOf=YYYY-MM-DD
