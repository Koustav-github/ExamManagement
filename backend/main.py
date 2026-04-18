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


@app.get("/student/signup")
def read_root():
    return {"message": "Hello from backend!"}
@app.get("/student/signout")
def read_root():
    return {"message": "Hello from backend!"}
@app.get("/teacher/signup")
def read_root():
    return {"message": "Hello from backend!"}
@app.get("/teacher/signout")
def read_root():
    return {"message": "Hello from backend!"}

# You can keep your main function for local testing if you want,
# but FastAPI doesn't need it to run the server.

def main():
    print("This runs only if you execute 'python main.py' directly")

if __name__ == "__main__":
    main()