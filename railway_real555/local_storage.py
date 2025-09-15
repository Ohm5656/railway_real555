"""
Local Cloud Storage Server
สร้าง local storage ที่มีฟีเจอร์เหมือน Firebase Cloud Storage
"""

import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
import json
from typing import Dict, List, Optional
import mimetypes

class LocalStorage:
    def __init__(self, storage_path: str = None, base_url: str = None):
        """
        Initialize Local Storage
        
        Args:
            storage_path: Path to storage directory
            base_url: Base URL for file access (e.g., https://file-server.up.railway.app)
        """
        # ---------------------------------------------------------------------
        # [Railway] ค่าเริ่มต้นอ่านจาก ENV เพื่อรองรับ deployment
        # ---------------------------------------------------------------------
        self.storage_path = Path(storage_path or os.environ.get("STORAGE_DIR", "/data/local_storage"))
        self.base_url = (base_url or os.environ.get("FILE_BASE_URL", "http://localhost:8001")).rstrip("/")

        # สร้างโฟลเดอร์ storage
        self.storage_path.mkdir(parents=True, exist_ok=True)
        (self.storage_path / "processed_images").mkdir(parents=True, exist_ok=True)
        (self.storage_path / "temp").mkdir(parents=True, exist_ok=True)
        
        # สร้างไฟล์ metadata
        self.metadata_file = self.storage_path / "metadata.json"
        self.metadata = self._load_metadata()
    
    def _load_metadata(self) -> Dict:
        """โหลด metadata จากไฟล์"""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def _save_metadata(self):
        """บันทึก metadata ลงไฟล์"""
        with open(self.metadata_file, 'w', encoding='utf-8') as f:
            json.dump(self.metadata, f, indent=2, ensure_ascii=False)
    
    def upload_file(self, file_path: str, destination_name: Optional[str] = None) -> Dict:
        """
        อัปโหลดไฟล์ไปยัง local storage
        
        Args:
            file_path: Path ของไฟล์ที่จะอัปโหลด
            destination_name: ชื่อไฟล์ใน storage (optional)
        
        Returns:
            Dict ที่มี download_url, file_id, size, created_at
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"ไม่พบไฟล์: {file_path}")
        
        # สร้างชื่อไฟล์
        if not destination_name:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            base_name = os.path.splitext(os.path.basename(file_path))[0]
            ext = os.path.splitext(file_path)[1]
            destination_name = f"processed_images/{base_name}_{timestamp}{ext}"
        
        # สร้าง file_id
        file_id = str(uuid.uuid4())
        
        # คัดลอกไฟล์ไปยัง storage
        dest_path = self.storage_path / destination_name
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, dest_path)
        
        # สร้าง download URL
        download_url = f"{self.base_url}/files/{file_id}"
        
        # บันทึก metadata
        file_info = {
            "file_id": file_id,
            "original_name": os.path.basename(file_path),
            "storage_path": str(destination_name),
            "download_url": download_url,
            "size": os.path.getsize(file_path),
            "mime_type": mimetypes.guess_type(file_path)[0] or "application/octet-stream",
            "created_at": datetime.now().isoformat(),
            "public": True
        }
        
        self.metadata[file_id] = file_info
        self._save_metadata()
        
        return {
            "download_url": download_url,
            "file_id": file_id,
            "size": file_info["size"],
            "created_at": file_info["created_at"]
        }
    
    def get_file_info(self, file_id: str) -> Optional[Dict]:
        """ดึงข้อมูลไฟล์จาก file_id"""
        # โหลด metadata ใหม่ทุกครั้ง
        self.metadata = self._load_metadata()
        return self.metadata.get(file_id)
    
    def list_files(self, prefix: str = "") -> List[Dict]:
        """แสดงรายการไฟล์ทั้งหมด"""
        # โหลด metadata ใหม่ก่อนเสมอ
        self.metadata = self._load_metadata()
        
        files = []
        for file_id, info in self.metadata.items():
            if prefix and not info["storage_path"].startswith(prefix):
                continue
            files.append({
                "file_id": file_id,
                "name": info["original_name"],
                "path": info["storage_path"],
                "download_url": info["download_url"],
                "size": info["size"],
                "created_at": info["created_at"]
            })
        return files
    
    def delete_file(self, file_id: str) -> bool:
        """ลบไฟล์จาก storage"""
        if file_id not in self.metadata:
            return False
        
        file_info = self.metadata[file_id]
        file_path = self.storage_path / file_info["storage_path"]
        
        try:
            if file_path.exists():
                file_path.unlink()
            del self.metadata[file_id]
            self._save_metadata()
            return True
        except Exception as e:
            print(f"Error deleting file: {e}")
            return False
    
    def get_file_path(self, file_id: str) -> Optional[str]:
        """ดึง path ของไฟล์จาก file_id"""
        # โหลด metadata ใหม่ก่อนเสมอ
        self.metadata = self._load_metadata()
        
        if file_id in self.metadata:
            return str(self.storage_path / self.metadata[file_id]["storage_path"])
        return None
    
    def cleanup_temp_files(self, max_age_hours: int = 24):
        """ลบไฟล์ชั่วคราวที่เก่าเกินไป"""
        temp_dir = self.storage_path / "temp"
        if not temp_dir.exists():
            return
        
        current_time = datetime.now()
        for file_path in temp_dir.iterdir():
            if file_path.is_file():
                file_age = current_time - datetime.fromtimestamp(file_path.stat().st_mtime)
                if file_age.total_seconds() > max_age_hours * 3600:
                    try:
                        file_path.unlink()
                        print(f"Deleted temp file: {file_path}")
                    except Exception as e:
                        print(f"Error deleting temp file {file_path}: {e}")

# -----------------------------------------------------------------------------
# [Railway] ลบการ import/พึ่งพา Ngrok_newChange ออก และคง helper แบบเดิมไว้
# -----------------------------------------------------------------------------
# ค่าเริ่มต้นจะอ่านจาก ENV (FILE_BASE_URL, STORAGE_DIR) ผ่านตัวสร้าง LocalStorage ด้านบน
local_storage = LocalStorage()  # [Railway]

def upload_to_local_storage(file_path: str, file_name: Optional[str] = None) -> tuple:
    """
    อัปโหลดไฟล์ไปยัง local storage
    
    Returns:
        tuple: (download_url, file_id)
    """
    result = local_storage.upload_file(file_path, file_name)
    return result["download_url"], result["file_id"]

def delete_from_local_storage(file_id: str) -> bool:
    """ลบไฟล์จาก local storage"""
    return local_storage.delete_file(file_id)

def get_local_storage_info(file_id: str) -> Optional[Dict]:
    """ดึงข้อมูลไฟล์จาก local storage"""
    return local_storage.get_file_info(file_id)

# Test function (รันเฉพาะตอนเรียกไฟล์นี้ตรง ๆ)
if __name__ == "__main__":
    test_file = "output_images/result_563000013844406-_2_.jpg"
    if os.path.exists(test_file):
        download_url, file_id = upload_to_local_storage(test_file)
        print(f"✅ อัปโหลดสำเร็จ!")
        print(f"📥 Download URL: {download_url}")
        print(f"🆔 File ID: {file_id}")
        
        files = local_storage.list_files()
        print(f"\n📁 รายการไฟล์ใน Local Storage ({len(files)} ไฟล์):")
        for file_info in files:
            print(f"  📄 {file_info['name']} ({file_info['size']} bytes)")
            print(f"     🔗 {file_info['download_url']}")
    else:
        print(f"⚠️  ไม่พบไฟล์ทดสอบ: {test_file}")
