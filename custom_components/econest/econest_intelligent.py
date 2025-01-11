from __future__ import annotations
import json
import aiohttp

from homeassistant.core import HomeAssistant


class EconestEnergy:

    def __init__(self, hass: HomeAssistant, serial_number_name: str, host: str) -> None:
        self.serial_number_name = serial_number_name
        self.serial_number = serial_number_name.split("-")[-1]
        self._hass = hass
        self._host = host
        self.econest_type = 2
        self.uuid_url = "http://{}/register"
        self.sync_url = "http://{}/sync"
        self.data_url = "http://{}/data-ctrl"
        self.main_info_url = "http://{}/system-info"

    async def register_uuid(self, host):
        """Register a UUID."""
        data = {"user": self.serial_number,
                "password": "cyber2019"}
        json_data = json.dumps(data)
        for ind in range(3):
            if ind == 0:
                url = self.uuid_url.format(self.serial_number_name)
                self.econest_type = "serial_number"
            elif ind == 1:
                url = self.uuid_url.format(self.serial_number_name + ".local")
                self.econest_type = "serial_number_local"
            else:
                url = self.uuid_url.format(host)
                self.econest_type = "host"
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, data=json_data) as response:
                        if response.status == 200:
                            data = await response.json()
                            res = data.get("uuid", None)
                            break
                        else:
                            res = None
                            continue
            except aiohttp.ClientError as e:
                # raise Exception(self.uuid_url2, e)
                # 处理网络错误
                res = None
                continue
        return res

    async def sync_data(self, device_uuid, host):
        """Sampling data synchronization settings"""
        data = {"uuid": device_uuid,
                "timestampFrom": 0,
                "timestampTo": 0}
        json_data = json.dumps(data)
        for ind in range(3):
            if ind == 0:
                url = self.sync_url.format(self.serial_number_name)
            elif ind == 1:
                url = self.sync_url.format(self.serial_number_name + ".local")
            else:
                url = self.sync_url.format(host)
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, data=json_data) as response:
                        if response.status == 200:
                            res = True
                            break
                        else:
                            res = False
                            continue
            except aiohttp.ClientError as e:
                # 处理网络错误
                res = False
                continue
        return res

    async def data_ctrl(self, device_uuid, host):
        """Data transmission control"""
        data = {"uuid": device_uuid,
                "rtdataEnable": 1,
                "syncEnable": 0,
                "logdataEnable": 0}
        json_data = json.dumps(data)
        for ind in range(3):
            if ind == 0:
                url = self.data_url.format(self.serial_number_name)
            elif ind == 1:
                url = self.data_url.format(self.serial_number_name + ".local")
            else:
                url = self.data_url.format(host)
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, data=json_data) as response:
                        if response.status == 200:
                            res = True
                            break
                        else:
                            res = False
                            continue
            except aiohttp.ClientError as e:
                # 处理网络错误
                res = False
                continue
        return res

    async def check_connection(self) -> bool:
        """Test connection."""
        for ind in range(3):
            if ind == 0:
                url = self.main_info_url.format(self.serial_number_name)
            elif ind == 1:
                url = self.main_info_url.format(self.serial_number_name + ".local")
            else:
                url = self.main_info_url.format(self._host)
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as response:
                        if response.status == 200:
                            res = True
                            break
                        else:
                            res = False
                            continue
            except aiohttp.ClientError as e:
                # 处理网络错误
                res = False
                continue
        return res



