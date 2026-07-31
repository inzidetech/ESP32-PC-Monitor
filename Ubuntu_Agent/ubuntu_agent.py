#!/usr/bin/env python3
import os
import sys
import time
import json
import threading
import subprocess
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler

try:
    import psutil
except ImportError:
    print("Por favor instala psutil: pip3 install psutil")
    sys.exit(1)

try:
    import serial
    import serial.tools.list_ports
    HAS_SERIAL = True
except ImportError:
    print("Por favor instala pyserial: pip3 install pyserial")
    HAS_SERIAL = False

# Variables de Configuración
PORT_HTTP = 8080
BAUDRATE_SERIAL = 115200
UPDATE_INTERVAL = 1.5

current_stats = {}
stats_lock = threading.Lock()
start_time = time.time()
last_net_bytes = {"in": 0, "out": 0, "time": time.time()}

def get_uptime():
    with open('/proc/uptime', 'r') as f:
        uptime_seconds = float(f.readline().split()[0])
    hours = int(uptime_seconds // 3600)
    minutes = int((uptime_seconds % 3600) // 60)
    if hours > 0: return f"{hours}h {minutes}m"
    return f"{minutes}m"

def get_sys_errors():
    try:
        cmd = ["journalctl", "-p", "3", "-n", "4", "--no-pager", "--output=json"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
        errors = []
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split('\n')
            for line in lines:
                try:
                    data = json.loads(line)
                    ts = int(data.get("__REALTIME_TIMESTAMP", 0)) // 1000000
                    time_str = time.strftime("%H:%M:%S", time.localtime(ts)) if ts > 0 else ""
                    msg = data.get("MESSAGE", "")[:37]
                    src = data.get("SYSLOG_IDENTIFIER", "Sys")[:12]
                    errors.append({"t": time_str, "s": src, "i": 100, "m": msg})
                except: pass
        return errors if errors else [{"t": time.strftime("%H:%M"), "s": "Monitor", "i": 200, "m": "Sistema OK (Sin errores críticos)"}]
    except:
        return [{"t": time.strftime("%H:%M"), "s": "Monitor", "i": 100, "m": "No se pudo leer journalctl"}]

def read_amdgpu_stats():
    gpu_temp = 0.0
    gpu_load = 0.0
    gpu_ram = 0.0
    try:
        hwmon_dir = "/sys/class/drm/card0/device/hwmon/"
        if os.path.exists(hwmon_dir):
            hwmon_sub = os.listdir(hwmon_dir)[0]
            temp_file = os.path.join(hwmon_dir, hwmon_sub, "temp1_input")
            if os.path.exists(temp_file):
                with open(temp_file, "r") as f:
                    gpu_temp = float(f.read().strip()) / 1000.0

        load_file = "/sys/class/drm/card0/device/gpu_busy_percent"
        if os.path.exists(load_file):
            with open(load_file, "r") as f:
                gpu_load = float(f.read().strip())

        vram_used = "/sys/class/drm/card0/device/mem_info_vram_used"
        if os.path.exists(vram_used):
            with open(vram_used, "r") as f:
                gpu_ram = float(f.read().strip()) / (1024.0 * 1024.0) # Bytes a MB
    except Exception:
        pass
    return gpu_load, gpu_temp, gpu_ram

def collect_metrics():
    global last_net_bytes
    
    cpu_load = psutil.cpu_percent()
    try:
        cpu_clock = round(psutil.cpu_freq().current / 1000.0, 2)
    except: cpu_clock = 2.0
    
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    
    net_io = psutil.net_io_counters()
    now = time.time()
    elapsed = now - last_net_bytes["time"]
    if elapsed > 0:
        net_dn = round(((net_io.bytes_recv - last_net_bytes["in"]) / (1024**2)) / elapsed, 2)
        net_up = round(((net_io.bytes_sent - last_net_bytes["out"]) / (1024**2)) / elapsed, 2)
    else:
        net_dn, net_up = 0.0, 0.0
    last_net_bytes = {"in": net_io.bytes_recv, "out": net_io.bytes_sent, "time": now}
    
    cpu_temp = 0.0
    ssd_temp = 0.0
    try:
        temps = psutil.sensors_temperatures()
        if 'coretemp' in temps: cpu_temp = temps['coretemp'][0].current
        elif 'k10temp' in temps: cpu_temp = temps['k10temp'][0].current
        elif 'cpu_thermal' in temps: cpu_temp = temps['cpu_thermal'][0].current # Raspberry Pi
        
        if 'nvme' in temps: ssd_temp = temps['nvme'][0].current
    except: pass
    
    # GPU Nvidia
    g_load, g_temp, g_ram = 0.0, 0.0, 0.0
    try:
        res = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,temperature.gpu,memory.used", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=1)
        if res.returncode == 0:
            parts = res.stdout.strip().split(",")
            g_load, g_temp, g_ram = float(parts[0]), float(parts[1]), float(parts[2])
    except: pass
    
    # GPU AMD
    if g_temp == 0:
        a_load, a_temp, a_ram = read_amdgpu_stats()
        if a_temp > 0:
            g_load, g_temp, g_ram = a_load, a_temp, a_ram
            
    if cpu_temp == 0: cpu_temp = 40.0 + (cpu_load * 0.2)
    
    return {
        "c_ld": int(cpu_load),
        "c_tp": int(cpu_temp),
        "c_ck": cpu_clock,
        "g_ld": int(g_load),
        "g_tp": int(g_temp),
        "g_fn": 0,
        "g_rm": int(g_ram),
        "s_tp": int(ssd_temp) if ssd_temp > 0 else 35,
        "r_pct": int(ram.percent),
        "r_ud": round(ram.used / (1024**3), 1),
        "r_tt": round(ram.total / (1024**3), 1),
        "d_pct": int(disk.percent),
        "d_fr": int(disk.free / (1024**3)),
        "net_dn": net_dn,
        "net_up": net_up,
        "uptime": get_uptime(),
        "date": time.strftime("%Y/%m/%d"),
        "time": time.strftime("%H:%M"),
        "errs": get_sys_errors()
    }

def update_stats_loop():
    global current_stats
    print("[HILO DATOS] Iniciado recolector de métricas para Linux.")
    while True:
        try:
            with stats_lock:
                current_stats = collect_metrics()
        except Exception as e:
            print(f"[ERROR DATOS] {e}")
        time.sleep(UPDATE_INTERVAL)

class StatsHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args): pass
    def do_GET(self):
        if self.path == "/stats":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            with stats_lock:
                self.wfile.write(json.dumps(current_stats).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

def run_http_server():
    server = HTTPServer(("0.0.0.0", PORT_HTTP), StatsHandler)
    print(f"[HTTP] Servidor activo en http://0.0.0.0:{PORT_HTTP}/stats")
    server.serve_forever()

def run_serial_sender():
    if not HAS_SERIAL: return
    while True:
        port = None
        ports = list(serial.tools.list_ports.comports())
        for p in ports:
            # En Linux los puertos USB a UART suelen ser ttyUSB* o ttyACM*
            if "USB" in p.device or "ACM" in p.device:
                port = p.device
                print(f"[USB] Puerto auto-detectado: {port}")
                break
        
        if not port:
            time.sleep(3)
            continue
            
        try:
            ser = serial.Serial(port, BAUDRATE_SERIAL, timeout=2)
            time.sleep(2)
            print(f"[USB] Conectado exitosamente en {port}. Enviando datos...")
            while True:
                with stats_lock:
                    if current_stats:
                        data_line = json.dumps(current_stats) + "\\n"
                        ser.write(data_line.encode('utf-8'))
                time.sleep(UPDATE_INTERVAL)
        except Exception as e:
            print(f"[USB ERROR] {e}. Reintentando...")
            time.sleep(5)

if __name__ == "__main__":
    t_data = threading.Thread(target=update_stats_loop, daemon=True)
    t_data.start()
    
    time.sleep(1.0)
    t_http = threading.Thread(target=run_http_server, daemon=True)
    t_http.start()
    
    try:
        run_serial_sender()
    except KeyboardInterrupt:
        print("Saliendo...")
        sys.exit(0)
