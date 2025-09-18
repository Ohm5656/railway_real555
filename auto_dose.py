import os
import math
import json
import time
from datetime import datetime, timedelta
import paho.mqtt.client as mqtt
import glob

# ================= CONFIG =================
RADIUS_CM = 6.5
HEIGHT_CM = 6.5
BULK_DENSITY = 0.8        # g/cm³ ความหนาแน่นของสารผง
LIQUID_PER_ROUND = 750

MQTT_BROKER = "broker.emqx.io"
MQTT_PORT = 1883
TOPIC_CMD = "pond/doser/cmd"       # backend → Arduino
TOPIC_STATUS = "pond/doser/status" # Arduino → backend (ส่ง ultrasonic)

# ✅ Path (Windows ใช้ full path, Railway ใช้ relative)
SENSOR_BASE = os.environ.get("SENSOR_BASE", "./local_storage/sensor")
POND_INFO_BASE = os.environ.get("POND_INFO_BASE", "./data_ponds")
TXT_WATER_DIR = os.environ.get("TXT_WATER_DIR", "./output/water_output")
SAN_BASE = os.environ.get("SAN_BASE", "./local_storage/san")
os.makedirs(SAN_BASE, exist_ok=True)

# =================================================
# ฟังก์ชันคำนวณสารที่เหลือ
# =================================================
def calc_remaining(distance_cm):
    """
    คำนวณน้ำหนักสารที่เหลือ (g) โดยเทียบเชิงเส้นจากค่าที่กำหนด
    ยิ่ง distance_cm มาก → ของเหลือน้อย
    ตัวอย่าง: ที่ 5 cm = 200 g, ที่ 10 cm = 100 g
    """
    # ✅ กำหนดค่าอ้างอิงเอง
    ref_points = {
        5: 200.0,   # 5 cm → 200 g
        10: 100.0,  # 10 cm → 100 g
        0: 300.0,   # 0 cm (เต็ม) → 300 g
        15: 0.0     # 15 cm (หมด) → 0 g
    }

    # ถ้าวัดได้ตรงกับที่กำหนดพอดี
    if distance_cm in ref_points:
        return ref_points[distance_cm]

    # หา 2 จุดที่ครอบระยะนี้
    keys = sorted(ref_points.keys())
    for i in range(len(keys) - 1):
        x1, x2 = keys[i], keys[i + 1]
        if x1 <= distance_cm <= x2:
            y1, y2 = ref_points[x1], ref_points[x2]
            # ✅ คำนวณแบบ linear interpolation (บัญญัติไตรยางค์)
            weight = y1 + (y2 - y1) * (distance_cm - x1) / (x2 - x1)
            return round(weight, 1)

    # ถ้าเกินช่วง → คืน 0
    return 0.0


def handle_san_status(data):
    """
    รับ ultrasonic จาก Arduino → คำนวณสารเหลือ → บันทึก JSON
    Example payload:
    {
      "pond_id": 1,
      "distances": [3.2, 4.0, 2.5, 6.5]
    }
    """
    try:
        pond_id = data.get("pond_id", 1)
        distances = data.get("distances", [])

        if not distances or len(distances) != 4:
            print("[WARN] ข้อมูล ultrasonic ไม่ครบ 4 ช่อง")
            return

        remaining_list = [calc_remaining(d) for d in distances]

        record = {
            "timestamp": datetime.now().isoformat(),
            "pond_id": pond_id,
            "distances_cm": distances,
            "remaining_g": remaining_list
        }

        save_path = os.path.join(
            SAN_BASE, f"san_{pond_id}_{datetime.now().strftime('%Y%m%dT%H%M%S')}.json"
        )
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

        print(f"[SAVE] ✅ บันทึกไฟล์ {save_path}")
        print(f"   → สารเหลือในแต่ละกล่อง (g): {remaining_list}")

    except Exception as e:
        print(f"[ERROR] handle_san_status: {e}")

# =================================================
# MQTT setup
# =================================================
def on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode("utf-8")
        data = json.loads(payload)
        print(f"[MQTT] 📩 รับจาก {msg.topic}: {data}")

        if "distances" in data:
            handle_san_status(data)

    except Exception as e:
        print(f"[ERROR] on_message: {e}")

