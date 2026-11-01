from contextlib import asynccontextmanager
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from io import BytesIO
import json
from pathlib import Path
import re
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import qrcode
import qrcode.image.svg
from fastapi import Cookie, Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import settings
from .database import Base, engine, get_db
from .audit import write_audit
from .models import AcademicYear, AcademicYearState, AttendanceAdjustment, AttendanceRecord, AttendanceSession, AttendanceStatus, AuditLog, AuthSession, ClassOffering, ClassPolicy, DeviceRegistration, Enrollment, OfflineAuthorizationPermit, QRCredential, SessionStatus, Student, StudentMovement, StudentPromotion, User, UserRole, VerificationAttempt
from .offline_auth import public_jwk, sign as sign_offline_permit, verify as verify_offline_permit
from .schemas import AcademicYearCreate, AcademicYearTransition, AttendanceAdjustmentCreate, AttendanceSessionView, AttendanceSyncBatch, AttendanceSyncResult, ClassCreate, ClassPolicyUpdate, ClassView, DeviceRegister, EnrollmentCreate, LoginRequest, PasswordChange, PromotionApply, QRReplacementRequest, QRValidationRequest, QRValidationResult, StudentCreate, StudentCreated, StudentSectionUpdate, StudentStatusUpdate, SyncConflict, UserCreate, UserView
from .security import SESSION_COOKIE, create_session, get_current_user, hash_password, require_roles, token_digest, verify_password
from .schemas import SF4Create, StudentSexUpdate, StudentProfileUpdate
from .sf4 import build_sf4


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.auto_create_schema:
        Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)

login_failures: dict[str, list[datetime]] = {}
SCHOOL_TZ = ZoneInfo("Asia/Manila")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    # The desktop bootstrap form is protected by its own random, one-time token.
    # Browsers can report differing loopback origins (localhost vs 127.0.0.1),
    # so applying the normal Origin allow-list here would prevent first setup.
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.url.path != "/desktop/setup":
        origin = request.headers.get("origin")
        if origin and origin not in settings.origins:
            return Response(content='{"detail":"Untrusted request origin"}', status_code=403, media_type="application/json")
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(self), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data: http://localhost:8000; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self' http://localhost:8000"
    return response


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "eduscan-api"}


@app.get("/api/v1/offline-authorization/public-key")
def offline_authorization_public_key(_: User = Depends(get_current_user)):
    return public_jwk()


def user_view(user: User) -> UserView:
    return UserView(id=user.id, full_name=user.full_name, email=user.email, role=user.role)


def photograph_url(student: Student) -> str | None:
    return f"/api/v1/students/{student.id}/photograph" if student.photograph_path else None


def student_full_name(student: Student) -> str:
    return " ".join(part for part in (student.first_name, student.middle_name, student.last_name, student.suffix) if part)


def student_profile_details(student: Student) -> dict:
    today = datetime.now(SCHOOL_TZ).date()
    born = student.date_of_birth
    return {"middle_name": student.middle_name, "suffix": student.suffix, "date_of_birth": born,
            "age": today.year - born.year - ((today.month, today.day) < (born.month, born.day)) if born else None,
            "enrollment_date": student.enrollment_date, "enrollment_type": student.enrollment_type,
            "guardian_name": student.guardian_name, "guardian_phone": student.guardian_phone, "address": student.address}


def normalized_section(value: str) -> str:
    return " ".join(value.split()).casefold()


def scheduled_start(class_item: ClassOffering, moment: datetime) -> datetime:
    local = moment.astimezone(SCHOOL_TZ)
    start_hour, start_minute = map(int, class_item.start_time.split(":"))
    return local.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)


def proposed_promotion(section: str) -> tuple[str, str | None]:
    match = re.search(r"(?i)\bgrade\s*(7|8|9|10|11|12)\b", section)
    if not match:
        return "retained", section
    grade = int(match.group(1))
    if grade == 12:
        return "graduated", None
    promoted = section[:match.start(1)] + str(grade + 1) + section[match.end(1):]
    return "promoted", promoted


def promotion_students(year_id: UUID, db: Session) -> list[Student]:
    class_ids = select(ClassOffering.id).where(ClassOffering.academic_year_id == year_id)
    return list(db.scalars(select(Student).join(Enrollment, Enrollment.student_id == Student.id).where(Enrollment.class_id.in_(class_ids)).distinct().order_by(Student.last_name, Student.first_name)))


def class_academic_year(class_item: ClassOffering, db: Session) -> AcademicYear | None:
    return db.get(AcademicYear, class_item.academic_year_id) if class_item.academic_year_id else db.scalar(select(AcademicYear).where(AcademicYear.name == class_item.school_year))


def require_year_state(class_item: ClassOffering, db: Session, allowed: set[AcademicYearState]) -> AcademicYear:
    year = class_academic_year(class_item, db)
    if not year or year.state not in allowed:
        raise HTTPException(status_code=409, detail="The academic year does not allow this operation")
    return year


def class_schedule_window(class_item: ClassOffering, db: Session, moment: datetime | None = None) -> tuple[datetime, datetime]:
    if class_item.weekday is None or not class_item.start_time or not class_item.end_time:
        raise HTTPException(status_code=409, detail="This class needs a complete attendance schedule")
    local = (moment or datetime.now(timezone.utc)).astimezone(SCHOOL_TZ)
    year = class_academic_year(class_item, db)
    local_date = local.date().isoformat()
    if year and ((year.starts_on and local_date < year.starts_on) or (year.ends_on and local_date > year.ends_on)):
        raise HTTPException(status_code=403, detail="Attendance is outside this school year's dates")
    if local.weekday() != class_item.weekday:
        raise HTTPException(status_code=403, detail="Attendance is only available on this class's scheduled day")
    start_hour, start_minute = map(int, class_item.start_time.split(":"))
    end_hour, end_minute = map(int, class_item.end_time.split(":"))
    scheduled_start = local.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
    scheduled_end = local.replace(hour=end_hour, minute=end_minute, second=0, microsecond=0)
    policy = db.scalar(select(ClassPolicy).where(ClassPolicy.class_id == class_item.id))
    opens_at = scheduled_start - timedelta(minutes=policy.open_before_minutes if policy else 15)
    closes_at = scheduled_end + timedelta(minutes=policy.close_after_minutes if policy else 15)
    if not opens_at <= local <= closes_at:
        raise HTTPException(status_code=403, detail=f"Attendance is available from {opens_at.strftime('%I:%M %p')} to {closes_at.strftime('%I:%M %p')}")
    return opens_at, closes_at


@app.post("/api/v1/academic-years", status_code=201)
def create_academic_year(payload: AcademicYearCreate, user: User = Depends(require_roles(UserRole.administrator)), db: Session = Depends(get_db)):
    if db.scalar(select(AcademicYear).where(AcademicYear.name == payload.name)):
        raise HTTPException(status_code=409, detail="Academic year already exists")
    start_year, end_year = map(int, payload.name.split("-"))
    if end_year != start_year + 1:
        raise HTTPException(status_code=422, detail="Academic year must contain consecutive years")
    year = AcademicYear(**payload.model_dump())
    db.add(year); db.flush(); write_audit(db, user, "academic_year.create", "academic_year", year.id, {"name": year.name}); db.commit(); db.refresh(year)
    return {"id": year.id, "name": year.name, "state": year.state, "starts_on": year.starts_on, "ends_on": year.ends_on, "principal_approved_at": year.principal_approved_at}


