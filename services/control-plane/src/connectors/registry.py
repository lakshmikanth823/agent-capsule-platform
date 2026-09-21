from typing import Dict, Optional, List
from .base import BaseConnector
from .fake_echo import FakeEchoConnector
from .slack_post import SlackPostConnector

_CONNECTORS: Dict[str, BaseConnector] = {
    FakeEchoConnector.name: FakeEchoConnector(),
    SlackPostConnector.name: SlackPostConnector(),
}


def get_connector(name: str) -> Optional[BaseConnector]:
    return _CONNECTORS.get(name)


def register_connector(connector: BaseConnector) -> None:
    _CONNECTORS[connector.name] = connector


def list_available_connectors() -> List[str]:
    return list(_CONNECTORS.keys())
