#!/usr/bin/env python3

#######################################################
#      Send 433MHz weather sensors data via MQTT
#                rtl433-mqtt Gateway
#                   V1.0 (C) 2026
#                  Daniel Luginbühl
#######################################################

import subprocess
import json
import yaml
import logging
import paho.mqtt.client as mqtt
import os
import re
import time

CONFIG_FILE = "/opt/rtl433-mqtt/config.yaml"
STATE_FILE = "/opt/rtl433-mqtt/rain_state.json"

# 1. Konfiguration laden
try:
    with open(CONFIG_FILE, "r") as f:
        cfg = yaml.safe_load(f)
except Exception as e:
    print(f"Failed to load config: {e}")
    exit(1)

# Debug Flag auslesen (Standard ist False, wenn nicht angegeben)
DEBUG_MODE = cfg["rtl_433"].get("debug", False)

# Log-Level dynamisch anpassen basierend auf dem Debug-Flag
LOG_LEVEL = logging.DEBUG if DEBUG_MODE else logging.INFO

LOG_FILE = cfg.get("logging", {}).get("file", "/var/log/rtl433-mqtt.log")
logging.basicConfig(
    filename=LOG_FILE,
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(message)s"  # Nutzt den Standard mit Millisekunden
)

# Hilfsfunktion für exakt dasselbe Format in den Prints
def get_now_ms():
    t = time.time()
    ltime = time.localtime(t)
    # Erzeugt "YYYY-MM-DD HH:MM:SS"
    formatted_time = time.strftime("%Y-%m-%d %H:%M:%S", ltime)
    # Fügt die Millisekunden mit Komma hinten an (,123)
    milliseconds = int((t - int(t)) * 1000)
    return f"{formatted_time},{milliseconds:03d}"

logging.info(f"Starting rtl433-mqtt bridge (Debug Mode: {DEBUG_MODE})")
if DEBUG_MODE:
    print(f"{get_now_ms()} [*] Debug-Modus AKTIV. Logs werden nach {LOG_FILE} geschrieben.")

last_mtime = os.path.getmtime(CONFIG_FILE)

# Variablen zuweisen
FREQ = cfg["rtl_433"]["frequency"]
MODEL_FILTER = cfg["rtl_433"]["model_filter"]

MQTT_HOST = cfg["mqtt"]["host"]
MQTT_PORT = cfg["mqtt"]["port"]
BASE_TOPIC = cfg["mqtt"]["base_topic"]

# 1. MQTT Client aufbauen
mqttc = mqtt.Client(client_id="rtl433_sdr_bridge", clean_session=True)

mqtt_user = cfg["mqtt"].get("username")
mqtt_pass = cfg["mqtt"].get("password")
if mqtt_user and mqtt_pass:
    mqttc.username_pw_set(mqtt_user, mqtt_pass)

try:
    mqttc.connect(MQTT_HOST, MQTT_PORT)
    mqttc.loop_start()
    logging.info("Connected to MQTT Broker successfully")
except Exception as e:
    logging.error(f"MQTT Connection failed: {e}")
    if DEBUG_MODE:
        print(f"{get_now_ms()} [!] MQTT Fehler: {e}")
    exit(1)

# 2. Funktionen für die zusätzlichen Regenwerte
def load_rain_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Fehler beim Laden der Regenstopps: {e}")
    return {}

def save_rain_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=4)
    except Exception as e:
        logging.error(f"Fehler beim Speichern der Regenstopps: {e}")

