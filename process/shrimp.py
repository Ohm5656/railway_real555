import cv2
from ultralytics import YOLO
import os

# โหลดโมเดลกุ้งลอยน้ำจากโฟลเดอร์ Model/
model_path = os.environ.get("MODEL_SHRIMP", os.path.join("Model", "shrimp.pt"))
model = YOLO(model_path)

output_folder = os.environ.get("OUTPUT_SHRIMP", "./output/shrimp_output")
os.makedirs(output_folder, exist_ok=True)

def analyze_kuny(image_path, original_name: str = None):
    image = cv2.imread(image_path)
    if image is None:
        raise ValueError(f"❌ ไม่พบภาพที่ path: {image_path}")

    results = model.predict(image_path)
    shrimp_count, info_list = 0, []

    for r in results:
        for box in r.boxes:
            cls_id = int(box.cls[0])
            name = r.names[cls_id]
            if name.lower() == "shrimp":
                shrimp_count += 1
                label = f"shrimp float id{shrimp_count}"
                info_list.append(label)

                x1, y1, x2, y2 = box.xyxy[0].int().tolist()
                cv2.rectangle(image, (x1, y1), (x2, y2), (255, 0, 0), 2)
                cv2.putText(image, label, (x1, y1-10),
                            cv2.FONT_HERSHEY_SIMPLEX, 2.0, (255, 0, 0), 10)

    header_text, color = ("HAVE SHRIMPS", (0, 0, 255)) if shrimp_count > 0 else ("NO SHRIMP", (0, 255, 0))
    cv2.putText(image, header_text, (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.5, color, 5)

    filename = os.path.splitext(original_name or os.path.basename(image_path))[0]

    txt_path = os.path.join(output_folder, f"{filename}.txt")
    text = f"🦐 พบกุ้งลอยผิวน้ำ {shrimp_count} ตัว\n" + "\n".join(info_list) if shrimp_count > 0 else "🆗 ไม่พบกุ้งลอยผิวน้ำในภาพนี้"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(text)

    image_output_path = os.path.join(output_folder, f"{filename}.jpg")
    cv2.imwrite(image_output_path, image)

    print("✅ ประมวลผลเสร็จ:", text)
    return image_output_path, txt_path
