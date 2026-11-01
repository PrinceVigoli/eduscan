from uuid import UUID, uuid4
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.config import settings
from app.main import app
from app.models import AttendanceRecord, AttendanceStatus, QRCredential, Student, User, UserRole
from app.security import hash_password


test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)


def override_get_db():
    with TestingSessionLocal() as db:
        yield db


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    original_upload_dir = settings.upload_dir
    original_auto_create_schema = settings.auto_create_schema
    settings.upload_dir = str(tmp_path_factory.mktemp("eduscan-test-uploads"))
    settings.auto_create_schema = False
    Base.metadata.create_all(bind=test_engine)
    with TestingSessionLocal() as db:
        teacher = User(full_name="Test Teacher", email="teacher@eduscan.test", role=UserRole.teacher, password_hash=hash_password("TeacherPass123"))
        admin = User(full_name="Test Admin", email="admin@eduscan.test", role=UserRole.administrator, password_hash=hash_password("AdminPass123"))
        principal = User(full_name="Test Principal", email="principal@eduscan.test", role=UserRole.principal, password_hash=hash_password("PrincipalPass123"))
        db.add_all([teacher, admin, principal])
        db.commit()
        teacher_id = teacher.id
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client, teacher_id
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)
    settings.upload_dir = original_upload_dir
    settings.auto_create_schema = original_auto_create_schema


def login(client, email, password):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def test_health_and_authentication_boundary(api):
    client, _ = api
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/students").status_code == 401
    assert login(client, "admin@eduscan.test", "wrong-password").status_code == 401
    signed_in = login(client, "admin@eduscan.test", "AdminPass123")
    assert signed_in.status_code == 200
    assert signed_in.json()["role"] == "administrator"


def test_principal_is_read_only(api):
    client, _ = api
    client.post("/api/v1/auth/logout")
    assert login(client, "principal@eduscan.test", "PrincipalPass123").status_code == 200
    denied = client.post("/api/v1/students", json={"first_name": "No", "last_name": "Write", "lrn": "123456789012", "section": "10-Rizal"})
    assert denied.status_code == 403


