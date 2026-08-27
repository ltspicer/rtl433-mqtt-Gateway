# rtl433-mqtt Gateway (eg. WeatherSense)

Dieses Projekt stellt eine ereignisgesteuerte Bridge bereit, die mithilfe eines SDR-Sticks und `rtl_433` die Funksignale von Wetterstationen (z. B. *Emax-W6*) abfängt. Die Daten werden in Celsius umgerechnet, lokale Statistiken für den Regenverlauf (Stunde, Tag, Gestern, Monat, Jahr) kalkuliert und die Werte sauber strukturiert per MQTT an einen Broker (zBsp. für den ioBroker `MQTT`-Adapter) übergeben.

Bei mir läuft dieses Script in einem Proxmox LXC (Container) mit Debian.

Ich selber habe einen "RTL2832U & R828D SDR USB2.0 TV-Stick-Tuner 25 MHz bis 1760 MHz" von https://de.aliexpress.com/item/1005005278623123.html

![Screenshot](https://github.com/ltspicer/rtl433-mqtt-Gateway/blob/main/sdr-stick.png)

Meine Wetterstation ist von Ideoon (Pearl)

![Screenshot](https://github.com/ltspicer/rtl433-mqtt-Gateway/blob/main/casativo_ideoon_weatherstation.png)

## 🛠️ 1. rtl_433 aus den Quellen kompilieren

Um die neuesten Sensoren zu unterstützen, sollte `rtl_433` direkt aus dem offiziellen GitHub-Repository kompiliert werden.

```bash
# 1. Abhängigkeiten installieren
sudo apt update
sudo apt install libtool libusb-1.0-0-dev librtlsdr-dev cmake pkg-config build-essential git -y

# 2. Quellcode holen und bauen
git clone https://github.com/merbanan/rtl_433
cd rtl_433
mkdir build && cd build
cmake ..
make
sudo make install
hash -r
```

### Installation überprüfen:
```bash
rtl_433 -V
```
*Hinweis: Sollte noch eine alte Version aktiv sein, die zuvor via `apt` installiert wurde, deinstalliere sie mit `sudo apt remove rtl-433 && hash -r`.*

---

## 📂 2. Projekt-Struktur anlegen

Erstelle das Anwendungsverzeichnis auf deinem (Debian) System:
```bash
sudo mkdir -p /opt/rtl433-mqtt
```

### Konfigurationsdatei: `/opt/rtl433-mqtt/config.yaml`
Erstelle die Konfiguration mit `nano /opt/rtl433-mqtt/config.yaml`:

```yaml
rtl_433:
  frequency: "434M"
  # Entweder eine Liste von Modellen:
  model_filter:
    - "Emax-W6"
#    - "LaCrosse-TX141THBv2"   # Beispiel für einen zweiten Sensor
#    - "inFactory_TH"          # Beispiel für einen dritten Sensor
#    - "Nexus-TH"              # Beispiel für einen vierten Sensor
  # ODER wenn du alles empfangen willst, schreibe einfach:
  # model_filter: "ALL"
  debug: false                 # Schaltet Live-Terminal-Prints und das LOG-Level auf DEBUG

mqtt:
  host: "192.168.1.50"         # IP deines MQTT-Brokers
  port: 1883
  base_topic: "weathersense/sdr"
  username: "dein_user"        # Leer lassen, falls keine Authentifizierung notwendig ist
  password: "dein_password"    # Leer lassen, falls keine Authentifizierung notwendig ist

logging:
  file: "/var/log/rtl433-mqtt.log"
```

### Python-Skript: `/opt/rtl433-mqtt/rtl433_mqtt.py`
Kopiere das Skript nach `/opt/rtl433-mqtt/rtl433_mqtt.py`. **Vergiss nicht, das Skript danach mit `chmod +x /opt/rtl433-mqtt/rtl433_mqtt.py` ausführbar zu machen.**

### systemd konfigurieren

`sudo nano /etc/systemd/system/rtl433-mqtt.service`

```
[Unit]
Description=rtl_433 SDR to MQTT Gateway (WeatherSense)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/rtl433-mqtt
ExecStart=/usr/bin/env python3 /opt/rtl433-mqtt/rtl433_mqtt.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

systemd starten:

```
sudo systemctl daemon-reload
sudo systemctl enable rtl433-mqtt.service
sudo systemctl start rtl433-mqtt.service
```

Prüfen:

```
systemctl status rtl433-mqtt.service
journalctl -u rtl433-mqtt.service -f
```
