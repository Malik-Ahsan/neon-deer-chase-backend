from fastapi import APIRouter, Depends, HTTPException
from pymongo import MongoClient
import os
from auth import get_current_user
from models import User, SubscriptionUpgradeRequest

router = APIRouter()

def get_db():
    client = MongoClient(os.getenv("MONGODB_URI"))
    db = client.get_database("resume_pivot")
    return db

@router.post("/subscriptions/upgrade")
async def upgrade_subscription(
    request: SubscriptionUpgradeRequest, current_user: User = Depends(get_current_user)
):
    db = get_db()
    users_collection = db.get_collection("users")

    result = users_collection.update_one(
        {"_id": current_user["_id"]},
        {"$set": {"subscription": request.tierId}},
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")

    return {"message": "Subscription upgraded successfully"}