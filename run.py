import argparse
import asyncio
import signal
import threading
import grpc
from concurrent import futures
from grpc_reflection.v1alpha import reflection

from proto import ytcms_pb2
from proto import ytcms_pb2_grpc

from grpc_health.v1 import health as health_mod
from grpc_health.v1 import health_pb2, health_pb2_grpc

from proto import info_pb2, info_pb2_grpc

from server.interceptors_srvr import AuthInterceptor
from server.service_impl_srvr import CaptionsServiceImpl
from server.health_info_srvr import InfoService
from jobs.queue_job import JobQueue
from config import get_settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9099)
    args = parser.parse_args()

    settings = get_settings()

    queue = JobQueue()
    asyncio.run(queue.start_workers())

    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=32),
        interceptors=[AuthInterceptor()],
    )

    ytcms_pb2_grpc.add_CaptionsServiceServicer_to_server(CaptionsServiceImpl(queue), server)

    health_servicer = health_mod.HealthServicer()
    health_pb2_grpc.add_HealthServicer_to_server(health_servicer, server)
    health_servicer.set("", health_pb2.HealthCheckResponse.SERVING)

    info_service = InfoService()
    info_pb2_grpc.add_InfoServicer_to_server(info_service, server)

    service_names = (
        health_pb2.DESCRIPTOR.services_by_name["Health"].full_name,
        info_pb2.DESCRIPTOR.services_by_name["Info"].full_name,
        ytcms_pb2.DESCRIPTOR.services_by_name["CaptionsService"].full_name,
        reflection.SERVICE_NAME,
    )
    reflection.enable_server_reflection(service_names, server)

    server.add_insecure_port(f"{args.host}:{args.port}")
    server.start()

    print(f"[ytcms] gRPC (sync) started on {args.host}:{args.port} (model={settings.model}, device={settings.device}, compute_type={settings.compute_type})")
    print(f"[ytcms] Reflection enabled. Try: grpcurl -plaintext {args.host}:{args.port} list")

    stop_evt = threading.Event()

    def _sig(signum, _frame):
        try:
            signame = signal.Signals(signum).name
        except Exception:
            signame = str(signum)
        print(f"[ytcms] Received {signame}, shutting down...")
        stop_evt.set()

    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    stop_evt.wait()

    # Stop gRPC first (no new requests)
    server.stop(grace=5).wait(timeout=10)

    # Stop workers
    asyncio.run(queue.stop())
    asyncio.run(queue.close())

    print("[ytcms] Shutdown complete.")


if __name__ == "__main__":
    main()