def setup_mqtt():
    client = mqtt.Client()
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.subscribe(TOPIC_STATUS)
    client.loop_start()
    return client

mqttc = setup_mqtt()

# =================================================
# ฟังก์ชัน auto_dose (เดิม)
# =================================================
def get_powder_weight_per_round():
    volume = math.pi * (RADIUS_CM ** 2) * HEIGHT_CM
    return volume * BULK_DENSITY

def calc_powder_rounds(grams):
    return grams / get_powder_weight_per_round()

def calc_liquid_rounds(ml):
    return ml / LIQUID_PER_ROUND

def send_servo_command(rounds_array, pond_id=1):
    cmd = {
        "type": "dose_servo",
        "pond_id": pond_id,
        "rounds": [int(round(x)) for x in rounds_array],
        "speed": 1.0
    }
    try:
        mqttc.publish(TOPIC_CMD, json.dumps(cmd), qos=1)
        print(f"[MQTT] ✅ ส่งคำสั่งเซอร์โว: {cmd}")
    except Exception as e:
        print(f"[ERROR] MQTT publish ล้มเหลว: {e}")

def should_dose_green_extract(txt):
    txt = txt.lower()
    return "clear" in txt or "น้ำใส" in txt or "ใสเกิน" in txt

def read_latest_txt(txt_dir):
    txt_files = sorted(glob.glob(os.path.join(txt_dir, "*.txt")), key=os.path.getmtime, reverse=True)
    if txt_files:
        with open(txt_files[0], "r", encoding="utf-8") as f:
            return f.read().strip(), txt_files[0]
    return "", ""

def get_pond_info(pond_id):
    pond_files = sorted(
        glob.glob(os.path.join(POND_INFO_BASE, f"pond_{pond_id}_*.json")),
        key=os.path.getmtime, reverse=True
    )
    if not pond_files:
        print(f"[DEBUG] ❗ ไม่พบไฟล์ข้อมูลบ่อ pond_{pond_id}_*.json")
        return None
    with open(pond_files[0], "r", encoding="utf-8") as f:
        pond_info = json.load(f)
    print(f"[DEBUG] โหลดข้อมูลบ่อ pond_{pond_id} จาก {os.path.basename(pond_files[0])}")
    return pond_info

