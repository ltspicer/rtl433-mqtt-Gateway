#!/bin/bash

echo
echo "#################################"
echo "#      rtl433-mqtt Gateway      #"
echo "#      Install Script V1.1      #"
echo "#      for Debian based OS      #"
echo "#      by Daniel Luginbuehl     #"
echo "#   webmaster@ltspiceusers.ch   #"
echo "#          (c) 2026             #"
echo "#################################"
echo

# Standard Pfade definieren
DEFAULT_PATH="/opt/rtl433-mqtt"
LOG_PATH="/var/log/rtl433-mqtt.log"

echo "This script compiles and installs the rtl_433 library."
echo "In addition, various packages will be installed."
echo "It also creates a service in systemd."
echo "For these reasons, root privileges are required."
echo
echo "Dieses Script kompiliert und installiert die rtl_433 Bibliothek."
echo "Zudem werden diverse Pakete installiert."
echo "Des Weiteren wird ein Dienst in systemd angelegt."
echo "Aus diesen Gründen ist eine root Berechtigung notwendig."
echo

# Prüfen, ob das Script als Root läuft
if [[ $EUID -ne 0 ]]; then
    echo "This script MUST be run with root privileges!"
    echo "Please run it like this: sudo $0"
    echo
    echo "Dieses Script MUSS mit root-Rechten ausgeführt werden!"
    echo "Bitte starte es so: sudo $0"
    echo
    exit 1
fi

echo "Plug in the SDR stick now!"
echo "SDR-Stick jetzt einstecken!"
echo

# Benutzer fragen
while true; do
    echo "Please enter the installation path. Default: $DEFAULT_PATH"
    echo "Bitte Installationspfad eingeben. Standard: $DEFAULT_PATH"
    echo
    echo "CTRL & C = Cancel / Abbruch"
    read -p "Enter path or press ENTER for default: " USER_INPUT

    # Wenn nur ENTER gedrückt wurde, Default-Wert nehmen und Schleife beenden
    if [[ -z "$USER_INPUT" ]]; then
        TARGET_PATH="$DEFAULT_PATH"
        break
    fi

    # Prüfen, ob der Pfad mit einem "/" beginnt (absoluter Pfad)
    if [[ "$USER_INPUT" =~ ^/ ]]; then
        TARGET_PATH="$USER_INPUT"
        break
    else
        echo
        echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
        echo "ERROR: Invalid path! The path must be absolute and start with a '/'."
        echo "FEHLER: Ungültiger Pfad! Der Pfad muss absolut sein und mit einem '/' beginnen."
        echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
        echo
    fi
done

# Entfernt ALLE Schrägstriche am Ende der Variable
while [[ "$TARGET_PATH" == */ ]]; do
    TARGET_PATH="${TARGET_PATH%/}"
done

# Wenn Pfad leer, dann exit
if [[ -z "$TARGET_PATH" ]]; then
    echo
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    echo "ERROR: Target path is empty! Installation aborted."
    echo "FEHLER: Zielpfad ist leer! Installation abgebrochen."
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    echo
    exit 1
fi

# Info-Ausgabe zur Kontrolle
echo
echo "The script will be installed in: / Das Script wird installiert in: $TARGET_PATH"
echo

# Prüfen, ob eine alte "rtl_433" Version im System gefunden wird
if command -v rtl_433 &> /dev/null; then
    echo "An old version of rtl_433 was found. / Eine alte Version von rtl_433 wurde gefunden."
    echo "Uninstall the old APT package... / Deinstalliere altes APT-Paket..."
    
    # Entfernt das Paket und bereinigt den Befehls-Cache der Bash
    apt remove -y rtl-433 && hash -r
fi

# System updaten und Pakete installieren und rtl_433 kompilieren
apt update
apt install -y libtool libusb-1.0-0-dev librtlsdr-dev cmake pkg-config build-essential git python3-pip python3-yaml python3-paho-mqtt wget

# In ein temporäres Verzeichnis wechseln, um den Quellcode zu bauen
START_DIR=$(pwd)

# Allfälligen Dienst stoppen um Blockaden zu vermeiden
if systemctl is-active --quiet rtl433-mqtt.service; then
    echo "Stopping active gateway service for update... / Stoppe aktiven Gateway-Dienst für das Update..."
    systemctl stop rtl433-mqtt.service
fi

echo "Cloning and building rtl_433... / Klone und baue rtl_433..."
cd /tmp
# Falls ein alter Klon existiert, löschen
rm -rf rtl_433

git clone https://github.com/merbanan/rtl_433
cd rtl_433
mkdir build && cd build
cmake ..
make
make install
hash -r

# Zurück zum ursprünglichen Verzeichnis wechseln
cd "$START_DIR"

# Kernel-Treiber blacklisten, damit der RTL-SDR Stick nicht blockiert wird
echo "Blacklisting default DVB-T drivers... / Blockiere Standard-DVB-T-Treiber..."
cat << EOF > /etc/modprobe.d/blacklist-rtlsdr.conf
blacklist dvb_usb_rtl28xxu
blacklist rtl2832
blacklist rtl820t
EOF

