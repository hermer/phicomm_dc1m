"""Constants for the AirCat integration."""

from homeassistant.const import Platform

DOMAIN = "phicomm_dc1m"
PLATFORMS = [Platform.SENSOR]

CONF_MACS = "macs"
CONF_NAME = "name"
CONF_BFU = "brightness_force_update"
CONF_SENSOR_TYPES = "sensor_types"

DEFAULT_NAME = "AirCat"
DEFAULT_PORT = 9000

SENSOR_PM25 = "value"
SENSOR_HCHO = "hcho"
SENSOR_TEMPERATURE = "temperature"
SENSOR_HUMIDITY = "humidity"

SENSOR_TYPES = {
    SENSOR_PM25: {
        "name": "PM2.5",
        "unit": "µg/m³",
        "icon": "mdi:blur",
        "device_class": "pm25",
        "state_class": "measurement",
    },
    SENSOR_HCHO: {
        "name": "HCHO",
        "unit": "mg/m³",
        "icon": "mdi:biohazard",
        "device_class": "volatile_organic_compounds",
        "state_class": "measurement",
    },
    SENSOR_TEMPERATURE: {
        "name": "Temperature",
        "unit": "°C",
        "icon": "mdi:thermometer",
        "device_class": "temperature",
        "state_class": "measurement",
    },
    SENSOR_HUMIDITY: {
        "name": "Humidity",
        "unit": "%",
        "icon": "mdi:water-percent",
        "device_class": "humidity",
        "state_class": "measurement",
    },
}

BRIGHTNESS_OFF = "关闭"
BRIGHTNESS_NIGHT = "夜间"
BRIGHTNESS_NORMAL = "正常"

BRIGHTNESS_MAP = {
    BRIGHTNESS_OFF: 0,
    BRIGHTNESS_NIGHT: 50,
    BRIGHTNESS_NORMAL: 80,
}
