"""
File Server สำหรับ serve ไฟล์จาก Local Storage และ Output
"""

import os
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from local_storage import LocalStorage # ✅ ใช้ instance ที่สร้างไว้แล้ว

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
        file_info = LocalStorage.get_file_info(file_id)  # ✅ ใช้ instance
        if not file_info:
            raise HTTPException(status_code=404, detail="File not found")

        file_path = LocalStorage.get_file_path(file_id)  # ✅ ใช้ instance
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
async def list_files():
    files = LocalStorage.list_files()  # ✅ ใช้ instance
    return {
        "total_files": len(files),
        "files": files
    }

@app.get("/info/{file_id}")
async def get_file_info(file_id: str):
    file_info = LocalStorage.get_file_info(file_id)  # ✅ ใช้ instance
    if not file_info:
        raise HTTPException(status_code=404, detail="File not found")
    return file_info

@app.delete("/files/{file_id}")
async def delete_file(file_id: str):
    success = LocalStorage.delete_file(file_id)  # ✅ ใช้ instance
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

# ===================== Entrypoint =====================
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("file_server:app", host="0.0.0.0", port=port)

