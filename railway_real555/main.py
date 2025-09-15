from fastapi import FastAPI, UploadFile, File, HTTPException, Request
import shutil
import os
import uuid
import json
from typing import List
from datetime import datetime
import requests

from process.size import analyze_shrimp
from process.shrimp import analyze_kuny
from process.din import analyze_video
from process.water import analyze_water
from local_storage import LocalStorage

import math
from datetime import datetime, timedelta
import paho.mqtt.client as mqtt

# =============== เปลี่ยนมาใช้ Gemini ===============
import google.generativeai as genai
genai.configure(api_key="YOUR_GOOGLE_API_KEY")   # ใส่ Google AI Studio API KEY ที่นี่

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
# [Railway] ตัดการพึ่งพา ngrok + ทำค่า BASE URL และ PATH ต่าง ๆ ให้อ่านจาก ENV
# ------------------------------------------------------------------------------------
FILE_BASE_URL = os.environ.get("FILE_BASE_URL", "http://localhost:8001").rstrip("/")  # [Railway] URL ของบริการ file-server อีกตัว
# ตัวอย่างบน Railway: FILE_BASE_URL="https://file-server.up.railway.app"

# ใช้โฟลเดอร์ที่ผูกกับ Railway Volume ได้ (เช่น /data) หรือ fallback เป็นโฟลเดอร์ local
LOCAL_STORAGE_BASE = os.environ.get("LOCAL_STORAGE_BASE", "/data/local_storage")       # [Railway]
DATA_PONDS_DIR = os.environ.get("DATA_PONDS_DIR", "/data/data_ponds")                  # [Railway]

os.makedirs(LOCAL_STORAGE_BASE, exist_ok=True)  # [Railway]
os.makedirs(DATA_PONDS_DIR, exist_ok=True)      # [Railway]

# LocalStorage ใช้ base_url เป็น FILE_BASE_URL (ชี้ไปยัง service ไฟล์จริง)
storage = LocalStorage(storage_path=LOCAL_STORAGE_BASE, base_url=FILE_BASE_URL)  # [Railway]

def make_public_url(file_path: str) -> str:
    """
    แปลง path ไฟล์เป็น URL สาธารณะ โดยอิง BASE URL ของ file server
    เดิมใช้ get_file_url() จาก ngrok ตอนนี้เปลี่ยนเป็นใช้ FILE_BASE_URL จาก ENV แทน
    """
    # ถ้าไฟล์อยู่ใน local_storage → map ปกติ
    if LOCAL_STORAGE_BASE in file_path:
        rel_path = os.path.relpath(file_path, LOCAL_STORAGE_BASE).replace("\\", "/")
        return f"{FILE_BASE_URL}/{rel_path}"  # [Railway]

    # ถ้าไฟล์อยู่ใน output/size_output → map ไปเป็น /size/
    if "output\\size_output" in file_path or "output/size_output" in file_path:
        filename = os.path.basename(file_path)
        return f"{FILE_BASE_URL}/size/{filename}"  # [Railway]

    # ถ้าไฟล์อยู่ใน output/shrimp_output → map ไปเป็น /shrimp/
    if "output\\shrimp_output" in file_path or "output/shrimp_output" in file_path:
        filename = os.path.basename(file_path)
        return f"{FILE_BASE_URL}/shrimp/{filename}"  # [Railway]

    # ถ้าไฟล์อยู่ใน output/din_output → map ไปเป็น /din/
    if "output\\din_output" in file_path or "output/din_output" in file_path:
        filename = os.path.basename(file_path)
        return f"{FILE_BASE_URL}/din/{filename}"  # [Railway]

    # ถ้าไฟล์อยู่ใน output/water_output → map ไปเป็น /water/
    if "output\\water_output" in file_path or "output/water_output" in file_path:
        filename = os.path.basename(file_path)
        return f"{FILE_BASE_URL}/water/{filename}"  # [Railway]

    # fallback (กรณีอื่น ๆ)
    return f"{FILE_BASE_URL}/{os.path.basename(file_path)}"  # [Railway]

