import time
import socket

from proto import info_pb2, info_pb2_grpc
from config import get_settings


class InfoService(info_pb2_grpc.InfoServicer):
    """
    grpc.health.v1.Info/All — a single method for the admin panel.
    Returns key fields:
    - app_name
    - instance_id
    - host (in the format "<host>:<port>")
    - version
    - uptime (integer seconds, since your info.proto has int64 uptime)
    - labels (optional)
    - metrics (optional)
    """

    def __init__(self) -> None:
        self._started = time.time()
        self._settings = get_settings()
        try:
            self._hostname = socket.gethostname()
        except Exception:
            self._hostname = "unknown"

    async def All(self, request: info_pb2.InfoRequest, context) -> info_pb2.InfoResponse:
        up_sec_float = time.time() - self._started
        up_sec_int = int(up_sec_float)

        host_port = f"{self._settings.host}:{self._settings.port}"

        app_name = "YTCms-srv"

        version = getattr(self._settings, "version", "") or self._settings.model

        labels = {}
        metrics = {"uptime_sec": float(up_sec_float)}

        return info_pb2.InfoResponse(
            app_name=app_name,
            instance_id=self._hostname,
            host=host_port,
            version=version,
            uptime=up_sec_int,
            labels=labels,
            metrics=metrics,
        )