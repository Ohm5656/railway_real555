# =========================
# Base image
# =========================
FROM python:3.10-slim

# =========================
# ติดตั้ง System packages ที่จำเป็น (แก้ปัญหา libGL.so.1)
# =========================
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# =========================
# ตั้ง working directory
# =========================
WORKDIR /app

# =========================
# คัดลอก requirements.txt และติดตั้ง Python dependencies
# =========================
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# =========================
# คัดลอกไฟล์ทั้งหมดเข้า container
# =========================
COPY . .

# =========================
# Run FastAPI app ด้วย Uvicorn
# =========================
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
