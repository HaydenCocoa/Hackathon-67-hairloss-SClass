# Database scripts

Use [supabase/schema.sql](supabase/schema.sql) for the complete initial schema matching the latest ERD. Read [supabase/README.md](supabase/README.md) for setup instructions and the current scheduling limitations.

If you already ran the earlier single-intake schema, use [the membership upgrade](supabase/migrations/202611080001_student_intake_memberships.sql) instead of rerunning the setup. It transfers existing student intake/group values to `student_intakes` while preserving identities and linked accounts.

Sample data: [rooms](supabase/seed_rooms.sql), [lecturers](supabase/seed_lecturers.sql), and [students with initial intake memberships](supabase/seed_students.sql). The room and lecturer scripts work with the membership design without changes.
