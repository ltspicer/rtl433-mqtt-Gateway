# rtl433-mqtt Gateway

Dieses Projekt stellt eine ereignisgesteuerte Bridge bereit, die mithilfe eines SDR-Sticks und `rtl_433` die Funksignale von Wetterstationen (z. B. *Emax-W6*) abfängt. Die Daten werden zusätzlich in Celsius umgerechnet, lokale Statistiken für den Regenverlauf (Stunde, Tag, Gestern, Monat, Jahr) kalkuliert und die Werte sauber strukturiert per MQTT an einen Broker (zBsp. für den ioBroker `MQTT`-Adapter) übergeben.

Bei mir läuft dieses Script in einem Proxmox LXC (Container) mit Debian. Da arbeite ich direkt als User root. Wenn das bei dir auch der Fall ist, dann verwende kein `sudo` !

Ich nutze einen "RTL2832U & R828D SDR USB2.0 TV-Stick-Tuner 25 MHz bis 1760 MHz" von

https://de.aliexpress.com/item/1005005278623123.html

![Screenshot](https://github.com/ltspicer/rtl433-mqtt-Gateway/blob/main/sdr-stick.png)

Meine (Casativo) Wetterstation ist von Ideoon (Pearl), welche nur mit der WeatherSense Cloud kommuniziert.

![Screenshot](https://github.com/ltspicer/rtl433-mqtt-Gateway/blob/main/casativo_ideoon_weatherstation.png)

---

### Für Debian basierte Systeme kann der Installer verwendet werden, welcher alles übernimmt (Schritte 1 bis 3).

Folgenden **1-Zeiler** verwenden und den Anweisungen folgen:

`wget https://raw.github.com/ltspicer/rtl433-mqtt-Gateway/main/install.sh && chmod +x install.sh && sudo ./install.sh`

**oder** manuell starten:

```bash
chmod +x install.sh
sudo ./install.sh
```

Weitere Schritte sind nicht notwendig. Viel Spass

---

## 1. rtl_433 aus den Quellen kompilieren

Um die neuesten Sensoren zu unterstützen, sollte `rtl_433` direkt aus dem offiziellen GitHub-Repository kompiliert werden.

```bash
# 1. Abhängigkeiten installieren
sudo apt update
apt install -y libtool libusb-1.0-0-dev librtlsdr-dev cmake pkg-config build-essential git python3-pip python3-yaml python3-paho-mqtt wget

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
*Hinweis: Sollte noch eine alte Version aktiv sein, die zuvor via `apt` installiert wurde, deinstalliere sie mit:*

`sudo apt remove rtl-433 && hash -r`

### Jetzt SDR-Stick einstecken

---

## 2. Projekt-Struktur anlegen

Erstelle das Anwendungsverzeichnis auf deinem (Debian) System:
```bash
sudo mkdir -p /opt/rtl433-mqtt
```

### Konfigurationsdatei erstellen:
Erstelle die Konfiguration mit `sudo nano /opt/rtl433-mqtt/config.yaml` **(Achtung: Muss im gleichen Ordner wie das Python Script sein)**:

```yaml
rtl_433:
  frequency: "434M"

  # Entweder eine Liste von Modellen:
  model_filter:
    - "Emax-W6"
#    - "LaCrosse-TX141THBv2"         # Beispiel für einen zweiten Sensor
#    - "inFactory_TH"                # Beispiel für einen dritten Sensor
#    - "Nexus-TH"                    # Beispiel für einen vierten Sensor
  # ODER wenn du alles empfangen willst, lass "model_filter:" einfach weg.

  temp_label_f: "temperature_F"      # Temperaturname für Fahrenheit, wonach in den Rohdaten gesucht wird
  temp_label_c: "temperature_C"      # Temperaturpräfix für Celsius, wie der berechnete Wert im Broker heissen soll
  rain_label_input: "rain_mm"        # Wonach in den Rohdaten gesucht wird
  wind_label_input: "wind_avg_km_h"  # Wonach in den Rohdaten gesucht wird
  debug: false                       # Schaltet Live-Terminal-Prints und das LOG-Level auf DEBUG

mqtt:
  host: "192.168.1.50"               # IP deines MQTT-Brokers
  port: 1883                         # MQTT-Port
  base_topic: "weatherstation/sdr"     # MQTT-Topic
  username: "dein_user"              # Leer lassen, falls keine Authentifizierung notwendig ist
  password: "dein_password"          # Leer lassen, falls keine Authentifizierung notwendig ist
  debounce: false                    # Bei true werden nur geänderte Daten gesendet

logging:
  file: "/var/log/rtl433-mqtt.log"
```

### Python-Script holen:

Du kannst entweder mit diesem **1-Zeiler** arbeiten:

`sudo wget -O /opt/rtl433-mqtt/rtl433_mqtt.py https://raw.github.com/ltspicer/rtl433-mqtt-Gateway/main/rtl433_mqtt.py && sudo chmod +x /opt/rtl433-mqtt/rtl433_mqtt.py`

**oder** das Script nach `/opt/rtl433-mqtt/rtl433_mqtt.py` kopieren und ausführbar machen:

`sudo chmod +x /opt/rtl433-mqtt/rtl433_mqtt.py`

---

## 3. systemd konfigurieren

Erstelle diese Datei mit `sudo nano /etc/systemd/system/rtl433-mqtt.service`

```
[Unit]
Description=rtl_433 SDR to MQTT Gateway
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

Blacklist erstellen, damit der Kernel den SDR-Stick nicht für DVB beschlagnahmt.

`sudo nano /etc/modprobe.d/blacklist-rtlsdr.conf`

```bash
blacklist dvb_usb_rtl28xxu
blacklist rtl2832
blacklist rtl820t
```

### Dienst starten:

```
sudo systemctl daemon-reload
sudo systemctl enable rtl433-mqtt.service
sudo systemctl start rtl433-mqtt.service

sudo reboot
```

### Prüfen:

```
systemctl status rtl433-mqtt.service
sudo journalctl -u rtl433-mqtt.service -f
```
