import cv2
import math
from ultralytics import YOLO
import os
from datetime import datetime
import numpy as np
from utils.loader_model import download_and_extract_model

# ===================== โหลดโมเดล =====================
MODEL_DIR = download_and_extract_model()
# ใช้ ENV กำหนด path ได้ ถ้าไม่มีจะ default ไปที่โมเดลในโฟลเดอร์ที่แตกจาก Model.zip
model_path = os.environ.get("MODEL_SIZE", os.path.join(MODEL_DIR, "shrimp_keypoint6/weights/best.pt"))
model = YOLO(model_path)
class_id = 0


# ===================== Helper Function =====================
def get_thai_datetime_string(dt):
    day, month, year = dt.day, dt.month, dt.year + 543
    time_str = dt.strftime("%H:%M")
    return f"{day:02d}/{month:02d}/{year} เวลา {time_str}"


def get_feed_plan(weight_avg):
    if weight_avg <= 2: return 6.0, 3
    elif weight_avg <= 5: return 5.0, 4
    elif weight_avg <= 10: return 4.7, '4หรือ5'
    elif weight_avg <= 15: return 3.5, 5
    elif weight_avg <= 20: return 3.2, 6
    elif weight_avg <= 25: return 2.8, 6
    elif weight_avg <= 30: return 2.5, 6
    elif weight_avg <= 50: return 2.0, 6
    else: return 2.0, 6


def calc_feed_per_day(avg_weight, n_alive, feed_percent):
    total_biomass = avg_weight * n_alive
    feed_amount = total_biomass * (feed_percent / 100)
    return feed_amount, total_biomass


def get_cumulative_survival(total_larvae, weight_avg):
    survival_table = [(2,1.00),(5,0.97),(10,0.95),(20,0.93),(30,0.90),(50,0.88),(9999,0.85)]
    n_current = total_larvae
    print("\n📊 คำนวนอัตรารอดแต่ละช่วง (สะสม):")
    for threshold, rate in survival_table:
        print(f" - น้ำหนัก < {threshold} g: x {rate:.2f} (เหลือ {int(n_current*rate)})")
        n_current *= rate
        if weight_avg <= threshold: break
    survival_rate_cumulative = n_current / total_larvae
    print(f"✅ Survival Rate (cumulative): {survival_rate_cumulative*100:.2f}%")
    print(f"✅ กุ้งรอดสะสม: {int(n_current)} ตัว\n")
    return survival_rate_cumulative, int(n_current)


