"""Platform for sensor integration."""
import aiohttp
import asyncio
import logging
import struct

from homeassistant.components.sensor import (
    SensorDeviceClass,
)
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import EconestConfigEntry
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
        hass: HomeAssistant,
        config_entry: EconestConfigEntry,
        async_add_entities: AddEntitiesCallback) -> None:
    """Set up sensor platform"""
    econest_energy = config_entry.runtime_data
    host = config_entry.data["host"]
    uuid = await econest_energy.register_uuid(host)
    if uuid:
        data_ctrl_res = await econest_energy.data_ctrl(uuid, host)
        if data_ctrl_res:
            sensor_manager = WebSocketSensorManager(hass, async_add_entities, econest_energy, uuid, host)
            hass.data.setdefault(DOMAIN, {})[config_entry.entry_id] = sensor_manager
            hass.loop.create_task(sensor_manager.start())


class WebSocketSensorManager:
    """Classes for managing WebSocket connections and sensors"""

    def __init__(self, hass, async_add_entities, econest_energy, uuid, host):
        self.hass = hass
        self.async_add_entities = async_add_entities
        self.sensors = {}
        self.econest_energy = econest_energy
        self.websocket_url = "ws://{}/ws/interface?uuid={}"
        self.running = True
        self.uuid = uuid
        self.host = host
        self.ws = None

    async def start(self):
        """Start WebSocket client"""
        while self.running:
            if self.econest_energy.econest_type == "serial_number":
                url = self.websocket_url.format(self.econest_energy.serial_number_name, self.uuid)
            elif self.econest_energy.econest_type == "serial_number_local":
                url = self.websocket_url.format(self.econest_energy.serial_number_name + ".local", self.uuid)
            else:
                url = self.websocket_url.format(self.host, self.uuid)
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(url) as ws:
                        self.ws = ws
                        _LOGGER.info("WebSocket connection established")

                        async def send_heartbeat():
                            while self.running:
                                try:
                                    await ws.ping()
                                    _LOGGER.debug("Heartbeat sent")
                                except Exception as e:
                                    _LOGGER.error("Failed to send heartbeat: %s", e)
                                    break
                                await asyncio.sleep(10)

                        heartbeat_task = asyncio.create_task(send_heartbeat())
                        try:
                            async for msg in ws:
                                if not self.running:
                                    break
                                if msg.type == aiohttp.WSMsgType.BINARY:
                                    await self.handle_message(msg.data)
                                elif msg.type == aiohttp.WSMsgType.ERROR:
                                    _LOGGER.error("WebSocket error: %s", msg.data)
                        finally:
                            _LOGGER.debug("task cancel")
                            heartbeat_task.cancel()
            except aiohttp.ClientError as e:
                _LOGGER.error("WebSocket connection failed: %s", e)
            except asyncio.CancelledError:
                _LOGGER.info("WebSocket connection canceled")
                break
            except Exception as e:
                _LOGGER.error("Unexpected error: %s", e)
                if not self.running:
                    break
            if self.running:
                _LOGGER.info("Attempting to reconnect in 10 seconds...")
                await asyncio.sleep(10)

    def stop(self):
        self.running = False
        if self.ws:
            asyncio.create_task(self.ws.close())

    async def handle_message(self, data):
        """Processing WebSocket messages"""
        analysis_device_data = self.analysis_data(data)
        if analysis_device_data:
            device_datas = {"main": analysis_device_data["sampleDataWsPayload"]["mainChData"],
                            "sub": analysis_device_data["sampleDataWsPayload"]["subDevChData"]}

            for device_type, device_data in device_datas.items():
                if device_type == "main":
                    self.add_sensor(device_data, "ecoMain")
                else:
                    for ind, sub_data in enumerate(device_data):
                        for ch_ind, ch_data in enumerate(sub_data["chDatas"]):
                            sub_ch_name = "ecoSub_" + str(ind) + "-channel_" + str(ch_ind + 1)
                            self.add_sensor(ch_data, sub_ch_name)

    def add_sensor(self, data, device_type):
        """Create sensors"""
        for key, value in data.items():
            sensor_name = f"{device_type}-{key}"
            if sensor_name not in self.sensors:
                new_sensor = EconestSensor(self.econest_energy, sensor_name)
                self.sensors[sensor_name] = new_sensor
                self.async_add_entities([new_sensor])
            self.sensors[sensor_name].update_state(value)

    def analysis_data(self, data):
        """Analyze complete data"""
        offset = 0
        econest_ws_pkg_head_format = "<IIII"  # version, crc, type, length
        econest_ws_pkg_head_size = struct.calcsize(econest_ws_pkg_head_format)
        version, crc, type_, length = struct.unpack_from(econest_ws_pkg_head_format, data, offset)
        offset += econest_ws_pkg_head_size
        if type_ != 2:
            return None
        econestWsPkgHead = {
            "version": version,
            "crc": crc,
            "type": type_,
            "length": length,
        }

        # sampleDataWsPayload
        sample_data_ws_payload_format = "<IB"  # timeStamp, subDevNum
        sample_data_ws_payload_size = struct.calcsize(sample_data_ws_payload_format)
        timeStamp, subDevNum = struct.unpack_from(sample_data_ws_payload_format, data, offset)
        # subDevNum = 2
        offset += sample_data_ws_payload_size

        # mainChData
        main_ch_data_format = "<iI"  # Power, Energy
        main_ch_data_size = struct.calcsize(main_ch_data_format)
        main_power, main_energy = struct.unpack_from(main_ch_data_format, data, offset)
        offset += main_ch_data_size

        mainChData = {
            "Power": main_power,
            "Energy": main_energy,
        }

        # subDevChData
        subDevChData = []
        for _ in range(1, subDevNum + 1):
            sub_dev_number_format = "<B"  # number
            sub_dev_number_size = struct.calcsize(sub_dev_number_format)
            number = struct.unpack_from(sub_dev_number_format, data, offset)[0]
            offset += sub_dev_number_size
            ch_data_format = "<iI"  # Power, Energy
            ch_data_size = struct.calcsize(ch_data_format)
            chDatas = []
            for _ in range(10):
                power, energy = struct.unpack_from(ch_data_format, data, offset)
                offset += ch_data_size
                chDatas.append({
                    "Power": power,
                    "Energy": energy,
                })

            subDevChData.append({
                "number": number,
                "chDatas": chDatas,
            })

        sampleDataWsPayload = {
            "timeStamp": timeStamp,
            "subDevNum": subDevNum,
            "mainChData": mainChData,
            "subDevChData": subDevChData,
        }

        res = {
            "econestWsPkgHead": econestWsPkgHead,
            "sampleDataWsPayload": sampleDataWsPayload,
        }
        return res


class EconestSensor(Entity):
    """Representation of a Sensor."""

    device_class = SensorDeviceClass.POWER

    _attr_unit_of_measurement = UnitOfPower.WATT

    def __init__(self, econest_energy, sensor_name):
        """Initialize the sensor."""
        self._sensor_name = sensor_name
        self._state = None
        self._econest_energy = econest_energy

    @property
    def device_info(self):
        return {"identifiers": {(DOMAIN, self._econest_energy.serial_number_name)},
                "name": self._econest_energy.serial_number_name,
                "manufacturer": "Econest",
                "model": "Econest"}

    @property
    def unique_id(self):
        """Return unique identifier"""
        return f"{self._econest_energy.serial_number_name}_{self._sensor_name}"

    @property
    def name(self):
        """Return the name of the sensor"""
        return self._sensor_name

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    def update_state(self, value):
        """Update sensor status"""
        self._state = value
        self.async_write_ha_state()

