#!/usr/bin/env python3

#######################################################
#      Send 433MHz weather sensors data via MQTT
#                rtl433-mqtt Gateway
#                   V2.2 (C) 2026
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

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.yaml")
STATE_FILE = os.path.join(SCRIPT_DIR, "weather_states.json")

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
FREQ = cfg.get("rtl_433", {}).get("frequency", "434M")
MODEL_FILTER = cfg.get("rtl_433", {}).get("model_filter", "ALL")
TEMP_LABEL_F = cfg["rtl_433"].get("temp_label_f", "temperature_F")
TEMP_LABEL_C = cfg["rtl_433"].get("temp_label_c", "temperature_C")
RAIN_LABEL_INPUT = cfg["rtl_433"].get("rain_label_input", "rain_mm")
WIND_LABEL_INPUT = cfg.get("rtl_433", {}).get("wind_label_input", "wind_avg_km_h")

MQTT_HOST = cfg["mqtt"]["host"]
MQTT_PORT = cfg["mqtt"]["port"]
BASE_TOPIC = cfg.get("mqtt", {}).get("base_topic", "weatherstation/sdr")
DEBOUNCE = cfg.get("mqtt", {}).get("debounce", False)

if MODEL_FILTER is None:
    MODEL_FILTER = "ALL"

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
def load_weather_states():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Fehler beim Laden der Regenstopps: {e}")
    return {}

def save_weather_states(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=4)
    except Exception as e:
        logging.error(f"Fehler beim Speichern der Regenstopps: {e}")

