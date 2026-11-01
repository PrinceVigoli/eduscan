from datetime import date, datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import AcademicYearState, AttendanceStatus, SessionStatus, UserRole


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=200)


class UserCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=10, max_length=200)
    role: UserRole


class UserView(BaseModel):
    id: UUID
    full_name: str
    email: str
    role: UserRole


class ClassCreate(BaseModel):
    subject: str = Field(min_length=1, max_length=120)
    section: str = Field(min_length=1, max_length=120)
    school_year: str = Field(min_length=4, max_length=20)
    schedule_label: str = Field(min_length=1, max_length=120)
    weekday: int = Field(ge=0, le=6)
    start_time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    end_time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    teacher_id: UUID | None = None


class AcademicYearCreate(BaseModel):
    name: str = Field(pattern=r"^\d{4}-\d{4}$")
    starts_on: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    ends_on: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class AcademicYearTransition(BaseModel):
    state: AcademicYearState
    confirmation: str | None = None
    backup_reference: str | None = Field(default=None, max_length=300)


class QRReplacementRequest(BaseModel):
    reason: str = Field(pattern=r"^(lost|damaged|compromised|administrative)$")


class StudentStatusUpdate(BaseModel):
    is_active: bool
    reason: str | None = Field(default=None, pattern=r"^(graduated|transferred|dropped_out|withdrawn|administrative)$")
    effective_on: date
    academic_year: str = Field(pattern=r"^\d{4}-\d{4}$")
    reason_note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_status(self):
        if self.effective_on > datetime.now(ZoneInfo("Asia/Manila")).date():
            raise ValueError("Status date cannot be in the future")
        if not self.is_active and not self.reason:
            raise ValueError("Select an inactive reason")
        if not self.is_active and not (self.reason_note or "").strip():
            raise ValueError("Provide a reason or supporting note")
        return self


class ClassView(ClassCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    weekday: int | None = None
    start_time: str | None = None
    end_time: str | None = None


class EnrollmentCreate(BaseModel):
    student_id: UUID


class StudentSectionUpdate(BaseModel):
    section: str = Field(min_length=1, max_length=120)

    @field_validator("section")
    @classmethod
    def trim_section(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Section cannot be blank")
        return value


class PromotionDecision(BaseModel):
    student_id: UUID
    action: str = Field(pattern=r"^(promoted|retained|graduated|transferred|withdrawn)$")
    target_section: str | None = Field(default=None, max_length=120)


class PromotionApply(BaseModel):
    target_year_id: UUID
    decisions: list[PromotionDecision] = Field(min_length=1, max_length=2000)


class AttendanceSessionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    class_id: UUID
    status: SessionStatus
    opened_at: datetime


class AttendanceSyncRecord(BaseModel):
    record_id: UUID
    session_id: UUID
    student_lrn: str = Field(min_length=6, max_length=32)
    status: AttendanceStatus
    scanned_at: datetime
    credential: UUID | None = None
    offline_authorization: dict | None = None
    offline_opened_at: datetime | None = None


class OfflineSessionClosure(BaseModel):
    session_id: UUID
    offline_authorization: dict
    offline_opened_at: datetime


class VerificationAttemptInput(BaseModel):
    attempt_id: UUID
    session_id: UUID
    student_lrn: str | None = Field(default=None, max_length=32)
    credential: UUID | None = None
    action: str = Field(pattern=r"^(rejected|flagged)$")
    reason: str = Field(min_length=3, max_length=300)
    occurred_at: datetime


class AttendanceSyncBatch(BaseModel):
    device_id: UUID
    records: list[AttendanceSyncRecord] = Field(max_length=500)
    session_closures: list[OfflineSessionClosure] = Field(default_factory=list, max_length=100)
    verification_attempts: list[VerificationAttemptInput] = Field(default_factory=list, max_length=500)


class SyncConflict(BaseModel):
    record_id: UUID
    reason: str


class AttendanceSyncResult(BaseModel):
    accepted_record_ids: list[UUID]
    duplicate_record_ids: list[UUID]
    conflicts: list[SyncConflict]
    server_time: datetime
    closed_session_ids: list[UUID] = Field(default_factory=list)
    accepted_attempt_ids: list[UUID] = Field(default_factory=list)


class StudentProfileUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    middle_name: str | None = Field(default=None, max_length=80)
    suffix: str | None = Field(default=None, max_length=20)
    sex: Literal["male", "female"]
    date_of_birth: date
    enrollment_date: date
    guardian_name: str | None = Field(default=None, max_length=160)
    guardian_phone: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=500)

    @field_validator("middle_name", "suffix", "guardian_name", "guardian_phone", "address", mode="before")
    @classmethod
    def optional_text(cls, value):
        return (value.strip() or None) if isinstance(value, str) else value

    @field_validator("guardian_phone")
    @classmethod
    def validate_phone(cls, value):
        if value:
            import re
            if not re.fullmatch(r"\+?[0-9 ()-]+", value) or not 7 <= len(re.sub(r"\D", "", value)) <= 15:
                raise ValueError("Use a contact number with 7–15 digits; spaces, +, parentheses and hyphens are allowed")
        return value

    @model_validator(mode="after")
    def validate_dates(self):
        today = datetime.now(ZoneInfo("Asia/Manila")).date()
        if self.date_of_birth >= today:
            raise ValueError("Date of birth must be before today")
        if self.enrollment_date > today:
            raise ValueError("Enrollment date cannot be in the future")
        if self.date_of_birth >= self.enrollment_date:
            raise ValueError("Date of birth must be before enrollment date")
        return self


class StudentCreate(StudentProfileUpdate):
    lrn: str = Field(min_length=6, max_length=32)
    section: str = Field(min_length=1, max_length=120)
    enrollment_type: Literal["regular", "transferred_in"] = "regular"
    academic_year: str | None = Field(default=None, pattern=r"^\d{4}-\d{4}$")
    created_by: UUID | None = None

    @model_validator(mode="after")
    def transfer_year(self):
        if self.enrollment_type == "transferred_in" and not self.academic_year:
            raise ValueError("Select the school year for a transferred-in learner")
        return self

    @field_validator("sex", mode="before")
    @classmethod
    def normalize_sex(cls, value):
        if isinstance(value, str):
            return {"m": "male", "f": "female", "": None}.get(value.strip().lower(), value.strip().lower())
        return value

    @field_validator("first_name", "last_name", "section")
    @classmethod
    def trim_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Value cannot be blank")
        return value

    @field_validator("lrn")
    @classmethod
    def validate_lrn(cls, value: str) -> str:
        value = value.strip()
        if not value.isdigit():
            raise ValueError("LRN must contain digits only")
        return value


class StudentCreated(BaseModel):
    id: UUID
    first_name: str
    last_name: str
    full_name: str
    lrn: str
    section: str
    sex: Literal["male", "female"] | None = None
    middle_name: str | None = None
    suffix: str | None = None
    date_of_birth: date | None = None
    age: int | None = None
    enrollment_date: date | None = None
    enrollment_type: str = "regular"
    guardian_name: str | None = None
    guardian_phone: str | None = None
    address: str | None = None
    credential_id: UUID | None
    qr_download_url: str | None
    qr_status: str = "active"
    qr_revocation_reason: str | None = None
    is_active: bool = True
    inactive_reason: str | None = None
    photograph_url: str | None = None


class QRValidationRequest(BaseModel):
    payload: str = Field(min_length=10, max_length=200)
    session_id: UUID


class QRValidationResult(BaseModel):
    valid: bool
    student_id: UUID
    full_name: str
    lrn: str
    section: str
    photograph_url: str | None = None


class ClassPolicyUpdate(BaseModel):
    grace_minutes: int = Field(default=10, ge=0, le=60)
    offline_package_hours: int = Field(default=72, ge=1, le=168)
    open_before_minutes: int = Field(default=15, ge=0, le=60)
    close_after_minutes: int = Field(default=15, ge=0, le=120)


class AttendanceAdjustmentCreate(BaseModel):
    status: AttendanceStatus
    reason: str = Field(min_length=5, max_length=1000)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=8, max_length=200)
    new_password: str = Field(min_length=10, max_length=200)