def process_auto_dose(pond_id, pond_size_rai, ph, temp, do, last_dose, txt_dir, now=None):
    if now is None:
        now = datetime.now()
    print(f"\n=== [DEBUG] ตรวจสอบบ่อ {pond_id} | ขนาด {pond_size_rai} ไร่ ===")
    print(f"เวลาปัจจุบัน: {now.isoformat()}")
    print(f"ค่าเซ็นเซอร์: pH={ph} | temp={temp} | DO={do}")

    ai_txt, _ = read_latest_txt(txt_dir)
    water_clear = should_dose_green_extract(ai_txt)
    print(f"[AI TXT] วิเคราะห์สีน้ำ: {ai_txt} | water_clear={water_clear}")

    # --- กำหนดเวลา ---
    hour = now.hour
    valid_morning_evening = (6 <= hour <= 8) or (16 <= hour <= 18)  # เช้า+เย็น
    valid_evening = (16 <= hour <= 18)  # เย็นอย่างเดียว

    # --- เวลาโดสล่าสุด ---
    def get_dt(name, default):
        try:
            return datetime.fromisoformat(last_dose[name])
        except Exception:
            return now - default

    last_probiotic = get_dt("probiotic", timedelta(days=8))
    last_caco3 = get_dt("caco3", timedelta(hours=12))
    last_mgso4 = get_dt("mgso4", timedelta(days=3))
    last_green_extract = get_dt("green_extract", timedelta(hours=24))

    # --- เตรียม array เก็บรอบหมุนเซอร์โว ---
    rounds_array = [0, 0, 0, 0]
    dosing_report = []

    # 1. โปรไบโอติก (ช่อง 0): ทุก 7 วัน
    if (now - last_probiotic) > timedelta(days=7) and valid_morning_evening:
        grams = 5 * float(pond_size_rai)  # 5 กรัมต่อไร่
        rounds = calc_powder_rounds(grams)
        rounds_array[0] = int(round(rounds))
        print(f"[ROUTINE] โปรไบโอติก {grams:.1f} g → {int(round(rounds))} รอบ")
        dosing_report.append(f"โปรไบโอติก {grams:.1f} g ({int(round(rounds))} รอบ)")

    # 2. CaCO₃ (ช่อง 1): ถ้า pH < 6.8
    if ph < 6.8 and (now - last_caco3) > timedelta(hours=8) and valid_morning_evening:
        grams = 2.5 * 1000 * float(pond_size_rai)  # 2.5 กก. ต่อไร่
        rounds = calc_powder_rounds(grams)
        rounds_array[1] = int(round(rounds))
        print(f"[ALERT] pH={ph} < 6.8 → CaCO₃ {grams:.1f} g → {int(round(rounds))} รอบ")
        dosing_report.append(f"CaCO₃ {grams:.1f} g ({int(round(rounds))} รอบ)")

    # 3. MgSO₄ (ช่อง 2): ถ้า temp > 30°C
    if temp > 30 and (now - last_mgso4) > timedelta(days=2) and valid_evening:
        grams = 2.5 * 1000 * float(pond_size_rai)  # 2.5 กก. ต่อไร่
        rounds = calc_powder_rounds(grams)
        rounds_array[2] = int(round(rounds))
        print(f"[ALERT] Temp={temp} > 30°C → MgSO₄ {grams:.1f} g → {int(round(rounds))} รอบ")
        dosing_report.append(f"MgSO₄ {grams:.1f} g ({int(round(rounds))} รอบ)")

    # 4. น้ำหมักพืชสีเขียว (ช่อง 3): ถ้าน้ำใสเกินหรือ pH < 6.8
    if (water_clear or ph < 6.8) and (now - last_green_extract) > timedelta(hours=20) and valid_morning_evening:
        ml = 150 * float(pond_size_rai)  # 150 ml ต่อไร่
        rounds = calc_liquid_rounds(ml)
        rounds_array[3] = int(round(rounds))
        cause = "น้ำใสเกิน" if water_clear else f"pH={ph} ต่ำ"
        print(f"[ALERT] {cause} → น้ำหมัก {ml:.1f} ml → {int(round(rounds))} รอบ")
        dosing_report.append(f"น้ำหมัก {ml:.1f} ml ({int(round(rounds))} รอบ)")

    # --- ส่งคำสั่งไปยัง Arduino ถ้ามีสารต้องปล่อย ---
    if any(rounds_array):
        send_servo_command(rounds_array, pond_id)
        print("[ACTION] ✅ ปล่อยสาร:", dosing_report)
    else:
        print("[ACTION] ❌ ไม่มีสารที่ต้องปล่อยในรอบนี้")

    return {
        "status": "success" if any(rounds_array) else "normal",
        "pond_id": pond_id,
        "pond_size_rai": pond_size_rai,
        "ph": ph,
        "temp": temp,
        "do": do,
        "auto_dosed": dosing_report,
        "rounds_array": rounds_array,
        "water_ai_txt": ai_txt
    }

