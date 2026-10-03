"""Sensor entities for PACEEX BMS."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import PaceexConfigEntry
from .const import (
    DOMAIN,
    MANUFACTURER,
    MODEL,
    UNAVAILABLE_AFTER_FAILURES,
)
from .coordinator import PaceexDataUpdateCoordinator


@dataclass(frozen=True, kw_only=True)
class PaceexSensorEntityDescription(SensorEntityDescription):
    """PACEEX sensor description.

    ``index_label`` names the attribute carrying the cell/sensor number of a
    stack-wide extreme (the pack number is always exposed as ``pack``).
    """

    index_label: str | None = None


SENSORS = (
    PaceexSensorEntityDescription(
        key="state_of_charge",
        name="State of charge",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    PaceexSensorEntityDescription(
        key="state_of_health",
        name="State of health",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery-heart-variant",
    ),
    PaceexSensorEntityDescription(
        key="voltage",
        name="Battery voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    PaceexSensorEntityDescription(
        key="current",
        name="Battery current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    PaceexSensorEntityDescription(
        key="power",
        name="Battery power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    PaceexSensorEntityDescription(
        key="remaining_capacity",
        name="Remaining capacity",
        native_unit_of_measurement="Ah",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery",
    ),
    # The key stays "design_capacity" so existing entity IDs keep working, but
    # the value is the measured full-charge capacity: on the master of a stack
    # it is the pack count times the master pack's own measured capacity.
    PaceexSensorEntityDescription(
        key="design_capacity",
        name="Measured capacity",
        native_unit_of_measurement="Ah",
        icon="mdi:battery-high",
    ),
    PaceexSensorEntityDescription(
        key="rated_capacity",
        name="Rated capacity",
        native_unit_of_measurement="Ah",
        icon="mdi:battery-high",
    ),
    PaceexSensorEntityDescription(
        key="pack_count", name="Pack count", icon="mdi:counter"
    ),
    PaceexSensorEntityDescription(
        key="cycles",
        name="Battery cycles",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:counter",
    ),
    PaceexSensorEntityDescription(
        key="cell_count", name="Cell count", icon="mdi:counter"
    ),
    PaceexSensorEntityDescription(
        key="cell_delta",
        name="Cell voltage delta",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:delta",
    ),
    PaceexSensorEntityDescription(
        key="cell_min_voltage",
        name="Minimum cell voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    PaceexSensorEntityDescription(
        key="cell_max_voltage",
        name="Maximum cell voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    PaceexSensorEntityDescription(
        key="system_max_cell_voltage",
        name="Maximum cell voltage (all packs)",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        index_label="cell",
    ),
    PaceexSensorEntityDescription(
        key="system_min_cell_voltage",
        name="Minimum cell voltage (all packs)",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        index_label="cell",
    ),
    PaceexSensorEntityDescription(
        key="system_cell_delta",
        name="Cell voltage delta (all packs)",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:delta",
    ),
    PaceexSensorEntityDescription(
        key="system_max_temperature",
        name="Maximum temperature (all packs)",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        index_label="sensor",
    ),
    PaceexSensorEntityDescription(
        key="system_min_temperature",
        name="Minimum temperature (all packs)",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        index_label="sensor",
    ),
)

TEMPERATURE_NAMES = {
    "temperature_cell_1": "Cell temperature 1",
    "temperature_cell_2": "Cell temperature 2",
    "temperature_cell_3": "Cell temperature 3",
    "temperature_cell_4": "Cell temperature 4",
    "temperature_mosfet": "MOSFET temperature",
    "temperature_ambient": "Ambient temperature",
}


DIAGNOSTIC_KEYS = frozenset({"consecutive_failures", "last_success"})

DIAGNOSTICS = (
    PaceexSensorEntityDescription(
        key="consecutive_failures",
        name="Consecutive failures",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:counter",
    ),
    PaceexSensorEntityDescription(
        key="last_success",
        name="Last successful update",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass,
    entry: PaceexConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up PACEEX BMS sensors."""
    coordinator = entry.runtime_data
    serial_number = entry.unique_id
    if serial_number is None:
        raise RuntimeError("PACEEX config entry is missing its serial-number unique ID")

    # Create only the entities this module actually reports: the stack-wide and
    # capacity-rating values are absent from slave modules and older firmware.
    data = coordinator.data
    descriptions = [description for description in SENSORS if description.key in data]
    descriptions.extend(
        PaceexSensorEntityDescription(
            key=key,
            name=name,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
        )
        for key, name in TEMPERATURE_NAMES.items()
        if key in data
    )
    for index in range(1, int(data["cell_count"]) + 1):
        descriptions.append(
            PaceexSensorEntityDescription(
                key=f"cell_{index:02d}_voltage",
                name=f"Cell {index:02d} voltage",
                native_unit_of_measurement=UnitOfElectricPotential.VOLT,
                device_class=SensorDeviceClass.VOLTAGE,
                state_class=SensorStateClass.MEASUREMENT,
                icon="mdi:battery-outline",
            )
        )
    async_add_entities(
        PaceexSensor(coordinator, description, serial_number)
        for description in (*descriptions, *DIAGNOSTICS)
    )


class PaceexSensor(CoordinatorEntity[PaceexDataUpdateCoordinator], SensorEntity):
    """A sensor backed by the shared PACEEX coordinator."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, description, serial_number: str) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{serial_number}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial_number)},
            manufacturer=MANUFACTURER,
            model=MODEL,
            name="PACEEX Smart BMS",
            serial_number=serial_number,
        )

    @property
    def available(self) -> bool:
        """Keep diagnostics visible while stale telemetry is unavailable."""
        if self.entity_description.key in DIAGNOSTIC_KEYS:
            return True
        return (
            self.coordinator.last_update_success
            and self.coordinator.consecutive_failures < UNAVAILABLE_AFTER_FAILURES
        )

    @property
    def extra_state_attributes(self) -> dict[str, int | None] | None:
        """Expose which pack and cell/sensor holds a stack-wide extreme."""
        label = self.entity_description.index_label
        if label is None:
            return None
        data = self.coordinator.data or {}
        key = self.entity_description.key
        return {"pack": data.get(f"{key}_pack"), label: data.get(f"{key}_index")}

    @property
    def native_value(self):
        """Return the latest coordinated sensor value."""
        if self.entity_description.key == "consecutive_failures":
            return self.coordinator.consecutive_failures
        if self.entity_description.key == "last_success":
            return self.coordinator.last_success
        return (self.coordinator.data or {}).get(self.entity_description.key)
