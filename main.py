from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from pymongo import MongoClient
import os
from dotenv import load_dotenv
from models import UserIn, User
from auth import get_password_hash, verify_password, create_access_token, get_current_user, oauth2_scheme
from fastapi.security import OAuth2PasswordRequestForm
from fastapi import Depends, HTTPException, status
from datetime import timedelta, datetime
from jose import jwt, JWTError
import resume
import subscription

# Construct the path to the .env file relative to this script
dotenv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path=dotenv_path)
else:
    print(f"Warning: .env file not found at {dotenv_path}")

app = FastAPI()

client = None

@app.on_event("startup")
async def startup_db_client():
    global client
    mongo_uri = None
    try:
        dotenv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
        with open(dotenv_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    if key.strip() == 'MONGODB_URI':
                        mongo_uri = value.strip().strip('"\'')
                        break
    except FileNotFoundError:
        raise Exception(f".env file not found at {dotenv_path}")

    if not mongo_uri:
        raise Exception("MONGODB_URI not found or is empty in .env file")
        
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)

@app.on_event("shutdown")
async def shutdown_db_client():
    global client
    client.close()

# CORS configuration
origins = os.getenv("CORS_ORIGINS", "http://localhost:5137").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/api/v1/auth/register")
def register_user(user: UserIn):
    db = client.get_database("resume_pivot")
    users_collection = db.get_collection("users")
    
    if users_collection.find_one({"email": user.email}):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )
    
    hashed_password = get_password_hash(user.password)
    user_data = user.dict()
    user_data["hashed_password"] = hashed_password
    del user_data["password"]
    
    users_collection.insert_one(user_data)
    
    return {"message": "User registered successfully", "user": {"username": user.username, "email": user.email}}

@app.post("/api/v1/auth/login")
def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    db = client.get_database("resume_pivot")
    users_collection = db.get_collection("users")
    
    user = users_collection.find_one({"username": form_data.username})
    
    if not user or not verify_password(form_data.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 60)))
    access_token = create_access_token(
        data={"sub": user["email"]}, expires_delta=access_token_expires
    )
    
    return {"access_token": access_token, "token_type": "bearer", "user": {"username": user["username"], "email": user["email"], "subscriptionTier": user.get("subscription", "free")}}

@app.post("/api/v1/auth/logout")
def logout(token: str = Depends(oauth2_scheme), _: User = Depends(get_current_user)):
    try:
        payload = jwt.decode(token, os.getenv("JWT_SECRET_KEY"), algorithms=[os.getenv("ALGORITHM")])
        jti = payload.get("jti")
        
        db = client.get_database("resume_pivot")
        blocklist_collection = db.get_collection("token_blocklist")
        
        blocklist_collection.insert_one({
            "jti": jti,
            "created_at": datetime.utcnow()
        })
        
        return {"message": "Successfully logged out"}
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

app.include_router(resume.router, prefix="/api/v1", tags=["resume"])
app.include_router(subscription.router, prefix="/api/v1", tags=["subscription"])

@app.get("/api/v1/users/me", response_model=User)
async def read_users_me(current_user: User = Depends(get_current_user)):
    return current_user

@app.get("/")
def read_root():
    return {"Hello": "World"}

@app.get("/api/v1/healthz")
def health_check():
    try:
        # Ping the database to check the connection
        client.admin.command('ping')
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "details": str(e)}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)