# ===================== Main Function =====================
def analyze_shrimp(input_path, total_larvae=None, pond_number=None,
                   known_lengths=None, known_weights=None,
                   a_weight=None, b_weight=None, pixel_per_cm=13):
    print("\n🚀 เริ่มการวิเคราะห์กุ้ง (size.py)")
    DEFAULT_A, DEFAULT_B = 0.0089, 3.0751
    a, b = a_weight or DEFAULT_A, b_weight or DEFAULT_B
    print(f"📘 ใช้ค่า a={a:.5f}, b={b:.3f} (มาตรฐานไทย)")

    # ===================== PATH =====================
    output_dir_output = os.environ.get("OUTPUT_SIZE", "./output/size_output")
    os.makedirs(output_dir_output, exist_ok=True)
    # =================================================

    now = datetime.now()
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    thai_datetime_str = get_thai_datetime_string(now)
    filename = os.path.splitext(os.path.basename(input_path))[0]

    output_img_path_output = os.path.join(output_dir_output, f"{filename}_{timestamp}.jpg")
    output_txt_path_output = os.path.join(output_dir_output, f"{filename}_{timestamp}.txt")

    # ===================== RUN YOLO =====================
    results = model(input_path)
    img = cv2.imread(input_path)
    shrimp_data = []

    for result in results:
        if result.keypoints is None or result.boxes is None: 
            continue
        keypoints = result.keypoints.xy.cpu().numpy()
        boxes_cls = result.boxes.cls.cpu().numpy() if result.boxes.cls is not None else []
        boxes_conf = result.boxes.conf.cpu().numpy() if result.boxes.conf is not None else []

        for i, kp in enumerate(keypoints):
            if i >= len(boxes_cls) or i >= len(boxes_conf): 
                continue
            if int(boxes_cls[i]) != class_id or boxes_conf[i] <= 0.5: 
                continue
            if len(kp) < 3: 
                continue

            head, middle, tail = kp[0], kp[1], kp[2]
            dist = lambda p1,p2: math.sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)
            total_length_cm = (dist(head, middle)+dist(middle, tail)) / pixel_per_cm
            weight = a * (total_length_cm ** b)
            shrimp_data.append((head[0], head[1], total_length_cm, weight))

            for (x,y) in [head,middle,tail]:
                cv2.circle(img,(int(x),int(y)),5,(0,255,0),-1)
            cv2.line(img,(int(head[0]),int(head[1])),(int(middle[0]),int(middle[1])),(255,0,0),2)
            cv2.line(img,(int(middle[0]),int(middle[1])),(int(tail[0]),int(tail[1])),(255,0,0),2)

    # ===================== สรุปผล =====================
    shrimp_data.sort(key=lambda p:(p[1],p[0]))
    output_lines = []
    print(f"\n🦐 พบกุ้งทั้งหมด: {len(shrimp_data)} ตัว")
    for idx,(x,y,length_cm,weight_g) in enumerate(shrimp_data,start=1):
        print(f" - Shrimp {idx}: {length_cm:.2f} cm / {weight_g:.2f} g")
        cv2.putText(img,f"{idx}",(int(x),int(y)-15),cv2.FONT_HERSHEY_SIMPLEX,0.7,(0,0,255),2,cv2.LINE_AA)
        cv2.putText(img,f"{weight_g:.1f}g",(int(x),int(y)+15),cv2.FONT_HERSHEY_SIMPLEX,0.5,(0,255,255),1,cv2.LINE_AA)
        output_lines.append(f"Shrimp {idx}: {length_cm:.2f} cm / {weight_g:.2f} g")

    count = len(shrimp_data)
    avg_weight = np.mean([w for *_,w in shrimp_data]) if shrimp_data else 0
    survival_rate_cumulative, n_alive = get_cumulative_survival(total_larvae, avg_weight)

    feed_percent, feed_size = get_feed_plan(avg_weight)
    feed_g_per_day, total_weight = calc_feed_per_day(avg_weight, n_alive, feed_percent)
    morning_feed, evening_feed = feed_g_per_day*0.3, feed_g_per_day*0.7

    summary_lines = [
        f"วันที่ {thai_datetime_str}",
        f"บ่อ {pond_number}",
        f"จำนวนกุ้งบนยอ : {count}",
        *output_lines,
        f"น้ำหนักกุ้งเฉลี่ยต่อตัว: {avg_weight:.2f} g",
        f"อัตราการรอด: {survival_rate_cumulative*100:.1f}%",
        f"จำนวนกุ้งที่เหลืออยู่: {n_alive}",
        f"น้ำหนักกุ้งทั้งบ่อ: {total_weight/1000:.2f} kg",
        f"ขนาดอาหารที่ควรใช้: เบอร์ {feed_size}",
        f"ปริมาณอาหารที่ควรให้: {feed_g_per_day/1000:.2f} kg",
        f" - ตอนเช้า: {morning_feed/1000:.2f} kg",
        f" - ตอนเย็น: {evening_feed/1000:.2f} kg",
    ]

    # ===================== Save Output =====================
    cv2.imwrite(output_img_path_output, img)
    with open(output_txt_path_output,"w",encoding="utf-8") as f:
        f.write("\n".join(summary_lines))

    print(f"\n✅ บันทึกรูปภาพ: {output_img_path_output}")
    print(f"✅ บันทึกผลลัพธ์: {output_txt_path_output}\n")

    return output_img_path_output, output_txt_path_output