# =================================================
# Monitor sensor + water
# =================================================
def monitor_sensor_and_water():
    print("=== [START] Monitor Sensor/Water File (FLAT sensor folder, check by pond_id) ===")
    last_txt_file = None
    pond_sensor_checked = {}  # pond_id -> set(sensor_file_names)

    while True:
        print(f"\n===== Loop @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} =====")
        # 1. Trigger จาก .txt สีน้ำ
        ai_txt, ai_txt_path = read_latest_txt(TXT_WATER_DIR)
        if ai_txt_path and ai_txt_path != last_txt_file and should_dose_green_extract(ai_txt):
            print(f"\n[TRIGGER] พบ .txt สีน้ำใหม่ ({os.path.basename(ai_txt_path)}) -> น้ำใส! (trigger ปล่อยน้ำหมัก)")
            # trigger ทุกบ่อ
            sensor_files = sorted(glob.glob(os.path.join(SENSOR_BASE, "sensor_*.json")), key=os.path.getmtime, reverse=True)
            pond_ids = set()
            for sf in sensor_files:
                with open(sf, "r", encoding="utf-8") as f:
                    d = json.load(f)
                pond_ids.add(str(d.get("pond_id", "1")))
            now = datetime.now()
            for pond_id in pond_ids:
                pond_info = get_pond_info(pond_id)
                pond_size_rai = pond_info.get("pond_size_rai", 1.0) if pond_info else 1.0
                ph, temp, do = 7, 29, 6
                last_dose = {
                    "probiotic": now - timedelta(days=8),
                    "caco3": now - timedelta(hours=12),
                    "mgso4": now - timedelta(days=3),
                    "green_extract": now - timedelta(hours=24),
                }
                process_auto_dose(
                    pond_id=pond_id,
                    pond_size_rai=pond_size_rai,
                    ph=ph,
                    temp=temp,
                    do=do,
                    last_dose=last_dose,
                    txt_dir=TXT_WATER_DIR,
                    now=now
                )
            last_txt_file = ai_txt_path

        # 2. Trigger sensor abnormal 5 ไฟล์ล่าสุดของแต่ละบ่อ
        sensor_files = sorted(glob.glob(os.path.join(SENSOR_BASE, "sensor_*.json")), key=os.path.getmtime, reverse=True)
        pond_files_map = {}
        for sf in sensor_files:
            with open(sf, "r", encoding="utf-8") as f:
                d = json.load(f)
            pond_id = str(d.get("pond_id", "1"))
            pond_files_map.setdefault(pond_id, []).append(sf)

        for pond_id, pond_files in pond_files_map.items():
            if len(pond_files) < 5:
                print(f"[DEBUG] pond_id={pond_id} มีไฟล์ sensor น้อยกว่า 5")
                continue
            # ห้าไฟล์ล่าสุดของบ่อนี้
            recent_files = pond_files[:5]
            sensor_set = tuple(os.path.basename(f) for f in recent_files)
            if pond_id in pond_sensor_checked and pond_sensor_checked[pond_id] == sensor_set:
                continue  # checked
            ph_list, temp_list, do_list = [], [], []
            all_ph_low = True
            all_temp_high = True
            all_do_low = True
            print(f"[DEBUG] {pond_id}: sensor set {[os.path.basename(f) for f in recent_files]}")
            for i, jf in enumerate(recent_files):
                with open(jf, "r", encoding="utf-8") as f:
                    d = json.load(f)
                ph = float(d.get("ph", 7))
                temp = float(d.get("temperature", 29))
                do = float(d.get("do", 6))
                ph_list.append(ph)
                temp_list.append(temp)
                do_list.append(do)
                print(f"    [{i+1}] {os.path.basename(jf)} | ph={ph} temp={temp} do={do}")
                if ph >= 6.8:
                    all_ph_low = False
                if temp <= 30:
                    all_temp_high = False
                if do >= 5.0:
                    all_do_low = False
            print(f"    all_ph_low={all_ph_low}, all_temp_high={all_temp_high}, all_do_low={all_do_low}")
            should_dose = all_ph_low or all_temp_high or all_do_low
            print(f"    should_dose={should_dose}")
            if should_dose:
                pond_info = get_pond_info(pond_id)
                pond_size_rai = pond_info.get("pond_size_rai", 1.0) if pond_info else 1.0
                now = datetime.now()
                last_dose = {
                    "probiotic": now - timedelta(days=8),
                    "caco3": now - timedelta(hours=12),
                    "mgso4": now - timedelta(days=3),
                    "green_extract": now - timedelta(hours=24),
                }
                print(f"\n[TRIGGER] Sensor abnormal 5 ไฟล์ล่าสุด {pond_id} → ปล่อยสาร")
                process_auto_dose(
                    pond_id=pond_id,
                    pond_size_rai=pond_size_rai,
                    ph=ph_list[0],
                    temp=temp_list[0],
                    do=do_list[0],
                    last_dose=last_dose,
                    txt_dir=TXT_WATER_DIR,
                    now=now
                )
                pond_sensor_checked[pond_id] = sensor_set
            else:
                print(f"[DEBUG] {pond_id}: sensor ยังไม่เข้าเงื่อนไขผิดปกติ 5 ไฟล์ล่าสุด")
        time.sleep(5)
# =================================================
if __name__ == "__main__":
    monitor_sensor_and_water()
