from fastapi import FastAPI, UploadFile, File, HTTPException, Request
import shutil
import os
import uuid
import json
from typing import List
from datetime import datetime
import requests
import math
import paho.mqtt.client as mqtt
import uvicorn
import re
import glob

from process.size import analyze_shrimp
from process.shrimp import analyze_kuny
from process.din import analyze_video
from process.water import analyze_water
from local_storage import LocalStorage

# =============== FastAPI และ CORS ====================
app = FastAPI()

from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------------------------------
# [Railway] Config พื้นฐาน
# ------------------------------------------------------------------------------------
FILE_BASE_URL = os.environ.get("FILE_BASE_URL", "http://localhost:8001").rstrip("/")
LOCAL_STORAGE_BASE = os.environ.get("LOCAL_STORAGE_BASE", "/data/local_storage")
DATA_PONDS_DIR = os.environ.get("DATA_PONDS_DIR", "/data/data_ponds")

os.makedirs(LOCAL_STORAGE_BASE, exist_ok=True)
os.makedirs(DATA_PONDS_DIR, exist_ok=True)

storage = LocalStorage(storage_path=LOCAL_STORAGE_BASE, base_url=FILE_BASE_URL)

# ------------------------------------------------------------------------------------
# Helper: แปลง path → public URL
# ------------------------------------------------------------------------------------
def make_public_url(file_path: str) -> str:
    file_path = file_path.replace("\\", "/")  # กัน windows path

    if "/data/local_storage/size" in file_path:
        return f"{FILE_BASE_URL}/size/{os.path.basename(file_path)}"

    if "/data/local_storage/shrimp" in file_path:
        return f"{FILE_BASE_URL}/shrimp/{os.path.basename(file_path)}"

    if "/data/local_storage/din" in file_path:
        return f"{FILE_BASE_URL}/din/{os.path.basename(file_path)}"

    if "/data/local_storage/water" in file_path:
        return f"{FILE_BASE_URL}/water/{os.path.basename(file_path)}"

    # fallback
    return f"{FILE_BASE_URL}/{os.path.basename(file_path)}"



# ------------------------------------------------------------------------------------
# Helper: ดึงค่า length/weight จาก text_content
# ------------------------------------------------------------------------------------
def _extract_size_from_text(text: str):
    matches = re.findall(r"Shrimp\s+\d+:\s*([\d.]+)\s*cm\s*/\s*([\d.]+)\s*g", text)
    if matches:
        lengths = [float(m[0]) for m in matches]
        weights = [float(m[1]) for m in matches]
        avg_length = sum(lengths) / len(lengths)
        avg_weight = sum(weights) / len(weights)
        return avg_length, avg_weight
    return None, None

# ------------------------------------------------------------------------------------
# save_json_result (แก้ไขให้มี shrimp_size)
# ------------------------------------------------------------------------------------
def save_json_result(result_type, original_name,
                     output_image=None, output_text_path=None,
                     pond_number=None, total_larvae=None,
                     survival_rate=None, output_video=None):

    text_content = None
    if output_text_path and os.path.exists(output_text_path):
        with open(output_text_path, 'r', encoding='utf-8') as f:
            text_content = f.read()

    result_data = {
        "id": str(uuid.uuid4()),
        "type": result_type,
        "original_name": original_name,
        "timestamp": datetime.now().isoformat(),
        "pond_number": pond_number,
        "total_larvae": total_larvae,
        "survival_rate": survival_rate,
        "text_content": text_content
    }

    if output_image:
        if isinstance(output_image, list):
            result_data["output_image"] = [make_public_url(p) for p in output_image]
        else:
            result_data["output_image"] = make_public_url(output_image)

    if output_video:
        result_data["output_video"] = make_public_url(output_video)

    # ✅ เพิ่ม shrimp_size ถ้าเป็น result_type = "size"
    if result_type == "size":
        length_cm, weight_avg_g = _extract_size_from_text(text_content or "")
        result_data["shrimp_size"] = {
            "length_cm": length_cm,
            "weight_avg_g": weight_avg_g,
            "image_url": result_data.get("output_image")
        }

    save_dir = os.path.join(LOCAL_STORAGE_BASE, result_type)
    os.makedirs(save_dir, exist_ok=True)

    json_filename = f"{os.path.splitext(original_name)[0]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    json_path = os.path.join(save_dir, json_filename)

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(result_data, f, ensure_ascii=False, indent=2)

    return json_path

