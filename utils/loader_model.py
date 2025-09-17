import os

# Path หลักที่เก็บโมเดลใน Railway Volume
BASE_MODEL_DIR = "/data/Model"

# ชื่อไฟล์โมเดลที่คุณจะอัปโหลดไปใน Volume
MODEL_FILES = {
    "size": "size.pt",   # โมเดลวัดขนาดกุ้ง
    "din": "din.pt",                              # โมเดลตรวจการเคลื่อนไหว (กุ้งดิ้น)
    "shrimp": "shrimp.pt",                        # โมเดลตรวจจับกุ้งลอย
    "water": "water_class.pt"                     # โมเดลวิเคราะห์น้ำ
}

def get_model_path(model_key: str) -> str:
    """
    คืนค่า path ของโมเดลตาม key
    :param model_key: เช่น "size", "din", "shrimp", "water"
    :return: path เต็มของโมเดล เช่น /data/Model/shrimp_keypoint6/weights/best.pt
    """
    if model_key not in MODEL_FILES:
        raise ValueError(f"❌ Unknown model key: {model_key}. ใช้ได้แค่ {list(MODEL_FILES.keys())}")
    
    model_path = os.path.join(BASE_MODEL_DIR, MODEL_FILES[model_key])
    
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"❌ Model file not found: {model_path}\n"
                                f"กรุณาอัปโหลดไฟล์ไปที่ Railway Volume (/data/Model)")
    print(f"✅ Using model: {model_path}")
    return model_path