@app.get("/api/v1/academic-years")
def list_academic_years(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    years = list(db.scalars(select(AcademicYear).order_by(AcademicYear.name.desc())))
    return [{"id": year.id, "name": year.name, "state": year.state, "starts_on": year.starts_on, "ends_on": year.ends_on, "principal_approved_at": year.principal_approved_at, "archived_at": year.archived_at} for year in years]


@app.get("/api/v1/academic-years/{year_id}/promotion-preview")
def promotion_preview(year_id: UUID, _: User = Depends(require_roles(UserRole.administrator)), db: Session = Depends(get_db)):
    source = db.get(AcademicYear, year_id)
    if not source or source.state != AcademicYearState.closing or not source.principal_approved_at:
        raise HTTPException(status_code=409, detail="The school year must be closing and approved by the principal")
    processed = set(db.scalars(select(StudentPromotion.student_id).where(StudentPromotion.source_year_id == source.id)))
    rows = []
    for student in promotion_students(source.id, db):
        action, target_section = proposed_promotion(student.section)
        rows.append({"student_id": student.id, "full_name": student_full_name(student), "lrn_suffix": student.lrn[-4:], "current_section": student.section, "suggested_action": action, "suggested_section": target_section, "already_processed": student.id in processed})
    targets = list(db.scalars(select(AcademicYear).where(AcademicYear.state == AcademicYearState.planning).order_by(AcademicYear.name)))
    return {"source_year": {"id": source.id, "name": source.name}, "target_years": [{"id": year.id, "name": year.name} for year in targets], "students": rows}


@app.post("/api/v1/academic-years/{year_id}/promotions")
def apply_promotions(year_id: UUID, payload: PromotionApply, user: User = Depends(require_roles(UserRole.administrator)), db: Session = Depends(get_db)):
    source = db.get(AcademicYear, year_id); target = db.get(AcademicYear, payload.target_year_id)
    if not source or source.state != AcademicYearState.closing or not source.principal_approved_at:
        raise HTTPException(status_code=409, detail="The source year must be closing and approved by the principal")
    if not target or target.state != AcademicYearState.planning:
        raise HTTPException(status_code=409, detail="Choose a planning school year as the promotion destination")
    if target.id == source.id:
        raise HTTPException(status_code=422, detail="Source and target school years must be different")
    if int(target.name.split("-")[0]) != int(source.name.split("-")[1]):
        raise HTTPException(status_code=422, detail="The promotion destination must be the immediately following school year")
    eligible = {student.id: student for student in promotion_students(source.id, db)}
    processed = set(db.scalars(select(StudentPromotion.student_id).where(StudentPromotion.source_year_id == source.id)))
    remaining = set(eligible) - processed
    decisions = {decision.student_id: decision for decision in payload.decisions}
    if len(decisions) != len(payload.decisions) or set(decisions) != remaining:
        raise HTTPException(status_code=422, detail="Submit exactly one decision for every unprocessed student in the preview")
    target_classes = list(db.scalars(select(ClassOffering).where(ClassOffering.academic_year_id == target.id, ClassOffering.is_active.is_(True))))
    now = datetime.now(timezone.utc); results = []
    for student_id, decision in decisions.items():
        student = eligible[student_id]; from_section = student.section; to_section = decision.target_section.strip() if decision.target_section else None
        if decision.action in {"promoted", "retained"}:
            if not to_section:
                raise HTTPException(status_code=422, detail=f"A target section is required for {student.first_name} {student.last_name}")
            student.section = " ".join(to_section.split()); student.is_active = True; student.inactive_reason = None
            for class_item in target_classes:
                if normalized_section(class_item.section) == normalized_section(student.section) and not db.scalar(select(Enrollment).where(Enrollment.class_id == class_item.id, Enrollment.student_id == student.id)):
                    db.add(Enrollment(class_id=class_item.id, student_id=student.id))
        else:
            student.is_active = False; student.inactive_reason = decision.action
            for credential in db.scalars(select(QRCredential).where(QRCredential.student_id == student.id, QRCredential.is_revoked.is_(False))):
                credential.is_revoked = True; credential.revoked_at = now; credential.revocation_reason = "administrative"
        db.add(StudentPromotion(source_year_id=source.id, target_year_id=target.id, student_id=student.id, action=decision.action, from_section=from_section, to_section=student.section if decision.action in {"promoted", "retained"} else None, applied_by=user.id))
        results.append({"student_id": student.id, "action": decision.action, "section": student.section if student.is_active else None})
    write_audit(db, user, "student_promotion.batch", "academic_year", source.id, {"target_year_id": str(target.id), "student_count": len(results), "counts": {action: sum(1 for item in results if item["action"] == action) for action in {item["action"] for item in results}}})
    db.commit()
    return {"source_year": source.name, "target_year": target.name, "processed": len(results), "results": results}


@app.post("/api/v1/academic-years/{year_id}/approve-closing", status_code=204)
def approve_academic_year_closing(year_id: UUID, user: User = Depends(require_roles(UserRole.principal)), db: Session = Depends(get_db)):
    year = db.get(AcademicYear, year_id)
    if not year or year.state != AcademicYearState.closing:
        raise HTTPException(status_code=409, detail="Only a closing academic year can be approved")
    year.principal_approved_by = user.id; year.principal_approved_at = datetime.now(timezone.utc)
    write_audit(db, user, "academic_year.principal_approve", "academic_year", year.id); db.commit()


@app.post("/api/v1/academic-years/{year_id}/transition")
def transition_academic_year(year_id: UUID, payload: AcademicYearTransition, user: User = Depends(require_roles(UserRole.administrator)), db: Session = Depends(get_db)):
    year = db.get(AcademicYear, year_id)
    if not year:
        raise HTTPException(status_code=404, detail="Academic year not found")
    allowed = {AcademicYearState.planning: AcademicYearState.active, AcademicYearState.active: AcademicYearState.closing, AcademicYearState.closing: AcademicYearState.archived}
    if allowed.get(year.state) != payload.state:
        raise HTTPException(status_code=409, detail="Invalid academic-year transition")
    if payload.state == AcademicYearState.active and db.scalar(select(AcademicYear).where(AcademicYear.state == AcademicYearState.active, AcademicYear.id != year.id)):
        raise HTTPException(status_code=409, detail="Close the current active academic year first")
    class_ids = list(db.scalars(select(ClassOffering.id).where(ClassOffering.academic_year_id == year.id)))
    if payload.state == AcademicYearState.closing:
        if class_ids and db.scalar(select(AttendanceSession).where(AttendanceSession.class_id.in_(class_ids), AttendanceSession.status == SessionStatus.open)):
            raise HTTPException(status_code=409, detail="Close all attendance sessions before ending the academic year")
        now = datetime.now(timezone.utc)
        if class_ids:
            for permit in db.scalars(select(OfflineAuthorizationPermit).where(OfflineAuthorizationPermit.class_id.in_(class_ids), OfflineAuthorizationPermit.used_session_id.is_(None), OfflineAuthorizationPermit.revoked_at.is_(None))): permit.revoked_at = now
    if payload.state == AcademicYearState.archived:
        if not year.principal_approved_at:
            raise HTTPException(status_code=409, detail="Principal approval is required before archiving")
        student_ids = {student.id for student in promotion_students(year.id, db)}
        promoted_ids = set(db.scalars(select(StudentPromotion.student_id).where(StudentPromotion.source_year_id == year.id)))
        if student_ids - promoted_ids:
            raise HTTPException(status_code=409, detail="Complete the student promotion review before archiving this school year")
        if payload.confirmation != f"ARCHIVE {year.name}" or not payload.backup_reference or len(payload.backup_reference.strip()) < 3:
            raise HTTPException(status_code=422, detail=f"Provide a backup reference and confirmation: ARCHIVE {year.name}")
        year.archived_at = datetime.now(timezone.utc)
        for class_item in db.scalars(select(ClassOffering).where(ClassOffering.academic_year_id == year.id)): class_item.is_active = False
    year.state = payload.state
    write_audit(db, user, "academic_year.transition", "academic_year", year.id, {"state": payload.state.value, "backup_reference": payload.backup_reference if payload.state == AcademicYearState.archived else None}); db.commit()
    return {"id": year.id, "name": year.name, "state": year.state}


@app.post("/api/v1/auth/login", response_model=UserView)
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    attempt_key = f"{request.client.host if request.client else 'unknown'}:{email}"
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
    login_failures[attempt_key] = [attempt for attempt in login_failures.get(attempt_key, []) if attempt > cutoff]
    if len(login_failures[attempt_key]) >= 5:
        raise HTTPException(status_code=429, detail="Too many failed attempts. Try again in 15 minutes")
    user = db.scalar(select(User).where(User.email == email))
    if not user or not user.is_active or not verify_password(payload.password, user.password_hash):
        login_failures[attempt_key].append(datetime.now(timezone.utc))
        raise HTTPException(status_code=401, detail="Invalid email or password")
    login_failures.pop(attempt_key, None)
    token, session = create_session(db, user)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=settings.session_days * 86400,
        expires=session.expires_at,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )
    return user_view(user)


@app.post("/api/v1/auth/logout", status_code=204)
def logout(
    response: Response,
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    db: Session = Depends(get_db),
):
    if session_token:
        session = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_digest(session_token)))
        if session:
            session.revoked_at = datetime.now(timezone.utc)
            db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


@app.get("/api/v1/auth/me", response_model=UserView)
def current_user(user: User = Depends(get_current_user)):
    return user_view(user)


@app.post("/api/v1/users", response_model=UserView, status_code=201)
def create_user(payload: UserCreate, _: User = Depends(require_roles(UserRole.administrator)), db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="Email already exists")
    user = User(full_name=payload.full_name.strip(), email=email, role=payload.role, password_hash=hash_password(payload.password))
    db.add(user)
    db.flush()
    write_audit(db, _, "user.create", "user", user.id, {"email": email, "role": payload.role.value})
    db.commit()
    db.refresh(user)
    return user_view(user)


@app.get("/api/v1/users", response_model=list[UserView])
def list_users(_: User = Depends(require_roles(UserRole.administrator)), db: Session = Depends(get_db)):
    return [user_view(user) for user in db.scalars(select(User).order_by(User.full_name))]