# ------------------------------------------------------------------------------------
# Helper: ดึง pond_id
# ------------------------------------------------------------------------------------
def extract_pond_id_from_filename(filename):
    match = re.search(r'pond(\d+)', filename)
    if match:
        return int(match.group(1))
    return None

def get_latest_pond_info_for_pond(data_ponds_dir, pond_id):
    pond_files = glob.glob(os.path.join(data_ponds_dir, f"pond_{pond_id}_*.json"))
    if not pond_files:
        return None, None
    pond_files.sort(reverse=True)
    latest_file = pond_files[0]
    with open(latest_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data.get("pond_id"), data.get("initial_stock")

# ------------------------------------------------------------------------------------
# API: /process
# ------------------------------------------------------------------------------------
@app.post("/process")
async def process_files(files: List[UploadFile] = File(...)):
    os.makedirs("input_raspi1", exist_ok=True)
    os.makedirs("input_raspi2", exist_ok=True)
    os.makedirs("input_video", exist_ok=True)

    results = []
    now_str = datetime.now().strftime("%Y%m%d_%H%M%S")

    for file in files:
        filename = file.filename
        filename_lower = filename.lower()
        ext = os.path.splitext(filename_lower)[-1]
        print(f"📦 Received file: {filename}")

        try:
            if ext in [".jpg", ".jpeg", ".png"]:
                content = await file.read()
                pond_id = extract_pond_id_from_filename(filename_lower)
                if pond_id is None:
                    raise HTTPException(status_code=400, detail="ไม่พบ pond_id ในชื่อไฟล์!")

                pond_number, total_larvae = get_latest_pond_info_for_pond(DATA_PONDS_DIR, pond_id)

                # Shrimp Floating
                if "shrimp_float" in filename_lower:
                    input_path = os.path.join("input_raspi2", f"shrimp_float_pond{pond_id}_{now_str}{ext}")
                    with open(input_path, "wb") as f:
                        f.write(content)

                    output_img_path, output_txt_path = analyze_kuny(input_path)

                    json_path = save_json_result(
                        result_type="shrimp",
                        original_name=filename,
                        output_image=output_img_path,
                        output_text_path=output_txt_path,
                        pond_number=pond_number,
                        total_larvae=total_larvae
                    )
                    results.append({"type": "shrimp_floating", "filename": filename, "json": json_path})

                # Shrimp Size
                elif "shrimp" in filename_lower:
                    input_path = os.path.join("input_raspi1", f"shrimp_pond{pond_id}_{now_str}{ext}")
                    with open(input_path, "wb") as f:
                        f.write(content)

                    output_img_path, output_txt_path = analyze_shrimp(input_path, total_larvae=total_larvae, pond_number=pond_number)

                    json_path = save_json_result(
                        result_type="size",
                        original_name=filename,
                        output_image=output_img_path,
                        output_text_path=output_txt_path,
                        pond_number=pond_number,
                        total_larvae=total_larvae
                    )
                    results.append({"type": "shrimp_size", "filename": filename, "json": json_path})

                # Water
                elif "water" in filename_lower:
                    input_path = os.path.join("input_raspi2", f"water_pond{pond_id}_{now_str}{ext}")
                    with open(input_path, "wb") as f:
                        f.write(content)

                    output_img_path, output_txt_path = analyze_water(input_path)

                    json_path = save_json_result(
                        result_type="water",
                        original_name=filename,
                        output_image=output_img_path,
                        output_text_path=output_txt_path,
                        pond_number=pond_number,
                        total_larvae=total_larvae
                    )
                    results.append({"type": "water_image", "filename": filename, "json": json_path})

                else:
                    raise HTTPException(status_code=400, detail="ชื่อไฟล์ไม่ถูกต้อง")

            # Video
            elif ext in [".mp4", ".avi", ".mov"]:
                pond_id = extract_pond_id_from_filename(filename_lower)
                if pond_id is None:
                    raise HTTPException(status_code=400, detail="ไม่พบ pond_id ในชื่อไฟล์!")

                pond_number, total_larvae = get_latest_pond_info_for_pond(DATA_PONDS_DIR, pond_id)

                input_path = os.path.join("input_video", f"video_pond{pond_id}_{now_str}{ext}")
                with open(input_path, "wb") as f:
                    shutil.copyfileobj(file.file, f)

                output_video_path, output_txt_path = analyze_video(input_path)

                json_path = save_json_result(
                    result_type="din",
                    original_name=filename,
                    output_video=output_video_path,
                    output_text_path=output_txt_path,
                    pond_number=pond_number,
                    total_larvae=total_larvae
                )
                results.append({"type": "shrimp_video", "filename": filename, "json": json_path})

            else:
                raise HTTPException(status_code=400, detail="ไม่รองรับไฟล์ประเภทนี้")

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"❗ Error processing {filename}: {e}")

    return {"status": "success", "message": f"✅ ประมวลผลไฟล์สำเร็จ {len(results)} รายการ", "results": results}

