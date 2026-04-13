# Schema Migrations

Add new migration files here as `NNN_description.sql` (e.g., `002_add_tags.sql`).

Rules:
- Files are applied in numeric order.
- Each file runs in a single transaction — either it all applies or none of it.
- After applying file `NNN_*.sql`, `pgrg_meta.schema_version` is set to `NNN`.
- Never edit a migration after it has been released — add a new one instead.
- The initial schema lives in `../schema.sql` (version 1). Migrations start at 2.
