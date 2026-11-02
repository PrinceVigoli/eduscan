# EduScan

A responsive, dependency-free PWA prototype for QR-based student attendance at Luna National High School.

## Run locally

The root folder contains the teacher PWA. Serve it over HTTP so its service worker, offline database, and camera permissions can work:

```powershell
python -m http.server 8080
```

Then open `http://localhost:8080`.

Start the synchronization API in a second terminal after installing Python 3.12+:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m app.seed_admin
.venv\Scripts\python -m uvicorn app.main:app --reload
```

The one-time `seed_admin` command securely prompts for the initial IT administrator's name, email, and password.

## First sign-in

Create an administrator with `python -m app.seed_admin` and sign in with the credentials you provide. Each installation creates its own accounts; local credentials and databases are excluded from the repository.

The API runs at `http://localhost:8000`; interactive API documentation is available at `http://localhost:8000/docs`.

For development tests, install `backend/requirements-dev.txt` after stopping any running API process, then run `python -m pytest -q`.

## Database migrations

Run migrations before starting the API, especially after pulling an update:

```powershell
cd backend
.venv\Scripts\python -m alembic upgrade head
```

SQLite is suitable for one computer and development. For consolidated multi-device deployment, set `EDUSCAN_DATABASE_URL` to a PostgreSQL SQLAlchemy URL in `backend/.env`, then run the same migration command.

## Backup and restore

Create a recoverable SQLite backup (database plus student photographs):

```powershell
cd backend
.venv\Scripts\python -m app.backup
```

Backups are written under `backend/backups` and are intentionally excluded from Git. Restore only a trusted archive from that directory:

```powershell
.venv\Scripts\python -m app.restore backups\eduscan-backup-YYYYMMDD-HHMMSS.zip
```

The restore command validates the archive and requires typing `RESTORE`. PostgreSQL deployments should use `pg_dump` and `pg_restore` instead.

## Offline operation

- The application shell, scanner, assigned roster, active QR credentials, and compressed student photographs are cached on the teacher device.
- After signing in online, each registered teacher device receives a short-lived, single-use, class-scoped authorization permit. The browser verifies its P-256 signature before allowing a new session to open without connectivity.
- The permit binds the teacher, device, class, validity window, and one-session limit. The private signing key never leaves the server.
- Offline-created sessions and offline closure requests survive browser restarts, synchronize later, and are adopted only once by the server. Closing them creates absences normally.
- Synchronization is idempotent. Rejected records are retained locally as conflicts instead of being retried forever.
- Closing a session on the server creates absences for unscanned enrolled students.

## End-of-year lifecycle

Academic years follow `planning → active → closing → archived`:

- Planning allows class and enrollment setup but no attendance sessions.
- Active allows normal attendance and synchronization. Only one year can be active.
- Moving to closing requires every open session to be closed and revokes unused offline authorization permits. Corrections remain available during review.
- The principal must approve a closing year before IT can archive it.
- After principal approval, IT reviews a promotion preview for every enrolled student and chooses promoted, retained, graduated, transferred, or withdrawn. Grade 7–11 proposals advance one grade; Grade 12 proposes graduation.
- Applying the review updates only the current student profile and next-year enrollments. Source-year classes, attendance, and enrollment history remain unchanged, and every decision receives a permanent promotion-history and audit record.
- A closing year cannot be archived until every student in that year has a recorded promotion decision.
- Archiving requires a backup reference plus the exact typed confirmation `ARCHIVE YYYY-YYYY`. Archived classes become read-only and disappear from active workspaces, while their attendance, audit history, and reports remain stored.
- Student profiles are retained between years; enrollments are created again for the new year. Graduated, transferred, or withdrawn students can be marked inactive without deleting history, and their active QR is revoked automatically.

## QR credential lifecycle

- New students receive a random physical-card credential automatically.
- A card can be marked lost, damaged, compromised, or administratively revoked.
- Replacement revokes the previous credential immediately, records the reason and replacement link, then issues a new random credential.
- Revocation without replacement keeps the student profile visible so an administrator can reactivate or issue a replacement later.
- Revoked cards fail both online validation and synchronized offline credential checks.

## Scheduled and verified attendance

