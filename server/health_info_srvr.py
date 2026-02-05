import os
import time
import socket

from proto import info_pb2, info_pb2_grpc


_START_TS = time.time()


class InfoService(info_pb2_grpc.InfoServicer):
    def All(self, request: info_pb2.InfoRequest, context) -> info_pb2.InfoResponse:
        host = socket.gethostname()
        uptime = int(time.time() - _START_TS)

        return info_pb2.InfoResponse(
            app_name="ytcms",
            instance_id=os.getenv("YTCMS_INSTANCE_ID", ""),
            host=host,
            version=os.getenv("YTCMS_VERSION", ""),
            uptime=uptime,
            labels={},
            metrics={},
            build_hash=os.getenv("YTCMS_BUILD_HASH", ""),
            build_time=os.getenv("YTCMS_BUILD_TIME", ""),
        )