def calculate_rain_stats(sensor_id, current_total_rain, current_time_str):
    state = load_rain_state()
    now = time.time()
    ltime = time.localtime(now)
    
    current_hour_str = time.strftime("%Y-%m-%d_%H", ltime)
    current_day_str = time.strftime("%Y-%m-%d", ltime)
    current_month_str = time.strftime("%Y-%m", ltime)
    current_year_str = time.strftime("%Y", ltime)
    
    # Zustand initialisieren, falls der Sensor neu ist
    if sensor_id not in state:
        state[sensor_id] = {
            "last_total": current_total_rain,
            "last_ts": now,
            "hour_key": current_hour_str,
            "hour_start_total": current_total_rain,
            "day_key": current_day_str,
            "day_start_total": current_total_rain,
            "month_key": current_month_str,
            "month_start_total": current_total_rain,
            "year_key": current_year_str,
            "year_start_total": current_total_rain,
            "currRainfall": 0.0,
            "hourRainfall": 0.0,
            "dayRainfall": 0.0,
            "monthRainfall": 0.0,
            "yearRainfall": 0.0,
            "yestRainfall": 0.0
        }

    s_state = state[sensor_id]

    # 1. Schutz vor Sensor-Reset (z.B. Batteriewechsel)
    if current_total_rain < s_state["last_total"]:
        logging.warning(f"Sensor-Reset erkannt für ID {sensor_id}")
        diff_offset = s_state["last_total"] - current_total_rain
        s_state["hour_start_total"] = max(0.0, s_state["hour_start_total"] - diff_offset)
        s_state["day_start_total"] = max(0.0, s_state["day_start_total"] - diff_offset)
        s_state["month_start_total"] = max(0.0, s_state["month_start_total"] - diff_offset)
        s_state["year_start_total"] = max(0.0, s_state["year_start_total"] - diff_offset)

    # 2. Zeitliche Wechsel prüfen (Stunde, Tag, Monat, Jahr)
    if current_hour_str != s_state["hour_key"]:
        s_state["hour_key"] = current_hour_str
        s_state["hour_start_total"] = current_total_rain

    if current_day_str != s_state["day_key"]:
        # Bevor der Tag überschrieben wird, wandert der Tagessatz zu "Gestern"
        s_state["yestRainfall"] = s_state["dayRainfall"]
        s_state["day_key"] = current_day_str
        s_state["day_start_total"] = current_total_rain

    if current_month_str != s_state["month_key"]:
        s_state["month_key"] = current_month_str
        s_state["month_start_total"] = current_total_rain

    if current_year_str != s_state["year_key"]:
        s_state["year_key"] = current_year_str
        s_state["year_start_total"] = current_total_rain

    # 3. Berechnungen durchführen
    
    # Kaskadierende Differenzen
    hour_rain = round(current_total_rain - s_state["hour_start_total"], 2)
    day_rain = round(current_total_rain - s_state["day_start_total"], 2)
    month_rain = round(current_total_rain - s_state["month_start_total"], 2)
    year_rain = round(current_total_rain - s_state["year_start_total"], 2)

    # Aktuelle Regenintensität (currRainfall) in mm/h hochrechnen
    time_diff = now - s_state["last_ts"]
    rain_diff = current_total_rain - s_state["last_total"]
    
    # Nur berechnen, wenn Zeit vergangen ist und der Wert plausibel stieg
    if time_diff > 5 and rain_diff >= 0:
        # Formel: (Regendifferenz / Sekunden) * 3600 Sekunden = mm/h
        calculated_intensity = (rain_diff / time_diff) * 3600.0
        # Sanftes Abklingen oder direkter Wert
        s_state["currRainfall"] = round(calculated_intensity, 2)
    elif rain_diff == 0 and time_diff > 120:
        # Wenn seit über 2 Minuten kein neuer Regenimpuls kam, steht der Regen still
        s_state["currRainfall"] = 0.0

    # Werte im Zustand sichern
    s_state["last_total"] = current_total_rain
    s_state["last_ts"] = now
    s_state["hourRainfall"] = hour_rain
    s_state["dayRainfall"] = day_rain
    s_state["monthRainfall"] = month_rain
    s_state["yearRainfall"] = year_rain

    save_rain_state(state)

    # Rückgabe aller 6 Werte als Dictionary
    return {
        "currRainfall": s_state["currRainfall"],
        "hourRainfall": s_state["hourRainfall"],
        "dayRainfall": s_state["dayRainfall"],
        "yestRainfall": s_state["yestRainfall"],
        "monthRainfall": s_state["monthRainfall"],
        "yearRainfall": s_state["yearRainfall"]
    }

