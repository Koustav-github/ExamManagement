"""One-shot bootstrap: create the first super_admin.

Usage (from backend/):
    python scripts/create_first_admin.py

Prompts for the admin details, hashes the password, inserts one row.
Refuses to run if any admins already exist.
"""
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bcrypt

from database import SessionLocal
import models


def main() -> None:
    db = SessionLocal()
    try:
        if db.query(models.Admins).count() > 0:
            print("Admins already exist. Use POST /admin/admins as an existing super_admin.")
            sys.exit(1)

        print("Creating first super_admin.")
        name = input("Name: ").strip()
        admin_id = input("Admin ID: ").strip()
        email = input("Email: ").strip()
        mobile = input("Mobile: ").strip()
        password = getpass.getpass("Password: ")
        confirm = getpass.getpass("Confirm password: ")

        if password != confirm:
            print("Passwords do not match.")
            sys.exit(1)
        if not all([name, admin_id, email, mobile, password]):
            print("All fields are required.")
            sys.exit(1)

        admin = models.Admins(
            name=name,
            admin_id=admin_id,
            email_id=email,
            mobile_number=mobile,
            password_hash=bcrypt.hashpw(
                password.encode("utf-8"), bcrypt.gensalt()
            ).decode("utf-8"),
            super_admin=True,
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)
        print(f"Created super_admin id={admin.id} admin_id={admin.admin_id}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
