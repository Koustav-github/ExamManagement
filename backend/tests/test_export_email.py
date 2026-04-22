"""Action layer: CSV/JSON export + mass email (SMTP monkeypatched)."""
import csv
import io
import json
import os

import main


def _seed(client, admin_headers):
    client.post(
        "/admin/students",
        json={
            "name": "Alice",
            "school_id": "S001",
            "email": "alice@test.com",
            "mobile_number": "1",
            "password": "p",
            "class_section": "ELEVEN_SC",
        },
        headers=admin_headers,
    )
    client.post(
        "/admin/students",
        json={
            "name": "Zed",
            "school_id": "S002",
            "email": "zed@test.com",
            "mobile_number": "2",
            "password": "p",
            "class_section": "NINE",
        },
        headers=admin_headers,
    )
    client.post(
        "/admin/teachers",
        json={
            "name": "Bob",
            "teacher_id": "T001",
            "email": "bob@test.com",
            "mobile_number": "3",
            "password": "p",
            "subjects": [
                {"subject": "PHYSICS", "class_level": "ELEVEN_SC"},
                {"subject": "MATH", "class_level": "ELEVEN_SC"},
            ],
        },
        headers=admin_headers,
    )


def test_export_students_csv_long_format(client, admin_headers):
    _seed(client, admin_headers)
    resp = client.get("/admin/students/export", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]

    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert len(rows) == 6 + 7  # Science (6 subjects) + Core (7 subjects)
    assert {"student_id", "name", "subject", "marks"}.issubset(rows[0].keys())

    alice_rows = [r for r in rows if r["name"] == "Alice"]
    assert {r["subject"] for r in alice_rows} == {
        "PHYSICS", "CHEMISTRY", "MATH", "BIOLOGY",
        "COMPUTER_SCIENCE", "ENGLISH",
    }


def test_export_students_filters_by_class(client, admin_headers):
    _seed(client, admin_headers)
    resp = client.get(
        "/admin/students/export",
        headers=admin_headers,
        params={"class_section": "NINE"},
    )
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert all(r["class_section"] == "NINE" for r in rows)
    assert all(r["name"] == "Zed" for r in rows)


def test_export_students_json_format(client, admin_headers):
    _seed(client, admin_headers)
    resp = client.get(
        "/admin/students/export",
        headers=admin_headers,
        params={"format": "json", "class_section": "ELEVEN_SC"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/x-ndjson")
    lines = [json.loads(l) for l in resp.text.splitlines() if l.strip()]
    assert len(lines) == 6
    assert all(l["name"] == "Alice" for l in lines)


def test_export_teachers_csv(client, admin_headers):
    _seed(client, admin_headers)
    resp = client.get("/admin/teachers/export", headers=admin_headers)
    assert resp.status_code == 200
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert len(rows) == 2
    assert {r["subject"] for r in rows} == {"PHYSICS", "MATH"}
    assert all(r["teacher_id"] == "T001" for r in rows)


def test_export_teachers_filters_by_subject(client, admin_headers):
    _seed(client, admin_headers)
    resp = client.get(
        "/admin/teachers/export",
        headers=admin_headers,
        params={"subject": "PHYSICS"},
    )
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert len(rows) == 1
    assert rows[0]["subject"] == "PHYSICS"


def test_export_requires_admin(client):
    resp = client.get("/admin/students/export")
    assert resp.status_code == 403


def test_mass_email_sends_to_filtered_cohort(
    client, admin_headers, monkeypatch
):
    _seed(client, admin_headers)
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USER", "sender@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "x")

    sent_to = []
    monkeypatch.setattr(
        main,
        "_send_smtp",
        lambda to, subject, body: sent_to.append((to, subject, body)),
    )

    resp = client.post(
        "/admin/students/email",
        headers=admin_headers,
        json={
            "subject": "Hello",
            "body": "Your results are out.",
            "filters": {"class_section": "ELEVEN_SC"},
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["recipients_matched"] == 1
    assert body["sent"] == 1
    assert body["failed"] == []
    assert sent_to == [("alice@test.com", "Hello", "Your results are out.")]


def test_mass_email_records_failures(client, admin_headers, monkeypatch):
    _seed(client, admin_headers)
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USER", "sender@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "x")

    def boom(to, subject, body):
        raise RuntimeError("connection refused")
    monkeypatch.setattr(main, "_send_smtp", boom)

    resp = client.post(
        "/admin/students/email",
        headers=admin_headers,
        json={"subject": "S", "body": "B", "filters": {}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["sent"] == 0
    assert len(body["failed"]) == body["recipients_matched"]
    assert "connection refused" in body["failed"][0]["error"]


def test_mass_email_503_when_smtp_unconfigured(
    client, admin_headers, monkeypatch
):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_USER", raising=False)
    resp = client.post(
        "/admin/students/email",
        headers=admin_headers,
        json={"subject": "S", "body": "B", "filters": {}},
    )
    assert resp.status_code == 503
