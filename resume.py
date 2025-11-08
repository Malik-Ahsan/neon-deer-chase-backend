from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pymongo import MongoClient
import os
import fitz  # PyMuPDF
from auth import get_current_user
from models import User, ResumeVersionRequest, TagUpdateRequest
import re
import uuid

router = APIRouter()

def get_db():
    client = MongoClient(os.getenv("MONGODB_URI"))
    db = client.get_database("resume_pivot")
    return db

def parse_experience(raw_text):
    experience = []
    # Look for a section header
    experience_section = re.search(r"(?i)(experience|work history|employment)", raw_text)
    if not experience_section:
        return experience

    text = raw_text[experience_section.end():]
    
    # Simple regex to find job title, company, and date range
    # This is a heuristic and may need to be improved
    # This regex is designed to find blocks of text that represent a single company's experience.
    entry_pattern = re.compile(
        r'^\s*([A-Z\s]{2,})\s*\n([\s\S]+?)(?=\n\s*[A-Z\s]{2,}\n|\n\s*(?:Projects|Awards|Additional)\s*\n|\Z)',
        re.MULTILINE
    )

    for company_match in entry_pattern.finditer(text):
        company = company_match.group(1).strip()
        details_block = company_match.group(2).strip()

        # This regex finds individual job roles within the company's block of text.
        role_pattern = re.compile(
            r'^\s*(.*?)\n\s*(.*?–.*?)\n([\s\S]+?)(?=\n\s*[A-Z][a-z].*?\n\s*.*?\–.*?\n|\Z)',
            re.MULTILINE
        )

        for role_match in role_pattern.finditer(details_block):
            title, date_range, description = role_match.groups()
            experience.append({
                "id": str(uuid.uuid4()),
                "title": title.strip(),
                "company": company,
                "description": description.strip()
            })
    return experience

@router.post("/resumes/master")
async def upload_master_resume(
    current_user: User = Depends(get_current_user),
    file: UploadFile = File(...)
):
    db = get_db()
    resumes_collection = db.get_collection("resumes")

    file_bytes = await file.read()

    if file.content_type == "application/pdf":
        try:
            pdf_document = fitz.open(stream=file_bytes, filetype="pdf")
            raw_text = ""
            for page_num in range(len(pdf_document)):
                page = pdf_document.load_page(page_num)
                raw_text += page.get_text()
            pdf_document.close()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error processing PDF file: {e}")
    else:
        try:
            raw_text = file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="File is not a valid PDF or plain text file.")

    experience = parse_experience(raw_text)

    resume_data = {
        "userId": current_user["_id"],
        "isMaster": True,
        "name": "Master Resume",
        "content": {
            "raw": raw_text,
            "experience": experience
        },
    }

    result = resumes_collection.update_one(
        {"userId": current_user["_id"], "isMaster": True},
        {"$set": resume_data},
        upsert=True
    )
    
    if result.upserted_id or result.modified_count > 0 or result.matched_count > 0:
        return {"content": {"raw": raw_text, "experience": experience}}
    else:
        raise HTTPException(status_code=500, detail="Failed to upload master resume")

@router.get("/resumes/master")
async def get_master_resume(current_user: User = Depends(get_current_user)):
    db = get_db()
    resumes_collection = db.get_collection("resumes")
    
    resume = resumes_collection.find_one({"userId": current_user["_id"], "isMaster": True})
    
    if resume:
        return {"content": resume.get("content", {})}
    else:
        raise HTTPException(status_code=404, detail="Master resume not found")

@router.get("/resumes/master/experience")
async def get_master_resume_experience(current_user: User = Depends(get_current_user)):
    db = get_db()
    resumes_collection = db.get_collection("resumes")
    
    resume = resumes_collection.find_one({"userId": current_user["_id"], "isMaster": True})
    
    if resume and "content" in resume and "experience" in resume["content"]:
        return resume["content"]["experience"]
    else:
        return []

@router.put("/resumes/master/experience/tags")
async def update_experience_tags(
    request: TagUpdateRequest,
    current_user: User = Depends(get_current_user)
):
    db = get_db()
    resumes_collection = db.get_collection("resumes")

    master_resume = resumes_collection.find_one({"userId": current_user["_id"], "isMaster": True})
    if not master_resume:
        raise HTTPException(status_code=404, detail="Master resume not found")

    experience_map = {exp.id: exp for exp in request.experience}
    
    if "content" not in master_resume or "experience" not in master_resume["content"]:
        raise HTTPException(status_code=404, detail="No experience data found in master resume")

    updated_experience = []
    for exp in master_resume["content"]["experience"]:
        if exp["id"] in experience_map:
            updated_exp = experience_map[exp["id"]]
            exp["tags"] = updated_exp.tags
        updated_experience.append(exp)

    result = resumes_collection.update_one(
        {"userId": current_user["_id"], "isMaster": True},
        {"$set": {"content.experience": updated_experience}}
    )

    if result.modified_count > 0:
        return {"message": "Experience tags updated successfully"}
    else:
        raise HTTPException(status_code=500, detail="Failed to update experience tags")

