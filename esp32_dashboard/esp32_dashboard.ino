#include <SPI.h>
#include <TFT_eSPI.h>
#include <ArduinoJson.h>
#include <XPT2046_Touchscreen.h>
#include <WiFi.h>
#include <HTTPClient.h>

// -------------------------------------------------------------------------
// CONFIGURACIÓN DE CONEXIÓN WIFI (Modificar según tu red)
// -------------------------------------------------------------------------
const char* ssid     = "INZIDETECH_INV";
const char* password = "73128373";
const char* pc_ip    = "192.168.1.48";
const int   pc_port  = 8080;

// -------------------------------------------------------------------------
// CONFIGURACIÓN TÁCTIL (Pines de CYD)
// -------------------------------------------------------------------------
#define XPT2046_CS   33
#define XPT2046_IRQ  36
XPT2046_Touchscreen touch(XPT2046_CS, XPT2046_IRQ);

#define TOUCH_MIN_X  200
#define TOUCH_MAX_X  3800
#define TOUCH_MIN_Y  200
#define TOUCH_MAX_Y  3800

// -------------------------------------------------------------------------
// PANTALLA TFT
// -------------------------------------------------------------------------
TFT_eSPI tft = TFT_eSPI();

#ifndef TFT_BL
#define TFT_BL 21
#endif

// Colores del Diseño Turing Smart Screen
#define COLOR_BG      0x0024 // Dark blue background
#define COLOR_CYAN    0x07FF // Neon cyan
#define COLOR_PINK    0xF81F // Neon pink/magenta
#define COLOR_TEXT    0xFFFF // White
#define COLOR_DIM     0x2965 // Dimmed cyan/blue for backgrounds

// -------------------------------------------------------------------------
// VARIABLES GLOBALES
// -------------------------------------------------------------------------
struct PCMetrics {
  int cpu_load;
  int cpu_temp;
  float cpu_clock;
  int gpu_load;
  int gpu_temp;
  int gpu_fan;
  int gpu_ram; // VRAM
  int ssd_temp;
  int ram_pct;
  float ram_used;
  float ram_total;
  int disk_pct;
  int disk_free;
  float net_down;
  float net_up;
  String uptime;
  String date_str;
  String time_str;
};

PCMetrics metrics = {0, 0, 0.0, 0, 0, 0, 0, 0, 0, 0.0, 0.0, 0, 0, 0.0, 0.0, "", "", ""};
PCMetrics last_metrics;

enum ConnMode { MODE_USB, MODE_WIFI };
ConnMode current_mode = MODE_USB;
bool is_connected = false;

unsigned long last_request_time = 0;
const unsigned long request_interval = 1500;
unsigned long last_serial_rx_time = 0;
const unsigned long serial_timeout = 4000;

// Prototipos
void drawStaticUI();
void updateDynamicUI();
bool processJsonData(String jsonStr);
void readTouch();
void drawArc(int x, int y, int r, int thickness, int start_angle, int end_angle, uint16_t color);
void drawGauge(int x, int y, int r, int thickness, int val_pct, uint16_t color, uint16_t bg_color);

void setup() {
  Serial.begin(115200);
  
  pinMode(TFT_BL, OUTPUT);
  digitalWrite(TFT_BL, HIGH);

  tft.begin();
  tft.setRotation(1);
  tft.invertDisplay(true); // <--- CORRECCIÓN DE COLORES INVERTIDOS (FONDO BLANCO)
  tft.fillScreen(COLOR_BG);

  SPI.begin(14, 12, 13);
  touch.begin();
  touch.setRotation(1);

  if (strcmp(ssid, "TU_SSID_WIFI") != 0) {
    WiFi.begin(ssid, password);
  }

  drawStaticUI();
}

