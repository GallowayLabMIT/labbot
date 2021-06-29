#ifndef MQTT_SECRETS
#define MQTT_SECRETS

// Enter entries in all of these 
#define WLAN_SSID "YOUR_SSID"
#define MQTT_BROKER_URL "example.com"
#define MQTT_PORT 8883
#define MQTT_CLIENT_ID "YOUR_CLIENT_ID"
#define MQTT_USERNAME "YOUR_USERNAME"
#define MQTT_PASSWORD "YOUR_PASSWORD"

static const char ca_cert[] PROGMEM = R"EOF(
-----BEGIN CERTIFICATE-----
PREFERABLY A ROOT KEY SO YOU
DON'T HAVE TO REFLASH YOUR ESP's
-----END CERTIFICATE-----
)EOF";
#endif