def test_authorized_class_attendance_vertical_slice(api, monkeypatch):
    # Exercise lateness consistently, including runs during the midnight grace period.
    fixed_now = datetime.now(ZoneInfo("Asia/Manila")).replace(hour=12, minute=0, second=0, microsecond=0)

    class TestDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now.astimezone(tz) if tz else fixed_now.replace(tzinfo=None)

    monkeypatch.setattr("app.main.datetime", TestDateTime)
    monkeypatch.setattr(__name__ + ".datetime", TestDateTime)
    client, teacher_id = api
    client.post("/api/v1/auth/logout")
    assert login(client, "admin@eduscan.test", "AdminPass123").status_code == 200
    lrn = str(uuid4().int)[:12]
    created = client.post("/api/v1/students", json={"first_name": "Maria", "last_name": "Luna", "lrn": lrn, "section": "Grade 10 · Rizal", "sex": "female", "date_of_birth": "2010-05-12", "enrollment_date": "2026-06-01"})
    assert created.status_code == 201
    student_id = created.json()["id"]
    assert client.get(created.json()["qr_download_url"]).status_code == 200
    year_response = client.post("/api/v1/academic-years", json={"name": "2026-2027"})
    assert year_response.status_code == 201
    year_id = year_response.json()["id"]
    assert client.post(f"/api/v1/academic-years/{year_id}/transition", json={"state": "active"}).status_code == 200
    local_now = datetime.now(ZoneInfo("Asia/Manila"))
    day_name = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")[local_now.weekday()]
    class_response = client.post("/api/v1/classes", json={"subject": "Mathematics", "section": "Grade 10 · Rizal", "school_year": "2026-2027", "schedule_label": f"{day_name} 00:00-23:59", "weekday": local_now.weekday(), "start_time": "00:00", "end_time": "23:59", "teacher_id": str(teacher_id)})
    assert class_response.status_code == 201
    class_id = class_response.json()["id"]
    unavailable_class = client.post("/api/v1/classes", json={"subject": "Science", "section": "Grade 10 · Rizal", "school_year": "2026-2027", "schedule_label": "Another day 00:00-23:59", "weekday": (local_now.weekday() + 1) % 7, "start_time": "00:00", "end_time": "23:59", "teacher_id": str(teacher_id)})
    assert unavailable_class.status_code == 201
    unavailable_class_id = unavailable_class.json()["id"]
    roster = client.get(f"/api/v1/classes/{class_id}/roster")
    assert roster.status_code == 200
    assert [student["id"] for student in roster.json()] == [student_id]
    class_payload = {"subject": "Mathematics", "section": "  Grade 10 � Rizal  ", "school_year": "2026-2027", "schedule_label": f"{day_name} 00:00-23:59", "weekday": local_now.weekday(), "start_time": "00:00", "end_time": "23:59", "teacher_id": str(teacher_id)}
    updated_class = client.put(f"/api/v1/classes/{class_id}", json=class_payload)
    assert updated_class.status_code == 200
    assert updated_class.json()["section"] == "Grade 10 � Rizal"
    # Creating a class automatically imports active students from its matching section.
    assert client.post(f"/api/v1/classes/{class_id}/enrollments", json={"student_id": student_id}).status_code == 409
    client.post("/api/v1/auth/logout")
    assert login(client, "teacher@eduscan.test", "TeacherPass123").status_code == 200
    device_id = str(uuid4())
    assert client.post("/api/v1/devices", json={"device_uuid": device_id, "label": "Test browser"}).status_code == 200
    assert {item["id"] for item in client.get("/api/v1/classes").json()} == {class_id, unavailable_class_id}
    assert client.post(f"/api/v1/classes/{unavailable_class_id}/sessions").status_code == 403
    session_response = client.post(f"/api/v1/classes/{class_id}/sessions")
    assert session_response.status_code == 201
    session_id = session_response.json()["id"]
    offline_package = client.get(f"/api/v1/classes/{class_id}/offline-package?device_id={device_id}")
    assert offline_package.status_code == 200
    assert offline_package.json()["payload"]["roster"][0]["photograph"] is None
    assert offline_package.json()["authorization"]["payload"]["device_id"] == device_id
    with TestingSessionLocal() as db:
        student = db.scalar(select(Student).where(Student.lrn == lrn))
        credential = db.scalar(select(QRCredential).where(QRCredential.student_id == student.id))
        qr_payload = f"EDUSCAN:{credential.credential}"
    assert client.post("/api/v1/qr-credentials/validate", json={"payload": qr_payload, "session_id": session_id}).status_code == 200
    record_id = str(uuid4())
    attempt_id = str(uuid4())
    batch = {"device_id": str(uuid4()), "records": [{"record_id": record_id, "session_id": session_id, "student_lrn": lrn, "status": "present", "scanned_at": datetime.now(timezone.utc).isoformat(), "credential": str(credential.credential)}], "verification_attempts": [{"attempt_id": attempt_id, "session_id": session_id, "student_lrn": lrn, "credential": str(credential.credential), "action": "flagged", "reason": "Teacher suspects a shared card", "occurred_at": datetime.now(timezone.utc).isoformat()}]}
    first = client.post("/api/v1/sync/attendance", json=batch)
    second = client.post("/api/v1/sync/attendance", json=batch)
    assert first.json()["accepted_record_ids"] == [record_id]
    assert first.json()["accepted_attempt_ids"] == [attempt_id]
    assert second.json()["duplicate_record_ids"] == [record_id]
    with TestingSessionLocal() as db:
        # The class starts at midnight, so lateness is based on its schedule—not when the teacher clicked Start.
        assert db.get(AttendanceRecord, UUID(record_id)).status == AttendanceStatus.late
    adjusted = client.post(f"/api/v1/attendance-records/{record_id}/adjustments", json={"status": "excused", "reason": "Approved medical documentation"})
    assert adjusted.status_code == 200
    summary = client.get("/api/v1/reports/attendance-summary").json()
    assert summary["counts"]["excused"] == 1
    closed = client.post(f"/api/v1/attendance-sessions/{session_id}/close")
    assert closed.status_code == 200
    assert closed.json()["absences_created"] == 0
    offline_session_id = str(uuid4())
    offline_record_id = str(uuid4())
    offline_opened_at = datetime.now(timezone.utc).isoformat()
    offline_sync = client.post("/api/v1/sync/attendance", json={"device_id": device_id, "records": [{"record_id": offline_record_id, "session_id": offline_session_id, "student_lrn": lrn, "status": "present", "scanned_at": offline_opened_at, "credential": str(credential.credential), "offline_authorization": offline_package.json()["authorization"], "offline_opened_at": offline_opened_at}], "session_closures": [{"session_id": offline_session_id, "offline_authorization": offline_package.json()["authorization"], "offline_opened_at": offline_opened_at}]})
    assert offline_sync.status_code == 200
    assert offline_sync.json()["accepted_record_ids"] == [offline_record_id]
    assert offline_sync.json()["closed_session_ids"] == [offline_session_id]
    replacement = client.post(f"/api/v1/students/{student_id}/qr-credential/replace", json={"reason": "lost"})
    assert replacement.status_code == 200
    assert replacement.json()["credential_id"] != created.json()["credential_id"]
    assert client.post(f"/api/v1/students/{student_id}/qr-credential/revoke", json={"reason": "compromised"}).status_code == 200
    revoked_student = next(item for item in client.get("/api/v1/students").json() if item["id"] == student_id)
    assert revoked_student["qr_status"] == "revoked"
    assert revoked_student["qr_revocation_reason"] == "compromised"
    client.post("/api/v1/auth/logout")
    assert login(client, "admin@eduscan.test", "AdminPass123").status_code == 200
    target_year = client.post("/api/v1/academic-years", json={"name": "2027-2028"})
    assert target_year.status_code == 201
    assert client.post(f"/api/v1/academic-years/{year_id}/transition", json={"state": "closing"}).status_code == 200
    client.post("/api/v1/auth/logout")
    assert login(client, "principal@eduscan.test", "PrincipalPass123").status_code == 200
    assert client.post(f"/api/v1/academic-years/{year_id}/approve-closing").status_code == 204
    client.post("/api/v1/auth/logout")
    assert login(client, "admin@eduscan.test", "AdminPass123").status_code == 200
    preview = client.get(f"/api/v1/academic-years/{year_id}/promotion-preview")
    assert preview.status_code == 200
    decision = preview.json()["students"][0]
    promotion = client.post(f"/api/v1/academic-years/{year_id}/promotions", json={"target_year_id": target_year.json()["id"], "decisions": [{"student_id": decision["student_id"], "action": decision["suggested_action"], "target_section": decision["suggested_section"]}]})
    assert promotion.status_code == 200
    assert promotion.json()["processed"] == 1
    assert client.post(f"/api/v1/academic-years/{year_id}/transition", json={"state": "archived", "confirmation": "ARCHIVE 2026-2027", "backup_reference": "test-backup.zip"}).status_code == 200
    inactive = client.put(f"/api/v1/students/{student_id}/status", json={"is_active": False, "reason": "graduated", "effective_on": datetime.now(ZoneInfo("Asia/Manila")).date().isoformat(), "academic_year": "2027-2028", "reason_note": "Completed school records review"})
    assert inactive.status_code == 200
    assert inactive.json()["inactive_reason"] == "graduated"
