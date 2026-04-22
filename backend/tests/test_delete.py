"""Admin delete flows: cascade cleanup + Marks preservation."""
import models


def _signin(client, email, password, role):
    resp = client.post(
        "/user/signin",
        json={"email": email, "password": password, "role": role},
    )
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _seed(client, admin_headers):
    s = client.post(
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
    t = client.post(
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
    return s.json()["id"], t.json()["id"]


def test_delete_student_cascades_subjects_and_links(client, admin_headers, db):
    student_id, _ = _seed(client, admin_headers)
    teacher_headers = _signin(client, "bob@test.com", "bob-pass", "teacher")
    client.post(
        "/teacher/marks",
        headers=teacher_headers,
        json={
            "student_id": student_id, "subject": "PHYSICS",
            "max_marks": 100, "marks_obtained": 50,
        },
    )

    resp = client.delete(
        f"/admin/students/{student_id}", headers=admin_headers
    )
    assert resp.status_code == 204

    assert db.get(models.Students, student_id) is None
    assert (
        db.query(models.StudentSubject)
        .filter(models.StudentSubject.student_id == student_id).count() == 0
    )
    assert (
        db.query(models.TeacherSubjectStudent)
        .filter(models.TeacherSubjectStudent.student_id == student_id).count() == 0
    )
    assert (
        db.query(models.Marks)
        .filter(models.Marks.student_id == student_id).count() == 0
    )


def test_delete_teacher_preserves_marks_and_nulls_teacher_ref(
    client, admin_headers, db
):
    student_id, teacher_id = _seed(client, admin_headers)
    teacher_headers = _signin(client, "bob@test.com", "bob-pass", "teacher")
    client.post(
        "/teacher/marks",
        headers=teacher_headers,
        json={
            "student_id": student_id, "subject": "PHYSICS",
            "max_marks": 100, "marks_obtained": 77,
        },
    )

    resp = client.delete(
        f"/admin/teachers/{teacher_id}", headers=admin_headers
    )
    assert resp.status_code == 204

    assert db.get(models.Teachers, teacher_id) is None
    assert (
        db.query(models.TeacherSubject)
        .filter(models.TeacherSubject.teacher_id == teacher_id).count() == 0
    )

    mark = (
        db.query(models.Marks)
        .filter(models.Marks.student_id == student_id).one()
    )
    assert mark.marks_obtained == 77
    assert mark.entered_by_teacher_id is None


def test_delete_student_404_when_missing(client, admin_headers):
    resp = client.delete("/admin/students/99999", headers=admin_headers)
    assert resp.status_code == 404


def test_delete_teacher_404_when_missing(client, admin_headers):
    resp = client.delete("/admin/teachers/99999", headers=admin_headers)
    assert resp.status_code == 404


def test_delete_student_requires_admin(client):
    resp = client.delete("/admin/students/1")
    assert resp.status_code == 403


def test_delete_teacher_requires_admin(client):
    resp = client.delete("/admin/teachers/1")
    assert resp.status_code == 403
