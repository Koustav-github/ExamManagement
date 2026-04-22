"""Student self-service report card PDF download."""


def _signin(client, email, password, role):
    client.post("/auth/logout")
    resp = client.post(
        "/user/signin",
        json={"email": email, "password": password, "role": role},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _seed_student_teacher_and_upload(client, admin_headers, obtained=87):
    client.post(
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
    client.post(
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
    teacher_headers = _signin(client, "bob@test.com", "bob-pass", "teacher")
    student_id_resp = client.get(
        "/admin/students", headers=admin_headers,
        params={"search": "alice"},
    )
    student_id = student_id_resp.json()["items"][0]["id"]
    client.post(
        "/teacher/marks",
        headers=teacher_headers,
        json={
            "student_id": student_id,
            "subject": "PHYSICS",
            "max_marks": 100,
            "marks_obtained": obtained,
        },
    )


def test_student_downloads_pdf(client, admin_headers):
    _seed_student_teacher_and_upload(client, admin_headers, obtained=87)
    student_headers = _signin(client, "alice@test.com", "alice-pass", "student")

    resp = client.get("/student/report-card", headers=student_headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert "attachment" in resp.headers["content-disposition"]
    assert "report-S001" in resp.headers["content-disposition"]
    # PDF magic bytes
    assert resp.content[:4] == b"%PDF"


def test_report_card_works_with_no_marks_yet(client, admin_headers):
    client.post(
        "/admin/students",
        json={
            "name": "Fresh",
            "school_id": "S999",
            "email": "fresh@test.com",
            "mobile_number": "0",
            "password": "pw",
            "class_section": "NINE",
        },
        headers=admin_headers,
    )
    student_headers = _signin(client, "fresh@test.com", "pw", "student")
    resp = client.get("/student/report-card", headers=student_headers)
    assert resp.status_code == 200
    assert resp.content[:4] == b"%PDF"


def test_report_card_forbidden_for_non_student(client, admin_headers):
    resp = client.get("/student/report-card", headers=admin_headers)
    assert resp.status_code == 403


def test_report_card_requires_auth(client):
    resp = client.get("/student/report-card")
    assert resp.status_code == 403
