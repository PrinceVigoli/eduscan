import enum
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AttendanceStatus(str, enum.Enum):
    present = "present"
    late = "late"
    absent = "absent"
    excused = "excused"


class UserRole(str, enum.Enum):
    teacher = "teacher"
    administrator = "administrator"
    principal = "principal"


class AcademicYearState(str, enum.Enum):
    planning = "planning"
    active = "active"
    closing = "closing"
    archived = "archived"


class AcademicYear(Base):
    __tablename__ = "academic_years"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    state: Mapped[AcademicYearState] = mapped_column(Enum(AcademicYearState), default=AcademicYearState.planning, index=True)
    starts_on: Mapped[str | None] = mapped_column(String(10), nullable=True)
    ends_on: Mapped[str | None] = mapped_column(String(10), nullable=True)
    principal_approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    principal_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    full_name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Student(Base):
    __tablename__ = "students"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    lrn: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80))
    section: Mapped[str] = mapped_column(String(120), index=True)
    sex: Mapped[str | None] = mapped_column(String(6), nullable=True)
    middle_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    suffix: Mapped[str | None] = mapped_column(String(20), nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    enrollment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    enrollment_type: Mapped[str] = mapped_column(String(20), default="regular", server_default="regular")
    guardian_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    guardian_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    photograph_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    is_active: Mapped[bool] = mapped_column(default=True, index=True)
    inactive_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)


class StudentMovement(Base):
    __tablename__ = "student_movements"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("students.id"), index=True)
    school_year: Mapped[str] = mapped_column(String(20), index=True)
    section: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(30))
    effective_on: Mapped[date] = mapped_column(Date)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="status")
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QRCredential(Base):
    __tablename__ = "qr_credentials"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(index=True)
    credential: Mapped[uuid.UUID] = mapped_column(unique=True, index=True, default=uuid.uuid4)
    is_revoked: Mapped[bool] = mapped_column(default=False, index=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    replacement_credential_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)


class ClassOffering(Base):
    __tablename__ = "class_offerings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    subject: Mapped[str] = mapped_column(String(120))
    section: Mapped[str] = mapped_column(String(120), index=True)
    school_year: Mapped[str] = mapped_column(String(20), index=True)
    academic_year_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("academic_years.id"), nullable=True, index=True)
    schedule_label: Mapped[str] = mapped_column(String(120))
    weekday: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    start_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    end_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    teacher_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(default=True, index=True)


class Enrollment(Base):
    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("class_id", "student_id", name="uq_class_student"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    class_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("class_offerings.id"), index=True)
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("students.id"), index=True)
    enrolled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StudentPromotion(Base):
    __tablename__ = "student_promotions"
    __table_args__ = (UniqueConstraint("source_year_id", "student_id", name="uq_promotion_source_student"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_year_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("academic_years.id"), index=True)
    target_year_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("academic_years.id"), index=True)
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("students.id"), index=True)
    action: Mapped[str] = mapped_column(String(20), index=True)
    from_section: Mapped[str] = mapped_column(String(120))
    to_section: Mapped[str | None] = mapped_column(String(120), nullable=True)
    applied_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SessionStatus(str, enum.Enum):
    open = "open"
    closed = "closed"


class AttendanceSession(Base):
    __tablename__ = "attendance_sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    class_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("class_offerings.id"), index=True)
    teacher_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[SessionStatus] = mapped_column(Enum(SessionStatus), default=SessionStatus.open, index=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    opened_offline: Mapped[bool] = mapped_column(default=False)
    authorization_permit_id: Mapped[uuid.UUID | None] = mapped_column(unique=True, nullable=True, index=True)
    device_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)


class OfflineAuthorizationPermit(Base):
    __tablename__ = "offline_authorization_permits"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    teacher_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    class_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("class_offerings.id"), index=True)
    device_id: Mapped[uuid.UUID] = mapped_column(index=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    not_before: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    used_session_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, unique=True)


class ClassPolicy(Base):
    __tablename__ = "class_policies"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    class_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("class_offerings.id"), unique=True, index=True)
    grace_minutes: Mapped[int] = mapped_column(Integer, default=10)
    offline_package_hours: Mapped[int] = mapped_column(Integer, default=72)
    open_before_minutes: Mapped[int] = mapped_column(Integer, default=15)
    close_after_minutes: Mapped[int] = mapped_column(Integer, default=15)


class VerificationAttempt(Base):
    __tablename__ = "verification_attempts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("attendance_sessions.id"), index=True)
    teacher_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    device_id: Mapped[uuid.UUID] = mapped_column(index=True)
    student_lrn: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    credential: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    action: Mapped[str] = mapped_column(String(20), index=True)
    reason: Mapped[str] = mapped_column(String(300))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AttendanceAdjustment(Base):
    __tablename__ = "attendance_adjustments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    attendance_record_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("attendance_records.id"), index=True)
    changed_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    old_status: Mapped[AttendanceStatus] = mapped_column(Enum(AttendanceStatus))
    new_status: Mapped[AttendanceStatus] = mapped_column(Enum(AttendanceStatus))
    reason: Mapped[str] = mapped_column(Text)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str] = mapped_column(String(80), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class DeviceRegistration(Base):
    __tablename__ = "device_registrations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    device_uuid: Mapped[uuid.UUID] = mapped_column(unique=True, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    label: Mapped[str] = mapped_column(String(120), default="Teacher device")
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"
    __table_args__ = (
        UniqueConstraint("session_id", "student_lrn", name="uq_session_student"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    session_id: Mapped[uuid.UUID] = mapped_column(index=True)
    student_lrn: Mapped[str] = mapped_column(String(32), index=True)
    device_id: Mapped[uuid.UUID] = mapped_column(index=True)
    status: Mapped[AttendanceStatus] = mapped_column(Enum(AttendanceStatus))
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    source: Mapped[str] = mapped_column(String(16), default="offline")