class DeviceRegister(BaseModel):
    device_uuid: UUID
    label: str = Field(default="Teacher device", min_length=1, max_length=120)


class StudentSexUpdate(BaseModel):
    sex: Literal["male", "female"]


class SF4Pair(BaseModel):
    male: int = Field(ge=0, le=100000)
    female: int = Field(ge=0, le=100000)


class SF4Row(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    section: str = Field(min_length=1, max_length=120)
    adviser: str = Field(min_length=1, max_length=160)
    grade: Literal["K", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "NG"]
    registered: SF4Pair
    # Learner-days, before dividing by the number of school days.
    attendance: SF4Pair
    dropout_previous: SF4Pair
    dropout_month: SF4Pair
    transfer_out_previous: SF4Pair
    transfer_out_month: SF4Pair
    transfer_in_previous: SF4Pair
    transfer_in_month: SF4Pair


class SF4Create(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    school_name: str = Field(min_length=1, max_length=160)
    school_id: str = Field(pattern=r"^\d{6}$")
    region: str = Field(min_length=1, max_length=80)
    division: str = Field(min_length=1, max_length=120)
    district: str = Field(min_length=1, max_length=120)
    school_head: str = Field(min_length=1, max_length=160)
    academic_year: str = Field(pattern=r"^\d{4}-\d{4}$")
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    school_days: int = Field(ge=1, le=31)
    school_level: Literal["elementary", "secondary"] = "secondary"
    rows: list[SF4Row] = Field(min_length=1, max_length=300)

    @field_validator("month")
    @classmethod
    def valid_month(cls, value: str) -> str:
        date.fromisoformat(value + "-01")
        return value

    @model_validator(mode="after")
    def validate_figures(self):
        from calendar import monthrange
        year, month = map(int, self.month.split("-"))
        if self.school_days > monthrange(year, month)[1]:
            raise ValueError("School days exceed the number of days in this month")
        grades = {"K", "1", "2", "3", "4", "5", "6", "NG"} if self.school_level == "elementary" else {"7", "8", "9", "10", "11", "12", "NG"}
        sections = set()
        for row in self.rows:
            section_key = " ".join(row.section.split()).casefold()
            if section_key in sections:
                raise ValueError("Include each section only once")
            sections.add(section_key)
            if row.grade not in grades:
                raise ValueError("Grade must match the selected school level")
            for sex in ("male", "female"):
                if getattr(row.attendance, sex) > getattr(row.registered, sex) * self.school_days:
                    raise ValueError("Attendance learner-days exceed registered learners × school days; verify the figures")
        return self
