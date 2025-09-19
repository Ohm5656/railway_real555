"""
File Server สำหรับ serve ไฟล์จาก Local Storage และ Output
"""

import os
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from local_storage import local_storage   # ✅ import instance แทน class

app = FastAPI(title="Local File Server")

# ====================== CORS ======================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------------------------------------------
# [Railway] ปรับฐาน path ให้ configurable ผ่าน ENV และชี้ไปยัง Volume (/data)
# -----------------------------------------------------------------
STORAGE_DIR = Path(os.environ.get("STORAGE_DIR", "/data/local_storage"))  # [Railway]
OUTPUT_DIR  = Path(os.environ.get("OUTPUT_DIR",  "/data/local_storage"))  # [Railway]

# สร้างโฟลเดอร์ย่อยสำหรับแต่ละหมวด
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
(OUTPUT_DIR / "size").mkdir(parents=True, exist_ok=True)
(OUTPUT_DIR / "shrimp").mkdir(parents=True, exist_ok=True)
(OUTPUT_DIR / "din").mkdir(parents=True, exist_ok=True)
(OUTPUT_DIR / "water").mkdir(parents=True, exist_ok=True)

# ===================== Mount static files =====================
app.mount("/storage", StaticFiles(directory=str(STORAGE_DIR)), name="storage")
app.mount("/size",   StaticFiles(directory="/data/local_storage/size"), name="size")
app.mount("/shrimp", StaticFiles(directory="/data/local_storage/shrimp"), name="shrimp")
app.mount("/din",    StaticFiles(directory="/data/local_storage/din"),   name="din")
app.mount("/water",  StaticFiles(directory="/data/local_storage/water"), name="water")

# ===================== Routes =====================
@app.get("/")
async def root():
    return {
        "message": "Local File Server",
        "endpoints": {
            "files": "/files/{file_id}",
            "list": "/list",
            "info": "/info/{file_id}",
            "static": ["/storage", "/size", "/shrimp", "/din", "/water"]
        }
    }

@app.get("/files/{file_id}")
@app.head("/files/{file_id}")
async def serve_file(file_id: str):
    """Serve ไฟล์จาก file_id (ใช้ metadata.json)"""
    try:
        file_info = local_storage.get_file_info(file_id)  # ✅ ใช้ instance
        if not file_info:
            raise HTTPException(status_code=404, detail="File not found")

        file_path = local_storage.get_file_path(file_id)  # ✅ ใช้ instance
        if not file_path or not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="File not found")

        return FileResponse(
            path=file_path,
            filename=file_info["original_name"],
            media_type=file_info["mime_type"]
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดในการ serve ไฟล์ {file_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")

@app.get("/list")
async def list_files(prefix: str = ""):
    files = local_storage.list_files(prefix)  # ✅ ใช้ instance
    return {
        "total_files": len(files),
        "files": files
    }

@app.get("/info/{file_id}")
async def get_file_info(file_id: str):
    file_info = local_storage.get_file_info(file_id)  # ✅ ใช้ instance
    if not file_info:
        raise HTTPException(status_code=404, detail="File not found")
    return file_info

@app.delete("/files/{file_id}")
async def delete_file(file_id: str):
    success = local_storage.delete_file(file_id)  # ✅ ใช้ instance
    if not success:
        raise HTTPException(status_code=404, detail="File not found")
    return {"message": "File deleted successfully"}

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "storage_path": str(STORAGE_DIR),
        "output_path": str(OUTPUT_DIR)
    }
    
    
    # วางไว้ส่วนบนไฟล์ ใกล้ๆ imports อื่นๆ
from pathlib import Path
import shutil
import glob

BASE_ROOT = Path(os.environ.get("LOCAL_STORAGE_BASE", "/data/local_storage")).resolve()
# 1) ลบไฟล์เดี่ยวด้วย path ตรง ๆ
@app.delete("/delete_by_path")
def delete_by_path(path: str):
    target = Path(path).resolve()
    if not str(target).startswith(str(BASE_ROOT)):
        raise HTTPException(status_code=400, detail="Invalid path: outside allowed base")

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    try:
        target.unlink()
        return {"status": "success", "deleted": str(target)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting file: {e}")


# 2) ลบทั้งโฟลเดอร์ (เช่น /data/local_storage/size)
#    - ถ้า recursive=false จะลบได้เฉพาะโฟลเดอร์ว่าง
#    - ถ้า recursive=true จะลบทั้งโฟลเดอร์และทุกไฟล์ย่อย
@app.delete("/delete_dir")
def delete_dir(path: str, recursive: bool = False):
    target = Path(path).resolve()
    if not str(target).startswith(str(BASE_ROOT)):
        raise HTTPException(status_code=400, detail="Invalid path: outside allowed base")

    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")

    try:
        if recursive:
            shutil.rmtree(target)
        else:
            target.rmdir()
        return {"status": "success", "deleted_dir": str(target), "recursive": recursive}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting directory: {e}")


# 3) ลบเป็นชุดด้วย pattern (เช่น size/*.json หรือ size/**/*.json)
@app.delete("/delete_glob")
def delete_glob(pattern: str):
    # สร้าง pattern ที่อยู่ใต้ BASE_ROOT เสมอ
    pattern_path = (BASE_ROOT / pattern.lstrip("/")).as_posix()
    matches = [Path(p).resolve() for p in glob.glob(pattern_path, recursive=True)]

    # กรองอีกชั้น กันหลุด base
    safe_matches = [p for p in matches if str(p).startswith(str(BASE_ROOT)) and p.is_file()]

    if not safe_matches:
        return {"status": "ok", "deleted_count": 0, "pattern": pattern}

    deleted = []
    errors = []
    for p in safe_matches:
        try:
            p.unlink()
            deleted.append(str(p))
        except Exception as e:
            errors.append({"path": str(p), "error": str(e)})

    return {
        "status": "ok",
        "pattern": pattern,
        "deleted_count": len(deleted),
        "deleted": deleted,
        "errors": errors
    }


# ===================== Entrypoint =====================
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("file_server:app", host="0.0.0.0", port=port)
