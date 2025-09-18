"""
File Server สำหรับ serve ไฟล์จาก Local Storage และ Output
"""

import os
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from local_storage import LocalStorage

app = FastAPI(title="Local File Server")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------------------------------------------------------
# [Railway] ปรับฐาน path ให้ configurable ผ่าน ENV และชี้ไปยัง Volume (/data)
# -----------------------------------------------------------------------------
STORAGE_DIR = Path(os.environ.get("STORAGE_DIR", "/data/local_storage"))  # [Railway]
OUTPUT_DIR  = Path(os.environ.get("OUTPUT_DIR",  "/data/output"))         # [Railway]
(STORAGE_DIR).mkdir(parents=True, exist_ok=True)                          # [Railway]
(OUTPUT_DIR / "size_output").mkdir(parents=True, exist_ok=True)           # [Railway]
(OUTPUT_DIR / "shrimp_output").mkdir(parents=True, exist_ok=True)         # [Railway]
(OUTPUT_DIR / "din_output").mkdir(parents=True, exist_ok=True)            # [Railway]
(OUTPUT_DIR / "water_output").mkdir(parents=True, exist_ok=True)          # [Railway]

# ===================== Mount static files =====================
# เสิร์ฟ local_storage ปกติ
app.mount("/storage", StaticFiles(directory=str(STORAGE_DIR)), name="storage")  # [Railway]

# เสิร์ฟ output/... -> /size|/shrimp|/din|/water
app.mount("/size",   StaticFiles(directory=str(OUTPUT_DIR / "size_output")),   name="size")     # [Railway]
app.mount("/shrimp", StaticFiles(directory=str(OUTPUT_DIR / "shrimp_output")), name="shrimp")   # [Railway]
app.mount("/din",    StaticFiles(directory=str(OUTPUT_DIR / "din_output")),    name="din")      # [Railway]
app.mount("/water",  StaticFiles(directory=str(OUTPUT_DIR / "water_output")),  name="water")    # [Railway]

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
    """
    Serve ไฟล์จาก file_id (ใช้ metadata.json)
    หมายเหตุ: โค้ดนี้ยังคงรูปแบบเดิมของโปรเจ็กต์ (ไม่เปลี่ยน logic ภายใน)
    """
    try:
        # โหลด metadata ใหม่ก่อนเสมอ
        LocalStorage.metadata = LocalStorage._load_metadata()  # คงรูปแบบเดิมตามโปรเจ็กต์
        
        file_info = LocalStorage.get_file_info(file_id)
        if not file_info:
            print(f"❌ ไม่พบไฟล์ใน metadata: {file_id}")
            raise HTTPException(status_code=404, detail="File not found")
        
        file_path = LocalStorage.get_file_path(file_id)
        if not file_path or not os.path.exists(file_path):
            print(f"❌ ไม่พบ path ของไฟล์จริง: {file_id}")
            raise HTTPException(status_code=404, detail="File not found")
        
        file_size = os.path.getsize(file_path)
        print(f"📁 Serve ไฟล์: {file_info['original_name']} ({file_size:,} bytes)")
        
        return FileResponse(
            path=file_path,
            filename=file_info["original_name"],
            media_type=file_info["mime_type"]
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดในการ serve ไฟล์ {file_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/list")
async def list_files():
    files = LocalStorage.list_files()
    return {
        "total_files": len(files),
        "files": files
    }

@app.get("/info/{file_id}")
async def get_file_info(file_id: str):
    file_info = LocalStorage.get_file_info(file_id)
    if not file_info:
        raise HTTPException(status_code=404, detail="File not found")
    return file_info

@app.delete("/files/{file_id}")
async def delete_file(file_id: str):
    success = LocalStorage.delete_file(file_id)
    if not success:
        raise HTTPException(status_code=404, detail="File not found")
    return {"message": "File deleted successfully"}

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "storage_path": str(LocalStorage.storage_path)
    }

# -----------------------------------------------------------------------------
# [Railway] เพิ่ม entrypoint สำหรับรันด้วยพอร์ตที่ Railway กำหนดผ่าน ENV PORT
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))  # ไม่ต้อง fix เป็น 8001
    uvicorn.run("file_server:app", host="0.0.0.0", port=port)
