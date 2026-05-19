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

_READ_TIMEOUT = 30.0          # 空闲超时，30秒无数据才断开
_MAX_BUFFER_SIZE = 65536      # 单连接最大缓冲，防内存泄漏
_FRAME_END = b"\xff#END#"     # 帧结束标记


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
        self._shutdown_event = asyncio.Event()
        self.devs: dict[str, dict[str, Any]] = {}

        for mac in self._macs:
            self._last_brightness[mac] = ""
            self._last_brightness_time[mac] = 0.0

    async def async_setup(self) -> None:
        """Set up the TCP server."""
        self._shutdown_event.clear()
        self._server = await asyncio.start_server(
            self._handle_client, host="", port=DEFAULT_PORT
        )
        _LOGGER.info("AirCat server started on port %s", DEFAULT_PORT)

    async def async_shutdown(self) -> None:
        """Shut down the TCP server."""
        self._shutdown_event.set()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            _LOGGER.info("AirCat server stopped")

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        """Return current device data."""
        return self.devs

    # --------------------------------------------------------------------- #
    #  Client handler with frame buffering
    # --------------------------------------------------------------------- #
    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle incoming client connection with TCP stream reassembly."""
        addr = writer.get_extra_info("peername")
        _LOGGER.debug("Connected %s", addr)
        buffer = bytearray()

        try:
            while not self._shutdown_event.is_set():
                try:
                    data = await asyncio.wait_for(
                        reader.read(4096), timeout=_READ_TIMEOUT
                    )
                except asyncio.TimeoutError:
                    # 30秒没收到数据，认为连接空闲，正常断开
                    _LOGGER.debug("Idle timeout from %s", addr)
                    break

                if not data:
                    # 对端优雅关闭
                    _LOGGER.debug("Peer closed %s", addr)
                    break

                buffer.extend(data)

                # 防内存泄漏：缓冲区超限则丢弃
                if len(buffer) > _MAX_BUFFER_SIZE:
                    _LOGGER.warning(
                        "Buffer overflow (%d bytes) from %s, dropping",
                        len(buffer),
                        addr,
                    )
                    buffer.clear()
                    continue

                # 如果缓冲区看起来像HTTP请求，处理完断开
                if buffer.lstrip().startswith(b"GET") and b"\r\n\r\n" in buffer:
                    await self._handle_http(writer, buffer)
                    break

                # 提取并处理所有完整帧
                while True:
                    frame, buffer = self._pop_frame(buffer)
                    if frame is None:
                        break
                    await self._handle_aircat_frame(writer, frame)

        except asyncio.CancelledError:
            _LOGGER.debug("Handler cancelled for %s", addr)
            raise
        except Exception:
            _LOGGER.exception("Error handling client %s", addr)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            _LOGGER.debug("Closed %s", addr)

    @staticmethod
    def _pop_frame(buffer: bytearray) -> tuple[bytes | None, bytearray]:
        """Extract one complete AirCat frame from buffer.

        Returns (frame_bytes, remaining_buffer).  If no complete frame,
        returns (None, original_buffer).
        """
        end_pos = buffer.find(_FRAME_END)
        if end_pos == -1:
            return None, buffer

        frame_end = end_pos + len(_FRAME_END)
        frame = bytes(buffer[:frame_end])
        remaining = buffer[frame_end:]
        return frame, remaining

    # --------------------------------------------------------------------- #
    #  Protocol handlers
    # --------------------------------------------------------------------- #
    async def _handle_http(self, writer: asyncio.StreamWriter, data: bytes) -> None:
        """Handle HTTP request."""
        _LOGGER.debug("HTTP request from %s", writer.get_extra_info("peername"))
        response_body = json.dumps(self.devs, indent=2).encode("utf-8")
        response = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: " + str(len(response_body)).encode() + b"\r\n"
            b"Connection: close\r\n"
            b"\r\n" + response_body
        )
        writer.write(response)
        await writer.drain()

    async def _handle_aircat_frame(
        self, writer: asyncio.StreamWriter, data: bytes
    ) -> None:
        """Handle a single complete AirCat protocol frame."""
        end = data.rfind(_FRAME_END)
        payload = data.rfind(b"{", 0, end)

        if payload == -1:
            payload = end

        if payload < 28:
            _LOGGER.error("Received invalid frame (len=%d): %s", len(data), data[:64])
            return

        mac = ""
        attributes: dict[str, Any] | None = None

        # 安全提取MAC
        mac_start = payload - 11
        mac_end = payload - 5
        if mac_start >= 0 and mac_end <= len(data):
            mac = "".join(f"{x:02X}" for x in data[mac_start:mac_end])
        else:
            _LOGGER.warning("MAC slice out of bounds in frame")

        if payload != end:
            try:
                json_str = data[payload:end].decode("utf-8")
                attributes = json.loads(json_str)
                self.devs[mac] = attributes
                _LOGGER.debug("Received %s: %s", mac, attributes)
                self.async_set_updated_data(self.devs.copy())
            except UnicodeDecodeError as err:
                _LOGGER.error("UTF-8 decode error: %s", err)
            except json.JSONDecodeError as err:
                _LOGGER.error("JSON decode error: %s", err)

        response = self._build_response(mac, data, payload, end)
        try:
            writer.write(response)
            await writer.drain()
        except (ConnectionResetError, BrokenPipeError, OSError) as err:
            _LOGGER.warning("Write failed to %s: %s", mac or "unknown", err)
            return

        _LOGGER.debug("mac:%s, Response %s", mac, response)

    def _build_response(
        self, mac: str, data: bytes, payload: int, end: int
    ) -> bytes:
        """Build response payload for device."""
        header = data[payload - 28 : payload - 5]

        if mac and self._macs.get(mac):
            entity_id = f"input_select.{self._macs[mac]}"
            brightness_state = self.hass.states.get(entity_id)
            brightness = brightness_state.state if brightness_state else ""

            _LOGGER.debug(
                "mac:%s, name:%s, brightness:%s, last:%s, last_time:%.0f",
                mac,
                self._macs[mac],
                brightness,
                self._last_brightness.get(mac),
                self._last_brightness_time.get(mac, 0),
            )

            should_update = True
            last_b = self._last_brightness.get(mac)
            last_t = self._last_brightness_time.get(mac, 0)
            if last_b and brightness in last_b:
                if not self._brightness_force_update:
                    should_update = False
                elif time.time() - last_t < 300:
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
                    {"brightness": str(round(float(level))), "type": 2},
                    separators=(",", ":"),
                ).encode("utf-8")
                return (
                    header
                    + b"\x00\x18\x00\x00\x02"
                    + json_payload
                    + _FRAME_END
                )

        # Status acknowledgment
        json_payload = b'{"type":5,"status":1}'
        return header + b"\x00\x18\x00\x00\x02" + json_payload + _FRAME_END

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
