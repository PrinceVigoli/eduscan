from datetime import datetime, timezone
from io import BytesIO
from uuid import uuid4
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models import AttendanceRecord, AttendanceSession, AttendanceStatus, ClassOffering, Enrollment, SessionStatus, Student, User, UserRole
from app.schemas import SF4Create, StudentCreate
from app.security import get_current_user
from app.sf4 import TEMPLATE, build_sf4

NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def report_data(count=1):
    row = dict(section='Grade 7 - A', adviser='=Teacher <One>', grade='7',
               registered={'male': 2, 'female': 3}, attendance={'male': 30, 'female': 45})
    for key in ('dropout_previous', 'dropout_month', 'transfer_out_previous', 'transfer_out_month', 'transfer_in_previous', 'transfer_in_month'):
        row[key] = {'male': 1, 'female': 2}
    return dict(school_name='Test School', school_id='123456', region='Region I', division='Test Division', district='Test District', school_head='Head Name', academic_year='2026-2027', month='2026-11', school_days=20, rows=[dict(row, section=f'Grade 7 - {i}') for i in range(count)])


def cell(sheet, address):
    node = sheet.find(f'.//m:c[@r="{address}"]', NS)
    value = node.find('m:v', NS)
    return float(value.text) if value is not None else ''.join(node.find('m:is', NS).itertext())


def test_sf4_workbook_counts_summaries_pagination_and_assets():
    data = build_sf4(SF4Create(**report_data(16)))
    with ZipFile(BytesIO(data)) as report, ZipFile(TEMPLATE) as template:
        assert report.testzip() is None
        for name in report.namelist():
            if name.endswith('.xml') or name.endswith('.rels'):
                ET.fromstring(report.read(name))
        sheet = ET.fromstring(report.read('xl/worksheets/sheet1.xml'))
        assert cell(sheet, 'C5') == '123456'
        assert cell(sheet, 'AJ7') == 'November 2026'
        assert cell(sheet, 'A12') == '=Teacher <One>'
        assert sheet.find('.//m:c[@r="A12"]/m:f', NS) is None
        assert [cell(sheet, f'{col}12') for col in ['E','F','G','H','I','J','K','L','M']] == [2,3,5,1.5,2.25,3.75,75,75,75]
        assert [cell(sheet, f'{col}12') for col in ['N','O','P','Q','R','S','T','U','V']] == [1,2,3,1,2,3,2,4,6]
        assert cell(sheet, 'G29') == 75
        assert cell(sheet, 'M36') == 75
        assert cell(sheet, 'AN36') == 90
        second = ET.fromstring(report.read('xl/worksheets/sheet2.xml'))
        assert cell(second, 'G36') == 5
        workbook = ET.fromstring(report.read('xl/workbook.xml'))
        assert len(workbook.find('m:sheets', NS)) == 2
        assert workbook.find('m:externalReferences', NS) is None
        for name in ['xl/styles.xml','xl/media/image1.png','xl/media/image2.wmf','xl/drawings/drawing1.xml','xl/printerSettings/printerSettings1.bin']:
            assert report.read(name) == template.read(name)


def test_sf4_validation_and_sex_import():
    assert StudentCreate(first_name='A', last_name='B', lrn='123456789012', section='7-A', sex='F', date_of_birth='2010-01-01', enrollment_date='2026-06-01').sex == 'female'
    data = report_data()
    data['rows'][0]['attendance']['male'] = 41
    with pytest.raises(ValidationError, match='Attendance learner-days'):
        SF4Create(**data)
    data = report_data()
    del data['rows'][0]['dropout_month']
    with pytest.raises(ValidationError):
        SF4Create(**data)
    data = report_data()
    data['month'] = '2026-02'
    data['school_days'] = 30
    with pytest.raises(ValidationError, match='School days exceed'):
        SF4Create(**data)