void loop() {
  readTouch();

  if (current_mode == MODE_USB) {
    if (Serial.available()) {
      String jsonStr = Serial.readStringUntil('\n');
      if (processJsonData(jsonStr)) {
        is_connected = true;
        last_serial_rx_time = millis();
      }
    }
    if (is_connected && (millis() - last_serial_rx_time > serial_timeout)) {
      is_connected = false;
    }
  } 
  else {
    if (WiFi.status() == WL_CONNECTED) {
      if (millis() - last_request_time > request_interval) {
        last_request_time = millis();
        HTTPClient http;
        http.begin("http://" + String(pc_ip) + ":" + String(pc_port) + "/stats");
        http.setTimeout(1000);
        if (http.GET() == HTTP_CODE_OK) {
          if (processJsonData(http.getString())) is_connected = true;
        } else {
          is_connected = false;
        }
        http.end();
      }
    } else {
      is_connected = false;
    }
  }

  updateDynamicUI();
  delay(20);
}

// -------------------------------------------------------------------------
// PROCESAMIENTO JSON
// -------------------------------------------------------------------------
bool processJsonData(String jsonStr) {
  if (jsonStr.length() < 10) return false;

  #if ARDUINOJSON_VERSION_MAJOR >= 7
    JsonDocument doc;
  #else
    DynamicJsonDocument doc(1536);
  #endif

  if (deserializeJson(doc, jsonStr)) return false;

  metrics.cpu_load  = doc["c_ld"] | 0;
  metrics.cpu_temp  = doc["c_tp"] | 0;
  metrics.cpu_clock = doc["c_ck"] | 0.0;
  metrics.gpu_load  = doc["g_ld"] | 0;
  metrics.gpu_temp  = doc["g_tp"] | 0;
  metrics.gpu_fan   = doc["g_fn"] | 0;
  metrics.gpu_ram   = doc["g_rm"] | 0; // VRAM
  metrics.ssd_temp  = doc["s_tp"] | 0;
  metrics.ram_pct   = doc["r_pct"] | 0;
  metrics.ram_used  = doc["r_ud"] | 0.0;
  metrics.ram_total = doc["r_tt"] | 0.0;
  metrics.disk_pct  = doc["d_pct"] | 0;
  metrics.disk_free = doc["d_fr"] | 0;
  metrics.net_down  = doc["net_dn"] | 0.0;
  metrics.net_up    = doc["net_up"] | 0.0;
  metrics.uptime    = doc["uptime"] | "";
  metrics.date_str  = doc["date"] | "2024/01/01";
  metrics.time_str  = doc["time"] | "00:00";

  return true;
}

// -------------------------------------------------------------------------
// DIBUJO ESTÁTICO (Réplica del Diseño Turing)
// -------------------------------------------------------------------------
void drawStaticUI() {
  tft.fillScreen(COLOR_BG);
  
  // Dibujar líneas de HUD decorativas de fondo
  tft.drawCircle(160, 120, 85, COLOR_DIM);
  tft.drawCircle(160, 120, 95, COLOR_DIM);
  tft.drawLine(0, 20, 60, 20, COLOR_CYAN);
  tft.drawLine(60, 20, 70, 30, COLOR_CYAN);
  tft.drawLine(70, 30, 120, 30, COLOR_CYAN);
  
  // Textos estáticos Izquierda (Se quitó Network)
  
  tft.setTextColor(COLOR_CYAN);
  tft.drawCentreString("RAM", 30, 135, 2); // Subido un poco más
  tft.drawRect(5, 205, 100, 10, COLOR_CYAN); // Contenedor barra RAM

  // Textos estáticos Centro (CPU)
  tft.setTextColor(COLOR_CYAN);
  tft.drawCentreString("USO DE CPU", 160, 75, 1); // Renombrado de CPU CORE
  tft.drawCentreString("AMD RYZEN / INTEL", 160, 205, 1); // Simula el texto del procesador
  
  // Textos estáticos Derecha
  tft.setTextColor(COLOR_CYAN);
  tft.drawString("GPU RAM", 240, 80, 2); // Subido más arriba
  tft.drawRect(305, 50, 10, 140, COLOR_PINK); // Contenedor barra VRAM (Vertical a la derecha)
  
  // Etiquetas pequeñas de medidores
  tft.setTextColor(COLOR_TEXT);
  tft.drawCentreString("CPU TEMP", 40, 35, 1); // Movido a la esquina superior izquierda
  tft.drawCentreString("GPU TEMP", 270, 170, 1); // Subido un poco
  
  // Forzar actualización total
  last_metrics = PCMetrics();
}

