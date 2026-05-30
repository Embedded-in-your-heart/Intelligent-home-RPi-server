from flask import Flask

from home_server.services.channel_service import ChannelService
from home_server.services.device_service import DeviceService
from home_server.web.services import get_channel_service, get_device_service


def test_services_registered_in_app(app: Flask) -> None:
    with app.app_context():
        assert isinstance(get_device_service(), DeviceService)
        assert isinstance(get_channel_service(), ChannelService)
