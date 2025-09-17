import cv2
import os
from ultralytics import YOLO
from deep_sort_realtime.deepsort_tracker import DeepSort
import numpy as np
from datetime import datetime

# โหลดโมเดล YOLO
model_path = os.environ.get("MODEL_DIN", "./Model/din.pt")
model = YOLO(model_path)

# โหลด DeepSORT Tracker
tracker = DeepSort(max_age=30, n_init=3, max_cosine_distance=0.3)

# Threshold การเคลื่อนไหว
NO_MOVE_THRESHOLD = 2000
LIGHT_MOVE_THRESHOLD = 2500

shrimp_moved_once = set()
movement_status = {}
CONFIDENCE_THRESHOLD = 0.5


def analyze_video(input_path, original_name: str = None):
    """
    วิเคราะห์วิดีโอกุ้งดิ้น
    """
    if not os.path.exists(input_path):
        print(f"❌ ไม่พบวิดีโอ: {input_path}")
        return

    # โฟลเดอร์ output
    output_dir = os.environ.get("OUTPUT_DIN", "./output/din_output")
    os.makedirs(output_dir, exist_ok=True)

    base_name = os.path.splitext(original_name or os.path.basename(input_path))[0]
    output_video_path = os.path.join(output_dir, f"{base_name}.mp4")
    output_txt_path = os.path.join(output_dir, f"{base_name}.txt")

    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        print(f"❌ ไม่สามารถเปิดวิดีโอ: {input_path}")
        return

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    fps = int(cap.get(cv2.CAP_PROP_FPS))
    width, height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    out = cv2.VideoWriter(output_video_path,fourcc,fps,(width,height))

    prev_positions = {}

    while True:
        ret, frame = cap.read()
        if not ret: break

        results = model.predict(source=frame, conf=CONFIDENCE_THRESHOLD, verbose=False)
        boxes = results[0].boxes.xyxy.cpu().numpy()
        scores = results[0].boxes.conf.cpu().numpy()

        detections = [([x1,y1,x2-x1,y2-y1],score,None) for (x1,y1,x2,y2),score in zip(boxes,scores) if score>=CONFIDENCE_THRESHOLD]
        tracks = tracker.update_tracks(detections, frame=frame)

        for track in tracks:
            if not track.is_confirmed(): continue
            track_id = track.track_id
            x1,y1,x2,y2 = map(int, track.to_ltrb())
            cx,cy = (x1+x2)//2,(y1+y2)//2

            if track_id in prev_positions:
                dx,dy = cx-prev_positions[track_id][0], cy-prev_positions[track_id][1]
                dist = np.sqrt(dx**2+dy**2)
                if dist < NO_MOVE_THRESHOLD:
                    if track_id not in shrimp_moved_once: movement_status[track_id]="sick"
                    color=(0,0,255)
                elif dist < LIGHT_MOVE_THRESHOLD:
                    movement_status[track_id]="medium"; shrimp_moved_once.add(track_id); color=(0,255,255)
                else:
                    movement_status[track_id]="good"; shrimp_moved_once.add(track_id); color=(0,255,0)
            else:
                color=(255,255,0)

            prev_positions[track_id]=(cx,cy)
            label=f"id_{track_id} ({movement_status.get(track_id,'None')})"
            cv2.rectangle(frame,(x1,y1),(x2,y2),color,2)
            cv2.putText(frame,label,(x1,y1-5),cv2.FONT_HERSHEY_SIMPLEX,0.5,color,1)

        out.write(frame)

    cap.release(); out.release()

    total=len(prev_positions); moved=len(shrimp_moved_once)
    moved_percent=(moved/total)*100 if total>0 else 0
    overall_status="✅ สุขภาพดี" if moved_percent>=70 else "⚠️ อ่อนแรง" if moved_percent>=50 else "❌ มีตัวนิ่งเยอะ"

    with open(output_txt_path,"w",encoding="utf-8") as f:
        f.write(f"🦐 จำนวนกุ้งทั้งหมด: {total} ตัว\n")
        f.write(f"✅ เคยขยับ: {moved} ตัว ({moved_percent:.2f}%)\n")
        f.write(f"📊 สถานะรวม: {overall_status}\n\n")
        for tid in sorted(prev_positions.keys()):
            f.write(f"id_{tid}: {movement_status.get(tid,'รอข้อมูล')}\n")

    print(f"✅ บันทึกวิดีโอที่: {output_video_path}")
    print(f"📄 บันทึกผลข้อความที่: {output_txt_path}")
    return output_video_path, output_txt_path
