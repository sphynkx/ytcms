import time
import uuid
import socket

from proto.captions_pb2 import (
    InfoRequest,
    InfoResponse,
    HealthCheckRequest,
    HealthCheckResponse,
)
from proto.captions_pb2_grpc import (
    add_InfoServicer_to_server,
    add_HealthServicer_to_server,
    InfoServicer,
    HealthServicer,
)
from config import get_settings


class HealthService(HealthServicer):
    def __init__(self):
        pass

    async def Check(self, request: HealthCheckRequest, context):
        # Always SERVING
        return HealthCheckResponse(status=HealthCheckResponse.SERVING)

    # Health/Watch cannot implement - will be UNIMPLEMENTED


class InfoService(InfoServicer):
    # To compute uptime
    def __init__(self):
        self.start_time = int(time.time())
        self.settings = get_settings()
        try:
            self.host = socket.gethostname()
        except Exception:
            self.host = "unknown"

    async def All(self, request: InfoRequest, context):
        uptime = int(time.time() - self.start_time)
        # Some minimal fields
        return InfoResponse(
            app_name="ytcms",
            instance_id=self.host,
            host=self.host,
            version="1.0.0",
            uptime=uptime,
            labels={"env": "prod"},
            metrics={},
            build_hash="",
            build_time=""
        )

    def add_to_server(self, server):
        add_InfoServicer_to_server(self, server)
        add_HealthServicer_to_server(HealthService(), server)