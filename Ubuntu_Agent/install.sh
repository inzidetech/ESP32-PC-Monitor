#!/bin/bash

echo "===================================================="
echo "    INSTALADOR DEL AGENTE ESP32 PARA UBUNTU"
echo "===================================================="

# Verificar permisos de superusuario
if [ "$EUID" -ne 0 ]
  then echo "Por favor, ejecuta este script como root (usando sudo bash install.sh)"
  exit
fi

echo "[1/4] Instalando dependencias (psutil, pyserial)..."
apt-get update
apt-get install -y python3-pip python3-psutil python3-serial

echo "[2/4] Creando directorio de instalación en /opt/esp32-monitor..."
mkdir -p /opt/esp32-monitor
cp ubuntu_agent.py /opt/esp32-monitor/
chmod +x /opt/esp32-monitor/ubuntu_agent.py

echo "[3/4] Configurando servicio Systemd..."
cp esp32-monitor.service /etc/systemd/system/
systemctl daemon-reload

echo "[4/4] Iniciando el Agente..."
systemctl enable esp32-monitor.service
systemctl restart esp32-monitor.service

echo ""
echo "===================================================="
echo "¡INSTALACIÓN COMPLETADA CON ÉXITO!"
echo "===================================================="
echo "El agente ahora está corriendo en segundo plano."
echo "- Para ver el estado:  sudo systemctl status esp32-monitor"
echo "- Para ver los logs:   sudo journalctl -u esp32-monitor -f"
echo "- Para detenerlo:      sudo systemctl stop esp32-monitor"
echo "===================================================="