@pytest.fixture
def api():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        teacher = User(full_name='Teacher', email='t@sf4.test', role=UserRole.teacher, password_hash='unused')
        other = User(full_name='Other', email='o@sf4.test', role=UserRole.teacher, password_hash='unused')
        db.add_all([teacher, other]); db.flush()
        classes = [ClassOffering(subject=subject, section='Grade 7 - 0', school_year='2026-2027', schedule_label='Test', teacher_id=teacher.id) for subject in ['Math','Science']]
        forbidden = ClassOffering(subject='Other', section='Grade 7 - Other', school_year='2026-2027', schedule_label='Test', teacher_id=other.id)
        db.add_all(classes + [forbidden]); db.flush()
        students = [Student(first_name=sex, last_name='Learner', sex=sex, lrn=str(index+123456789010), section='Grade 7 - 0') for index, sex in enumerate(['male','female'])]
        db.add_all(students); db.flush()
        for class_item in classes:
            for student in students:
                db.add(Enrollment(class_id=class_item.id, student_id=student.id, enrolled_at=datetime(2026,6,1,tzinfo=timezone.utc)))
            session = AttendanceSession(class_id=class_item.id, teacher_id=teacher.id, status=SessionStatus.closed)
            db.add(session); db.flush()
            for student in students:
                db.add(AttendanceRecord(id=uuid4(), session_id=session.id, device_id=uuid4(), student_lrn=student.lrn, status=AttendanceStatus.late, scanned_at=datetime(2026,10,31,16,30,tzinfo=timezone.utc)))
        db.commit()
        def get_test_db():
            yield db
        app.dependency_overrides[get_db] = get_test_db
        app.dependency_overrides[get_current_user] = lambda: teacher
        original = settings.auto_create_schema
        settings.auto_create_schema = False
        try:
            with TestClient(app) as client:
                yield client, db, students, other
        finally:
            settings.auto_create_schema = original
            app.dependency_overrides.clear()
    engine.dispose()


def test_sf4_api_prefill_deduplicates_days_scopes_and_exports(api):
    client, db, students, other = api
    response = client.get('/api/v1/reports/sf4?academic_year=2026-2027&month=2026-11')
    assert response.status_code == 200
    row = response.json()['rows'][0]
    assert row['registered'] == {'male':1,'female':1}
    assert row['attendance'] == {'male':1,'female':1}
    assert row['recorded_days'] == 1
    assert len(response.json()['rows']) == 1
    assert client.post('/api/v1/reports/sf4', json=report_data()).status_code == 200
    data = report_data(); data['rows'][0]['section'] = 'Grade 7 - Other'
    assert client.post('/api/v1/reports/sf4', json=data).status_code == 403
    students[0].sex = None; db.commit()
    row = client.get('/api/v1/reports/sf4?academic_year=2026-2027&month=2026-11').json()['rows'][0]
    assert row['missing_sex'] == 1
    assert row['registered']['male'] is None
    assert client.put(f'/api/v1/students/{students[0].id}/sex', json={'sex':'male'}).status_code == 200
    app.dependency_overrides[get_current_user] = lambda: other
    assert client.put(f'/api/v1/students/{students[0].id}/sex', json={'sex':'female'}).status_code == 404


def test_existing_student_database_migration_preserves_records(tmp_path, monkeypatch):
    import sqlite3
    from alembic import command
    from alembic.config import Config
    database = tmp_path / 'upgrade.db'
    with sqlite3.connect(database) as connection:
        connection.execute('CREATE TABLE students (id TEXT PRIMARY KEY, first_name TEXT NOT NULL)')
        connection.execute("INSERT INTO students VALUES ('existing-student', 'Maria')")
    monkeypatch.setattr(settings, 'database_url', f'sqlite:///{database.as_posix()}')
    config = Config('alembic.ini')
    command.stamp(config, 'c61e04a7b912')
    command.upgrade(config, 'head')
    with sqlite3.connect(database) as connection:
        assert connection.execute('SELECT first_name, sex, date_of_birth, enrollment_date, enrollment_type FROM students').fetchone() == ('Maria', None, None, None, 'regular')
        assert connection.execute('SELECT count(*) FROM student_movements').fetchone()[0] == 0
        assert connection.execute('SELECT version_num FROM alembic_version').fetchone()[0] == 'f6c0d2a9b814'
