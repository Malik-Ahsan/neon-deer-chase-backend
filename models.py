from pydantic import BaseModel, EmailStr

class User(BaseModel):
    username: str
    email: EmailStr
    hashed_password: str

class UserIn(BaseModel):
    username: str
    email: EmailStr
    password: str