@app.post("/api/v1/classes", response_model=ClassView, status_code=201)
def create_class(payload: ClassCreate, _: User = Depends(require_roles(UserRole.administrator)), db: Session = Depends(get_db)):
    if payload.teacher_id:
        teacher = db.get(User, payload.teacher_id)
        if not teacher or teacher.role != UserRole.teacher or not teacher.is_active:
            raise HTTPException(status_code=422, detail="Assigned user must be an active teacher")
    year = db.scalar(select(AcademicYear).where(AcademicYear.name == payload.school_year))
    if not year:
        raise HTTPException(status_code=422, detail="Create the academic year before adding classes")
    if year.state not in {AcademicYearState.planning, AcademicYearState.active}:
        raise HTTPException(status_code=409, detail="Classes cannot be added to a closing or archived year")
    if payload.end_time <= payload.start_time:
        raise HTTPException(status_code=422, detail="End time must be later on the same day. For 12 noon choose 12:00; 00:00 means 12 midnight. Overnight classes are not supported.")
    class_data = payload.model_dump()
    class_data["subject"] = " ".join(payload.subject.split())
    class_data["section"] = " ".join(payload.section.split())
    item = ClassOffering(**class_data, academic_year_id=year.id)
    db.add(item)
    db.flush()
    db.add(ClassPolicy(class_id=item.id))
    matching_students = [student for student in db.scalars(select(Student).where(Student.is_active.is_(True))) if normalized_section(student.section) == normalized_section(item.section)]
    for student in matching_students:
        db.add(Enrollment(class_id=item.id, student_id=student.id))
    write_audit(db, _, "class.create", "class", item.id, {"subject": item.subject, "section": item.section, "auto_enrolled_students": len(matching_students)})
    db.commit()
    db.refresh(item)
    return item