// -------------------------------------------------------------------------
// ACTUALIZACIÓN DINÁMICA
// -------------------------------------------------------------------------
void updateDynamicUI() {
  // RELOJ Y FECHA (Top Right)
  if (metrics.time_str != last_metrics.time_str || metrics.date_str != last_metrics.date_str) {
    // Uso del modo de color con fondo para no tapar el arco circular de fondo con un rect
    tft.setTextColor(COLOR_CYAN, COLOR_BG);
    tft.drawString(metrics.date_str, 220, 10, 2); 
    tft.setTextColor(COLOR_TEXT, COLOR_BG);
    tft.drawString(metrics.time_str, 230, 28, 4); 
  }

  // RED (NETWORK) eliminado según solicitud, reemplazado por CPU TEMP más adelante

  // MEDIDOR CENTRAL (CPU LOAD)
  if (metrics.cpu_load != last_metrics.cpu_load) {
    // Dibujar anillo de progreso exterior (Cyan) - Más pequeño
    drawGauge(160, 120, 75, 8, metrics.cpu_load, COLOR_CYAN, COLOR_DIM);
    // Dibujar anillo interior secundario (Pink) - Más pequeño
    drawGauge(160, 120, 60, 4, metrics.cpu_load, COLOR_PINK, COLOR_DIM);
    
    // Texto central grande (Tamaño incrementado + %)
    tft.fillRect(125, 100, 70, 45, COLOR_BG); // Limpieza exacta solo en el hoyo central
    tft.setTextColor(COLOR_PINK);
    tft.drawCentreString(String(metrics.cpu_load) + "%", 160, 105, 6); // Aumentado a Fuente 6 con %
  }

  // MEDIDORES CIRCULARES SECUNDARIOS
  // 1. RAM STATUS
  if (metrics.ram_pct != last_metrics.ram_pct || metrics.ram_used != last_metrics.ram_used) {
    drawGauge(30, 180, 20, 3, metrics.ram_pct, COLOR_CYAN, COLOR_DIM);
    tft.fillRect(15, 172, 30, 16, COLOR_BG);
    tft.setTextColor(COLOR_TEXT);
    tft.drawCentreString(String(metrics.ram_pct), 30, 172, 2);
    
    // Texto de MB usados
    tft.fillRect(60, 172, 45, 18, COLOR_BG);
    tft.setTextColor(COLOR_CYAN);
    tft.drawString(String(metrics.ram_used, 0) + " GB", 60, 172, 2);
    
    // Barra lineal
    tft.fillRect(6, 206, 98, 8, COLOR_BG);
    int w = (98 * metrics.ram_pct) / 100;
    tft.fillRect(6, 206, w, 8, COLOR_CYAN);
  }

  // 2. CPU TEMP (Gauge movido a donde estaba Network, más abajo y más grande)
  if (metrics.cpu_temp != last_metrics.cpu_temp) {
    drawGauge(40, 75, 25, 4, (metrics.cpu_temp * 100) / 100, COLOR_PINK, COLOR_DIM); // y=75, radio=25
    tft.fillRect(25, 67, 30, 16, COLOR_BG);
    tft.setTextColor(COLOR_TEXT);
    tft.drawCentreString(String(metrics.cpu_temp), 40, 67, 2);
  }

  // 3. GPU RAM (VRAM) - Ahora con barra VERTICAL en el lado derecho
  if (metrics.gpu_ram != last_metrics.gpu_ram) {
    int vram_pct = (metrics.gpu_ram * 100) / 8192;
    if (vram_pct > 100) vram_pct = 100;
    
    drawGauge(265, 125, 20, 3, vram_pct, COLOR_CYAN, COLOR_DIM); // Bajado a y=125
    tft.fillRect(250, 117, 30, 16, COLOR_BG);
    tft.setTextColor(COLOR_TEXT);
    tft.drawCentreString(String(vram_pct), 265, 117, 2);
    
    // Eliminado el texto de 'xxxxM'
    
    // Barra VERTICAL VRAM a la derecha
    tft.fillRect(306, 51, 8, 138, COLOR_BG);
    int h = (138 * vram_pct) / 100;
    tft.fillRect(306, 51 + (138 - h), 8, h, COLOR_PINK);
  }

  // 4. GPU TEMP (Movido más abajo)
  if (metrics.gpu_temp != last_metrics.gpu_temp) {
    drawGauge(270, 210, 20, 4, metrics.gpu_temp, COLOR_PINK, COLOR_DIM);
    tft.fillRect(260, 202, 20, 16, COLOR_BG);
    tft.setTextColor(COLOR_TEXT);
    tft.drawCentreString(String(metrics.gpu_temp), 270, 202, 2);
  }

  last_metrics = metrics;
}

