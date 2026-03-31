import qrcode
import os
from fastapi.responses import FileResponse
import uuid
from fastapi.responses import FileResponse
from fastapi import UploadFile, File
import shutil
import os
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .models import User, Document
from .schemas import UserCreate, UserLogin
from .auth import hash_password, verify_password, create_access_token, verify_token

security = HTTPBearer()

Base.metadata.create_all(bind=engine)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/signup")
def signup(user: UserCreate, db: Session = Depends(get_db)):
    hashed_pw = hash_password(user.password)

    new_user = User(
        username=user.username,
        email=user.email,
        hashed_password=hashed_pw
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {"message": "User created successfully"}

@app.post("/login")
def login(user: UserLogin, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.username == user.username).first()

    if not db_user:
        raise HTTPException(status_code=400, detail="User not found")

    if not verify_password(user.password, db_user.hashed_password):
        raise HTTPException(status_code=400, detail="Wrong password")

    token = create_access_token({"sub": str(db_user.id)})
    return {"access_token": token, "token_type": "bearer"}

@app.get("/profile")
def profile(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    payload = verify_token(token)

    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return {
        "message": "Protected profile accessed",
        "user": payload.get("sub")
    }
@app.post("/upload")
def upload_file(
    file: UploadFile = File(...),
    title: str = Form(None),
    category: str = Form(None),
    description: str = Form(None),
    issuer_name: str = Form(None),
    issue_date: str = Form(None),
    expiry_date: str = Form(None),
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    token = credentials.credentials
    payload = verify_token(token)

    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = int(payload.get("sub"))

    upload_dir = "uploads"
    file_path = os.path.join(upload_dir, file.filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    new_document = Document(
        filename=file.filename,
        file_path=file_path,
        title=title,
        category=category,
        description=description,
        issuer_name=issuer_name,
        issue_date=issue_date,
        expiry_date=expiry_date,
        verification_code=f"SPV-{uuid.uuid4().hex[:10].upper()}",
        owner_id=user_id
    )

    db.add(new_document)
    db.commit()
    db.refresh(new_document)

    verify_url = f"http://127.0.0.1:8000/verify/{new_document.verification_code}"

    qr_img = qrcode.make(verify_url)
    qr_path = os.path.join("storage", "qr_codes", f"{new_document.verification_code}.png")
    qr_img.save(qr_path)

    return {
        "message": "File uploaded successfully",
        "document_id": new_document.id,
        "filename": new_document.filename,
        "title": new_document.title,
        "category": new_document.category,
        "issuer_name": new_document.issuer_name,
        "verification_code": new_document.verification_code
    }
@app.get("/my-files")
def get_my_files(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    token = credentials.credentials
    payload = verify_token(token)

    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = int(payload.get("sub"))

    documents = db.query(Document).filter(Document.owner_id == user_id).all()

    return {
        "files": [
            {
                "id": doc.id,
                "filename": doc.filename,
                "file_path": doc.file_path,
                "title": doc.title,
                "category": doc.category,
                "description": doc.description,
                "issuer_name": doc.issuer_name,
                "issue_date": doc.issue_date,
                "expiry_date": doc.expiry_date,
                "verification_code": doc.verification_code,
                "qr_url": f"/qr/{doc.verification_code}"if doc.verification_code else None
            }
            for doc in documents
        ]
    }
from fastapi.responses import FileResponse

from fastapi.responses import FileResponse

@app.get("/verify/{code}")
def verify_page(code: str):
    return FileResponse("static/verify.html")

@app.get("/download/{file_id}")
def download_file(file_id: int, db: Session = Depends(get_db)):
    document = db.query(Document).filter(Document.id == file_id).first()

    if not document:
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(path=document.file_path, filename=document.filename)

@app.get("/api/verify/{code}")
def verify_document_api(code: str, db: Session = Depends(get_db)):
    document = db.query(Document).filter(Document.verification_code == code).first()

    if not document:
        return {"verified": False}

    return {
        "verified": True,
        "filename": document.filename,
        "title": document.title,
        "category": document.category,
        "issuer_name": document.issuer_name,
        "issue_date": document.issue_date,
        "expiry_date": document.expiry_date,
        "verification_code": document.verification_code
    }

@app.delete("/delete/{file_id}")
def delete_file(
    file_id: int,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    token = credentials.credentials
    payload = verify_token(token)

    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = int(payload.get("sub"))

    document = db.query(Document).filter(
        Document.id == file_id,
        Document.owner_id == user_id
    ).first()

    if not document:
        raise HTTPException(status_code=404, detail="File not found")

    if os.path.exists(document.file_path):
        os.remove(document.file_path)

    db.delete(document)
    db.commit()

    return {"message": "File deleted successfully"}

app.mount("/", StaticFiles(directory="static", html=True), name="static")