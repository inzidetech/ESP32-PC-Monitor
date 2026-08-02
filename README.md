<div align="center">
  <img src="https://img.shields.io/badge/ESP32-2432S028R-blue?style=for-the-badge&logo=espressif">
  <img src="https://img.shields.io/badge/Windows-0078D6?style=for-the-badge&logo=windows&logoColor=white">
  <img src="https://img.shields.io/badge/Linux-FCC624?style=for-the-badge&logo=linux&logoColor=black">
  <br>
  <h1>🚀 ESP32 PC Hardware Monitor</h1>
  <p>Convierte tu ESP32 con pantalla TFT (CYD - Cheap Yellow Display) en un monitor de hardware premium y elegante para tu PC por conexión USB.</p>
</div>

---

## 🌟 Características Principales

- **Diseño Premium**: Interfaz inspirada en las pantallas "Turing Smart Screen", con anillos de neón dinámicos y medidores lineales.
- **Baja Latencia (USB)**: Funciona exclusivamente a través de conexión Serial (USB) a 115200 baudios, eliminando por completo los retrasos e inestabilidad del Wi-Fi.
- **Plug & Play**: 
  - **Pantalla QR Offline**: Si el PC se apaga, la pantalla detecta la desconexión automáticamente, limpia la interfaz y muestra un Código QR para descargar el agente de PC.
  - Al recibir datos de nuevo, el software se auto-restaura instantáneamente.
- **Soporte Multi-Plataforma**: 
  - Agente invisible para Windows (con autoarranque seguro sin alertas de Antivirus).
  - Agente nativo para Linux/Ubuntu con instalación automatizada como servicio `systemd` y métricas reales (Nvidia-SMI & sysfs).

## 📊 Parámetros Monitorizados

El monitor recoge las siguientes métricas del sistema en tiempo real:

| Componente | Métricas |
| :--- | :--- |
| **Carga de CPU** | `%` Uso, Temperatura (°C), Frecuencia (MHz) |
| **Carga de GPU** | `%` Uso, Temperatura (°C), Ventiladores (RPM), VRAM Usada |
| **Memoria RAM** | `%` Uso, RAM Total, RAM Libre |
| **Almacenamiento (Disco)** | `%` Uso, Espacio Libre (GB), Temp SSD (°C) |
| **Red (Network)** | Velocidad de Descarga y Subida (Kbps/Mbps) |
| **Sistema** | Tiempo encendido (Uptime), Fecha y Hora |

---

## 🛠️ Requisitos de Hardware

- **Placa Recomendada:** ESP32-2432S028R (conocida como "Cheap Yellow Display" o CYD).
- También compatible con cualquier ESP32 acoplado a una pantalla **ILI9341 de 2.8"** o **2.4"** (Resolución 320x240).
- Cable Micro-USB o USB-C con transferencia de datos.

---

## ⚙️ Guía de Instalación (Paso a Paso)

### 1. Preparar el ESP32
1. Abre el archivo `esp32_dashboard.ino` en tu **Arduino IDE**.
2. Asegúrate de tener instaladas las siguientes librerías desde el Gestor de Librerías:
   - `TFT_eSPI` (Configura el archivo `User_Setup.h` según tu pantalla, o usa la configuración para CYD).
   - `ArduinoJson` (Versión 7.x).
3. Selecciona la placa (ej. "ESP32 Dev Module") y compila/sube el código.
4. Si la pantalla se ve con el código QR gigante: ¡El flasheo fue un éxito!

---

### 2. Uso en Windows 🪟

El agente para Windows es un ejecutable ligero que corre en segundo plano y transmite por USB.

1. Descarga el ejecutable `ESP32-MONITOR.exe` desde la carpeta `dist`.
2. Ejecuta el programa. Se ocultará de inmediato y aparecerá en la bandeja del sistema (abajo a la derecha, cerca del reloj) con un ícono de círculos de colores.
3. El ESP32 se conectará instantáneamente al PC y comenzará a mostrar las métricas.
4. **Autoarranque**: Haz clic derecho en el ícono de la bandeja y selecciona **"Iniciar con Windows"**. El programa arrancará de forma invisible cada vez que enciendas la PC. *(Totalmente seguro contra falsos positivos de antivirus).*

---

### 3. Uso en Servidores Linux / Ubuntu 🐧

El agente de Linux se instala como un servicio del sistema (`systemd`) que arranca con el SO. Lee métricas puras sin necesidad de entornos gráficos, ideal para servidores hogareños.

1. Abre una terminal en tu servidor Ubuntu.
2. Descarga y ejecuta el instalador automatizado con una sola línea:
```bash
sudo wget -qO- https://raw.githubusercontent.com/inzidetech/ESP32-PC-Monitor/main/Ubuntu_Agent/install.sh | sudo bash
```
3. El script instalará las dependencias (lm-sensors, sysstat), creará el servicio y comenzará a enviar datos a la pantalla USB automáticamente.
4. Puedes ver el estado del agente ejecutando: `sudo systemctl status esp32-monitor`

---

## 🤝 Contribuciones y Modificaciones
Este proyecto es completamente Open Source. El agente de Windows fue compilado con `PyInstaller` a partir de `pc_agent.py`, si deseas modificar las métricas, simplemente edita el script y compílalo usando el siguiente comando:
`python -m PyInstaller --noconsole --onefile --name "ESP32-MONITOR" pc_agent.py`

*Creado y optimizado por [InzideTech](https://github.com/inzidetech)*