// -------------------------------------------------------------------------
// LECTURA TÁCTIL (Para switch USB/WIFI)
// -------------------------------------------------------------------------
void readTouch() {
  if (touch.touched()) {
    TS_Point p = touch.getPoint();
    if (p.z < 300) return;
    
    // Toque en la esquina superior izquierda reinicia/cambia modo
    int16_t x = map(p.x, TOUCH_MIN_X, TOUCH_MAX_X, 0, 320);
    int16_t y = map(p.y, TOUCH_MIN_Y, TOUCH_MAX_Y, 240, 0);

    static unsigned long last_button_press = 0;
    if (x < 50 && y < 50 && (millis() - last_button_press > 800)) {
      last_button_press = millis();
      current_mode = (current_mode == MODE_USB) ? MODE_WIFI : MODE_USB;
      is_connected = false;
      drawStaticUI();
    }
  }
}

// -------------------------------------------------------------------------
// FUNCIONES GRÁFICAS DE DIBUJO DE ANILLOS (Optimizado sin librerías externas)
// -------------------------------------------------------------------------
void drawArc(int x, int y, int r, int thickness, int start_angle, int end_angle, uint16_t color) {
  for (int a = start_angle; a <= end_angle; a++) {
    float rad = a * 0.0174532925;
    float cos_a = cos(rad);
    float sin_a = sin(rad);
    for (int w = 0; w < thickness; w++) {
      int px = x + cos_a * (r - w);
      int py = y + sin_a * (r - w);
      tft.drawPixel(px, py, color);
    }
  }
}

// Dibuja un medidor circular con fondo oscuro y progreso a color
void drawGauge(int x, int y, int r, int thickness, int val_pct, uint16_t color, uint16_t bg_color) {
  if (val_pct < 0) val_pct = 0;
  if (val_pct > 100) val_pct = 100;
  
  // El arco va de 135 grados a 405 grados (270 grados en total)
  int start_angle = 135;
  int total_angle = 270;
  int active_angle = start_angle + (total_angle * val_pct) / 100;
  
  // Dibujar arco activo (con pasos de 2 grados para velocidad)
  for (int a = start_angle; a <= start_angle + total_angle; a+=2) {
    float rad = a * 0.0174532925;
    float cos_a = cos(rad);
    float sin_a = sin(rad);
    uint16_t draw_color = (a <= active_angle) ? color : bg_color;
    
    // Dibujar el grosor
    for (int w = 0; w < thickness; w++) {
      int px = x + cos_a * (r - w);
      int py = y + sin_a * (r - w);
      tft.drawPixel(px, py, draw_color);
      // Rellenar huecos por los pasos de 2 grados
      tft.drawPixel(px+1, py, draw_color);
    }
  }
}
