"""Admin endpoint tests: student/teacher creation, auth guards, auto-enrollment."""
import models


def _create_student(client, admin_headers, **overrides):
    payload = {
        "name": "Alice",
        "school_id": "S001",
        "email": "alice@test.com",
        "mobile_number": "1111111111",
        "password": "alice-pass",
        "class_section": "ELEVEN_SC",
    }
    payload.update(overrides)
    return client.post("/admin/students", json=payload, headers=admin_headers)


def _create_teacher(client, admin_headers, **overrides):
    payload = {
        "name": "Bob",
        "teacher_id": "T001",
        "email": "bob@test.com",
        "mobile_number": "2222222222",
        "password": "bob-pass",
        "subjects": [{"subject": "PHYSICS", "class_level": "ELEVEN_SC"}],
    }
    payload.update(overrides)
    return client.post("/admin/teachers", json=payload, headers=admin_headers)


def test_create_student_auto_enrolls_subjects(client, admin_headers, db):
    resp = _create_student(client, admin_headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    enrolled = {s["subject"] for s in body["subjects"]}
    expected = set(models.ScienceSubject.__members__.keys())
    assert enrolled == expected
    for s in body["subjects"]:
        assert s["marks"] == 0


def test_create_student_requires_auth_header(client):
    resp = client.post(
        "/admin/students",
        json={
            "name": "X",
            "school_id": "S999",
            "email": "x@test.com",
            "mobile_number": "9",
            "password": "p",
            "class_section": "NINE",
        },
    )
    assert resp.status_code == 403


def test_create_student_duplicate_school_id_returns_409(client, admin_headers):
    first = _create_student(client, admin_headers)
    assert first.status_code == 201
    dup = _create_student(
        client,
        admin_headers,
        email="other@test.com",
    )
    assert dup.status_code == 409


def test_create_student_invalid_class_section_returns_422(client, admin_headers):
    resp = _create_student(client, admin_headers, class_section="NOT_A_CLASS")
    assert resp.status_code == 422


def test_create_teacher_links_existing_students(client, admin_headers, db):
    student_resp = _create_student(client, admin_headers)
    assert student_resp.status_code == 201
    student_id = student_resp.json()["id"]

    teacher_resp = _create_teacher(client, admin_headers)
    assert teacher_resp.status_code == 201, teacher_resp.text
    body = teacher_resp.json()
    assert body["subjects"][0]["students_enrolled"] == 1

    links = (
        db.query(models.TeacherSubjectStudent)
        .filter(models.TeacherSubjectStudent.student_id == student_id)
        .all()
    )
    assert len(links) == 1


def test_create_teacher_invalid_subject_for_class_returns_400(
    client, admin_headers
):
    resp = _create_teacher(
        client,
        admin_headers,
        subjects=[{"subject": "HISTORY", "class_level": "ELEVEN_SC"}],
    )
    assert resp.status_code == 400


def test_create_teacher_duplicate_teacher_id_returns_409(client, admin_headers):
    first = _create_teacher(client, admin_headers)
    assert first.status_code == 201
    dup = _create_teacher(client, admin_headers, email="other@test.com")
    assert dup.status_code == 409


def test_list_students_filters_and_paginates(client, admin_headers):
    _create_student(
        client, admin_headers, school_id="S1", email="a1@test.com",
        class_section="NINE",
    )
    _create_student(
        client, admin_headers, school_id="S2", email="a2@test.com",
        name="Alex", class_section="NINE",
    )
    _create_student(
        client, admin_headers, school_id="S3", email="b3@test.com",
        name="Bob", class_section="TEN",
    )

    resp = client.get(
        "/admin/students",
        headers=admin_headers,
        params={"class_section": "NINE"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2

    resp2 = client.get(
        "/admin/students",
        headers=admin_headers,
        params={"search": "bob"},
    )
    assert resp2.status_code == 200
    assert resp2.json()["total"] == 1


def test_list_students_rejects_invalid_sort_by(client, admin_headers):
    resp = client.get(
        "/admin/students",
        headers=admin_headers,
        params={"sort_by": "password_hash"},
    )
    assert resp.status_code == 400
