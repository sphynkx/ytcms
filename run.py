import argparse
import asyncio
import signal
import grpc
from grpc_reflection.v1alpha import reflection

from proto import captions_pb2
from proto import captions_pb2_grpc

from grpc_health.v1 import health as health_mod
from grpc_health.v1 import health_pb2, health_pb2_grpc

from proto import info_pb2, info_pb2_grpc

from server.interceptors_srvr import AuthInterceptor
from server.service_impl_srvr import CaptionsServiceImpl
from server.health_info_srvr import InfoService
from jobs.queue_job import JobQueue
from config import get_settings


async def serve(host: str, port: int):
    settings = get_settings()
    queue = JobQueue()
    await queue.init()
    await queue.start_workers()

    server = grpc.aio.server(interceptors=[AuthInterceptor()])

    captions_pb2_grpc.add_CaptionsServiceServicer_to_server(
        CaptionsServiceImpl(queue),
        server
    )

    health_servicer = health_mod.HealthServicer()
    health_pb2_grpc.add_HealthServicer_to_server(health_servicer, server)
    # Global status (service=""): SERVING
    health_servicer.set("", health_pb2.HealthCheckResponse.SERVING)

    # grpc.health.v1.Info/All
    info_service = InfoService()
    info_pb2_grpc.add_InfoServicer_to_server(info_service, server)

    # Reflection
    service_names = (
        health_pb2.DESCRIPTOR.services_by_name["Health"].full_name,          # grpc.health.v1.Health
        info_pb2.DESCRIPTOR.services_by_name["Info"].full_name,              # grpc.health.v1.Info
        captions_pb2.DESCRIPTOR.services_by_name["CaptionsService"].full_name,  # ytcms.CaptionsService
        reflection.SERVICE_NAME,
    )
    reflection.enable_server_reflection(service_names, server)

    server.add_insecure_port(f"{host}:{port}")
    await server.start()
    print(f"[ytcms] gRPC server started on {host}:{port} (model={settings.model}, device={settings.device}, compute_type={settings.compute_type})")
    print(f"[ytcms] Reflection enabled. Try: grpcurl -plaintext {host}:{port} list")

    shutdown_event = asyncio.Event()

    def _signal_handler(sig):
        print(f"[ytcms] Received signal {sig.name}, shutting down...")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda s=sig: _signal_handler(s))
        except NotImplementedError:
            pass

    await shutdown_event.wait()

    await server.stop(grace=5)
    await queue.stop()
    await queue.close()
    print("[ytcms] Shutdown complete.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9099)
    args = parser.parse_args()
    asyncio.run(serve(args.host, args.port))


if __name__ == "__main__":
    main()