- IT assigns every class a teacher, weekday, start time, and end time.
- Attendance opens 15 minutes before class and closes 15 minutes after class by default. IT can change both buffers per class.
- The API enforces the school-year dates, scheduled weekday, and time window. Changing the browser clock or bypassing the interface does not bypass the server check.
- Signed offline sessions contain the same schedule and are checked in the browser and again by the server during synchronization.
- Old sessions accidentally left open are finalized before a new scheduled session is created.
- Scanning a card does not immediately mark attendance. EduScan shows the registered photograph, name, section, and masked LRN; the teacher must choose **Confirm present**.
- **Wrong student** records a rejected attempt without attendance. **Flag shared card** creates a review item for IT and the principal.
- Student photographs are optional. When available, the teacher can compare the photograph before confirming; otherwise the name, section, and masked LRN are shown.
- Simulation and role-preview controls, empty report downloads, and duplicate class-creation controls have been removed from the production interface.

## Production settings

Copy `backend/.env.example` to `backend/.env` and change every deployment-specific value. At minimum:

- use PostgreSQL for shared consolidation;
- set a long random `EDUSCAN_OFFLINE_SIGNING_KEY`;
- generate the asymmetric authorization key with `.venv\Scripts\python -m app.generate_offline_key` and place its output in `.env`;
- serve both PWA and API over HTTPS and set `EDUSCAN_SECURE_COOKIES=true`;
- list only the actual PWA origin in `EDUSCAN_ALLOWED_ORIGINS`;
- create installation-specific administrator credentials and keep them out of source control.

For a consolidated Docker deployment, copy `.env.compose.example` to `.env`, replace both secrets, then run `docker compose up --build -d`. The PWA is exposed on port 8080 and routes `/api` to the FastAPI service; PostgreSQL and uploaded photographs use persistent named volumes. Put an HTTPS reverse proxy in front of it and change the origin/cookie settings before use outside a trusted local network.

Use a long PostgreSQL password containing letters, numbers, underscores, and hyphens. If other URL-reserved characters are used, percent-encode them in `EDUSCAN_DATABASE_URL`. A persistent volume is not a backup: schedule `pg_dump`, copy backups off the server, and test `pg_restore` before production use.

## Included flows

- Administrator overview, student records, class tracking, reports, and QR card views
- Teacher-controlled attendance sessions with camera access and saved-image scanning
- IndexedDB persistence for attendance scans and visible synchronization state
- Idempotent FastAPI synchronization endpoint with conflict detection
- Argon2 password hashing and revocable HTTP-only login sessions
- Server-enforced teacher, IT administrator, and principal roles
- IT-managed users, classes, teacher assignments, and enrollments
- Server-owned attendance sessions with automatic absence creation
- Duplicate protection, automatic late rules, corrections with reasons, and immutable audit records
- CSV import template/export, student creation, responsive mobile navigation, and eight QR cards per A4 sheet
- Installable PWA manifest and offline application shell
- Signed offline roster packages, compressed protected photographs, QR revocation/replacement, device registration, and login throttling
- Alembic migrations plus SQLite backup/restore tooling

## Verification

```powershell
cd backend
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest -q
```

The automated API suite uses an in-memory database and temporary photograph storage; it does not add sample students to the real system.

### SF4 monthly Excel reports

Reports → **Create SF4** uses the supplied School Form 4 workbook, including its layout, logos, and print settings. Enter school details, month, school days, and school level, then load section figures. Review the advisory teacher and grade for every section. Male/female enrollment and attendance are prefilled from synchronized records; enter verified prior cumulative and current-month dropout/transfer counts (including explicit zeros). The downloaded `.xlsx` calculates M/F/total enrollment, daily averages, attendance percentages, cumulative movement, grade summaries, and page totals. More than 15 sections produce additional worksheet pages, each with its own totals.

Student creation and the CSV template now include `sex` (`male`/`female`; imports also accept `M`/`F`). Existing records remain unknown until updated through **Students → View → Sex (for SF4) → Save sex**. Missing sex leaves SF4 counts empty for explicit correction. New students and CSV imports require sex, date of birth, and enrollment date; use the updated CSV template. Existing profiles retain missing values until completed.

