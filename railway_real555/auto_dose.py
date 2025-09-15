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
BULK_DENSITY = 0.8
LIQUID_PER_ROUND = 750
MQTT_BROKER = "broker.emqx.io"
MQTT_PORT = 1883
TOPIC_CMD = "pond/doser/cmd"

# ✅ เปลี่ยนจาก path Windows → ใช้ ENV + default
SENSOR_BASE = os.environ.get("SENSOR_BASE", "./local_storage/sensor")
POND_INFO_BASE = os.environ.get("POND_INFO_BASE", "./data_ponds")
TXT_WATER_DIR = os.environ.get("TXT_WATER_DIR", "./output/water_output")

# =================================================

def get_powder_weight_per_round():
    volume = math.pi * (RADIUS_CM ** 2) * HEIGHT_CM
    return volume * BULK_DENSITY

def calc_powder_rounds(grams):
    return grams / get_powder_weight_per_round()

def calc_liquid_rounds(ml):
    return ml / LIQUID_PER_ROUND

def send_servo_command(rounds_array, pond_id=1):
    """
    ส่งคำสั่งไปยัง MQTT ให้บอร์ดหมุนเซอร์โว
    """
    cmd = {
        "type": "dose_servo",
        "pond_id": pond_id,
        "rounds": [int(round(x)) for x in rounds_array],
        "speed": 1.0
    }

    try:
        mqttc = mqtt.Client()
        mqttc.connect(MQTT_BROKER, MQTT_PORT, 60)
        mqttc.loop_start()
        mqttc.publish(TOPIC_CMD, json.dumps(cmd), qos=1)
        mqttc.loop_stop()
        mqttc.disconnect()
        print(f"[MQTT] ✅ ส่งคำสั่งเซอร์โวไปที่ {TOPIC_CMD}:", cmd)
    except Exception as e:
        print(f"[ERROR] ❌ MQTT publish ล้มเหลว: {e}")

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

def process_auto_dose(
    pond_id,
    pond_size_rai,
    ph,
    temp,
    do,
    last_dose,
    txt_dir,
    now=None
):
    if now is None:
        now = datetime.now()
    print(f"\n=== [DEBUG] ตรวจสอบบ่อ {pond_id} | ขนาด {pond_size_rai} ไร่ ===")
    print(f"เวลาปัจจุบัน: {now.isoformat()}")
    print(f"ค่าเซ็นเซอร์: pH={ph} | temp={temp} | DO={do}")

    ai_txt, ai_txt_path = read_latest_txt(txt_dir)
    water_clear = should_dose_green_extract(ai_txt)
    print(f"[AI TXT] วิเคราะห์สีน้ำ: {ai_txt} | water_clear={water_clear} (file={os.path.basename(ai_txt_path)})")

    def get_dt(name, default):
        try:
            return datetime.fromisoformat(last_dose[name])
        except Exception:
            return now - default

    last_probiotic = get_dt("probiotic", timedelta(days=8))
    last_caco3 = get_dt("caco3", timedelta(hours=12))
    last_mgso4 = get_dt("mgso4", timedelta(days=3))
    last_green_extract = get_dt("green_extract", timedelta(hours=24))

    rounds_array = [0, 0, 0, 0]
    dosing_report = []

    hour = now.hour
    valid_morning_evening = (6 <= hour <= 8) or (16 <= hour <= 18)
    valid_evening = (16 <= hour <= 18)

    # 1. โปรไบโอติก (ช่อง 0): สัปดาห์ละ 1 ครั้ง
    if (now - last_probiotic) > timedelta(days=7) and valid_morning_evening:
        grams = 5 * float(pond_size_rai)
        rounds = calc_powder_rounds(grams)
        rounds_array[0] = int(round(rounds))
        print(f"[ROUTINE] ปล่อยโปรไบโอติกครบกำหนด 7 วัน | ปล่อย {grams:.1f}g ({int(round(rounds))} รอบ)")
        dosing_report.append(f"โปรไบโอติก {grams:.1f} g ({int(round(rounds))} รอบ)")

    # 2. CaCO3 (ช่อง 1): pH < 6.8
    if ph < 6.8 and (now - last_caco3) > timedelta(hours=8) and valid_morning_evening:
        grams = 2.5 * 1000 * float(pond_size_rai)
        rounds = calc_powder_rounds(grams)
        rounds_array[1] = int(round(rounds))
        print(f"[ALERT] pH ต่ำกว่า 6.8 (={ph}), ปล่อย CaCO₃ {grams:.1f}g ({int(round(rounds))} รอบ)")
        dosing_report.append(f"CaCO₃ {grams:.1f} g ({int(round(rounds))} รอบ)")

    # 3. MgSO4 (ช่อง 2): temp > 30
    if temp > 30 and (now - last_mgso4) > timedelta(days=2) and valid_evening:
        grams = 2.5 * 1000 * float(pond_size_rai)
        rounds = calc_powder_rounds(grams)
        rounds_array[2] = int(round(rounds))
        print(f"[ALERT] อุณหภูมิสูงกว่า 30°C (={temp}), ปล่อย MgSO₄ {grams:.1f}g ({int(round(rounds))} รอบ)")
        dosing_report.append(f"MgSO₄ {grams:.1f} g ({int(round(rounds))} รอบ)")

    # 4. น้ำหมักพืชสีเขียว (ช่อง 3): น้ำใส/pH < 6.8
    if (water_clear or ph < 6.8) and (now - last_green_extract) > timedelta(hours=20) and valid_morning_evening:
        ml = 150 * float(pond_size_rai)
        rounds = calc_liquid_rounds(ml)
        rounds_array[3] = int(round(rounds))
        cause = "น้ำใสเกิน" if water_clear else "pH ต่ำ"
        print(f"[ALERT] {cause}, ปล่อยน้ำหมัก {ml:.1f}ml ({int(round(rounds))} รอบ)")
        dosing_report.append(f"น้ำหมักพืชสีเขียว {ml:.1f} ml ({int(round(rounds))} รอบ)")

    if any(rounds_array):
        send_servo_command(rounds_array)
        print("[ACTION] ปล่อยสาร ->", dosing_report)
    else:
        print("[ACTION] ไม่พบสารที่ต้องปล่อยในรอบนี้ (sensor/เวลาไม่เข้าเงื่อนไข)")

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
        time.sleep(60)

if __name__ == "__main__":
    monitor_sensor_and_water()