@app.post("/data_ponds")
async def receive_stock_json(request: Request):
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    required_keys = ["pond_id", "date", "initial_stock"]
    if not all(k in data for k in required_keys):
        raise HTTPException(status_code=400, detail="Missing required data fields")

    pond_id = data['pond_id']
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"pond_{pond_id}_{timestamp}.json"
    file_path = os.path.join(DATA_PONDS_DIR, filename)

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save stock data: {e}")

    print(f"✅ Saved pond JSON data: {file_path}")
    return {"status": "success", "saved_file": file_path}


SENSOR_DIR = os.environ.get("SENSOR_DIR", "/data/local_storage/sensor")  # [Railway]
os.makedirs(SENSOR_DIR, exist_ok=True)  # [Railway]

@app.post("/data")
async def receive_sensor_data(request: Request):
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    required_keys = ["pond_id", "ph", "temperature", "do", "timestamp"]
    if not all(k in data for k in required_keys):
        raise HTTPException(status_code=400, detail="Missing required fields")

    filename = f"sensor_{datetime.now().strftime('%Y%m%dT%H%M%S%f')}.json"
    file_path = os.path.join(SENSOR_DIR, filename)

    try:
        with open(file_path, "w", encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save sensor data: {e}")

    print(f"✅ Saved sensor JSON: {file_path}")
    return {"status": "success", "saved_file": file_path}

# -----------------------------------------------------------------------------
# [Railway] เพิ่ม entrypoint สำหรับรันด้วยพอร์ตที่ Railway กำหนดผ่าน ENV PORT


# =========================
# 1) CONFIG: โฟลเดอร์แหล่งข้อมูล (แก้ ENV ได้)
import asyncio

# =========================
# 1) CONFIG
# =========================
BASE_LOCAL = os.environ.get("LOCAL_STORAGE_ROOT", "/data/local_storage")
APP_STATUS_URL = os.environ.get("APP_STATUS_URL")   # ตั้งค่า ENV ใน Railway
APP_SIZE_URL   = os.environ.get("APP_SIZE_URL")     # ตั้งค่า ENV ใน Railway

FS_SENSOR_DIR = os.path.join(BASE_LOCAL, "sensor")
FS_SAN_DIR    = os.path.join(BASE_LOCAL, "san")
FS_WATER_DIR  = os.path.join(BASE_LOCAL, "water")
FS_SHRIMP_DIR = os.path.join(BASE_LOCAL, "shrimp")
FS_SIZE_DIR   = os.path.join(BASE_LOCAL, "size")
FS_DIN_DIR    = os.path.join(BASE_LOCAL, "din")

POND_STATUS_FILE = os.path.join(BASE_LOCAL, "pond_status.json")
SHRIMP_SIZE_FILE = os.path.join(BASE_LOCAL, "shrimp_size.json")

# =========================
# 2) HELPERS
# =========================
def _latest_json_in_dir(dir_path: str, pond_id: int | None = None):
    if not os.path.isdir(dir_path):
        return None, None
    files = glob.glob(os.path.join(dir_path, "*.json"))
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    if not files:
        return None, None
    for p in files:
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
            pid = d.get("pond_id", d.get("pond_number"))
            if pond_id is None or pid == pond_id:
                return p, d
        except:
            continue
    return None, None

def _pick_url_maybe_list(v):
    if isinstance(v, list):
        return v[0] if v else None
    return v

def _send_json_to(url: str, data: dict):
    """ส่ง JSON ไปยังปลายทาง ถ้าไม่ได้ตั้งค่า URL จะไม่ส่ง"""
    try:
        if not url:  # ✅ ป้องกันไม่ให้ยิงไปถ้าไม่มี URL
            print("ℹ️ Skip push: No URL set")
            return
        r = requests.post(url, json=data, timeout=6)
        if r.status_code == 200:
            print(f"✅ Sent to {url}")
        else:
            print(f"⚠️ App responded {r.status_code}: {r.text}")
    except Exception as e:
        print(f"❌ Push to app failed ({url}): {e}")

def _extract_size_from_json(size_json: dict):
    if "shrimp_size" in size_json:
        sc = size_json["shrimp_size"]
        return sc.get("length_cm"), sc.get("weight_avg_g")

    txt = size_json.get("text_content") or ""
    # ✅ Match pattern "Shrimp 1: 0.33 cm / 0.00 g"
    matches = re.findall(r"Shrimp\s+\d+:\s*([\d.]+)\s*cm\s*/\s*([\d.]+)\s*g", txt)
    if matches:
        lengths = [float(m[0]) for m in matches]
        weights = [float(m[1]) for m in matches]
        avg_length = sum(lengths) / len(lengths)
        avg_weight = sum(weights) / len(weights)
        return avg_length, avg_weight

    return None, None


# =========================
# 3) CACHE
# =========================
last_seen_data = {
    "sensor": None,
    "san": None,
    "water": None,
    "shrimp": None,
    "size": None,
    "din": None
}

# =========================
# 4) BUILDERS
# =========================
def build_pond_status_json(pond_id: int) -> dict:
    sensor_d = last_seen_data["sensor"]
    san_d    = last_seen_data["san"]
    water_d  = last_seen_data["water"]
    shrimp_d = last_seen_data["shrimp"]

    sensor_part = {"temperature": None, "ph": None, "do": None}
    if sensor_d:
        sensor_part = {
            "temperature": sensor_d.get("temperature"),
            "ph": sensor_d.get("ph"),
            "do": sensor_d.get("do"),
        }

    minerals = {"Mineral_1": 0.0, "Mineral_2": 0.0, "Mineral_3": 0.0, "Mineral_4": 0.0}
    if san_d:
        arr = san_d.get("remaining_g") or []
        for i in range(4):
            minerals[f"Mineral_{i+1}"] = float(arr[i]) if i < len(arr) else 0.0

    water_image = None
    water_color = "unknown"
    if water_d:
        water_image = _pick_url_maybe_list(water_d.get("output_image"))
        water_color = (water_d.get("text_content") or "").strip() or "unknown"

    shrimp_float_image = None
    if shrimp_d:
        shrimp_float_image = _pick_url_maybe_list(shrimp_d.get("output_image"))

    data = {
        "pond_id": pond_id,
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "sensor": sensor_part,
        "chemicals": minerals,
        "water": {"color": water_color, "image_url": water_image},
        "shrimp_float": {"image_url": shrimp_float_image},
        "status": "normal"
    }
    with open(POND_STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data

def build_shrimp_size_json(pond_id: int) -> dict:
    size_d = last_seen_data["size"]
    din_d  = last_seen_data["din"]

    size_image = None
    length_cm, weight_g = None, None
    if size_d:
        size_image = _pick_url_maybe_list(size_d.get("output_image"))
        length_cm, weight_g = _extract_size_from_json(size_d)

    video_url = None
    if din_d:
        video_url = din_d.get("output_video")

    data = {
        "pond_id": pond_id,
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "shrimp_size": {
            "length_cm": length_cm,
            "weight_avg_g": weight_g,
            "image_url": size_image
        },
        "shrimp_feed": {"image_url": size_image},
        "shrimp_video_url": video_url
    }
    with open(SHRIMP_SIZE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data

# =========================
# 5) BACKGROUND LOOP
# =========================
async def loop_build_and_push(pond_id: int):
    global last_seen_data
    while True:
        try:
            _, sensor_d = _latest_json_in_dir(FS_SENSOR_DIR, pond_id=pond_id)
            if sensor_d: last_seen_data["sensor"] = sensor_d

            _, san_d = _latest_json_in_dir(FS_SAN_DIR, pond_id=pond_id)
            if san_d: last_seen_data["san"] = san_d

            _, water_d = _latest_json_in_dir(FS_WATER_DIR, pond_id=pond_id)
            if water_d: last_seen_data["water"] = water_d

            _, shrimp_d = _latest_json_in_dir(FS_SHRIMP_DIR, pond_id=pond_id)
            if shrimp_d: last_seen_data["shrimp"] = shrimp_d

            _, size_d = _latest_json_in_dir(FS_SIZE_DIR, pond_id=pond_id)
            if size_d: last_seen_data["size"] = size_d

            _, din_d = _latest_json_in_dir(FS_DIN_DIR, pond_id=pond_id)
            if din_d: last_seen_data["din"] = din_d

            status_json = build_pond_status_json(pond_id)
            size_json   = build_shrimp_size_json(pond_id)

            # ✅ ส่งก็ต่อเมื่อมีการตั้งค่า ENV ไว้
            if APP_STATUS_URL:
                _send_json_to(APP_STATUS_URL, status_json)
            if APP_SIZE_URL:
                _send_json_to(APP_SIZE_URL, size_json)

        except Exception as e:
            print("❌ Loop error:", e)

        await asyncio.sleep(5)


@app.on_event("startup")
async def start_background():
    asyncio.create_task(loop_build_and_push(pond_id=1))

# =========================
# 6) ENDPOINTS
# =========================
@app.get("/ponds/{pond_id}/status")
def get_status(pond_id: int):
    if os.path.exists(POND_STATUS_FILE):
        with open(POND_STATUS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"error": "no pond_status.json yet"}

@app.get("/ponds/{pond_id}/shrimp_size")
def get_size(pond_id: int):
    if os.path.exists(SHRIMP_SIZE_FILE):
        with open(SHRIMP_SIZE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"error": "no shrimp_size.json yet"}



from fastapi.responses import JSONResponse
from pathlib import Path


@app.get("/list")
def list_dir(path: str = ""):
    """
    list directory/file ทั้งหมดจาก BASE_LOCAL (/data/local_storage) หรือ path ที่ส่งมา
    ใช้ query param เช่น ?path=sensor หรือ ?path=../input_raspi2
    """
    base = Path("/")   # จุดเริ่ม root ของ container
    target = (base / path).resolve()

    # ป้องกันไม่ให้หลุดออกนอก root
    if not str(target).startswith(str(base)):
        raise HTTPException(status_code=400, detail="Invalid path")

    if not target.exists():
        raise HTTPException(status_code=404, detail="Path not found")

    items = []
    for p in sorted(target.iterdir()):
        items.append({
            "name": p.name,
            "is_dir": p.is_dir(),
            "size": p.stat().st_size if p.is_file() else None,
            "path": str(p)
        })
    return JSONResponse(items)

from fastapi.responses import FileResponse
@app.get("/view")
def view_file(path: str):
    """
    ดูไฟล์ที่อยู่ใน container (เช่น JSON หรือ TXT)
    ใช้ query param เช่น /view?path=/data/local_storage/pond_status.json
    """
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, media_type="application/json")



@app.get("/json")
def read_json(path: str):
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading JSON: {e}")


# =========================
# 7) ENTRYPOINT
# =========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)