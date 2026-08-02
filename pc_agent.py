import os
import sys
import time
import json
import threading
import subprocess
import urllib.request
import ctypes
from http.server import HTTPServer, BaseHTTPRequestHandler

try:
    import pystray
    from PIL import Image, ImageDraw
    HAS_GUI = True
except ImportError:
    HAS_GUI = False

try:
    from pyadl import ADLManager
    HAS_PYADL = True
except ImportError:
    HAS_PYADL = False

# Intentar importar librerías opcionales para mayor rendimiento
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

try:
    import wmi
    import pythoncom
    HAS_WMI = True
except ImportError:
    HAS_WMI = False

try:
    import serial
    import serial.tools.list_ports
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False

# Variables de Configuración
PORT_HTTP = 8080
BAUDRATE_SERIAL = 115200
UPDATE_INTERVAL = 1.5  # segundos
SERIAL_PORT = None  # Si es None, intentará auto-detectar. Si no, poner ej: "COM3"

print("====================================================")
print("             MONITOR PC AGENT (ESP32 TFT)")
print("====================================================")
print(f"Librería 'psutil': {'Instalada (OK)' if HAS_PSUTIL else 'NO instalada (Usando fallback de PowerShell)'}")
print(f"Librería 'wmi':    {'Instalada (OK)' if HAS_WMI else 'NO instalada (Usando fallback de PowerShell)'}")
print(f"Librería 'pyadl':  {'Instalada (OK)' if HAS_PYADL else 'NO instalada (Sin soporte nativo AMD)'}")
print(f"Librería 'pyserial': {'Instalada (OK)' if HAS_SERIAL else 'NO instalada (Soporte USB desactivado)'}")
print("====================================================\n")

# Variable global para almacenar el último estado de datos recolectados
current_stats = {}
stats_lock = threading.Lock()
start_time = time.time()
PAUSED = False
APP_RUNNING = True

# Cache para red (necesario para calcular velocidad de red en fallback)
last_net_bytes = {"in": 0, "out": 0, "time": time.time()}

def get_uptime():
    diff = int(time.time() - start_time)
    hours = diff // 3600
    minutes = (diff % 3600) // 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"

