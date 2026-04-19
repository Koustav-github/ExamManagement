from fastapi import FastAPI, Depends, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from database import Base, engine, get_database, SessionLocal
from sqlalchemy.orm import Session

from pydantic import BaseModel, EmailStr
import models
import os
import httpx
from dotenv import load_dotenv

# 1. Create the app instance (the CLI looks for this variable name)
app = FastAPI(title="Academic Report backend")
load_dotenv()

class userSync():
    email: str
    password: str
    role: models.Role
    if models.Role.STUDENT:
        school_id = str


@app.get("/user/signin")
async def sync_user(user_data = userSync, db: Session = Depends(get_database)):
    if user_data.role is models.Role.STUDENT:
        user = db.query(models.Students).filter(user_data.email == models.Students.email_id & user_data.password == models.Students.password).first()
    if user_data.role is models.Role.TEACHER:
        user = db.query(models.Teachers).filter(user_data.email == models.Teachers.email_id & user_data.password == models.Teachers.password).first()
    if user_data.role is models.Role.ADMIN:
        user = db.query(models.Admins).filter(user_data.email == models.Admins.email_id & user_data.password == models.Admins.password).first()

    if not user:
        return {"message":"User is not signed in"}

# You can keep your main function for local testing if you want,
# but FastAPI doesn't need it to run the server.

def main():
    print("This runs only if you execute 'python main.py' directly")

if __name__ == "__main__":
    main()