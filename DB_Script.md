# Database scripts

Use [supabase/schema.sql](supabase/schema.sql) for the complete initial schema matching the latest ERD. Read [supabase/README.md](supabase/README.md) for setup instructions and the current scheduling limitations.

If you already ran the earlier single-intake schema, use [the membership upgrade](supabase/migrations/202611080001_student_intake_memberships.sql) instead of rerunning the setup. It transfers existing student intake/group values to `student_intakes` while preserving identities and linked accounts.

Sample data: [rooms](supabase/seed_rooms.sql), [lecturers](supabase/seed_lecturers.sql), and [students with initial intake memberships](supabase/seed_students.sql). The room and lecturer scripts work with the membership design without changes.

Course assignments: [seed_courses.sql](supabase/seed_courses.sql) adds the Programming, Networking, and Software Engineering teaching components for `APU1F2611CS(SE)`. Run it after the lecturer seed. Each session component lasts 120 minutes, and both components of a subject use the same lecturer.

For an existing database, run [the student age upgrade](supabase/migrations/202611080002_student_age.sql) before the latest student seed. New projects created with `schema.sql` already include integer `age`. The seed supplies sample ages 18 through 25 for the 1,000 students.