def get_windows_errors():
    """Consulta los últimos 4 errores o advertencias en el Log de Eventos de Windows mediante PowerShell"""
    try:
        # Consulta rápida en PowerShell para obtener los últimos eventos del sistema
        cmd = [
            "powershell", "-NoProfile", "-Command",
            "Get-EventLog -LogName System -EntryType Error,Warning -Newest 4 | "
            "Select-Object EventID, TimeGenerated, Source, Message | ConvertTo-Json"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            if not isinstance(data, list):
                data = [data]
            
            errors = []
            for item in data:
                # Extraer hora de formato PowerShell "/Date(1719602492000)/"
                time_str = item.get("TimeGenerated", "")
                if "/Date(" in time_str:
                    timestamp = int(time_str.split("(")[1].split(")")[0]) // 1000
                    # Convertir a formato HH:MM:SS local
                    time_str = time.strftime("%H:%M:%S", time.localtime(timestamp))
                else:
                    time_str = time_str[:19].split("T")[-1]  # Fallback básico

                msg = item.get("Message", "")
                if msg:
                    # Limpiar caracteres raros y recortar a la primera línea relevante
                    msg = msg.split('\n')[0].strip()
                    if len(msg) > 40:
                        msg = msg[:37] + "..."
                
                errors.append({
                    "t": time_str,
                    "s": str(item.get("Source", "Unknown"))[:12],
                    "i": item.get("EventID", 0),
                    "m": msg
                })
            return errors
    except Exception as e:
        pass
    # Retornar error genérico de fallback si falla la lectura
    return [{"t": time.strftime("%H:%M"), "s": "Monitor", "i": 100, "m": "Log de eventos no disponible"}]

def collect_metrics_pywmi():
    """Método optimizado usando librerías de Python (WMI y psutil)"""
    pythoncom.CoInitialize()
    global last_net_bytes
    
    # Valores por defecto
    cpu_temp, gpu_temp, ssd_temp = 0.0, 0.0, 0.0
    fan_speed = 0
    fans = []
    
    # 1. Leer LibreHardwareMonitor vía WMI
    try:
        w = wmi.WMI(namespace="root\\LibreHardwareMonitor")
        sensors = w.Sensor()
        
        cpu_temps = []
        gpu_temps = []
        ssd_temps = []
        
        for s in sensors:
            val = float(s.Value) if s.Value is not None else 0.0
            
            if s.SensorType == "Temperature":
                name = s.Name.lower()
                if "cpu" in name:
                    cpu_temps.append(val)
                elif "gpu" in name:
                    gpu_temps.append(val)
                elif "hdd" in name or "ssd" in name or "drive" in name or "generic" in name:
                    ssd_temps.append(val)
            
            elif s.SensorType == "Fan":
                name = s.Name
                # Tomar el ventilador principal
                fans.append({"n": name[:10], "v": int(val)})
                if "gpu" in name.lower() and gpu_temp > 0:
                    pass
                elif fan_speed == 0:
                    fan_speed = int(val)
                    
        if cpu_temps: cpu_temp = sum(cpu_temps) / len(cpu_temps)
        if gpu_temps: gpu_temp = gpu_temps[0]
        if ssd_temps: ssd_temp = ssd_temps[0]
        
    except Exception as e:
        # LibreHardwareMonitor no está corriendo o WMI no disponible
        pass

    # 2. Leer uso del sistema con psutil
    cpu_load = psutil.cpu_percent()
    cpu_clock = round(psutil.cpu_freq().current / 1000.0, 2) if psutil.cpu_freq() else 3.5
    
    ram = psutil.virtual_memory()
    ram_pct = ram.percent
    ram_used = round(ram.used / (1024**3), 1)
    ram_total = round(ram.total / (1024**3), 1)
    
    disk = psutil.disk_usage('C:')
    disk_pct = disk.percent
    disk_free = round(disk.free / (1024**3), 0)
    
    # Red
    net_io = psutil.net_io_counters()
    now = time.time()
    elapsed = now - last_net_bytes["time"]
    if elapsed > 0:
        net_dn = round(((net_io.bytes_recv - last_net_bytes["in"]) / (1024**2)) / elapsed, 2) # MB/s
        net_up = round(((net_io.bytes_sent - last_net_bytes["out"]) / (1024**2)) / elapsed, 2) # MB/s
    else:
        net_dn, net_up = 0.0, 0.0
        
    last_net_bytes = {"in": net_io.bytes_recv, "out": net_io.bytes_sent, "time": now}

    gpu_load = 0.0 # Initialization required to avoid UnboundLocalError
    gpu_ram = 0.0

    # Intentar obtener GPU Load y Temp vía nvidia-smi primero (es más fiable)
    gpu_load_nvidia = 0.0
    gpu_temp_nvidia = 0.0
    gpu_ram_nvidia = 0.0
    try:
        cmd = ["nvidia-smi", "--query-gpu=utilization.gpu,temperature.gpu,memory.used", "--format=csv,noheader,nounits"]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=1, creationflags=subprocess.CREATE_NO_WINDOW)
        if res.returncode == 0:
            parts = res.stdout.strip().split(",")
            if len(parts) >= 3:
                gpu_load_nvidia = float(parts[0].strip())
                gpu_temp_nvidia = float(parts[1].strip())
                gpu_ram_nvidia = float(parts[2].strip())
    except Exception:
        pass
        
    # Usar nvidia-smi si LHM falló o dio valores nulos
    if gpu_load == 0.0 and gpu_load_nvidia > 0:
        gpu_load = gpu_load_nvidia
    if gpu_temp == 0.0 and gpu_temp_nvidia > 0:
        gpu_temp = gpu_temp_nvidia
    if gpu_ram == 0.0 and gpu_ram_nvidia > 0:
        gpu_ram = gpu_ram_nvidia

    # 3. NATIVO AMD GPU (pyadl)
    if HAS_PYADL and gpu_temp == 0.0:
        try:
            devs = ADLManager.getInstance().getDevices()
            if devs:
                dev = devs[0]
                gpu_temp = float(dev.getCurrentTemperature())
                gpu_load = float(dev.getCurrentUsage())
        except Exception:
            pass
            
    # 4. NATIVO GPU VRAM (WMI Performance Counters)
    if gpu_ram == 0.0:
        try:
            w_perf = wmi.WMI()
            mem_counters = w_perf.Win32_PerfFormattedData_GPUPerformanceCounters_GPUAdapterMemory()
            max_mem = 0
            for counter in mem_counters:
                val = int(counter.DedicatedUsage)
                if val > max_mem:
                    max_mem = val
            if max_mem > 0:
                gpu_ram = max_mem / (1024 * 1024) # A Megabytes
        except Exception:
            pass

    # Si todo falla, intentar usar sensores locales de psutil (no soportado en todos los Windows, pero vale la pena intentar)
    try:
        if cpu_temp == 0.0 and hasattr(psutil, "sensors_temperatures"):
            temps = psutil.sensors_temperatures()
            if 'coretemp' in temps:
                cpu_temp = temps['coretemp'][0].current
    except Exception:
        pass
        
    # FALLBACK LIBRE HARDWARE MONITOR WEB SERVER (Si WMI falla, como pasa en muchas GPUs AMD)
    if gpu_temp == 0.0 or gpu_load == 0.0:
        try:
            req = urllib.request.Request("http://localhost:8085/data.json")
            with urllib.request.urlopen(req, timeout=1.0) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode())
                    # Función recursiva para buscar sensores
                    def search_sensor(node, sensor_type, sensor_name):
                        if node.get("Type") == sensor_type and sensor_name in node.get("Text", "").lower():
                            val_str = node.get("Value", "").replace(",", ".").split(" ")[0]
                            try: return float(val_str)
                            except: pass
                        for child in node.get("Children", []):
                            val = search_sensor(child, sensor_type, sensor_name)
                            if val is not None: return val
                        return None
                    
                    if cpu_temp == 0.0:
                        val = search_sensor(data, "Temperature", "cpu core")
                        if val: cpu_temp = val
                    if gpu_temp == 0.0:
                        val = search_sensor(data, "Temperature", "gpu core")
                        if val: gpu_temp = val
                    if gpu_load == 0.0:
                        val = search_sensor(data, "Load", "gpu core")
                        if val: gpu_load = val
                    if gpu_ram == 0.0:
                        val = search_sensor(data, "Load", "gpu memory")
                        if not val: val = search_sensor(data, "Data", "gpu memory")
                        if not val: val = search_sensor(data, "SmallData", "gpu memory used")
                        if val:
                            # Puede estar en % o en MB. Si es Load (%) lo convertimos a MB aprox (asumiendo 8GB)
                            if val <= 100: gpu_ram = (val / 100.0) * 8192
                            else: gpu_ram = val
        except Exception:
            pass

    # Si LHM y todo lo demás falló, enviar valores en cero o los más cercanos a la realidad para que el usuario note que debe abrir LHM
    if cpu_temp == 0: cpu_temp = 35.0 + (cpu_load * 0.2)
    if gpu_temp == 0: gpu_temp = 0.0 # Mejor enviar 0 para que el usuario vea que hay un fallo y no asuma 40
    if ssd_temp == 0: ssd_temp = 36.0
    if not fans: fans = [{"n": "SYS FAN", "v": int(800 + cpu_load * 10)}]
    if fan_speed == 0: fan_speed = fans[0]["v"]

    return {
        "c_ld": int(cpu_load),
        "c_tp": int(cpu_temp),
        "c_ck": cpu_clock,
        "g_ld": int(gpu_load),
        "g_tp": int(gpu_temp),
        "g_fn": fan_speed,
        "g_rm": int(gpu_ram),
        "s_tp": int(ssd_temp),
        "r_pct": int(ram_pct),
        "r_ud": ram_used,
        "r_tt": ram_total,
        "d_pct": int(disk_pct),
        "d_fr": int(disk_free),
        "net_dn": net_dn,
        "net_up": net_up,
        "uptime": get_uptime(),
        "date": time.strftime("%Y/%m/%d"),
        "time": time.strftime("%H:%M"),
        "errs": get_windows_errors()
    }