from pydantic import BaseModel

class ResumeUpdate(BaseModel):
    content: str

@router.put("/resumes/master")
async def update_master_resume(
    resume_data: ResumeUpdate,
    current_user: User = Depends(get_current_user)
):
    db = get_db()
    resumes_collection = db.get_collection("resumes")
    
    update_data = {
        "userId": current_user["_id"],
        "isMaster": True,
        "name": "Master Resume",
        "content": resume_data.content,
    }
    result = resumes_collection.update_one(
        {"userId": current_user["_id"], "isMaster": True},
        {"$set": update_data},
        upsert=True
    )

    if result.upserted_id:
        return {"message": "Master resume created successfully"}
    elif result.modified_count > 0 or result.matched_count > 0:
        return {"message": "Master resume updated successfully"}
    else:
        raise HTTPException(status_code=500, detail="Failed to update master resume")

@router.post("/resumes/versions")
async def create_resume_version(
    request: ResumeVersionRequest,
    current_user: User = Depends(get_current_user)
):
    db = get_db()
    resumes_collection = db.get_collection("resumes")

    # 1. Check subscription tier and limit versions for free users
    if current_user.get("subscription") == "free":
        version_count = resumes_collection.count_documents({"userId": current_user["_id"], "isMaster": False})
        if version_count >= 2:
            raise HTTPException(status_code=403, detail="Free users are limited to 2 resume versions. Please upgrade to create more.")

    # 2. Fetch the master resume
    master_resume = resumes_collection.find_one({"userId": current_user["_id"], "isMaster": True})
    if not master_resume:
        raise HTTPException(status_code=404, detail="Master resume not found. Please upload one first.")

    master_content = master_resume.get("content", {}).get("raw", "")
    if not master_content:
        raise HTTPException(status_code=404, detail="Master resume content is empty.")

    # 2. Simplified generation logic (keyword filtering)
    job_keywords = set(request.jobDescription.lower().split())
    
    # A simple way to filter might be to check for sentences containing keywords.
    # This is a placeholder for the more complex logic that will be developed.
    generated_content_lines = [
        line for line in master_content.splitlines()
        if any(keyword in line.lower() for keyword in job_keywords)
    ]
    
    # If no lines match, we can return the whole master resume content as a fallback
    if not generated_content_lines:
        generated_content = master_content
    else:
        generated_content = "\n".join(generated_content_lines)


    # 3. Save the new version to the database
    new_version = {
        "userId": current_user["_id"],
        "isMaster": False,
        "name": request.versionName,
        "content": {"raw": generated_content},
    }
    result = resumes_collection.insert_one(new_version)

    # 4. Return the new version
    if result.inserted_id:
        return {
            "id": str(result.inserted_id),
            "name": request.versionName,
            "content": {"raw": generated_content},
        }
    else:
        raise HTTPException(status_code=500, detail="Failed to create resume version")

@router.get("/resumes/versions")
async def get_resume_versions(current_user: User = Depends(get_current_user)):
    db = get_db()
    resumes_collection = db.get_collection("resumes")
    
    versions_cursor = resumes_collection.find({
        "userId": current_user["_id"],
        "isMaster": False
    })
    
    versions = []
    for version in versions_cursor:
        versions.append({
            "id": str(version["_id"]),
            "name": version.get("name"),
            "content": version.get("content", {}),
            "createdAt": version.get("createdAt"),
            "lastModified": version.get("lastModified")
        })
        

from bson import ObjectId

@router.put("/resumes/versions/{version_id}")
async def update_resume_version(
    version_id: str,
    resume_data: ResumeUpdate,
    current_user: User = Depends(get_current_user)
):
    db = get_db()
    resumes_collection = db.get_collection("resumes")
    
    try:
        oid = ObjectId(version_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid version ID")

    result = resumes_collection.update_one(
        {"_id": oid, "userId": current_user["_id"]},
        {"$set": {"content": {"raw": resume_data.content}, "lastModified": ""}}
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Resume version not found")

@router.post("/resumes/versions/{version_id}/sync")
async def sync_resume_version(
    version_id: str,
    current_user: User = Depends(get_current_user)
):
    db = get_db()
    resumes_collection = db.get_collection("resumes")

    # 1. Fetch the master resume
    master_resume = resumes_collection.find_one({"userId": current_user["_id"], "isMaster": True})
    if not master_resume:
        raise HTTPException(status_code=404, detail="Master resume not found. Please upload one first.")

    master_content = master_resume.get("content", {}).get("raw", "")
    if not master_content:
        raise HTTPException(status_code=404, detail="Master resume content is empty.")

    # 2. Update the version with the master content
    try:
        oid = ObjectId(version_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid version ID")

    result = resumes_collection.update_one(
        {"_id": oid, "userId": current_user["_id"]},
        {"$set": {"content": {"raw": master_content}, "masterLastSynced": ""}}
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Resume version not found")

    return {"message": "Resume version synced successfully"}
    
    if result.modified_count == 0:
        return {"message": "No changes detected"}

    return {"message": "Resume version updated successfully"}