"""Config flow for econest integration."""
from __future__ import annotations

import logging
from typing import Any
from collections.abc import Mapping
from ipaddress import ip_address as ip

import voluptuous as vol

from homeassistant import config_entries, exceptions
from homeassistant.core import HomeAssistant

from .econest_intelligent import EconestEnergy

from homeassistant.core import callback
from homeassistant.components import zeroconf
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.util.network import is_ip_address as is_ip

from .const import DOMAIN, SERIAL_NUMBER

_LOGGER = logging.getLogger(__name__)

HTTP_SUFFIX = "._http._tcp.local."
DEFAULT_PORT = 80

DATA_SCHEMA = vol.Schema({("serial_number"): str, ("host"): str})


async def validate_input(hass: HomeAssistant, data: dict) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    serial_number = data["serial_number"]
    if "econest-hems-" in serial_number:
        serial_number_name = serial_number
    else:
        serial_number_name = "econest-hems-" + serial_number
    econest_energy = EconestEnergy(hass, serial_number_name,  data["host"])
    result = await econest_energy.check_connection()
    if not result:
        raise CannotConnect

    return {"title": serial_number_name}


class EconestFlowHandler(ConfigFlow, domain=DOMAIN):
    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    def __init__(self) -> None:
        """Initialize the econest config flow."""
        self.discovered_conf: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
                return self.async_create_entry(title=info["title"], data=user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )

    async def async_step_zeroconf(
        self, discovery_info: zeroconf.ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Handle zeroconf discovery."""
        if not discovery_info or not discovery_info.host or not discovery_info.name:
            _LOGGER.error("Invalid Zeroconf discovery info: %s", discovery_info)
            return self.async_abort(reason="invalid_discovery_info")
        host = discovery_info.host
        serial_number = discovery_info.name.removesuffix(HTTP_SUFFIX)
        return await self.async_step_confirm_discovery(host, serial_number)

    def _async_get_existing_entry(self, serial_number: str):
        for entry in self._async_current_entries():
            if serial_number in [
                name.removesuffix(HTTP_SUFFIX) for name in entry.data.get(SERIAL_NUMBER, [])
            ]:
                return entry
        return None

    async def async_step_confirm_discovery(
        self, host: str, serial_number: str
    ) -> ConfigFlowResult:
        """Handle discovery confirm."""
        await self.async_set_unique_id(serial_number)
        existing_entry = self._async_get_existing_entry(serial_number)
        self._abort_if_unique_id_configured()

        if (
            existing_entry
            and is_ip(existing_entry.data[CONF_HOST])
            and is_ip(host)
            and existing_entry.data[CONF_HOST] != host
            and ip(existing_entry.data[CONF_HOST]).version == ip(host).version
        ):
            _LOGGER.debug(
                "Update host from '%s' to '%s' for NAS '%s' via discovery",
                existing_entry.data[CONF_HOST],
                host,
                existing_entry.unique_id,
            )
            self.hass.config_entries.async_update_entry(
                existing_entry,
                data={**existing_entry.data, CONF_HOST: host},
            )
            return self.async_abort(reason="reconfigure_successful")

        if existing_entry:
            return self.async_abort(reason="already_configured")

        self.discovered_conf = {
            CONF_NAME: serial_number,
            CONF_HOST: host,
            SERIAL_NUMBER: serial_number
        }
        self.context["title_placeholders"] = self.discovered_conf
        return await self.async_step_link()

    async def async_step_link(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Link a config entry from discovery."""
        if not user_input:
            return self.async_show_form(
                step_id="link",
                # description_placeholders=self.discovered_conf,
                data_schema=vol.Schema({
                    vol.Required("confirm", default=True): bool,
                })
            )
        if not user_input.get("confirm"):
            return self.async_abort(reason="user declined")
        try:
            user_input = self.discovered_conf
            return await self.async_validate_input_create_entry(user_input)
        except Exception as e:
            _LOGGER.error("Failed to create entry: %s", e)
            return self.async_abort(reason="unknown error")

    async def async_validate_input_create_entry(
        self, user_input: dict[str, Any]
    ) -> ConfigFlowResult:
        """Process user input and create new or update existing config entry."""
        host = user_input[CONF_HOST]
        port = user_input.get(CONF_PORT)
        serial_number = user_input.get(SERIAL_NUMBER)

        if not port:
            port = DEFAULT_PORT

        config_data = {
            CONF_HOST: host,
            CONF_PORT: port,
            CONF_NAME: serial_number,
            SERIAL_NUMBER: serial_number
        }

        return self.async_create_entry(title=serial_number or host, data=config_data)

    @callback
    def async_create_entry(
        self,
        *,
        title: str,
        data: Mapping[str, Any],
        description: str | None = None,
        description_placeholders: Mapping[str, str] | None = None,
        options: Mapping[str, Any] | None = None,
    ):
        """Finish config flow and create a config entry."""
        result = super().async_create_entry(
            title=title,
            data=data,
            description=description,
            description_placeholders=description_placeholders,
        )

        result["options"] = options or {}

        return result


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""