@app.get("/api/v1/classes", response_model=list[ClassView])
def list_classes(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = select(ClassOffering).where(ClassOffering.is_active.is_(True)).order_by(ClassOffering.section, ClassOffering.subject)
    if user.role == UserRole.teacher:
        query = query.where(ClassOffering.teacher_id == user.id)
    return list(db.scalars(query))


@app.put("/api/v1/classes/{class_id}", response_model=ClassView)
def update_class(class_id: UUID, payload: ClassCreate, user: User = Depends(require_roles(UserRole.administrator)), db: Session = Depends(get_db)):
    item = db.get(ClassOffering, class_id)
    if not item or not item.is_active:
        raise HTTPException(status_code=404, detail="Class not found")
    year = db.scalar(select(AcademicYear).where(AcademicYear.name == payload.school_year))
    if not year or year.state not in {AcademicYearState.planning, AcademicYearState.active}:
        raise HTTPException(status_code=409, detail="Choose a planning or active school year")
    if payload.teacher_id:
        teacher = db.get(User, payload.teacher_id)
        if not teacher or teacher.role != UserRole.teacher or not teacher.is_active:
            raise HTTPException(status_code=422, detail="Assigned user must be an active teacher")
    if payload.end_time <= payload.start_time:
        raise HTTPException(status_code=422, detail="End time must be later on the same day. For 12 noon choose 12:00; 00:00 means 12 midnight.")
    previous_teacher = item.teacher_id
    item.subject = " ".join(payload.subject.split()); item.section = " ".join(payload.section.split())
    item.school_year = payload.school_year; item.academic_year_id = year.id; item.schedule_label = payload.schedule_label
    item.weekday = payload.weekday; item.start_time = payload.start_time; item.end_time = payload.end_time; item.teacher_id = payload.teacher_id
    enrolled_ids = set(db.scalars(select(Enrollment.student_id).where(Enrollment.class_id == item.id)))
    added = 0
    for student in db.scalars(select(Student).where(Student.is_active.is_(True))):
        if student.id not in enrolled_ids and normalized_section(student.section) == normalized_section(item.section):
            db.add(Enrollment(class_id=item.id, student_id=student.id)); added += 1
    write_audit(db, user, "class.update", "class", item.id, {"previous_teacher_id": str(previous_teacher) if previous_teacher else None, "teacher_id": str(item.teacher_id) if item.teacher_id else None, "section": item.section, "students_added": added})
    db.commit(); db.refresh(item)
    return item


@app.get("/api/v1/classes/{class_id}/roster")
def class_roster(class_id: UUID, user: User = Depends(require_roles(UserRole.teacher, UserRole.administrator)), db: Session = Depends(get_db)):
    permitted_class(class_id, user, db)
    students = db.scalars(select(Student).join(Enrollment, Enrollment.student_id == Student.id).where(Enrollment.class_id == class_id).order_by(Student.last_name, Student.first_name))
    return [{"id": student.id, "full_name": student_full_name(student), "lrn": student.lrn, "section": student.section, "is_active": student.is_active} for student in students]


def permitted_class(class_id: UUID, user: User, db: Session) -> ClassOffering:
    class_item = db.get(ClassOffering, class_id)
    if not class_item or not class_item.is_active:
        raise HTTPException(status_code=404, detail="Class not found")
    if user.role == UserRole.teacher and class_item.teacher_id != user.id:
        raise HTTPException(status_code=403, detail="This class is not assigned to you")
    return class_item


def finalize_attendance_session(session: AttendanceSession, db: Session) -> int:
    if session.status == SessionStatus.closed:
        return 0
    enrolled_students = list(db.scalars(select(Student).join(Enrollment, Enrollment.student_id == Student.id).where(Enrollment.class_id == session.class_id, Student.is_active.is_(True))))
    recorded_lrns = set(db.scalars(select(AttendanceRecord.student_lrn).where(AttendanceRecord.session_id == session.id)))
    absences = 0
    for student in enrolled_students:
        if student.lrn not in recorded_lrns:
            db.add(AttendanceRecord(id=UUID(int=student.id.int ^ session.id.int), session_id=session.id, student_lrn=student.lrn, device_id=UUID(int=0), status=AttendanceStatus.absent, scanned_at=datetime.now(timezone.utc), source="system"))
            absences += 1
    session.status = SessionStatus.closed
    session.closed_at = datetime.now(timezone.utc)
    return absences


@app.post("/api/v1/classes/{class_id}/enrollments", status_code=201)
def enroll_student(class_id: UUID, payload: EnrollmentCreate, user: User = Depends(require_roles(UserRole.teacher, UserRole.administrator)), db: Session = Depends(get_db)):
    class_item = permitted_class(class_id, user, db)
    require_year_state(class_item, db, {AcademicYearState.planning, AcademicYearState.active})
    student = db.get(Student, payload.student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    if not student.is_active:
        raise HTTPException(status_code=409, detail="Inactive students cannot be enrolled")
    if db.scalar(select(Enrollment).where(Enrollment.class_id == class_id, Enrollment.student_id == payload.student_id)):
        raise HTTPException(status_code=409, detail="Student is already enrolled")
    db.add(Enrollment(class_id=class_id, student_id=payload.student_id))
    write_audit(db, user, "enrollment.create", "class", class_id, {"student_id": str(payload.student_id)})
    db.commit()
    return {"status": "enrolled"}


@app.delete("/api/v1/classes/{class_id}/enrollments/{student_id}", status_code=204)
def remove_enrollment(class_id: UUID, student_id: UUID, user: User = Depends(require_roles(UserRole.administrator)), db: Session = Depends(get_db)):
    class_item = permitted_class(class_id, user, db)
    require_year_state(class_item, db, {AcademicYearState.planning, AcademicYearState.active})
    enrollment = db.scalar(select(Enrollment).where(Enrollment.class_id == class_id, Enrollment.student_id == student_id))
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    db.delete(enrollment)
    write_audit(db, user, "enrollment.remove", "class", class_id, {"student_id": str(student_id)})
    db.commit()


@app.post("/api/v1/classes/{class_id}/sessions", response_model=AttendanceSessionView, status_code=201)
def open_session(class_id: UUID, user: User = Depends(require_roles(UserRole.teacher)), db: Session = Depends(get_db)):
    class_item = permitted_class(class_id, user, db)
    require_year_state(class_item, db, {AcademicYearState.active})
    class_schedule_window(class_item, db)
    existing = db.scalar(select(AttendanceSession).where(AttendanceSession.class_id == class_id, AttendanceSession.teacher_id == user.id, AttendanceSession.status == SessionStatus.open))
    if existing:
        opened_local = existing.opened_at.replace(tzinfo=timezone.utc) if existing.opened_at.tzinfo is None else existing.opened_at
        if opened_local.astimezone(SCHOOL_TZ).date() == datetime.now(SCHOOL_TZ).date():
            return existing
        stale_absences = finalize_attendance_session(existing, db)
        write_audit(db, user, "attendance_session.auto_close_stale", "attendance_session", existing.id, {"absences_created": stale_absences})
        db.commit()
    session = AttendanceSession(class_id=class_id, teacher_id=user.id)
    db.add(session)
    write_audit(db, user, "attendance_session.open", "attendance_session", session.id, {"class_id": str(class_id)})
    db.commit()
    db.refresh(session)
    return session


@app.post("/api/v1/students", response_model=StudentCreated, status_code=201)
def create_student(payload: StudentCreate, user: User = Depends(require_roles(UserRole.teacher, UserRole.administrator)), db: Session = Depends(get_db)):
    if db.scalar(select(Student).where(Student.lrn == payload.lrn)):
        raise HTTPException(status_code=409, detail="A student with this LRN already exists")

    student = Student(
        first_name=payload.first_name.strip(),
        last_name=payload.last_name.strip(),
        lrn=payload.lrn.strip(),
        section=payload.section.strip(),
        sex=payload.sex,
        **payload.model_dump(include=set(StudentProfileUpdate.model_fields) - {"first_name", "last_name", "sex"}),
        enrollment_type=payload.enrollment_type,
        created_by=user.id,
    )
    db.add(student)
    db.flush()
    credential = QRCredential(student_id=student.id)
    db.add(credential)
    matching_classes = select(ClassOffering).where(ClassOffering.is_active.is_(True))
    if user.role == UserRole.teacher:
        matching_classes = matching_classes.where(ClassOffering.teacher_id == user.id)
    if payload.academic_year:
        matching_classes = matching_classes.where(ClassOffering.school_year == payload.academic_year)
    enrolled_class_ids = []
    enrollment_years = set()
    for class_item in db.scalars(matching_classes):
        year = class_academic_year(class_item, db)
        if normalized_section(class_item.section) == normalized_section(student.section) and year and year.state in {AcademicYearState.planning, AcademicYearState.active}:
            db.add(Enrollment(class_id=class_item.id, student_id=student.id, enrolled_at=datetime.combine(payload.enrollment_date, datetime.min.time(), tzinfo=SCHOOL_TZ)))
            enrollment_years.add(class_item.school_year)
            enrolled_class_ids.append(str(class_item.id))
    if payload.academic_year and not enrolled_class_ids:
        raise HTTPException(status_code=422, detail="Choose a writable school year and section assigned to you")
    for school_year in enrollment_years:
        db.add(StudentMovement(student_id=student.id, school_year=school_year, section=student.section,
                               kind="transferred_in" if payload.enrollment_type == "transferred_in" else "enrolled",
                               effective_on=payload.enrollment_date, source="enrollment", created_by=user.id))
    write_audit(db, user, "student.create", "student", student.id, {"lrn_suffix": student.lrn[-4:], "auto_enrolled_class_ids": enrolled_class_ids})
    db.commit()
    db.refresh(student)
    db.refresh(credential)
    return StudentCreated(
        id=student.id,
        first_name=student.first_name,
        last_name=student.last_name,
        full_name=student_full_name(student),
        lrn=student.lrn,
        section=student.section,
        sex=student.sex,
        **student_profile_details(student),
        credential_id=credential.id,
        qr_download_url=f"/api/v1/qr-credentials/{credential.id}/image.svg",
        photograph_url=photograph_url(student),
    )


@app.get("/api/v1/students", response_model=list[StudentCreated])
def list_students(user: User = Depends(require_roles(UserRole.teacher, UserRole.administrator)), db: Session = Depends(get_db)):
    records = []
    query = select(Student).order_by(Student.last_name, Student.first_name)
    if user.role == UserRole.teacher:
        query = query.join(Enrollment, Enrollment.student_id == Student.id).join(ClassOffering, ClassOffering.id == Enrollment.class_id).where(ClassOffering.teacher_id == user.id).distinct()
    for student in db.scalars(query):
        credential = db.scalar(
            select(QRCredential).where(
                QRCredential.student_id == student.id,
                QRCredential.is_revoked.is_(False),
            )
        )
        latest_revoked = None if credential else db.scalar(select(QRCredential).where(QRCredential.student_id == student.id).order_by(QRCredential.issued_at.desc()))
        records.append(StudentCreated(
            id=student.id,
            first_name=student.first_name,
            last_name=student.last_name,
            full_name=student_full_name(student),
            lrn=student.lrn,
            section=student.section,
            sex=student.sex,
            **student_profile_details(student),
            credential_id=credential.id if credential else None,
            qr_download_url=f"/api/v1/qr-credentials/{credential.id}/image.svg" if credential else None,
            qr_status="active" if credential else "revoked",
            qr_revocation_reason=latest_revoked.revocation_reason if latest_revoked else None,
            is_active=student.is_active,
            inactive_reason=student.inactive_reason,
            photograph_url=photograph_url(student),
        ))
    return records


@app.get("/api/v1/qr-credentials/{credential_id}/image.svg")
def download_qr_credential(credential_id: UUID, user: User = Depends(require_roles(UserRole.teacher, UserRole.administrator)), db: Session = Depends(get_db)):
    credential = db.get(QRCredential, credential_id)
    if not credential or credential.is_revoked:
        raise HTTPException(status_code=404, detail="Active QR credential not found")
    student = db.get(Student, credential.student_id)
    if not student or not can_manage_student(student, user, db):
        raise HTTPException(status_code=404, detail="Active QR credential not found")

    qr_payload = f"EDUSCAN:{credential.credential}"
    image = qrcode.make(qr_payload, image_factory=qrcode.image.svg.SvgPathImage, box_size=12, border=4)
    output = BytesIO()
    image.save(output)
    return Response(
        content=output.getvalue(),
        media_type="image/svg+xml",
        headers={"Content-Disposition": f'attachment; filename="eduscan-{credential_id}.svg"'},
    )


def can_manage_student(student: Student, user: User, db: Session) -> bool:
    if user.role == UserRole.administrator or student.created_by == user.id:
        return True
    return bool(db.scalar(select(Enrollment).join(ClassOffering, ClassOffering.id == Enrollment.class_id).where(Enrollment.student_id == student.id, ClassOffering.teacher_id == user.id)))


@app.put("/api/v1/students/{student_id}/sex")
def update_student_sex(student_id: UUID, payload: StudentSexUpdate, user: User = Depends(require_roles(UserRole.teacher, UserRole.administrator)), db: Session = Depends(get_db)):
    student = db.get(Student, student_id)
    if not student or not can_manage_student(student, user, db):
        raise HTTPException(status_code=404, detail="Student not found")
    student.sex = payload.sex
    write_audit(db, user, "student.sex.update", "student", student.id)
    db.commit()
    return {"id": student.id, "sex": student.sex}


@app.put("/api/v1/students/{student_id}/profile")
def update_student_profile(student_id: UUID, payload: StudentProfileUpdate, user: User = Depends(require_roles(UserRole.teacher, UserRole.administrator)), db: Session = Depends(get_db)):
    student = db.get(Student, student_id)
    if not student or not can_manage_student(student, user, db):
        raise HTTPException(status_code=404, detail="Student not found")
    # A corrected admission date must not move past any later status event.
    movements = list(db.scalars(select(StudentMovement).where(StudentMovement.student_id == student.id)))
    if any(item.source != "enrollment" and item.effective_on < payload.enrollment_date for item in movements):
        raise HTTPException(status_code=422, detail="Enrollment date cannot be after a recorded status change")
    for field, value in payload.model_dump().items():
        setattr(student, field, value)
    for item in movements:
        if item.source == "enrollment":
            item.effective_on = payload.enrollment_date
    write_audit(db, user, "student.profile.update", "student", student.id, {"fields": list(payload.model_fields_set)})
    db.commit()
    return {"id": student.id, "first_name": student.first_name, "last_name": student.last_name,
            "full_name": student_full_name(student), "sex": student.sex, **student_profile_details(student)}


@app.get("/api/v1/students/{student_id}/movements")
def student_movement_history(student_id: UUID, user: User = Depends(require_roles(UserRole.teacher, UserRole.administrator)), db: Session = Depends(get_db)):
    student = db.get(Student, student_id)
    if not student or not can_manage_student(student, user, db):
        raise HTTPException(status_code=404, detail="Student not found")
    rows = db.scalars(select(StudentMovement).where(StudentMovement.student_id == student.id).order_by(StudentMovement.effective_on, StudentMovement.created_at))
    return [{"id": item.id, "school_year": item.school_year, "section": item.section, "kind": item.kind,
             "effective_on": item.effective_on, "reason": item.reason} for item in rows]


@app.post("/api/v1/students/{student_id}/photograph")
async def upload_student_photograph(student_id: UUID, file: UploadFile = File(...), user: User = Depends(require_roles(UserRole.teacher, UserRole.administrator)), db: Session = Depends(get_db)):
    student = db.get(Student, student_id)
    if not student or not can_manage_student(student, user, db):
        raise HTTPException(status_code=404, detail="Student not found")
    content = await file.read(3 * 1024 * 1024)
    if len(content) > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Photograph must be 2 MB or smaller")
    try:
        image = Image.open(BytesIO(content))
        image = ImageOps.exif_transpose(image).convert("RGB")
        image.thumbnail((512, 512))
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(status_code=422, detail="Upload a valid JPEG, PNG, or WebP photograph") from exc
    upload_root = Path(settings.upload_dir).resolve() / "students"
    upload_root.mkdir(parents=True, exist_ok=True)
    destination = upload_root / f"{student.id}.webp"
    image.save(destination, "WEBP", quality=82, method=6)
    student.photograph_path = str(destination)
    write_audit(db, user, "student.photograph.update", "student", student.id)
    db.commit()
    return {"photograph_url": photograph_url(student)}


@app.get("/api/v1/students/{student_id}/photograph")
def get_student_photograph(student_id: UUID, user: User = Depends(require_roles(UserRole.teacher, UserRole.administrator)), db: Session = Depends(get_db)):
    student = db.get(Student, student_id)
    if not student or not student.photograph_path or not can_manage_student(student, user, db):
        raise HTTPException(status_code=404, detail="Photograph not found")
    path = Path(student.photograph_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Photograph file not found")
    return Response(path.read_bytes(), media_type="image/webp", headers={"Cache-Control": "private, max-age=3600"})


@app.post("/api/v1/students/{student_id}/qr-credential/replace", response_model=StudentCreated)
def replace_qr_credential(student_id: UUID, payload: QRReplacementRequest, user: User = Depends(require_roles(UserRole.teacher, UserRole.administrator)), db: Session = Depends(get_db)):
    student = db.get(Student, student_id)
    if not student or not can_manage_student(student, user, db):
        raise HTTPException(status_code=404, detail="Student not found")
    if not student.is_active:
        raise HTTPException(status_code=409, detail="Reactivate the student before issuing a QR credential")
    now = datetime.now(timezone.utc)
    revoked = list(db.scalars(select(QRCredential).where(QRCredential.student_id == student.id, QRCredential.is_revoked.is_(False))))
    for credential in revoked:
        credential.is_revoked = True; credential.revoked_at = now; credential.revocation_reason = payload.reason
    replacement = QRCredential(student_id=student.id)
    db.add(replacement)
    db.flush()
    for credential in revoked: credential.replacement_credential_id = replacement.id
    write_audit(db, user, "qr_credential.replace", "student", student.id, {"credential_id": str(replacement.id), "reason": payload.reason})
    db.commit()
    return StudentCreated(id=student.id, first_name=student.first_name, last_name=student.last_name, full_name=student_full_name(student), lrn=student.lrn, section=student.section, sex=student.sex, **student_profile_details(student), credential_id=replacement.id, qr_download_url=f"/api/v1/qr-credentials/{replacement.id}/image.svg", photograph_url=photograph_url(student))


@app.post("/api/v1/students/{student_id}/qr-credential/revoke")
def revoke_qr_credential(student_id: UUID, payload: QRReplacementRequest, user: User = Depends(require_roles(UserRole.teacher, UserRole.administrator)), db: Session = Depends(get_db)):
    student = db.get(Student, student_id)
    if not student or not can_manage_student(student, user, db):
        raise HTTPException(status_code=404, detail="Student not found")
    credentials = list(db.scalars(select(QRCredential).where(QRCredential.student_id == student.id, QRCredential.is_revoked.is_(False))))
    if not credentials:
        raise HTTPException(status_code=409, detail="Student has no active QR credential")
    now = datetime.now(timezone.utc)
    for credential in credentials:
        credential.is_revoked = True; credential.revoked_at = now; credential.revocation_reason = payload.reason
    write_audit(db, user, "qr_credential.revoke", "student", student.id, {"reason": payload.reason})
    db.commit()
    return {"status": "revoked", "reason": payload.reason}


@app.put("/api/v1/students/{student_id}/status")
def update_student_status(student_id: UUID, payload: StudentStatusUpdate, user: User = Depends(require_roles(UserRole.administrator)), db: Session = Depends(get_db)):
    student = db.get(Student, student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    if not payload.is_active and not payload.reason:
        raise HTTPException(status_code=422, detail="An inactive reason is required")
    if student.is_active == payload.is_active:
        raise HTTPException(status_code=409, detail="The student already has this status")
    year = db.scalar(select(AcademicYear).where(AcademicYear.name == payload.academic_year))
    if not year or year.state not in {AcademicYearState.planning, AcademicYearState.active}:
        raise HTTPException(status_code=409, detail="Choose a writable school year")
    enrolled = db.scalar(select(Enrollment.id).join(ClassOffering, ClassOffering.id == Enrollment.class_id).where(Enrollment.student_id == student.id, ClassOffering.school_year == payload.academic_year))
    promoted = db.scalar(select(StudentPromotion.id).where(StudentPromotion.student_id == student.id, StudentPromotion.target_year_id == year.id, StudentPromotion.action.in_(["promoted", "retained"])))
    if not enrolled and not promoted:
        raise HTTPException(status_code=422, detail="Student has no enrollment in the selected school year")
    if student.enrollment_date and payload.effective_on < student.enrollment_date:
        raise HTTPException(status_code=422, detail="Status date cannot be before enrollment")
    latest = db.scalar(select(StudentMovement).where(StudentMovement.student_id == student.id).order_by(StudentMovement.effective_on.desc()).limit(1))
    if latest and payload.effective_on < latest.effective_on:
        raise HTTPException(status_code=422, detail="Status date cannot be before the latest recorded movement")
    kind = "reactivated" if payload.is_active else {"transferred": "transferred_out"}.get(payload.reason, payload.reason)
    db.add(StudentMovement(student_id=student.id, school_year=payload.academic_year, section=student.section,
                           kind=kind, effective_on=payload.effective_on, reason=(payload.reason_note or "").strip() or None,
                           source="status", created_by=user.id))
    student.is_active = payload.is_active
    student.inactive_reason = None if payload.is_active else payload.reason
    if not payload.is_active:
        now = datetime.now(timezone.utc)
        for credential in db.scalars(select(QRCredential).where(QRCredential.student_id == student.id, QRCredential.is_revoked.is_(False))):
            credential.is_revoked = True; credential.revoked_at = now; credential.revocation_reason = "administrative"
    write_audit(db, user, "student.status.update", "student", student.id, {"is_active": payload.is_active, "reason": payload.reason,
                "effective_on": payload.effective_on.isoformat(), "academic_year": payload.academic_year})
    db.commit()
    return {"id": student.id, "is_active": student.is_active, "inactive_reason": student.inactive_reason}


@app.put("/api/v1/students/{student_id}/section")
def update_student_section(student_id: UUID, payload: StudentSectionUpdate, user: User = Depends(require_roles(UserRole.administrator)), db: Session = Depends(get_db)):
    student = db.get(Student, student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    old_section = student.section
    student.section = payload.section
    writable_classes = []
    for class_item in db.scalars(select(ClassOffering).where(ClassOffering.is_active.is_(True))):
        year = class_academic_year(class_item, db)
        if year and year.state in {AcademicYearState.planning, AcademicYearState.active}:
            writable_classes.append(class_item)
    writable_ids = {item.id for item in writable_classes}
    desired_ids = {item.id for item in writable_classes if student.is_active and normalized_section(item.section) == normalized_section(student.section)}
    existing = {enrollment.class_id: enrollment for enrollment in db.scalars(select(Enrollment).where(Enrollment.student_id == student.id))}
    for class_id, enrollment in existing.items():
        if class_id in writable_ids and class_id not in desired_ids:
            db.delete(enrollment)
    for class_id in desired_ids - set(existing):
        db.add(Enrollment(class_id=class_id, student_id=student.id))
    added_class_ids = [str(class_id) for class_id in sorted(desired_ids, key=str)]
    write_audit(db, user, "student.section.update", "student", student.id, {"old_section": old_section, "new_section": student.section, "enrolled_class_ids": added_class_ids})
    db.commit()
    return {"id": student.id, "section": student.section, "enrolled_class_ids": added_class_ids}


@app.post("/api/v1/qr-credentials/validate", response_model=QRValidationResult)
def validate_qr_credential(payload: QRValidationRequest, user: User = Depends(require_roles(UserRole.teacher)), db: Session = Depends(get_db)):
    attendance_session = db.get(AttendanceSession, payload.session_id)
    if not attendance_session or attendance_session.status != SessionStatus.open or attendance_session.teacher_id != user.id:
        raise HTTPException(status_code=403, detail="An open assigned attendance session is required")
    class_schedule_window(db.get(ClassOffering, attendance_session.class_id), db)
    prefix = "EDUSCAN:"
    if not payload.payload.startswith(prefix):
        raise HTTPException(status_code=422, detail="This is not an EduScan QR card")
    try:
        credential_value = UUID(payload.payload.removeprefix(prefix))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Malformed EduScan credential") from exc

    credential = db.scalar(select(QRCredential).where(QRCredential.credential == credential_value))
    if not credential or credential.is_revoked:
        raise HTTPException(status_code=404, detail="QR credential is unknown or revoked")
    student = db.get(Student, credential.student_id)
    if not student or not student.is_active:
        raise HTTPException(status_code=404, detail="Student record not found")
    if not db.scalar(select(Enrollment).where(Enrollment.class_id == attendance_session.class_id, Enrollment.student_id == student.id)):
        raise HTTPException(status_code=403, detail="Student is not enrolled in this class")
    return QRValidationResult(
        valid=True,
        student_id=student.id,
        full_name=student_full_name(student),
        lrn=student.lrn,
        section=student.section,
        photograph_url=photograph_url(student),
    )


@app.post("/api/v1/sync/attendance", response_model=AttendanceSyncResult)
def synchronize_attendance(batch: AttendanceSyncBatch, user: User = Depends(require_roles(UserRole.teacher)), db: Session = Depends(get_db)):
    accepted = []
    duplicates = []
    conflicts: list[SyncConflict] = []

    for incoming in batch.records:
        attendance_session = db.get(AttendanceSession, incoming.session_id)
        if not attendance_session and incoming.offline_authorization and incoming.offline_opened_at:
            envelope = incoming.offline_authorization
            permit_payload = envelope.get("payload") if isinstance(envelope, dict) else None
            permit_signature = envelope.get("signature") if isinstance(envelope, dict) else None
            try:
                permit_id = UUID(permit_payload["permit_id"])
                permit_class_id = UUID(permit_payload["class_id"])
                permit_teacher_id = UUID(permit_payload["teacher_id"])
                permit_device_id = UUID(permit_payload["device_id"])
                not_before = datetime.fromisoformat(permit_payload["not_before"])
                expires_at = datetime.fromisoformat(permit_payload["expires_at"])
                sync_deadline = datetime.fromisoformat(permit_payload["sync_deadline"])
            except (KeyError, TypeError, ValueError):
                conflicts.append(SyncConflict(record_id=incoming.record_id, reason="Malformed offline session authorization"))
                continue
            permit = db.get(OfflineAuthorizationPermit, permit_id)
            opened_at = incoming.offline_opened_at if incoming.offline_opened_at.tzinfo else incoming.offline_opened_at.replace(tzinfo=timezone.utc)
            if not verify_offline_permit(permit_payload, permit_signature or "") or not permit or permit.revoked_at or permit.used_session_id or permit.teacher_id != user.id or permit_teacher_id != user.id or permit.class_id != permit_class_id or permit.device_id != batch.device_id or permit_device_id != batch.device_id or not_before > opened_at or expires_at < opened_at or datetime.now(timezone.utc) > sync_deadline:
                conflicts.append(SyncConflict(record_id=incoming.record_id, reason="Offline session authorization is invalid, expired, revoked, or already used"))
                continue
            class_item = db.get(ClassOffering, permit.class_id)
            if not class_item or not class_item.is_active or class_item.teacher_id != user.id:
                conflicts.append(SyncConflict(record_id=incoming.record_id, reason="Offline class assignment is no longer valid"))
                continue
            try:
                class_schedule_window(class_item, db, opened_at)
            except HTTPException as exc:
                conflicts.append(SyncConflict(record_id=incoming.record_id, reason=str(exc.detail)))
                continue
            attendance_session = AttendanceSession(id=incoming.session_id, class_id=permit.class_id, teacher_id=user.id, opened_at=opened_at, opened_offline=True, authorization_permit_id=permit.id, device_id=batch.device_id)
            permit.used_session_id = incoming.session_id
            db.add(attendance_session)
            write_audit(db, user, "attendance_session.adopt_offline", "attendance_session", incoming.session_id, {"permit_id": str(permit.id), "device_id": str(batch.device_id)})
            db.commit()
        if not attendance_session or attendance_session.teacher_id != user.id:
            conflicts.append(SyncConflict(record_id=incoming.record_id, reason="Session is not assigned to this teacher"))
            continue
        try:
            class_schedule_window(db.get(ClassOffering, attendance_session.class_id), db, incoming.scanned_at)
        except HTTPException as exc:
            conflicts.append(SyncConflict(record_id=incoming.record_id, reason=str(exc.detail)))
            continue
        student = db.scalar(select(Student).where(Student.lrn == incoming.student_lrn))
        if not student or not student.is_active or not db.scalar(select(Enrollment).where(Enrollment.class_id == attendance_session.class_id, Enrollment.student_id == student.id)):
            conflicts.append(SyncConflict(record_id=incoming.record_id, reason="Student is not enrolled in this class"))
            continue
        if incoming.credential:
            credential = db.scalar(select(QRCredential).where(QRCredential.credential == incoming.credential, QRCredential.student_id == student.id, QRCredential.is_revoked.is_(False)))
            if not credential:
                conflicts.append(SyncConflict(record_id=incoming.record_id, reason="QR credential is unknown, revoked, or belongs to another student"))
                continue
        existing = db.get(AttendanceRecord, incoming.record_id)
        if existing:
            duplicates.append(incoming.record_id)
            continue

        same_student = db.scalar(
            select(AttendanceRecord).where(
                AttendanceRecord.session_id == incoming.session_id,
                AttendanceRecord.student_lrn == incoming.student_lrn,
            )
        )
        if same_student:
            conflicts.append(SyncConflict(record_id=incoming.record_id, reason="Student already has attendance in this session"))
            continue

        record_status = incoming.status
        policy = db.scalar(select(ClassPolicy).where(ClassPolicy.class_id == attendance_session.class_id))
        scanned_at = incoming.scanned_at if incoming.scanned_at.tzinfo else incoming.scanned_at.replace(tzinfo=timezone.utc)
        class_item = db.get(ClassOffering, attendance_session.class_id)
        late_after = scheduled_start(class_item, scanned_at) + timedelta(minutes=policy.grace_minutes if policy else 10)
        if record_status == AttendanceStatus.present and scanned_at.astimezone(SCHOOL_TZ) > late_after:
            record_status = AttendanceStatus.late
        db.add(AttendanceRecord(
            id=incoming.record_id,
            session_id=incoming.session_id,
            student_lrn=incoming.student_lrn,
            device_id=batch.device_id,
            status=record_status,
            scanned_at=incoming.scanned_at,
        ))
        try:
            db.commit()
            accepted.append(incoming.record_id)
        except IntegrityError:
            db.rollback()
            conflicts.append(SyncConflict(record_id=incoming.record_id, reason="Conflicting attendance record"))

    closed_session_ids = []
    for closure in batch.session_closures:
        session = db.get(AttendanceSession, closure.session_id)
        if not session:
            envelope = closure.offline_authorization
            payload = envelope.get("payload") if isinstance(envelope, dict) else None
            try:
                permit_id = UUID(payload["permit_id"])
                opened_at = closure.offline_opened_at if closure.offline_opened_at.tzinfo else closure.offline_opened_at.replace(tzinfo=timezone.utc)
                not_before = datetime.fromisoformat(payload["not_before"])
                expires_at = datetime.fromisoformat(payload["expires_at"])
                sync_deadline = datetime.fromisoformat(payload["sync_deadline"])
                permit = db.get(OfflineAuthorizationPermit, permit_id)
                valid = verify_offline_permit(payload, envelope.get("signature", "")) and permit and not permit.revoked_at and (not permit.used_session_id or permit.used_session_id == closure.session_id) and permit.teacher_id == user.id and UUID(payload["teacher_id"]) == user.id and permit.device_id == batch.device_id and UUID(payload["device_id"]) == batch.device_id and permit.class_id == UUID(payload["class_id"]) and not_before <= opened_at <= expires_at and datetime.now(timezone.utc) <= sync_deadline
            except (KeyError, TypeError, ValueError):
                valid = False
            if valid:
                class_item = db.get(ClassOffering, permit.class_id)
                if class_item and class_item.is_active and class_item.teacher_id == user.id:
                    try:
                        class_schedule_window(class_item, db, opened_at)
                    except HTTPException:
                        continue
                    session = AttendanceSession(id=closure.session_id, class_id=permit.class_id, teacher_id=user.id, opened_at=opened_at, opened_offline=True, authorization_permit_id=permit.id, device_id=batch.device_id)
                    permit.used_session_id = closure.session_id
                    db.add(session)
                    db.flush()
        if not session or session.teacher_id != user.id:
            continue
        if session.status != SessionStatus.closed:
            enrolled_students = list(db.scalars(select(Student).join(Enrollment, Enrollment.student_id == Student.id).where(Enrollment.class_id == session.class_id, Student.is_active.is_(True))))
            recorded_lrns = set(db.scalars(select(AttendanceRecord.student_lrn).where(AttendanceRecord.session_id == session.id)))
            for student in enrolled_students:
                if student.lrn not in recorded_lrns:
                    db.add(AttendanceRecord(id=UUID(int=student.id.int ^ session.id.int), session_id=session.id, student_lrn=student.lrn, device_id=UUID(int=0), status=AttendanceStatus.absent, scanned_at=datetime.now(timezone.utc), source="system"))
            session.status = SessionStatus.closed
            session.closed_at = datetime.now(timezone.utc)
            write_audit(db, user, "attendance_session.close_offline", "attendance_session", session.id)
            db.commit()
        closed_session_ids.append(session.id)

    accepted_attempt_ids = []
    for attempt in batch.verification_attempts:
        if db.get(VerificationAttempt, attempt.attempt_id):
            accepted_attempt_ids.append(attempt.attempt_id)
            continue
        attempt_session = db.get(AttendanceSession, attempt.session_id)
        if not attempt_session or attempt_session.teacher_id != user.id:
            continue
        db.add(VerificationAttempt(id=attempt.attempt_id, session_id=attempt.session_id, teacher_id=user.id, device_id=batch.device_id, student_lrn=attempt.student_lrn, credential=attempt.credential, action=attempt.action, reason=attempt.reason, occurred_at=attempt.occurred_at))
        write_audit(db, user, f"qr_verification.{attempt.action}", "attendance_session", attempt.session_id, {"student_lrn_suffix": attempt.student_lrn[-4:] if attempt.student_lrn else None, "reason": attempt.reason, "device_id": str(batch.device_id)})
        db.commit()
        accepted_attempt_ids.append(attempt.attempt_id)

    return AttendanceSyncResult(
        accepted_record_ids=accepted,
        duplicate_record_ids=duplicates,
        conflicts=conflicts,
        server_time=datetime.now(timezone.utc),
        closed_session_ids=closed_session_ids,
        accepted_attempt_ids=accepted_attempt_ids,
    )


@app.post("/api/v1/attendance-sessions/{session_id}/close")
def close_attendance_session(session_id: UUID, user: User = Depends(require_roles(UserRole.teacher)), db: Session = Depends(get_db)):
    session = db.get(AttendanceSession, session_id)
    if not session or session.teacher_id != user.id:
        raise HTTPException(status_code=404, detail="Attendance session not found")
    if session.status == SessionStatus.closed:
        return {"status": "closed", "absences_created": 0}
    absences = finalize_attendance_session(session, db)
    write_audit(db, user, "attendance_session.close", "attendance_session", session.id, {"absences_created": absences})
    db.commit()
    return {"status": "closed", "absences_created": absences}


@app.put("/api/v1/classes/{class_id}/policy")
def update_class_policy(class_id: UUID, payload: ClassPolicyUpdate, user: User = Depends(require_roles(UserRole.administrator)), db: Session = Depends(get_db)):
    permitted_class(class_id, user, db)
    policy = db.scalar(select(ClassPolicy).where(ClassPolicy.class_id == class_id))
    if not policy:
        policy = ClassPolicy(class_id=class_id)
        db.add(policy)
    policy.grace_minutes = payload.grace_minutes
    policy.offline_package_hours = payload.offline_package_hours
    policy.open_before_minutes = payload.open_before_minutes
    policy.close_after_minutes = payload.close_after_minutes
    write_audit(db, user, "class.policy.update", "class", class_id, payload.model_dump())
    db.commit()
    return payload


@app.get("/api/v1/classes/{class_id}/policy", response_model=ClassPolicyUpdate)
def get_class_policy(class_id: UUID, user: User = Depends(require_roles(UserRole.administrator)), db: Session = Depends(get_db)):
    permitted_class(class_id, user, db)
    policy = db.scalar(select(ClassPolicy).where(ClassPolicy.class_id == class_id))
    if not policy:
        return ClassPolicyUpdate()
    return ClassPolicyUpdate(grace_minutes=policy.grace_minutes, offline_package_hours=policy.offline_package_hours, open_before_minutes=policy.open_before_minutes, close_after_minutes=policy.close_after_minutes)


@app.get("/api/v1/classes/{class_id}/offline-package")
def offline_class_package(class_id: UUID, device_id: UUID | None = Query(default=None), user: User = Depends(require_roles(UserRole.teacher, UserRole.administrator)), db: Session = Depends(get_db)):
    class_item = permitted_class(class_id, user, db)
    require_year_state(class_item, db, {AcademicYearState.active})
    policy = db.scalar(select(ClassPolicy).where(ClassPolicy.class_id == class_id)) or ClassPolicy(class_id=class_id)
    issued_at = datetime.now(timezone.utc)
    roster = []
    enrolled_students = db.scalars(select(Student).join(Enrollment, Enrollment.student_id == Student.id).where(Enrollment.class_id == class_id, Student.is_active.is_(True)).order_by(Student.last_name, Student.first_name))
    for student in enrolled_students:
        credential = db.scalar(select(QRCredential).where(QRCredential.student_id == student.id, QRCredential.is_revoked.is_(False)))
        if not credential:
            continue
        photo_data = None
        if student.photograph_path and Path(student.photograph_path).is_file():
            photo_data = "data:image/webp;base64," + base64.b64encode(Path(student.photograph_path).read_bytes()).decode("ascii")
        roster.append({"student_id": str(student.id), "full_name": student_full_name(student), "lrn": student.lrn, "section": student.section, "credential": str(credential.credential), "photograph": photo_data})
    payload = {"version": 1, "issued_at": issued_at.isoformat(), "expires_at": (issued_at + timedelta(hours=policy.offline_package_hours)).isoformat(), "class": {"id": str(class_item.id), "subject": class_item.subject, "section": class_item.section, "schedule": class_item.schedule_label, "weekday": class_item.weekday, "start_time": class_item.start_time, "end_time": class_item.end_time, "open_before_minutes": policy.open_before_minutes, "close_after_minutes": policy.close_after_minutes, "grace_minutes": policy.grace_minutes}, "roster": roster}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(settings.offline_signing_key.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
    write_audit(db, user, "offline_package.download", "class", class_id, {"student_count": len(roster), "expires_at": payload["expires_at"]})
    authorization = None
    if user.role == UserRole.teacher:
        device = db.scalar(select(DeviceRegistration).where(DeviceRegistration.device_uuid == device_id, DeviceRegistration.user_id == user.id, DeviceRegistration.revoked_at.is_(None))) if device_id else None
        if not device:
            raise HTTPException(status_code=403, detail="A registered, active teacher device is required for offline authorization")
        for old_permit in db.scalars(select(OfflineAuthorizationPermit).where(OfflineAuthorizationPermit.teacher_id == user.id, OfflineAuthorizationPermit.class_id == class_id, OfflineAuthorizationPermit.device_id == device.device_uuid, OfflineAuthorizationPermit.used_session_id.is_(None), OfflineAuthorizationPermit.revoked_at.is_(None))):
            old_permit.revoked_at = issued_at
        permit = OfflineAuthorizationPermit(teacher_id=user.id, class_id=class_id, device_id=device.device_uuid, not_before=issued_at - timedelta(minutes=5), expires_at=issued_at + timedelta(hours=min(policy.offline_package_hours, 24)))
        db.add(permit)
        db.flush()
        permit_payload = {"version": 1, "permit_id": str(permit.id), "teacher_id": str(user.id), "class_id": str(class_id), "device_id": str(device.device_uuid), "not_before": permit.not_before.isoformat(), "expires_at": permit.expires_at.isoformat(), "sync_deadline": (permit.expires_at + timedelta(days=7)).isoformat(), "max_sessions": 1}
        authorization = {"payload": permit_payload, "signature": sign_offline_permit(permit_payload), "public_key": public_jwk()}
        write_audit(db, user, "offline_permit.issue", "offline_authorization_permit", permit.id, {"class_id": str(class_id), "device_id": str(device.device_uuid), "expires_at": permit.expires_at.isoformat()})
    db.commit()
    return {"payload": payload, "signature": signature, "authorization": authorization}


@app.post("/api/v1/attendance-records/{record_id}/adjustments")
def adjust_attendance(record_id: UUID, payload: AttendanceAdjustmentCreate, user: User = Depends(require_roles(UserRole.teacher, UserRole.administrator)), db: Session = Depends(get_db)):
    record = db.get(AttendanceRecord, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Attendance record not found")
    session = db.get(AttendanceSession, record.session_id)
    class_item = db.get(ClassOffering, session.class_id) if session else None
    if not class_item:
        raise HTTPException(status_code=404, detail="Attendance class not found")
    require_year_state(class_item, db, {AcademicYearState.active, AcademicYearState.closing})
    if user.role == UserRole.teacher and (not session or session.teacher_id != user.id):
        raise HTTPException(status_code=403, detail="Attendance record is not assigned to you")
    old_status = record.status
    record.status = payload.status
    adjustment = AttendanceAdjustment(attendance_record_id=record.id, changed_by=user.id, old_status=old_status, new_status=payload.status, reason=payload.reason.strip())
    db.add(adjustment)
    write_audit(db, user, "attendance.adjust", "attendance_record", record.id, {"old_status": old_status.value, "new_status": payload.status.value, "reason": payload.reason.strip()})
    db.commit()
    return {"id": adjustment.id, "old_status": old_status, "new_status": payload.status, "reason": adjustment.reason}


@app.get("/api/v1/reports/attendance-summary")
def attendance_summary(
    academic_year: str | None = Query(default=None, max_length=20),
    section: str | None = Query(default=None, max_length=120),
    date_from: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    date_to: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    query = select(AttendanceRecord, ClassOffering).join(AttendanceSession, AttendanceSession.id == AttendanceRecord.session_id).join(ClassOffering, ClassOffering.id == AttendanceSession.class_id)
    if user.role == UserRole.teacher: query = query.where(AttendanceSession.teacher_id == user.id)
    if academic_year: query = query.where(ClassOffering.school_year == academic_year)
    if section: query = query.where(ClassOffering.section == section)
    if date_from: query = query.where(AttendanceRecord.scanned_at >= datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc))
    if date_to: query = query.where(AttendanceRecord.scanned_at < datetime.fromisoformat(date_to).replace(tzinfo=timezone.utc) + timedelta(days=1))
    rows = list(db.execute(query))
    counts = {status.value: 0 for status in AttendanceStatus}
    sections: dict[str, dict] = {}
    for record, class_item in rows:
        counts[record.status.value] += 1
        group = sections.setdefault(class_item.section, {"section": class_item.section, "teacher_id": class_item.teacher_id, "present": 0, "late": 0, "absent": 0, "excused": 0, "total": 0})
        group[record.status.value] += 1; group["total"] += 1
    section_rows = []
    for group in sorted(sections.values(), key=lambda item: item["section"]):
        teacher_id = group.pop("teacher_id")
        teacher = db.get(User, teacher_id) if teacher_id else None
        group["adviser"] = teacher.full_name if teacher else "Unassigned"
        group["attendance_rate"] = round((group["present"] + group["late"]) / group["total"] * 100, 2) if group["total"] else 0.0
        section_rows.append(group)
    total = len(rows)
    return {"total": total, "counts": counts, "attendance_rate": round((counts["present"] + counts["late"]) / total * 100, 2) if total else 0.0, "sections": section_rows, "filters": {"academic_year": academic_year, "section": section, "date_from": date_from, "date_to": date_to}}


def sf4_classes(academic_year: str, user: User, db: Session):
    query = select(ClassOffering).where(ClassOffering.school_year == academic_year).order_by(ClassOffering.section, ClassOffering.subject)
    if user.role == UserRole.teacher:
        query = query.where(ClassOffering.teacher_id == user.id)
    return list(db.scalars(query))


@app.get("/api/v1/reports/sf4")
def sf4_prefill(academic_year: str = Query(pattern=r"^\d{4}-\d{4}$"), month: str = Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$"), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        start = datetime.fromisoformat(month + "-01").replace(tzinfo=SCHOOL_TZ)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid reporting month")
    groups = {}
    for item in sf4_classes(academic_year, user, db):
        group = groups.setdefault(normalized_section(item.section), {"section": item.section, "classes": [], "teachers": set()})
        group["classes"].append(item.id)
        if item.teacher_id:
            teacher = db.get(User, item.teacher_id)
            if teacher:
                group["teachers"].add(teacher.full_name)
    result = []
    report_movements = list(db.execute(select(StudentMovement, Student.sex).join(Student, Student.id == StudentMovement.student_id).where(StudentMovement.school_year == academic_year, StudentMovement.effective_on < end.date())))
    for group in groups.values():
        roster = list(db.scalars(select(Student).join(Enrollment, Enrollment.student_id == Student.id).where(Enrollment.class_id.in_(group["classes"]), Enrollment.enrolled_at < end.astimezone(timezone.utc)).distinct()))
        registered = {sex: sum(student.sex == sex and student.is_active for student in roster) for sex in ("male", "female")}
        missing = sum(student.sex is None for student in roster)
        records = db.execute(select(AttendanceRecord, AttendanceSession).join(AttendanceSession, AttendanceSession.id == AttendanceRecord.session_id).where(AttendanceSession.class_id.in_(group["classes"]), AttendanceSession.status == SessionStatus.closed, AttendanceRecord.scanned_at >= start.astimezone(timezone.utc), AttendanceRecord.scanned_at < end.astimezone(timezone.utc)))
        sexes = {student.lrn: student.sex for student in roster}
        attended = {"male": set(), "female": set()}
        observed_days = set()
        for record, session in records:
            timestamp = record.scanned_at
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            day = timestamp.astimezone(SCHOOL_TZ).date().isoformat()
            observed_days.add(day)
            sex = sexes.get(record.student_lrn)
            if sex in attended and record.status in {AttendanceStatus.present, AttendanceStatus.late}:
                attended[sex].add((record.student_lrn, day))
        grade_match = re.search(r"(?:grade\s*)?(1[0-2]|[1-9])(?=\D|$)", group["section"], re.I)
        grade = grade_match.group(1) if grade_match else ("K" if "kinder" in group["section"].lower() else "")
        movement_figures = {}
        movements = [(movement, sex) for movement, sex in report_movements if normalized_section(movement.section) == normalized_section(group["section"])]
        for key, kind in (("dropout", "dropped_out"), ("transfer_out", "transferred_out"), ("transfer_in", "transferred_in")):
            matching = [(movement, sex) for movement, sex in movements if movement.kind == kind]
            if matching:
                for suffix, previous in (("previous", True), ("month", False)):
                    selected = [(movement, sex) for movement, sex in matching if (movement.effective_on < start.date()) == previous]
                    movement_figures[f"{key}_{suffix}"] = {sex: sum(value == sex for _, value in selected) if all(value in {"male", "female"} for _, value in selected) else None for sex in ("male", "female")}
        result.append({"section": group["section"], "grade": grade, "adviser": next(iter(group["teachers"])) if len(group["teachers"]) == 1 else "",
                       "registered": registered if not missing else {"male": None, "female": None},
                       "attendance": {sex: len(attended[sex]) if not missing and observed_days else None for sex in attended},
                       **movement_figures,
                       "missing_sex": missing, "recorded_days": len(observed_days)})
    return {"rows": result}


@app.post("/api/v1/reports/sf4")
def export_sf4(payload: SF4Create, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    allowed = {normalized_section(item.section) for item in sf4_classes(payload.academic_year, user, db)}
    if any(normalized_section(row.section) not in allowed for row in payload.rows):
        raise HTTPException(status_code=403, detail="Report includes a section outside your assigned school year/classes")
    return Response(content=build_sf4(payload), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="eduscan-sf4-{payload.month}.xlsx"', "Cache-Control": "no-store"})


@app.get("/api/v1/audit-logs")
def list_audit_logs(_: User = Depends(require_roles(UserRole.administrator, UserRole.principal)), db: Session = Depends(get_db)):
    logs = list(db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(500)))
    return [{"id": log.id, "actor_user_id": log.actor_user_id, "action": log.action, "entity_type": log.entity_type, "entity_id": log.entity_id, "details": log.details, "created_at": log.created_at} for log in logs]


@app.post("/api/v1/auth/change-password", status_code=204)
def change_password(payload: PasswordChange, response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    user.password_hash = hash_password(payload.new_password)
    now = datetime.now(timezone.utc)
    for session in db.scalars(select(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))):
        session.revoked_at = now
    write_audit(db, user, "password.change", "user", user.id)
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


@app.post("/api/v1/devices")
def register_device(payload: DeviceRegister, user: User = Depends(require_roles(UserRole.teacher)), db: Session = Depends(get_db)):
    device = db.scalar(select(DeviceRegistration).where(DeviceRegistration.device_uuid == payload.device_uuid))
    if device and device.user_id != user.id:
        raise HTTPException(status_code=409, detail="Device is registered to another account")
    if not device:
        device = DeviceRegistration(device_uuid=payload.device_uuid, user_id=user.id, label=payload.label)
        db.add(device)
    device.last_seen_at = datetime.now(timezone.utc)
    device.revoked_at = None
    write_audit(db, user, "device.register", "device", payload.device_uuid, {"label": payload.label})
    db.commit()
    return {"id": device.id, "device_uuid": device.device_uuid, "label": device.label}
