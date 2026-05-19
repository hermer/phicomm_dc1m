"""DataUpdateCoordinator for AirCat."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    BRIGHTNESS_NIGHT,
    BRIGHTNESS_OFF,
    CONF_BFU,
    CONF_MACS,
    DEFAULT_PORT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class AirCatCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """AirCat data coordinator."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=None,  # local push, no polling
            always_update=False,
        )
        self.entry = entry
        # Merge data + options so options updates take effect after reload
        config = {**entry.data, **entry.options}
        self._macs: dict[str, str] = config.get(CONF_MACS, {})
        self._brightness_force_update: bool = config.get(CONF_BFU, False)
        self._last_brightness: dict[str, str] = {}
        self._last_brightness_time: dict[str, float] = {}
        self._server: asyncio.Server | None = None
        self._shutdown = False
        self.devs: dict[str, dict[str, Any]] = {}

        for mac in self._macs:
            self._last_brightness[mac] = ""
            self._last_brightness_time[mac] = 0.0

    async def async_setup(self) -> None:
        """Set up the TCP server."""
        self._server = await asyncio.start_server(
            self._handle_client, host="", port=DEFAULT_PORT
        )
        _LOGGER.info("AirCat server started on port %s", DEFAULT_PORT)

    async def async_shutdown(self) -> None:
        """Shut down the TCP server."""
        self._shutdown = True
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            _LOGGER.info("AirCat server stopped")

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        """Return current device data."""
        return self.devs

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle incoming client connection."""
        addr = writer.get_extra_info("peername")
        _LOGGER.debug("Connected %s", addr)

        try:
            while not self._shutdown:
                data = await reader.read(4096)
                if not data:
                    break

                if data.startswith(b"GET"):
                    await self._handle_http(writer, data)
                    break

                await self._handle_aircat_data(writer, data)

        except asyncio.TimeoutError:
            _LOGGER.debug("Timeout from %s", addr)
        except Exception:
            _LOGGER.exception("Error handling client %s", addr)
        finally:
            writer.close()
            await writer.wait_closed()
            _LOGGER.debug("Closed %s", addr)

    async def _handle_http(self, writer: asyncio.StreamWriter, data: bytes) -> None:
        """Handle HTTP request."""
        _LOGGER.debug("Request from HTTP -->\n%s", data)
        response_body = json.dumps(self.devs, indent=2).encode("utf-8")
        response = (
            b"HTTP/1.0 200 OK\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: " + str(len(response_body)).encode() + b"\r\n"
            b"\r\n" + response_body
        )
        writer.write(response)
        await writer.drain()

    async def _handle_aircat_data(
        self, writer: asyncio.StreamWriter, data: bytes
    ) -> None:
        """Handle AirCat protocol data."""
        end = data.rfind(b"\xff#END#")
        payload = data.rfind(b"{", 0, end)
        if payload == -1:
            payload = end
        if payload < 28:
            _LOGGER.error("Received invalid %s", data)
            return

        mac = ""
        attributes: dict[str, Any] | None = None

        if payload != end:
            try:
                mac = "".join(
                    f"{x:02X}"
                    for x in data[payload - 11 : payload - 5]
                )
                json_str = data[payload:end].decode("utf-8")
                attributes = json.loads(json_str)
                self.devs[mac] = attributes
                _LOGGER.debug("Received %s: %s", mac, attributes)
                self.async_set_updated_data(self.devs.copy())
            except (UnicodeDecodeError, json.JSONDecodeError):
                _LOGGER.error("Received invalid JSON: %s", data)
                return

        response = self._build_response(mac, data, payload, end)
        writer.write(response)
        await writer.drain()
        _LOGGER.debug("mac:%s, Response %s", mac, response)

    def _build_response(
        self, mac: str, data: bytes, payload: int, end: int
    ) -> bytes:
        """Build response payload for device."""
        header = data[payload - 28 : payload - 5]

        if mac and mac in self._macs:
            entity_id = f"input_select.{self._macs[mac]}"
            brightness_state = self.hass.states.get(entity_id)
            brightness = brightness_state.state if brightness_state else ""

            _LOGGER.debug(
                "mac:%s, name:%s, brightness:%s, last:%s, last_time:%.0f",
                mac,
                self._macs[mac],
                brightness,
                self._last_brightness.get(mac),
                self._last_brightness_time.get(mac),
            )

            should_update = True
            if (
                self._last_brightness.get(mac)
                and brightness in self._last_brightness[mac]
            ):
                if not self._brightness_force_update:
                    should_update = False
                elif time.time() - self._last_brightness_time.get(mac, 0) < 300:
                    should_update = False

            if should_update:
                _LOGGER.info(
                    "update brightness mac:%s, name:%s, brightness:%s",
                    mac,
                    self._macs[mac],
                    brightness,
                )
                self._last_brightness[mac] = brightness
                self._last_brightness_time[mac] = time.time()

                if BRIGHTNESS_OFF in brightness:
                    level = 0
                elif BRIGHTNESS_NIGHT in brightness:
                    level = 50
                else:
                    level = 80

                json_payload = json.dumps(
                    {"brightness": str(round(float(level))), "type": 2}
                ).encode("utf-8")
                return (
                    header
                    + b"\x00\x18\x00\x00\x02"
                    + json_payload
                    + b"\xff#END#"
                )

        # Status acknowledgment
        json_payload = b'{"type":5,"status":1}'
        return (
            header
            + b"\x00\x18\x00\x00\x02"
            + json_payload
            + b"\xff#END#"
        )

    @callback
    def async_update_macs(self, macs: dict[str, str]) -> None:
        """Update MAC addresses from options."""
        self._macs = macs
        for mac in self._macs:
            if mac not in self._last_brightness:
                self._last_brightness[mac] = ""
                self._last_brightness_time[mac] = 0.0

    @callback
    def async_update_bfu(self, bfu: bool) -> None:
        """Update brightness force update setting."""
        self._brightness_force_update = bfu
