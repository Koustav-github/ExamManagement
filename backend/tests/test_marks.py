"""Marks upload: 3-table sync (Marks + StudentSubject.marks + TeacherSubjectStudent.marks)."""
import models


def _signin(client, email, password, role):
    # Clear any previous session — /user/signin 409s on an active cookie.
    client.post("/auth/logout")
    resp = client.post(
        "/user/signin",
        json={"email": email, "password": password, "role": role},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _seed_student_and_teacher(client, admin_headers):
    student = client.post(
        "/admin/students",
        json={
            "name": "Alice",
            "school_id": "S001",
            "email": "alice@test.com",
            "mobile_number": "1",
            "password": "alice-pass",
            "class_section": "ELEVEN_SC",
        },
        headers=admin_headers,
    )
    assert student.status_code == 201, student.text
    teacher = client.post(
        "/admin/teachers",
        json={
            "name": "Bob",
            "teacher_id": "T001",
            "email": "bob@test.com",
            "mobile_number": "2",
            "password": "bob-pass",
            "subjects": [{"subject": "PHYSICS", "class_level": "ELEVEN_SC"}],
        },
        headers=admin_headers,
    )
    assert teacher.status_code == 201, teacher.text
    return student.json()["id"], teacher.json()["id"]


def test_upload_marks_syncs_all_three_tables(client, admin_headers, db):
    student_id, _ = _seed_student_and_teacher(client, admin_headers)
    teacher_headers = _signin(client, "bob@test.com", "bob-pass", "teacher")

    resp = client.post(
        "/teacher/marks",
        json={
            "student_id": student_id,
            "subject": "PHYSICS",
            "max_marks": 100,
            "marks_obtained": 87,
        },
        headers=teacher_headers,
    )
    assert resp.status_code == 200, resp.text

    mark = (
        db.query(models.Marks)
        .filter(
            models.Marks.student_id == student_id,
            models.Marks.subject == "PHYSICS",
        )
        .one()
    )
    assert mark.marks_obtained == 87
    assert mark.max_marks == 100

    ss = (
        db.query(models.StudentSubject)
        .filter(
            models.StudentSubject.student_id == student_id,
            models.StudentSubject.subject == "PHYSICS",
        )
        .one()
    )
    assert ss.marks == 87

    tss = (
        db.query(models.TeacherSubjectStudent)
        .filter(models.TeacherSubjectStudent.student_id == student_id)
        .one()
    )
    assert tss.marks == 87


def test_upload_marks_upserts_existing_row(client, admin_headers, db):
    student_id, _ = _seed_student_and_teacher(client, admin_headers)
    teacher_headers = _signin(client, "bob@test.com", "bob-pass", "teacher")

    payload = {
        "student_id": student_id,
        "subject": "PHYSICS",
        "max_marks": 100,
        "marks_obtained": 50,
    }
    client.post("/teacher/marks", json=payload, headers=teacher_headers)
    payload["marks_obtained"] = 77
    client.post("/teacher/marks", json=payload, headers=teacher_headers)

    marks = (
        db.query(models.Marks)
        .filter(models.Marks.student_id == student_id)
        .all()
    )
    assert len(marks) == 1
    assert marks[0].marks_obtained == 77


def test_upload_marks_rejects_unauthorized_subject(client, admin_headers):
    student_id, _ = _seed_student_and_teacher(client, admin_headers)
    teacher_headers = _signin(client, "bob@test.com", "bob-pass", "teacher")

    resp = client.post(
        "/teacher/marks",
        json={
            "student_id": student_id,
            "subject": "CHEMISTRY",
            "max_marks": 100,
            "marks_obtained": 80,
        },
        headers=teacher_headers,
    )
    assert resp.status_code == 403


def test_upload_marks_rejects_exceeding_max(client, admin_headers):
    student_id, _ = _seed_student_and_teacher(client, admin_headers)
    teacher_headers = _signin(client, "bob@test.com", "bob-pass", "teacher")

    resp = client.post(
        "/teacher/marks",
        json={
            "student_id": student_id,
            "subject": "PHYSICS",
            "max_marks": 100,
            "marks_obtained": 120,
        },
        headers=teacher_headers,
    )
    assert resp.status_code == 400


def test_upload_marks_requires_teacher_role(client, admin_headers):
    student_id, _ = _seed_student_and_teacher(client, admin_headers)
    resp = client.post(
        "/teacher/marks",
        json={
            "student_id": student_id,
            "subject": "PHYSICS",
            "max_marks": 100,
            "marks_obtained": 80,
        },
        headers=admin_headers,
    )
    assert resp.status_code == 403
