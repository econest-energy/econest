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
    """设置传感器平台"""
    econest_energy = config_entry.runtime_data
    host = config_entry.data["host"]
    uuid = await econest_energy.register_uuid(host)
    if uuid:
        data_ctrl_res = await econest_energy.data_ctrl(uuid, host)
        if data_ctrl_res:
            sensor_manager = WebSocketSensorManager(hass, async_add_entities, econest_energy, uuid, host)
            hass.loop.create_task(sensor_manager.start())


class WebSocketSensorManager:
    """管理 WebSocket 连接和传感器的类"""

    def __init__(self, hass, async_add_entities, econest_energy, uuid, host):
        self.hass = hass
        self.async_add_entities = async_add_entities
        self.sensors = {}  # 保存已经创建的传感器
        self.econest_energy = econest_energy
        self.websocket_url = "ws://{}/ws/interface?uuid={}"
        # self.max_subdev_num = 3
        self.uuid = uuid
        self.host = host

    async def start(self):
        """启动 WebSocket 客户端"""
        if self.econest_energy.econest_type == "serial_number":
            url = self.websocket_url.format(self.econest_energy.serial_number_name, self.uuid)
        elif self.econest_energy.econest_type == "serial_number_local":
            url = self.websocket_url.format(self.econest_energy.serial_number_name + ".local", self.uuid)
        else:
            url = self.websocket_url.format(self.host, self.uuid)
        while True:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(url) as ws:
                        _LOGGER.info("WebSocket connection established")

                        # 启动心跳任务
                        async def send_heartbeat():
                            while True:
                                try:
                                    await ws.ping()
                                    _LOGGER.debug("Heartbeat sent")
                                except Exception as e:
                                    _LOGGER.error("Failed to send heartbeat: %s", e)
                                    break
                                await asyncio.sleep(10)  # 心跳间隔时间

                        # 启动处理消息和心跳的并行任务
                        heartbeat_task = asyncio.create_task(send_heartbeat())
                        try:
                            async for msg in ws:
                                if msg.type == aiohttp.WSMsgType.BINARY:
                                    await self.handle_message(msg.data)
                                elif msg.type == aiohttp.WSMsgType.ERROR:
                                    _LOGGER.error("WebSocket error: %s", msg.data)
                        finally:
                            heartbeat_task.cancel()
            except aiohttp.ClientError as e:
                _LOGGER.error("WebSocket connection failed: %s", e)
            except asyncio.CancelledError:
                _LOGGER.info("WebSocket connection canceled")
                break
            except Exception as e:
                _LOGGER.error("Unexpected error: %s", e)

            _LOGGER.info("Attempting to reconnect in 10 seconds...")
            # 等待一段时间后重试连接
            await asyncio.sleep(10)

    async def handle_message(self, data):
        """处理 WebSocket 消息"""
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
        """创建传感器"""
        for key, value in data.items():
            sensor_name = f"{device_type}-{key}"
            if sensor_name not in self.sensors:
                # 如果尚未创建对应的传感器，则创建
                new_sensor = EconestSensor(self.econest_energy, sensor_name)
                self.sensors[sensor_name] = new_sensor
                self.async_add_entities([new_sensor])
            # 更新传感器状态
            self.sensors[sensor_name].update_state(value)

    def analysis_data(self, data):
        """解析完整数据"""
        offset = 0  # 偏移量
        # 解析 econestWsPkgHead
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

        # 解析 sampleDataWsPayload
        sample_data_ws_payload_format = "<IB"  # timeStamp, subDevNum
        sample_data_ws_payload_size = struct.calcsize(sample_data_ws_payload_format)
        timeStamp, subDevNum = struct.unpack_from(sample_data_ws_payload_format, data, offset)
        # subDevNum = 2
        offset += sample_data_ws_payload_size

        # 解析 mainChData
        main_ch_data_format = "<iI"  # Power, Energy
        main_ch_data_size = struct.calcsize(main_ch_data_format)
        main_power, main_energy = struct.unpack_from(main_ch_data_format, data, offset)
        offset += main_ch_data_size

        mainChData = {
            "Power": main_power,
            "Energy": main_energy,
        }

        # 解析 subDevChData
        subDevChData = []
        for _ in range(1, subDevNum + 1):
            # 解析子设备编号
            sub_dev_number_format = "<B"  # number
            sub_dev_number_size = struct.calcsize(sub_dev_number_format)
            number = struct.unpack_from(sub_dev_number_format, data, offset)[0]
            offset += sub_dev_number_size

            # 解析 10 个 chDatas
            ch_data_format = "<iI"  # Power, Energy
            ch_data_size = struct.calcsize(ch_data_format)
            chDatas = []
            for _ in range(10):  # 每个子设备有 10 个数据对
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

        # 返回解析结果
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
        """返回唯一标识符"""
        return f"{self._econest_energy.serial_number_name}_{self._sensor_name}"

    @property
    def name(self):
        """返回传感器的名称"""
        return self._sensor_name

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    def update_state(self, value):
        """更新传感器状态"""
        self._state = value
        self.async_write_ha_state()