def save_json_result(result_type, original_name, output_image=None, output_text_path=None, pond_number=None, total_larvae=None, survival_rate=None, output_video=None):
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

    save_dir = os.path.join(LOCAL_STORAGE_BASE, result_type)
    os.makedirs(save_dir, exist_ok=True)

    json_filename = f"{os.path.splitext(original_name)[0]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    json_path = os.path.join(save_dir, json_filename)

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(result_data, f, ensure_ascii=False, indent=2)

    return json_path

import re
import glob
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
    pond_id = data.get("pond_id", None)
    initial_stock = data.get("initial_stock", None)
    return pond_id, initial_stock

@app.post("/process")
async def process_files(files: List[UploadFile] = File(...)):
    # folder input ชั่วคราว (อยู่ใน container ของ service นี้)
    os.makedirs("input_raspi1", exist_ok=True)
    os.makedirs("input_raspi2", exist_ok=True)
    os.makedirs("input_video", exist_ok=True)

    results = []

    for file in files:
        filename = file.filename  # ชื่อไฟล์ต้นฉบับ
        filename_lower = filename.lower()
        ext = os.path.splitext(filename_lower)[-1]
        now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        print(f"📦 Received file: {filename}")

        try:
            if ext in [".jpg", ".jpeg", ".png"]:
                content = await file.read()
                pond_id = extract_pond_id_from_filename(filename_lower)
                if pond_id is None:
                    raise HTTPException(status_code=400, detail="ไม่พบ pond_id ในชื่อไฟล์!")

                pond_number, total_larvae = get_latest_pond_info_for_pond(DATA_PONDS_DIR, pond_id)

                # ================= Shrimp Floating =================
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
                    results.append({
                        "type": "shrimp_floating",
                        "filename": filename,
                        "json": json_path
                    })

                # ================= Shrimp Size =================
                elif "shrimp" in filename_lower:
                    input_path = os.path.join("input_raspi1", f"shrimp_pond{pond_id}_{now_str}{ext}")
                    with open(input_path, "wb") as f:
                        f.write(content)

                    output_img_path, output_txt_path = analyze_shrimp(
                        input_path,
                        total_larvae=total_larvae,
                        pond_number=pond_number
                    )

                    json_path = save_json_result(
                        result_type="size",
                        original_name=filename,
                        output_image=output_img_path,
                        output_text_path=output_txt_path,
                        pond_number=pond_number,
                        total_larvae=total_larvae
                    )
                    results.append({
                        "type": "shrimp_size",
                        "filename": filename,
                        "json": json_path
                    })

                # ================= Water =================
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
                    results.append({
                        "type": "water_image",
                        "filename": filename,
                        "json": json_path
                    })

                else:
                    raise HTTPException(status_code=400, detail="ชื่อไฟล์ไม่ถูกต้อง")

            # ================= Video =================
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
                results.append({
                    "type": "shrimp_video",
                    "filename": filename,
                    "json": json_path
                })

            else:
                raise HTTPException(status_code=400, detail="ไม่รองรับไฟล์ประเภทนี้")

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"❗ Error processing {filename}: {e}")

    return {
        "status": "success",
        "message": f"✅ ประมวลผลไฟล์สำเร็จ {len(results)} รายการ",
        "results": results
    }

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

# ================= Gemini Q&A API ====================
@app.post("/ask")
async def ask_bot(request: Request):
    try:
        data = await request.json()
        question = data.get("question", "").strip()
        if not question:
            return {"answer": "กรุณาพิมพ์คำถาม"}
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = f"""
คุณคือผู้เชี่ยวชาญด้านกุ้งก้ามกรามและเกษตรกรไทย
- คุณชื่อShrimpSenseเท่านั้น เวลาตอบคำถามต้องขึ้นต้นด้วยด้วยว่า"สวัสดีครับพวกเราShrimpSense" 
-ถ้าถามเรื่องเกี่ยวกับการยกยอเนี่ย ให้ตอบประมาณว่า การยกยอปกติจะยก2ครั้งช่วงเช้าและเย็น
***ใช้ภาษาไทยง่ายๆ เหมือนคุยกับชาวบ้าน***

{question}
"""
        response = model.generate_content(prompt)
        answer = response.text.strip()
    except Exception as e:
        answer = f"เกิดข้อผิดพลาดกับ Gemini API: {e}"
    
    return {"answer": answer}

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
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))  # [Railway]
    uvicorn.run("main:app", host="0.0.0.0", port=port)
