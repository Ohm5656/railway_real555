import os

# ===============================
# PATH CONFIG (Railway Persistent Volume)
# ===============================
# ที่เก็บโมเดลทั้งหมด
BASE_MODEL_DIR = "/data/Model"

# ชื่อไฟล์โมเดลหลักที่ถูก unzip ลงมาจาก Model.zip
MODEL_FILES = {
    "size": "size.pt",        # โมเดลวัดขนาดกุ้ง
    "din": "din.pt",          # โมเดลตรวจการเคลื่อนไหว (กุ้งดิ้น)
    "shrimp": "shrimp.pt",    # โมเดลตรวจจับกุ้งลอย
    "water": "water_class.pt" # โมเดลวิเคราะห์คุณภาพน้ำ
}

def get_model_path(model_key: str) -> str:
    """
    คืนค่า path เต็มของโมเดลที่อยู่ใน Railway Volume
    :param model_key: เช่น "size", "din", "shrimp", "water"
    :return: path เต็มของไฟล์ เช่น /data/Model/shrimp.pt
    """
    if model_key not in MODEL_FILES:
        raise ValueError(
            f"❌ Unknown model key: {model_key}. "
            f"ใช้ได้แค่ {list(MODEL_FILES.keys())}"
        )
    
    # path เต็ม
    model_path = os.path.join(BASE_MODEL_DIR, MODEL_FILES[model_key])
    
    if not os.path.exists(model_path):
        raise FileNotFoundError(
            f"❌ Model file not found: {model_path}\n"
            f"👉 กรุณาตรวจสอบว่าได้ unzip Model.zip ลงใน /data/Model แล้ว"
        )
    
    print(f"✅ Using model: {model_path}")
    return model_path