# Zielordner erstellen
mkdir -p $TARGET_PATH

# Konfigurationsdatei config.yaml erstellen
WRITE_CONFIG=true

if [[ -f "$TARGET_PATH/config.yaml" ]]; then
    echo "An existing config.yaml was found! / Eine bestehende config.yaml wurde gefunden!"
    read -p "Keep existing configuration? / Bestehende Konfiguration behalten? [Y/n]: " KEEP_CONFIG
    
    # Wenn die Antwort leer ist oder mit Y/y beginnt, alte config.yaml behalten
    if [[ -z "$KEEP_CONFIG" || "$KEEP_CONFIG" =~ ^[Yy]$ ]]; then
        echo "Keeping your existing config.yaml. / Bestehende config.yaml wird beibehalten."
        WRITE_CONFIG=false
    else
        echo "Backing up old config to $TARGET_PATH/config.yaml.bak... / Sichere alte Konfiguration als $TARGET_PATH/config.yaml.bak..."
        cp "$TARGET_PATH/config.yaml" "$TARGET_PATH/config.yaml.bak"
    fi
fi

if [ "$WRITE_CONFIG" = true ]; then
echo "Create configuration file... / Erstelle Konfigurationsdatei..."
cat << 'EOF' > "$TARGET_PATH/config.yaml"
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
  base_topic: "weatherstation/sdr"   # MQTT-Topic
  username: "dein_user"              # Leer lassen, falls keine Authentifizierung notwendig ist
  password: "dein_password"          # Leer lassen, falls keine Authentifizierung notwendig ist
  debounce: false                    # Bei true werden nur geänderte Daten gesendet

logging:
  file: "TARGET_LOG_PLACEHOLDER"
EOF

    # Platzhalter durch echten Pfad ersetzen
    sed -i "s|TARGET_LOG_PLACEHOLDER|$LOG_PATH|g" "$TARGET_PATH/config.yaml"

    echo "config.yaml was created successfully! / config.yaml wurde erfolgreich erstellt!"
fi

# Script holen und ausführbar machen
wget -O "$TARGET_PATH/rtl433_mqtt.py" "https://raw.github.com/ltspicer/rtl433-mqtt-Gateway/main/rtl433_mqtt.py"
chmod +x "$TARGET_PATH/rtl433_mqtt.py"

# Systemd Service-Datei erstellen
echo "Create a systemd service at /etc/systemd/system/rtl433-mqtt.service..."
echo "Erstelle Systemd-Dienst unter /etc/systemd/system/rtl433-mqtt.service..."
cat << EOF > /etc/systemd/system/rtl433-mqtt.service
[Unit]
Description=rtl_433 SDR to MQTT Gateway
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=$TARGET_PATH
ExecStart=/usr/bin/env python3 $TARGET_PATH/rtl433_mqtt.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

# Abfrage Konfiguration bearbeiten
echo
echo "**********************************************************************************"
echo
read -p "Edit Configuration Now? / Jetzt Konfiguration bearbeiten? [Y/n]: " CONF_ANSWER

# Ist die Antwort "n"?
if [[ "$CONF_ANSWER" =~ ^[Nn]$ ]]; then
    echo "No configuration changes. / Keine Bearbeitung der Konfiguration."
else
    nano "$TARGET_PATH/config.yaml"
fi

# Systemd neu laden und Dienst aktivieren/starten
echo
echo "Enable and start the rtl433-mqtt service..."
echo "Aktiviere und starte den rtl433-mqtt Dienst..."
systemctl daemon-reload
systemctl enable rtl433-mqtt.service
systemctl start rtl433-mqtt.service

echo "The service has been successfully set up and launched!"
echo "Der Dienst wurde erfolgreich eingerichtet und gestartet!"
echo
echo "**********************************************************************************"
echo
echo "You can check whether the script is running. To do so, use the following commands:"
echo "Du kannst prüfen, ob das Script läuft. Benutze dazu folgende Befehle:"
echo
echo "sudo systemctl status rtl433-mqtt.service"
echo "sudo journalctl -u rtl433-mqtt.service -f"
echo
echo "To edit the configuration: / Um die Konfiguration zu editieren:"
echo "sudo nano $TARGET_PATH/config.yaml"
echo
echo "Log path / Log Pfad: $LOG_PATH"
echo
echo "**********************************************************************************"
echo

# Abfrage für Reboot
read -p "A reboot is recommended for the changes to take effect. Reboot now? / Ein Neustart wird empfohlen. Jetzt neu starten? [y/N]: " REBOOT_ANSWER

# Ist die Antwort "y"?
if [[ "$REBOOT_ANSWER" =~ ^[Yy]$ ]]; then
    echo "Rebooting system now... / System wird jetzt neu gestartet..."
    reboot
else
    echo "Reboot skipped. Please remember to reboot manually later! / Neustart übersprungen. Bitte denke daran, später manuell neu zu starten!"
fi

