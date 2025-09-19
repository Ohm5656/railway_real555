import cv2
import os
from ultralytics import YOLO

# โหลดโมเดลสีน้ำจากโฟลเดอร์ Model/
model_path = os.environ.get("MODEL_WATER", os.path.join("Model", "water_class.pt"))
model = YOLO(model_path)

output_folder = os.environ.get("OUTPUT_WATER", "/data/output/water_output")
os.makedirs(output_folder, exist_ok=True)

def analyze_water(image_path: str, original_name: str = None):
    image = cv2.imread(image_path)
    if image is None:
        raise ValueError(f"❌ ไม่พบภาพที่ path: {image_path}")

    results = model.predict(image_path)
    top1_id = results[0].probs.top1
    class_name = results[0].names[top1_id]
    confidence = results[0].probs.data[top1_id].item()
    result_text = f"{class_name} ({confidence * 100:.0f}%)"

    base_filename = os.path.splitext(original_name or os.path.basename(image_path))[0]

    txt_path = os.path.join(output_folder, f"{base_filename}.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(result_text)

    image_output_path = os.path.join(output_folder, f"{base_filename}.jpg")
    cv2.imwrite(image_output_path, image)

    print(f"✅ วิเคราะห์สีน้ำ: {result_text}")
    return image_output_path, txt_path
