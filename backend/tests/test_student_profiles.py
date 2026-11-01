from datetime import datetime
from zoneinfo import ZoneInfo
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models import AcademicYear, AcademicYearState, UserRole
from app.schemas import StudentCreate
from app.security import get_current_user
from app.main import app
from test_sf4 import api  # In-memory database and isolated authenticated users.


def profile_data():
    return dict(first_name='Maria', middle_name='Isabel', last_name='Santos', suffix='Jr.', sex='female',
                date_of_birth='2011-03-12', enrollment_date='2026-06-01', guardian_name='Ana Santos',
                guardian_phone='+63 917 123 4567', address='Barangay One\nLuna')


def test_new_student_requires_core_details_and_validates_dates():
    data = dict(profile_data(), lrn='123456789012', section='Grade 7 - 0')
    for field in ['sex', 'date_of_birth', 'enrollment_date', 'first_name', 'last_name']:
        incomplete = dict(data); del incomplete[field]
        with pytest.raises(ValidationError):
            StudentCreate(**incomplete)
    for invalid in [dict(date_of_birth='2999-01-01'), dict(enrollment_date='2000-01-01'), dict(guardian_phone='abc'), dict(first_name='   ')]:
        with pytest.raises(ValidationError):
            StudentCreate(**(data | invalid))
    value = StudentCreate(**(data | {'middle_name':' ', 'guardian_name':' '}))
    assert value.middle_name is None and value.guardian_name is None
    with pytest.raises(ValidationError, match='school year'):
        StudentCreate(**(data | {'enrollment_type':'transferred_in'}))


def test_profile_edits_permissions_age_and_existing_qr(api):
    client, db, students, other = api
    student = students[0]
    response = client.put(f'/api/v1/students/{student.id}/profile', json=profile_data())
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['full_name'] == 'Maria Isabel Santos Jr.'
    assert result['guardian_phone'] == '+63 917 123 4567'
    today = datetime.now(ZoneInfo('Asia/Manila')).date()
    assert result['age'] == today.year - 2011 - ((today.month, today.day) < (3,12))
    assert db.get(type(student), student.id).date_of_birth.isoformat() == '2011-03-12'
    listed = next(row for row in client.get('/api/v1/students').json() if row['id'] == str(student.id))
    assert listed['address'] == 'Barangay One\nLuna'
    assert listed['middle_name'] == 'Isabel'
    app.dependency_overrides[get_current_user] = lambda: other
    assert client.put(f'/api/v1/students/{student.id}/profile', json=profile_data()).status_code == 404
    assert client.get(f'/api/v1/students/{student.id}/movements').status_code == 404
    other.role = UserRole.principal
    assert client.put(f'/api/v1/students/{student.id}/profile', json=profile_data()).status_code == 403


def test_create_complete_profile_transfer_history_and_sf4_counts(api):
    client, db, students, other = api
    db.add(AcademicYear(name='2026-2027', state=AcademicYearState.active)); db.commit()
    data = profile_data() | {'lrn':str(uuid4().int)[:12], 'section':'Grade 7 - 0', 'academic_year':'2026-2027', 'enrollment_type':'transferred_in'}
    response = client.post('/api/v1/students', json=data)
    assert response.status_code == 201, response.text
    created = response.json(); student_id = created['id']; credential_id = created['credential_id']
    assert created['date_of_birth'] == data['date_of_birth']
    assert created['guardian_name'] == data['guardian_name']
    assert created['full_name'] == 'Maria Isabel Santos Jr.'
    # QR contains its opaque credential, not the expanded student information.
    qr = client.get(created['qr_download_url'])
    assert qr.status_code == 200
    for secret in ['Maria', 'Santos', 'guardian_phone', '+63', '2011-03-12', 'Barangay']:
        assert secret not in qr.text
    history = client.get(f'/api/v1/students/{student_id}/movements').json()
    assert len(history) == 1  # Two subject enrollments must produce one movement.
    assert history[0]['kind'] == 'transferred_in'
    assert history[0]['effective_on'] == '2026-06-01'
    before = client.get('/api/v1/reports/sf4?academic_year=2026-2027&month=2026-11').json()['rows'][0]
    assert before['transfer_in_previous'] == {'male':0,'female':1}
    assert before['transfer_in_month'] == {'male':0,'female':0}
    edited = client.put(f'/api/v1/students/{student_id}/profile', json=profile_data() | {'enrollment_date':'2026-07-01'})
    assert edited.status_code == 200
    assert client.get(f'/api/v1/students/{student_id}/movements').json()[0]['effective_on'] == '2026-07-01'
    listed = next(row for row in client.get('/api/v1/students').json() if row['id'] == student_id)
    assert listed['credential_id'] == credential_id  # Editing the profile preserves the card.
    # Only the administrator can change enrollment status.
    status = {'is_active':False,'reason':'dropped_out','academic_year':'2026-2027','effective_on':'2026-10-01','reason_note':'Confirmed with guardian'}
    assert client.put(f'/api/v1/students/{student_id}/status', json=status).status_code == 403
    other.role = UserRole.administrator
    app.dependency_overrides[get_current_user] = lambda: other
    saved = client.put(f'/api/v1/students/{student_id}/status', json=status)
    assert saved.status_code == 200, saved.text
    assert client.put(f'/api/v1/students/{student_id}/status', json=status).status_code == 409
    history = client.get(f'/api/v1/students/{student_id}/movements').json()
    assert [row['kind'] for row in history] == ['transferred_in','dropped_out']
    row = client.get('/api/v1/reports/sf4?academic_year=2026-2027&month=2026-11').json()['rows'][0]
    assert row['dropout_previous'] == {'male':0,'female':1}
    listed = next(row for row in client.get('/api/v1/students').json() if row['id'] == student_id)
    assert listed['qr_status'] == 'revoked'
    assert client.get(created['qr_download_url']).status_code == 404
    # Neither malformed nor backwards dates create a status record.
    assert client.put(f'/api/v1/students/{student_id}/status', json=status | {'is_active':True,'effective_on':'2026-06-01'}).status_code == 422
    assert len(client.get(f'/api/v1/students/{student_id}/movements').json()) == 2