# Berechnet alle Regen- und Windstatistiken
def calculate_weather_stats(sensor_id, current_total_rain, current_wind):
    state = load_weather_states()  # Datei laden
    now = time.time()
    ltime = time.localtime(now)
    
    current_hour_str = time.strftime("%Y-%m-%d_%H", ltime)
    current_day_str = time.strftime("%Y-%m-%d", ltime)
    current_month_str = time.strftime("%Y-%m", ltime)
    current_year_str = time.strftime("%Y", ltime)
    
    # 1. ID-Block sauber als EINZIGES Objekt initialisieren, falls neu
    if sensor_id not in state or not isinstance(state[sensor_id], dict):
        state[sensor_id] = {}

    # 2. REGEN-STRUKTUR INITIALISIEREN ODER LADEN
    if "rain_stats" not in state[sensor_id]:
        state[sensor_id]["rain_stats"] = {
            "last_total": current_total_rain, "last_ts": now,
            "hour_key": current_hour_str, "hour_start_total": current_total_rain,
            "day_key": current_day_str, "day_start_total": current_total_rain,
            "month_key": current_month_str, "month_start_total": current_total_rain,
            "year_key": current_year_str, "year_start_total": current_total_rain,
            "currRainfall": 0.0, "hourRainfall": 0.0, "dayRainfall": 0.0,
            "monthRainfall": 0.0, "yearRainfall": 0.0, "yestRainfall": 0.0
        }
    r_state = state[sensor_id]["rain_stats"]

    # 3. WIND-STRUKTUR INITIALISIEREN ODER LADEN
    if "wind_stats" not in state[sensor_id]:
        state[sensor_id]["wind_stats"] = {
            "hour_key": current_hour_str, "hourMax": current_wind,
            "day_key": current_day_str, "dayMax": current_wind,
            "month_key": current_month_str, "monthMax": current_wind,
            "year_key": current_year_str, "yearMax": current_wind
        }
    w_state = state[sensor_id]["wind_stats"]

    # --- REGEN-BERECHNUNG ---
    # Erkennung eines Batteriewechsels / Resets (Wert fällt stark ab oder geht auf 0)
    if current_total_rain < r_state["last_total"]:
        if current_total_rain == 0.0 or (r_state["last_total"] - current_total_rain) > 10.0:
            # BATTERIEWECHSEL ERKANNT:
            r_state["hour_start_total"] = 0.0
            r_state["day_start_total"] = 0.0
            r_state["month_start_total"] = 0.0
            r_state["year_start_total"] = 0.0
            
            # Start-Wert im Minus annehmen, um den bisherigen Wert einzufrieren.
            r_state["hour_start_total"] = current_total_rain - r_state["hourRainfall"]
            r_state["day_start_total"] = current_total_rain - r_state["dayRainfall"]
            r_state["month_start_total"] = current_total_rain - r_state["monthRainfall"]
            r_state["year_start_total"] = current_total_rain - r_state["yearRainfall"]
        else:
            # Kleinerer Rücksprung (z.B. Signalfehler)
            diff_offset = r_state["last_total"] - current_total_rain
            r_state["hour_start_total"] = max(0.0, r_state["hour_start_total"] - diff_offset)
            r_state["day_start_total"] = max(0.0, r_state["day_start_total"] - diff_offset)
            r_state["month_start_total"] = max(0.0, r_state["month_start_total"] - diff_offset)
            r_state["year_start_total"] = max(0.0, r_state["year_start_total"] - diff_offset)

    if current_hour_str != r_state["hour_key"]:
        r_state["hour_key"] = current_hour_str
        r_state["hour_start_total"] = current_total_rain
    if current_day_str != r_state["day_key"]:
        r_state["yestRainfall"] = r_state["dayRainfall"]
        r_state["day_key"] = current_day_str
        r_state["day_start_total"] = current_total_rain
    if current_month_str != r_state["month_key"]:
        r_state["month_key"] = current_month_str
        r_state["month_start_total"] = current_total_rain
    if current_year_str != r_state["year_key"]:
        r_state["year_key"] = current_year_str
        r_state["year_start_total"] = current_total_rain

    r_state["hourRainfall"] = round(current_total_rain - r_state["hour_start_total"], 2)
    r_state["dayRainfall"] = round(current_total_rain - r_state["day_start_total"], 2)
    r_state["monthRainfall"] = round(current_total_rain - r_state["month_start_total"], 2)
    r_state["yearRainfall"] = round(current_total_rain - r_state["year_start_total"], 2)

    time_diff = now - r_state["last_ts"]
    rain_diff = current_total_rain - r_state["last_total"]

    if time_diff > 5:
        if rain_diff > 0:
            # 1. Es gab einen neuen Regen-Impuls -> Aktuelle Intensität berechnen
            new_intensity = (rain_diff / time_diff) * 3600.0
            
            # Alter Wert dämpfen (80% alter Wert, 20% neuer Peak)
            # Extremes Hochschnellen bei einem einzelnen Wippenschlag verhindern
            if r_state.get("currRainfall", 0.0) > 0:
                r_state["currRainfall"] = round((r_state["currRainfall"] * 0.8) + (new_intensity * 0.2), 2)
            else:
                r_state["currRainfall"] = round(new_intensity, 2)
        else:
            # 2. Kein neuer Impuls in diesem Paket (rain_diff == 0)
            # Wert langsam abklingen lassen
            old_intensity = r_state.get("currRainfall", 0.0)
            if old_intensity > 0.5:
                r_state["currRainfall"] = round(old_intensity * 0.7, 2)
            else:
                r_state["currRainfall"] = 0.0

    r_state["last_total"] = current_total_rain
    r_state["last_ts"] = now

    # --- WIND-BERECHNUNG ---
    if current_hour_str != w_state["hour_key"]:
        w_state["hour_key"] = current_hour_str
        w_state["hourMax"] = current_wind
    if current_day_str != w_state["day_key"]:
        w_state["day_key"] = current_day_str
        w_state["dayMax"] = current_wind
    if current_month_str != w_state["month_key"]:
        w_state["month_key"] = current_month_str
        w_state["monthMax"] = current_wind
    if current_year_str != w_state["year_key"]:
        w_state["year_key"] = current_year_str
        w_state["yearMax"] = current_wind

    w_state["hourMax"] = max(w_state["hourMax"], current_wind)
    w_state["dayMax"] = max(w_state["dayMax"], current_wind)
    w_state["monthMax"] = max(w_state["monthMax"], current_wind)
    w_state["yearMax"] = max(w_state["yearMax"], current_wind)

    # --- SPEICHERN ---
    state[sensor_id]["rain_stats"] = r_state
    state[sensor_id]["wind_stats"] = w_state
    save_weather_states(state)

    # Alle berechneten Werte zurückliefern
    return {
        "currRainfall": r_state["currRainfall"], "hourRainfall": r_state["hourRainfall"],
        "dayRainfall": r_state["dayRainfall"], "yestRainfall": r_state["yestRainfall"],
        "monthRainfall": r_state["monthRainfall"], "yearRainfall": r_state["yearRainfall"],
        "currWindSpeed": round(current_wind, 1), "hourWindSpeed": round(w_state["hourMax"], 1),
        "dayWindSpeed": round(w_state["dayMax"], 1), "monthWindSpeed": round(w_state["monthMax"], 1),
        "yearWindSpeed": round(w_state["yearMax"], 1)
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

    # Filterprüfung: Entweder der Filter steht auf "ALL" oder das Modell ist in der Liste
    is_allowed = False
    if MODEL_FILTER == "ALL":
        is_allowed = True
    elif isinstance(MODEL_FILTER, list):
        if current_model in MODEL_FILTER:
            is_allowed = True
    elif isinstance(MODEL_FILTER, str):
        if current_model == MODEL_FILTER:
            is_allowed = True
    else:
        logging.warning(f"Ungültiges Format für model_filter in config.yaml. Paket für {current_model} wird ignoriert.")

    if is_allowed:
        sensor_id = data.get("id", "unknown")
        if DEBUG_MODE:
            print(f"\n{get_now_ms()} [+] Sensor gefunden ({current_model} ID: {sensor_id}):")
        
        extra_weather_data = {}
        
        # 1. Originale Sensorwerte senden
        for key, value in data.items():
            if key in ["model", "id", "mic"]:
                continue
                
            key_clean = sanitize(key)
            topic = f"{BASE_TOPIC}/{sanitize(current_model)}/{sensor_id}/{key_clean}"

            if DEBOUNCE:
                # DeBounce Logik
                if DEBUG_MODE:
                    logging.info("DeBounce aktiv")
                if key_clean != "time":
                    if topic in last_values and last_values[topic] == value:
                        if DEBUG_MODE:
                            logging.info(f"DeBounce: Topic {topic} überspringen")
                        continue
                    last_values[topic] = value

            mqttc.publish(topic, str(value), retain=True)
            
            if DEBUG_MODE:
                print(f"    -> MQTT Publish: {topic} = {value}")

            # Celsius-Umrechnung
            if key_clean.lower() == TEMP_LABEL_F.lower():
                try:
                    temp_f = float(value)
                    extra_weather_data[TEMP_LABEL_C] = round((temp_f - 32) * 5 / 9, 1)
                except ValueError:
                    pass

        # Werte für Regen/Wind prüfen
        raw_rain = data.get(RAIN_LABEL_INPUT)
        raw_wind = data.get(WIND_LABEL_INPUT)

        # Bestehenden Zustand laden
        state_file_data = load_weather_states().get(str(sensor_id), {})

        # Fallback auf alte Werte aus der JSON, falls das aktuelle Paket das Feld NICHT enthält
        if raw_rain is None:
            raw_rain = state_file_data.get("rain_stats", {}).get("last_total", 0.0)
        if raw_wind is None:
            raw_wind = state_file_data.get("wind_stats", {}).get("hourMax", 0.0)

        # 2. Regen- und Wind-Rohwerte für die Statistik holen
        # Wenn ein Wert im Funkspruch fehlt, dann letzten Stand aus der JSON als Fallback
        state_file_data = load_weather_states().get(str(sensor_id), {})
        
        raw_rain = data.get(RAIN_LABEL_INPUT)
        if raw_rain is None:
            raw_rain = state_file_data.get("rain_stats", {}).get("last_total", 0.0)
            
        raw_wind = data.get(WIND_LABEL_INPUT)
        if raw_wind is None:
            raw_wind = state_file_data.get("wind_stats", {}).get("hourMax", 0.0) # Oder 0.0 als Fallback

        # 3. Berechnen wenn das Paket REGEN oder WIND enthält
        if RAIN_LABEL_INPUT in data or WIND_LABEL_INPUT in data:
            try:
                stats = calculate_weather_stats(str(sensor_id), float(raw_rain), float(raw_wind))
                extra_weather_data.update(stats)
            except Exception as e:
                logging.error(f"Fehler bei der Wetterstatistik-Berechnung: {e}")
        else:
            # Reines Temperatur-Paket -> alte berechnete Werte mitsenden für neuen Zeitstempel
            if "rain_stats" in state_file_data:
                extra_weather_data.update(state_file_data["rain_stats"])
            if "wind_stats" in state_file_data:
                w_old = state_file_data["wind_stats"]
                extra_weather_data.update({
                    "currWindSpeed": round(float(raw_wind), 1),
                    "hourWindSpeed": round(w_old.get("hourMax", 0.0), 1),
                    "dayWindSpeed": round(w_old.get("dayMax", 0.0), 1),
                    "monthWindSpeed": round(w_old.get("monthMax", 0.0), 1),
                    "yearWindSpeed": round(w_old.get("yearMax", 0.0), 1)
                })

        # 4. Alle berechneten Werte (Regen, Wind, Celsius) auf einmal senden
        for w_key, w_value in extra_weather_data.items():
            w_topic = f"{BASE_TOPIC}/{sanitize(current_model)}/{sensor_id}/{w_key}"
            mqttc.publish(w_topic, str(w_value), retain=True)
            if DEBUG_MODE:
                print(f"    -> MQTT Publish (Calculated): {w_topic} = {w_value} ({get_now_ms()})")

        if DEBUG_MODE:
            logging.info(f"Published data packet for {current_model} ID {sensor_id}")

