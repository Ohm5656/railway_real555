# ใช้ Python 3.10 ที่เบา (slim)
FROM python:3.10-slim

# ตั้ง working directory
WORKDIR /app

# ติดตั้ง system dependencies ที่จำเป็นสำหรับ OpenCV
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# คัดลอก requirements.txt เข้าไป
COPY requirements.txt .

# ติดตั้ง dependencies
RUN pip install --no-cache-dir -r requirements.txt

# คัดลอกไฟล์ทั้งหมดเข้า container
COPY . .

# คำสั่งรัน FastAPI ด้วย uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