# 3. Sanitize Funktion
def sanitize(text):
    text = (
        text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
            .replace("Ä", "Ae").replace("Ö", "Oe").replace("Ü", "Ue")
            .replace("ß", "ss")
    )
    text = text.replace("-", "_").replace(":", "_")
    text = re.sub(r"[^A-Za-z0-9_]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")

# 4. rtl_433 Prozess starten
cmd = ["rtl_433", "-f", FREQ, "-F", "json"]
logging.info(f"Launching process: {' '.join(cmd)}")
proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)

last_values = {}

# 5. Ereignisschleife (Stream auslesen)
for line in proc.stdout:
    # Auto‑Reload wenn config.yaml geändert wurde
    current_mtime = os.path.getmtime(CONFIG_FILE)
    if current_mtime != last_mtime:
        logging.info("Config changed, restarting script...")
        if DEBUG_MODE:
            print(f"{get_now_ms()} [*] Konfiguration geändert, starte Skript neu...")
        mqttc.loop_stop()
        proc.terminate()
        exit(0)

    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        continue

    # Wenn Debug aktiv ist, logge jeden empfangenen Funkspruch im Logfile
    logging.debug(f"Raw JSON received: {line.strip()}")

    # Modell aus dem empfangenen Funkspruch holen
    current_model = data.get("model")
    if not current_model:
        continue

    # Filterprüfung: Entweder der Filter steht auf "ALL" oder das Modell ist in unserer Liste
    is_allowed = False
    if MODEL_FILTER == "ALL":
        is_allowed = True
    elif isinstance(MODEL_FILTER, list) and current_model in MODEL_FILTER:
        is_allowed = True
    elif isinstance(MODEL_FILTER, str) and current_model == MODEL_FILTER:
        is_allowed = True
    else:
        logging.warning(f"Ungültiges Format für model_filter in config.yaml. Paket für {current_model} wird ignoriert.")

    if is_allowed:
        sensor_id = data.get("id", "unknown")
        
        if DEBUG_MODE:
            print(f"\n{get_now_ms()} [+] Sensor gefunden ({current_model} ID: {sensor_id}):")

        extra_rain_data = {}
        
        for key, value in data.items():
            if key in ["model", "id", "mic"]:
                continue
                
            key_clean = sanitize(key)
            topic = f"{BASE_TOPIC}/{sanitize(current_model)}/{sensor_id}/{key_clean}"

#            # DeBounce Logik
#            if key_clean != "time":
#                if topic in last_values and last_values[topic] == value:
#                    continue
#                last_values[topic] = value

            # Senden an Broker (ohne DeBounce - immer senden!)
            mqttc.publish(topic, str(value), retain=True)
            
            if DEBUG_MODE:
                print(f"    -> MQTT Publish: {topic} = {value}")

            # Sobald die Schleife das Feld "rain_mm" verarbeitet, triggern wir die 6 Berechnungen
            if key_clean == "rain_mm":
                try:
                    current_total_rain = float(value)
                    # Funktion aufrufen und das extra_rain_data-Wörterbuch mit den 6 neuen Werten befüllen
                    rain_stats = calculate_rain_stats(sensor_id, current_total_rain, data.get("time", ""))
                    extra_rain_data.update(rain_stats)
                except ValueError:
                    pass

            # Trigger für die Celsius-Umrechnung (unabhängig von Groß-/Kleinschreibung)
            if key_clean.lower() == "temperature_f":
                try:
                    temp_f = float(value)
                    # Umrechnung in Celsius und auf 1 Nachkommastelle runden
                    temp_c = round((temp_f - 32) * 5 / 9, 1)
                    extra_rain_data["temperature_C"] = temp_c
                except ValueError:
                    pass
            
        # Nachdem alle Standard-Werte gesendet wurden, feuern wir die 6 berechneten Werte ab
        for r_key, r_value in extra_rain_data.items():
            r_topic = f"{BASE_TOPIC}/{sanitize(current_model)}/{sensor_id}/{r_key}"
            mqttc.publish(r_topic, str(r_value), retain=True)
            if DEBUG_MODE:
                print(f"    -> MQTT Publish (Calculated): {r_topic} = {r_value}")

        logging.info(f"Published data packet for {current_model} ID {sensor_id}")
