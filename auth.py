from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
import os
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_password_hash(password):
    return pwd_context.hash(password[:72])

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

import uuid

def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire, "jti": str(uuid.uuid4())})
    encoded_jwt = jwt.encode(to_encode, os.getenv("JWT_SECRET_KEY"), algorithm=os.getenv("ALGORITHM"))
    return encoded_jwt

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

from pymongo import MongoClient

def is_token_blocklisted(jti: str):
    client = MongoClient(os.getenv("MONGODB_URI"))
    db = client.get_database("resume_pivot")
    blocklist_collection = db.get_collection("token_blocklist")
    return blocklist_collection.find_one({"jti": jti}) is not None

async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, os.getenv("JWT_SECRET_KEY"), algorithms=[os.getenv("ALGORITHM")])
        email: str = payload.get("sub")
        jti: str = payload.get("jti")
        if email is None or jti is None:
            raise credentials_exception
        if is_token_blocklisted(jti):
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    client = MongoClient(os.getenv("MONGODB_URI"))
    db = client.get_database("resume_pivot")
    users_collection = db.get_collection("users")
    
    user = users_collection.find_one({"email": email})
    
    if user is None:
        raise credentials_exception
    
    return user