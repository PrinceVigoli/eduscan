# EduScan architecture

EduScan is an offline-first teacher system. Classroom work is local; the server synchronizes and consolidates shared records.

## Components

1. **Teacher PWA** caches its application shell with a service worker.
2. **IndexedDB** holds assigned rosters, optimized photographs, QR validation data, sessions, and pending attendance.
3. **Synchronization API** accepts idempotent batches when connectivity returns.
4. **PostgreSQL** is the authoritative consolidated database.
5. **Administrative reporting** reads only consolidated server records.

## Synchronization contract

Every locally created record has a device-generated UUID. Re-uploading the same UUID is safe. A second record for the same student and session is retained as a conflict rather than silently overwriting the first record.

Client states are `pending`, `syncing`, `synced`, `failed`, and `conflict`.

## Trust boundaries

- The device provides uninterrupted classroom operation.
- The server revalidates identity, authorization, enrollment, session, and QR status.
- The server is authoritative after consolidation.
- QR cards contain random revocable credentials, never names or LRNs.

## Roles

| Role | Primary responsibility | Dashboard |
|---|---|---|
| Teacher | Own class rosters, photographs, QR distribution, and attendance | Assigned classes, pending scans, roster actions, sync status |
| IT administrator | Accounts, academic structure, devices, credentials, backups, and technical audit | System health, users, unresolved conflicts, QR revocations, backup status |
| Principal | Read-only consolidated attendance oversight | School-wide attendance, exceptions, trends, and signed exports |

Authorization is enforced by the API using revocable HTTP-only sessions. Teachers are restricted to assigned classes, IT administrators manage academic setup, and principals are read-only. Hiding a navigation item is only a user-interface convenience and is never the security boundary.

## Delivery model

The PWA is the canonical client and is installable from a browser on Android, iOS, and desktop. A later Windows `.exe` may wrap the same PWA using Tauri for IT administrators and the principal. The wrapper must not contain separate business logic or a separate database format.

Teachers primarily use the PWA because QR scanning requires phone-camera support. Windows installation is optional rather than mandatory.

## QR issuance

Creating a student creates a cryptographically random credential in the same server transaction. The QR contains only the credential—not the student's name or LRN. The API returns an authenticated download URL for an SVG/PNG card. Credentials can be revoked and replaced without changing the student record.

## Current milestone

The current system authenticates each role, creates server-owned classes and attendance sessions, validates enrollment, persists scans in IndexedDB, and queues them for `/api/v1/sync/attendance`. The API implements UUID idempotency, teacher/class authorization, conflict detection, and automatic absences on session close. Signed offline roster packages and photographs are subsequent milestones.