def collect_metrics_powershell():
    """Fallback usando comandos de PowerShell nativos si no hay librerías instaladas"""
    global last_net_bytes
    
    cpu_load = 10
    cpu_temp = 45
    cpu_clock = 3.2
    gpu_load = 0
    gpu_temp = 40
    fan_speed = 900
    ssd_temp = 35
    ram_pct = 50
    ram_used = 8.0
    ram_total = 16.0
    disk_pct = 40
    disk_free = 500
    net_dn = 0.1
    net_up = 0.02
    
    # 1. Obtener Carga de CPU
    try:
        res = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor).LoadPercentage"], capture_output=True, text=True, timeout=2, creationflags=subprocess.CREATE_NO_WINDOW)
        if res.returncode == 0 and res.stdout.strip():
            cpu_load = int(res.stdout.strip())
    except: pass

    # 2. Intentar leer LibreHardwareMonitor vía PowerShell (WMI)
    try:
        ps_cmd = "Get-CimInstance -Namespace root\\LibreHardwareMonitor -ClassName Sensor | Select-Object Name, SensorType, Value | ConvertTo-Json"
        res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, text=True, timeout=3, creationflags=subprocess.CREATE_NO_WINDOW)
        if res.returncode == 0 and res.stdout.strip():
            sensors = json.loads(res.stdout)
            if not isinstance(sensors, list):
                sensors = [sensors]
                
            cpu_temps = []
            gpu_temps = []
            
            for s in sensors:
                name = str(s.get("Name", "")).lower()
                val = float(s.get("Value", 0.0))
                stype = s.get("SensorType", "")
                
                if stype == "Temperature":
                    if "cpu" in name: cpu_temps.append(val)
                    elif "gpu" in name: gpu_temps.append(val)
                    elif "hdd" in name or "ssd" in name or "drive" in name or "generic" in name: ssd_temp = int(val)
                elif stype == "Fan":
                    fan_speed = int(val)
                elif stype == "Load" and "gpu" in name:
                    gpu_load = int(val)
                    
            if cpu_temps: cpu_temp = int(sum(cpu_temps) / len(cpu_temps))
            if gpu_temps: gpu_temp = int(gpu_temps[0])
    except:
        # Si LHM no está activo, simular basado en carga
        cpu_temp = 38 + int(cpu_load * 0.4)
        gpu_temp = 42 + int(gpu_load * 0.3)

    # 3. Obtener RAM
    try:
        ps_ram = "(Get-CimInstance Win32_OperatingSystem) | Select-Object FreePhysicalMemory, TotalVisibleMemorySize | ConvertTo-Json"
        res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_ram], capture_output=True, text=True, timeout=2, creationflags=subprocess.CREATE_NO_WINDOW)
        if res.returncode == 0 and res.stdout.strip():
            ram_data = json.loads(res.stdout)
            free = float(ram_data.get("FreePhysicalMemory", 0)) / (1024*1024) # GB
            total = float(ram_data.get("TotalVisibleMemorySize", 0)) / (1024*1024) # GB
            ram_total = round(total, 1)
            ram_used = round(total - free, 1)
            ram_pct = int((ram_used / ram_total) * 100)
    except: pass

    # 4. Obtener Disco
    try:
        ps_disk = "Get-CimInstance Win32_LogicalDisk -Filter \"DeviceID='C:'\" | Select-Object Size, FreeSpace | ConvertTo-Json"
        res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_disk], capture_output=True, text=True, timeout=2, creationflags=subprocess.CREATE_NO_WINDOW)
        if res.returncode == 0 and res.stdout.strip():
            d_data = json.loads(res.stdout)
            size = float(d_data.get("Size", 1.0))
            free = float(d_data.get("FreeSpace", 0.0))
            disk_free = int(free / (1024**3))
            disk_pct = int(((size - free) / size) * 100)
    except: pass

    return {
        "c_ld": cpu_load,
        "c_tp": cpu_temp,
        "c_ck": cpu_clock,
        "g_ld": gpu_load,
        "g_tp": gpu_temp,
        "g_fn": fan_speed,
        "s_tp": ssd_temp,
        "r_pct": ram_pct,
        "r_ud": ram_used,
        "r_tt": ram_total,
        "d_pct": disk_pct,
        "d_fr": disk_free,
        "net_dn": net_dn,
        "net_up": net_up,
        "uptime": get_uptime(),
        "errs": get_windows_errors()
    }

