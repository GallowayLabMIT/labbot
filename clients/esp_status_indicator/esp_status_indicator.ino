
#include <ArduinoMqttClient.h>
#include <ESP8266WiFi.h>
#include <time.h>

#include "mqtt_secrets.h"
int onboard = 2;
int redPin = 14;
int yellowPin = 12;
int greenPin = 13;

const char inTopic[] = "status/current";
const char requestTopic[] = "status/request";
const String inTopicStr = String(inTopic);
int heartbeatDelayMillis = 1000 * 60 * 15;

time_t setClock() {
  configTime(3 * 3600, 0, "pool.ntp.org", "time.nist.gov");

  Serial.print("Waiting for NTP time sync: ");
  time_t now = time(nullptr);
  while (now < 8 * 3600 * 2) {
    delay(500);
    Serial.print(".");
    now = time(nullptr);
  }
  Serial.println("");
  struct tm timeinfo;
  gmtime_r(&now, &timeinfo);
  Serial.print("Current time: ");
  Serial.print(asctime(&timeinfo));
  return now;
}

// WiFiFlientSecure for SSL/TLS support
BearSSL::WiFiClientSecure client;
BearSSL::X509List cert(ca_cert);
MqttClient mqttClient(client);

void errorLoop() {
  char stat = 0;
  while (true) {
    digitalWrite(onboard, stat);
    digitalWrite(redPin, stat);
    digitalWrite(yellowPin, stat);
    digitalWrite(greenPin, stat);
    delay(500);
    stat = stat ^ 1;
  }
}

int lastReceiveMillis = 0;
char state = 1;

void onMqttMessage(int messageSize) {
  Serial.print(F("Received on topic: "));
  Serial.println(mqttClient.messageTopic());
  if (mqttClient.messageTopic().compareTo(inTopicStr) == 0 && messageSize > 0) {
    char in_char = (char)mqttClient.read();
    switch (in_char) {
      case '0':
        state = 0;
        break;
      case '1':
        state = 1;
        break;
      case '2':
        state = 2;
        break;
      default:
        errorLoop();
        break;
    }
    lastReceiveMillis = millis();
    while (mqttClient.available()) {
      mqttClient.read();
    }
  }
}

void requestUpdate() {
  mqttClient.beginMessage(requestTopic);
  mqttClient.print('1');
  mqttClient.endMessage();
}
/*************************** Sketch Code ************************************/

void setup() {
  pinMode(onboard, OUTPUT);
  pinMode(redPin, OUTPUT);
  pinMode(yellowPin, OUTPUT);
  pinMode(greenPin, OUTPUT);
  digitalWrite(onboard, LOW);
  
  Serial.begin(115200);
  // Connect to wifi
  Serial.print(F("\nConnecting to wifi"));
  WiFi.begin(WLAN_SSID);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(F("."));
  }
  Serial.println(F("done!"));
  Serial.print(F("IP address: "));
  Serial.println(WiFi.localIP());
  digitalWrite(redPin, HIGH);

  // Set trust anchors and set current time with NTP
  client.setTrustAnchors(&cert);
  setClock();
  digitalWrite(yellowPin, HIGH);

  // Connect to the MQTT broker
  Serial.print(F("Connecting to MQTT broker: "));
  Serial.println(MQTT_BROKER_URL);

  mqttClient.setId(MQTT_CLIENT_ID);
  mqttClient.setUsernamePassword(MQTT_USERNAME, MQTT_PASSWORD);
  if (!mqttClient.connect(MQTT_BROKER_URL, MQTT_PORT)) {
    Serial.print(F("\nMQTT connection failed! Error code = "));
    Serial.println(mqttClient.connectError());
    errorLoop();
  }
  mqttClient.subscribe(inTopic);
  mqttClient.onMessage(onMqttMessage);
  requestUpdate();

  Serial.println(F("Done connecting to MQTT!"));
  digitalWrite(greenPin, HIGH);
  delay(1000);

  digitalWrite(onboard, HIGH);
  digitalWrite(redPin, LOW);
  digitalWrite(yellowPin, LOW);
  digitalWrite(greenPin, LOW);
  delay(1000);
  
  
}

void heartbeat(int pin) {
  int setpoint = (millis() / 6) % 512;
  if (setpoint > 255) {
    analogWrite(pin, 512 - setpoint);
  } else {
    analogWrite(pin, setpoint);
  }
}

void flash(int pin) {
  if (millis() % 1000 < 500) {
    digitalWrite(pin, HIGH);
  } else {
    digitalWrite(pin, LOW);
  }
}

void loop() {
  delay(10);
 
  if(!mqttClient.connected()){ // if the client has been disconnected, 
    if (!mqttClient.connect(MQTT_BROKER_URL, MQTT_PORT)) {
        Serial.print("MQTT connection failed! Error code = ");
        Serial.println(mqttClient.connectError());
        errorLoop();
    }
  }
  mqttClient.poll();

  // Check to see if we haven't gotten a heartbeat in a while
  int currentMillis = millis();
  if (currentMillis < lastReceiveMillis || (currentMillis - lastReceiveMillis) > heartbeatDelayMillis) {
    if (state == 0) {
      state = 1;
    }
    requestUpdate();
    Serial.println(F("Requesting update from server, no heartbeat received!"));
    lastReceiveMillis = currentMillis;
  }
  switch (state) {
    case 0:
      digitalWrite(redPin, LOW);
      digitalWrite(yellowPin, LOW);
      digitalWrite(greenPin, HIGH);
      break;
    case 1:
      digitalWrite(redPin, LOW);
      digitalWrite(greenPin, LOW);
      heartbeat(yellowPin);
      break;
    case 2:
      digitalWrite(yellowPin, LOW);
      digitalWrite(greenPin, LOW);
      flash(redPin);
      break;
  }
}