Attendance uses unique learner/day present or late marks from closed sessions in Asia/Manila; multiple subjects cannot count the same learner twice on the same day. Excused marks do not count as present. Enrollment is a current active-roster snapshot, not historical month-end enrollment. Verify past-month figures and incomplete or subject-only attendance against SF2, and edit learner-days/counts as needed. Dated transfer and dropout records suggest movement figures where available. Review and complete earlier history; the system does not infer past events from an inactive flag. Report entries are used for the download and are not saved as monthly drafts.

For an existing installation, back up the database and run `python -m alembic upgrade head` from `backend` before restarting the backend. Desktop installers apply migrations on launch; rebuild the installer to include these changes and the bundled template. Existing release binaries are unchanged.


### Expanded student profiles

**Add student** requires first/last name, LRN, sex, date of birth, enrollment date, school year, and grade/section. Middle name, suffix, parent/guardian name, guardian contact number, home address, and photograph are optional. Choose **Transferred in** to record a dated transfer-in event for the selected school year. A photograph may be uploaded during creation or later through the profile. If creation succeeds but the photograph fails, the student and QR remain created; retry only the photo through the profile.

Use **Students → View → Edit student details** to complete existing profiles. Age is calculated from birth date in Asia/Manila. Editing student details preserves the QR credential. LRN remains unchanged, and administrators use the separate section control to update class assignments. Missing historical dates are left empty during migration.

Administrators use **Set inactive / Reactivate** to record the school year, effective date, status, and supporting note. Transfers out and dropouts retain dated history and suggest SF4 male/female movement figures. Withdrawal is a separate status and is not automatically counted as dropout. Repeated status submissions are rejected. Inactive students' QR credentials are revoked; reactivation requires issuing a replacement QR.

The expanded CSV template uses `first_name,middle_name,last_name,suffix,lrn,sex,date_of_birth,enrollment_date,academic_year,section,enrollment_type,guardian_name,guardian_phone,address`. Dates use `YYYY-MM-DD`; sex accepts `male`/`female` or `M`/`F`; enrollment type accepts `regular`/`transferred_in`. Required columns are first/last name, LRN, sex, birth date, enrollment date, academic year, and section. Import results show row-specific validation errors.

Contact details, address, and birth date remain in authorized staff profiles and student exports. They are excluded from QR payloads and offline scanner rosters. Dated history starts with newly recorded events; migration does not invent prior movement records.


### Government-style school workspace

The workspace uses the school logo, local system fonts, accessible navigation icons, and responsive layouts for desktop and phone screens. The overview shows synchronized attendance for the selected school year, configured classes, and recorded activity. Student forms group personal, enrollment, and optional contact details, with save controls kept visible while scrolling. SF4 calculation guidance is collapsible; all report inputs remain available.

On phones, open the navigation menu with the menu button. Close it with the close button, the backdrop, or Escape; keyboard focus stays inside the open drawer. QR printing retains eight ID-sized cards per A4 page. The browser smoke test also checks SF4 download requests, QR print sizing, login layouts, role-specific workspaces, and mobile overflow. Run it from the project root with `node test/browser/student-profiles.smoke.mjs` on Windows with Chrome installed. Test records are isolated from the local school database.

On desktop, the sidebar arrow switches between full navigation and an icons-only view. Navigation labels appear on hover or keyboard focus, and the browser remembers the choice. Phone navigation keeps its separate drawer behavior. Student create/edit/status forms, CSV imports, SF4 loading/generation, and attendance CSV downloads show progress and prevent overlapping submissions. Failed saves retain form values and show an inline error; CSV results identify skipped rows. Save notifications appear above open dialogs.

The current interface uses a green sidebar, neutral surfaces, green action accents, flatter panels, and a compact attendance overview. The device synchronization panel reads actual pending attendance from this browser. Student records support exact section and enrollment filters, name/LRN search, sortable name/LRN/section columns, and 10/25/50-row pagination; exports still include the full authorized student list. The smoke test verifies filtering, sorting, page boundaries, saved sidebar preferences, error recovery, and duplicate-submission protection. Design references: [Singapore Government Design System](https://designsystem.tech.gov.sg/), [U.S. Web Design System tables](https://designsystem.digital.gov/components/table/), and [GOV.UK components](https://design-system.service.gov.uk/components/).
