"""Vehicle render image for the MySkoda PublicAPI integration."""

from __future__ import annotations

from homeassistant.components.image import ImageEntity, ImageEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import MySkodaCoordinator, MySkodaPublicApiConfigEntry
from .entity import MySkodaVehicleEntity

RENDER_DESCRIPTION = ImageEntityDescription(
    key="render",
    translation_key="render",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MySkodaPublicApiConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the image platform."""
    coordinator = entry.runtime_data
    async_add_entities(
        MySkodaRenderImage(hass, coordinator, vin, RENDER_DESCRIPTION)
        for vin, state in coordinator.vehicles.items()
        if state.data is not None and state.data.raw.get("renderUrl")
    )


class MySkodaRenderImage(MySkodaVehicleEntity, ImageEntity):
    """The render of the vehicle provided by ``renderUrl``."""

    entity_description: ImageEntityDescription

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: MySkodaCoordinator,
        vin: str,
        description: ImageEntityDescription,
    ) -> None:
        """Initialise both base classes."""
        ImageEntity.__init__(self, hass)
        MySkodaVehicleEntity.__init__(self, coordinator, vin, description)
        self._attr_image_url = self.get("renderUrl")
        self._attr_image_last_updated = dt_util.utcnow()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Follow a changed render URL."""
        url = self.get("renderUrl")
        if url != self._attr_image_url:
            self._attr_image_url = url
            self._cached_image = None
            self._attr_image_last_updated = dt_util.utcnow()
        super()._handle_coordinator_update()
