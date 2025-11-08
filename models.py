from datetime import datetime
from pydantic import BaseModel, EmailStr
from typing import List, Optional

class User(BaseModel):
    username: str
    email: EmailStr
    hashed_password: str

class UserIn(BaseModel):
    username: str
    email: EmailStr
    password: str

class TokenBlocklist(BaseModel):
    jti: str
    created_at: datetime

class ResumeVersionRequest(BaseModel):
    jobDescription: str
    versionName: str

class SubscriptionUpgradeRequest(BaseModel):
    tierId: str

class Experience(BaseModel):
    id: str
    title: str
    company: str
    description: str
    tags: Optional[List[str]] = []

class TagUpdateRequest(BaseModel):
    experience: List[Experience]
