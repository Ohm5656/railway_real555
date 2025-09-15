import os
import requests
import zipfile

# Path สำหรับเก็บไฟล์โมเดล
MODEL_DIR = "/data/Model"
ZIP_PATH = "/data/Model.zip"

# Google Drive File ID ของ Model.zip
GDRIVE_ID = os.getenv("MODEL_ZIP_ID", "1oR_6mOC3eBWy9gC9VOQRPaOTVrR8Uffs")

def download_and_extract_model():
    os.makedirs(MODEL_DIR, exist_ok=True)

    # ถ้า Model.zip ยังไม่มี → โหลดจาก Google Drive
    if not os.path.exists(ZIP_PATH):
        print("📥 Downloading Model.zip from Google Drive...")
        url = f"https://drive.google.com/uc?id={GDRIVE_ID}&export=download"
        r = requests.get(url)
        with open(ZIP_PATH, "wb") as f:
            f.write(r.content)

    # แตกไฟล์
    print("📦 Extracting Model.zip...")
    with zipfile.ZipFile(ZIP_PATH, "r") as zip_ref:
        zip_ref.extractall(MODEL_DIR)

    print("✅ Models ready in:", MODEL_DIR)
    return MODEL_DIR