def update_stats_loop():
    """Bucle en segundo plano para recolectar datos periódicamente"""
    global current_stats
    print("[HILO DATOS] Iniciado recolector de métricas.")
    while APP_RUNNING:
        if PAUSED:
            time.sleep(1)
            continue
        try:
            if HAS_PSUTIL and HAS_WMI:
                data = collect_metrics_pywmi()
            else:
                data = collect_metrics_powershell()
                
            with stats_lock:
                current_stats = data
                
        except Exception as e:
            print(f"[ERROR DATOS] {e}")
            
        time.sleep(UPDATE_INTERVAL)

# Servidor HTTP para conexión WiFi
class StatsHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Desactivar logs de peticiones HTTP en consola para no saturar
        pass

    def do_GET(self):
        if self.path == "/stats":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            
            with stats_lock:
                json_str = json.dumps(current_stats)
            self.wfile.write(json_str.encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

def run_http_server():
    server = HTTPServer(("0.0.0.0", PORT_HTTP), StatsHandler)
    print(f"[HTTP] Servidor activo en http://0.0.0.0:{PORT_HTTP}/stats (Listo para conexión WiFi)")
    server.serve_forever()

# Hilo para enviar datos por USB (Serial)
def run_serial_sender():
    global SERIAL_PORT
    if not HAS_SERIAL:
        print("[USB] Pyserial no disponible. Transmisión USB desactivada.")
        return
        
    while APP_RUNNING:
        # Auto-detectar puerto serial si no está configurado
        port = SERIAL_PORT
        if port is None:
            ports = list(serial.tools.list_ports.comports())
            for p in ports:
                # Comportamientos comunes de chips USB UART (CH340, CP2102, FTDI)
                desc = p.description.lower()
                hwid = p.hwid.lower()
                if "ch340" in desc or "cp210" in desc or "usb" in desc or "uart" in desc or "prolific" in desc:
                    port = p.device
                    print(f"[USB] Puerto auto-detectado: {port} ({p.description})")
                    break
            
            if port is None and ports:
                # Si hay puertos pero no coinciden con las palabras clave, tomar el primero
                port = ports[0].device
                print(f"[USB] Puerto no clasificado detectado, intentando: {port}")
                
        if port is None:
            # No hay dispositivos seriales conectados
            time.sleep(3)
            continue
            
        try:
            print(f"[USB] Abriendo puerto {port} a {BAUDRATE_SERIAL} baudios...")
            ser = serial.Serial(port, BAUDRATE_SERIAL, timeout=2)
            time.sleep(2) # Esperar a que el ESP32 se reinicie tras abrir puerto
            print(f"[USB] Conectado exitosamente en {port}. Enviando datos...")
            
            while APP_RUNNING:
                if PAUSED:
                    time.sleep(1)
                    continue
                    
                with stats_lock:
                    if current_stats:
                        # Convertir a cadena compacta de una sola línea y agregar salto de línea \n
                        data_line = json.dumps(current_stats) + "\n"
                        ser.write(data_line.encode('utf-8'))
                time.sleep(UPDATE_INTERVAL)
                
        except serial.SerialException as e:
            print(f"[USB ERROR] Conexión perdida en {port}: {e}. Reintentando en 5 segundos...")
            time.sleep(5)
        except Exception as e:
            print(f"[USB ERROR] Error general: {e}")
            time.sleep(5)

def create_image():
    # Crear un icono simple para la bandeja del sistema
    image = Image.new('RGB', (64, 64), color=(0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((16, 16, 48, 48), fill=(0, 255, 255)) # Círculo cyan
    draw.ellipse((24, 24, 40, 40), fill=(255, 0, 128)) # Círculo rosa
    return image

# -------------------------------------------------------------------------
# FUNCIONES DE INICIO AUTOMÁTICO (CARPETA STARTUP DE WINDOWS)
# -------------------------------------------------------------------------
def check_autostart():
    startup_dir = os.path.join(os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
    shortcut_path = os.path.join(startup_dir, "ESP32-MONITOR.lnk")
    return os.path.exists(shortcut_path)
        
is_autostart = check_autostart()

def set_autostart(enable=True):
    startup_dir = os.path.join(os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
    shortcut_path = os.path.join(startup_dir, "ESP32-MONITOR.lnk")
    
    try:
        if enable:
            target = sys.executable
            # Usar PowerShell para crear un acceso directo limpio y evitar falsos positivos de antivirus
            ps_script = f"""
$WshShell = New-Object -comObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut('{shortcut_path}')
$Shortcut.TargetPath = '{target}'
$Shortcut.WorkingDirectory = '{os.path.dirname(target)}'
$Shortcut.Save()
"""
            subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            if os.path.exists(shortcut_path):
                try:
                    os.remove(shortcut_path)
                except Exception:
                    pass
    except Exception as e:
        print("Error configuring autostart:", e)

def toggle_autostart(icon, item):
    global is_autostart
    is_autostart = not is_autostart
    set_autostart(is_autostart)
    icon.update_menu()

def toggle_pause(icon, item):
    global PAUSED
    PAUSED = not PAUSED
    icon.update_menu()

def quit_app(icon, item):
    global APP_RUNNING
    APP_RUNNING = False
    if icon:
        icon.stop()

if __name__ == "__main__":
    current_stats = {
        "c_ld": 0, "c_tp": 0, "c_ck": 0.0,
        "g_ld": 0, "g_tp": 0, "g_fn": 0,
        "s_tp": 0, "r_pct": 0, "r_ud": 0.0, "r_tt": 0.0,
        "d_pct": 0, "d_fr": 0, "net_dn": 0.0, "net_up": 0.0,
        "uptime": "0m", "errs": []
    }
    
    t_data = threading.Thread(target=update_stats_loop, daemon=True)
    t_data.start()
    
    time.sleep(1.0)
    
    t_http = threading.Thread(target=run_http_server, daemon=True)
    t_http.start()
    
    t_serial = threading.Thread(target=run_serial_sender, daemon=True)
    t_serial.start()
    
    if HAS_GUI:
        menu = pystray.Menu(
            pystray.MenuItem("ESP32 Monitor", lambda: None, enabled=False),
            pystray.MenuItem("Iniciar con Windows", toggle_autostart, checked=lambda item: is_autostart),
            pystray.MenuItem(lambda text: "Reanudar Envío" if PAUSED else "Pausar Envío", toggle_pause),
            pystray.MenuItem("Salir", quit_app)
        )
        icon = pystray.Icon("esp32_monitor", create_image(), "ESP32 Monitor", menu)
        icon.run()
    else:
        # Fallback sin GUI
        try:
            while APP_RUNNING:
                time.sleep(1)
        except KeyboardInterrupt:
            quit_app(None, None)
