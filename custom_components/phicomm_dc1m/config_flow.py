"""Config flow for AirCat integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    BooleanSelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_BFU,
    CONF_MACS,
    CONF_NAME,
    CONF_SENSOR_TYPES,
    DEFAULT_NAME,
    DOMAIN,
    SENSOR_TYPES,
)

_LOGGER = logging.getLogger(__name__)

SENSOR_OPTIONS = [
    {"value": key, "label": info["name"]}
    for key, info in SENSOR_TYPES.items()
]


class AirCatConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for AirCat."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            macs = self._parse_macs(user_input.get(CONF_MACS, ""))
            if not macs:
                errors["base"] = "no_macs"
            else:
                await self.async_set_unique_id(
                    "_".join(sorted(macs.keys()))
                )
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=user_input.get(CONF_NAME, DEFAULT_NAME),
                    data={
                        CONF_NAME: user_input.get(CONF_NAME, DEFAULT_NAME),
                        CONF_MACS: macs,
                        CONF_BFU: user_input.get(CONF_BFU, False),
                        CONF_SENSOR_TYPES: user_input.get(
                            CONF_SENSOR_TYPES, list(SENSOR_TYPES.keys())
                        ),
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_NAME, default=DEFAULT_NAME): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.TEXT)
                    ),
                    vol.Required(CONF_MACS): TextSelector(
                        TextSelectorConfig(
                            type=TextSelectorType.TEXT,
                            multiline=True,
                        )
                    ),
                    vol.Optional(CONF_BFU, default=False): BooleanSelector(
                        BooleanSelectorConfig()
                    ),
                    vol.Optional(
                        CONF_SENSOR_TYPES, default=list(SENSOR_TYPES.keys())
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=SENSOR_OPTIONS,
                            multiple=True,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
            errors=errors,
            description_placeholders={
                "macs_help": "Format: MAC=Name per line, e.g.\\nAABBCCDDEEFF=Living Room",
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        """Get the options flow for this handler."""
        return AirCatOptionsFlow()

    @staticmethod
    def _parse_macs(text: str) -> dict[str, str]:
        """Parse MAC addresses from multiline text."""
        result: dict[str, str] = {}
        for line in text.strip().splitlines():
            line = line.strip()
            if "=" in line:
                mac, name = line.split("=", 1)
                mac = mac.strip().upper().replace(":", "").replace("-", "")
                if len(mac) == 12:
                    result[mac] = name.strip()
        return result


class AirCatOptionsFlow(OptionsFlow):
    """Handle options flow for AirCat."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            macs = AirCatConfigFlow._parse_macs(user_input.get(CONF_MACS, ""))
            if not macs:
                errors["base"] = "no_macs"
            else:
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_NAME: user_input.get(CONF_NAME, DEFAULT_NAME),
                        CONF_MACS: macs,
                        CONF_BFU: user_input.get(CONF_BFU, False),
                        CONF_SENSOR_TYPES: user_input.get(
                            CONF_SENSOR_TYPES, list(SENSOR_TYPES.keys())
                        ),
                    },
                )

        macs = self.config_entry.options.get(CONF_MACS, self.config_entry.data.get(CONF_MACS, {}))
        macs_text = "\n".join(f"{k}={v}" for k, v in macs.items())

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_NAME,
                        default=self.config_entry.options.get(CONF_NAME, self.config_entry.data.get(CONF_NAME, DEFAULT_NAME)),
                    ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
                    vol.Required(CONF_MACS, default=macs_text): TextSelector(
                        TextSelectorConfig(
                            type=TextSelectorType.TEXT,
                            multiline=True,
                        )
                    ),
                    vol.Optional(
                        CONF_BFU,
                        default=self.config_entry.options.get(CONF_BFU, self.config_entry.data.get(CONF_BFU, False)),
                    ): BooleanSelector(BooleanSelectorConfig()),
                    vol.Optional(
                        CONF_SENSOR_TYPES,
                        default=self.config_entry.options.get(
                            CONF_SENSOR_TYPES, self.config_entry.data.get(CONF_SENSOR_TYPES, list(SENSOR_TYPES.keys()))
                        ),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=SENSOR_OPTIONS,
                            multiple=True,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
            errors=errors,
        )
