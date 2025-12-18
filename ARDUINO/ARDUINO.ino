
#include <WiFi.h>
#include <HTTPClient.h>
#include <SD.h>
#include <SPI.h>

// ===== CONFIG =====
const char* ssid = "Sowjanya";
const char* password = "Sdevi@!06";
String serverUrl = "http://10.233.253.123:8000/upload";

#define MIC_PIN 34
#define SD_CS 5
#define SAMPLE_RATE 16000
#define RECORD_SECONDS 30
#define WAV_FILE "/record.wav"

// ===== WAV HEADER =====
typedef struct {
  char riff_header[4];
  uint32_t wav_size;
  char wave_header[4];
  char fmt_header[4];
  uint32_t fmt_chunk_size;
  uint16_t audio_format;
  uint16_t num_channels;
  uint32_t sample_rate;
  uint32_t byte_rate;
  uint16_t sample_alignment;
  uint16_t bit_depth;
  char data_header[4];
  uint32_t data_bytes;
} WAVHeader;

void createWavHeader(WAVHeader &header, uint32_t sampleRate, uint32_t numSamples) {
  memcpy(header.riff_header, "RIFF", 4);
  memcpy(header.wave_header, "WAVE", 4);
  memcpy(header.fmt_header, "fmt ", 4);
  memcpy(header.data_header, "data", 4);

  header.fmt_chunk_size = 16;
  header.audio_format = 1;
  header.num_channels = 1;
  header.sample_rate = sampleRate;
  header.bit_depth = 16;
  header.byte_rate = sampleRate * header.num_channels * (header.bit_depth / 8);
  header.sample_alignment = header.num_channels * (header.bit_depth / 8);
  header.data_bytes = numSamples * header.sample_alignment;
  header.wav_size = header.data_bytes + sizeof(WAVHeader) - 8;
}

// ===== RECORD AUDIO =====
bool recordAudio() {
  // ---- FIX: Always delete old file before recording ----
  if (SD.exists(WAV_FILE)) {
    Serial.println("🗑 Deleting old WAV file...");
    SD.remove(WAV_FILE);
    delay(100);  // small safety delay
  }
  
  uint32_t numSamples = SAMPLE_RATE * RECORD_SECONDS;
  File file = SD.open(WAV_FILE, FILE_WRITE);
  if (!file) {
    Serial.println("❌ Failed to open file for writing!");
    return false;
  }

  WAVHeader header;
  createWavHeader(header, SAMPLE_RATE, numSamples);
  file.write((uint8_t*)&header, sizeof(WAVHeader));

  Serial.println("🎙 Recording...");
  unsigned long interval = 1000000UL / SAMPLE_RATE;
  unsigned long t = micros();

  for (uint32_t i = 0; i < numSamples; i++) {
    while (micros() - t < interval);
    t += interval;

    int16_t sample = analogRead(MIC_PIN) - 2048; // center
    sample *= 16; // scale
    file.write((uint8_t*)&sample, sizeof(sample));

    if (i % 1000 == 0) {
      Serial.print("📊 Sample #: "); Serial.println(i);
    }
  }

  file.close();
  Serial.println("✅ Recording complete!");
  return true;
}

// ===== UPLOAD TO SERVER =====
bool uploadToServer(String filename) {
  File file = SD.open(filename);
  if (!file) {
    Serial.println("❌ Cannot open file for upload!");
    return false;
  }

  WiFiClient client;
  HTTPClient http;
  http.begin(client, serverUrl);

  String boundary = "----ESP32Boundary";
  http.addHeader("Content-Type", "multipart/form-data; boundary=" + boundary);

  String head = "--" + boundary + "\r\n";
  head += "Content-Disposition: form-data; name=\"file\"; filename=\"record.wav\"\r\n";
  head += "Content-Type: audio/wav\r\n\r\n";

  String tail = "\r\n--" + boundary + "--\r\n";

  int totalLen = head.length() + file.size() + tail.length();
  http.addHeader("Content-Length", String(totalLen));

  Serial.println("🌐 Uploading...");

  if (!client.connect("10.233.253.123", 8000)) {
    Serial.println("❌ Connection failed");
    file.close();
    http.end();
    return false;
  }

  // Send headers
  client.print(String("POST /upload HTTP/1.1\r\n") +
               "Host:10.233.253.123\r\n" +
               "Content-Type: multipart/form-data; boundary=" + boundary + "\r\n" +
               "Content-Length: " + String(totalLen) + "\r\n\r\n");

  // Send file data
  client.print(head);
  uint8_t buf[512];
  while (file.available()) {
    size_t n = file.read(buf, sizeof(buf));
    client.write(buf, n);
  }
  client.print(tail);

  // Read response
  unsigned long start = millis();
  while (!client.available() && millis() - start < 5000) delay(10);
  Serial.println("📨 Server response:");
  while (client.available()) Serial.write(client.read());

  file.close();
  http.end();
  return true;
}

// ===== SETUP =====
void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println("🔌 Connecting to WiFi...");
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500); Serial.print(".");
  }
  Serial.printf("\n✅ Connected! IP: %s\n", WiFi.localIP().toString().c_str());

  if (!SD.begin(SD_CS)) {
    Serial.println("❌ SD init failed!");
    while (true);
  }
  Serial.println("✅ SD card ready.");
  analogReadResolution(12);
  Serial.println("✅ Analog mic ready.");
}

// ===== LOOP =====
void loop() {
  if (recordAudio()) {
    if (!uploadToServer(WAV_FILE)) {
      Serial.println("⚠️ Upload failed, will retry next loop.");
    }
  }
  Serial.println("⏳ Waiting 30 seconds before next recording...");
  delay(30000);
}


