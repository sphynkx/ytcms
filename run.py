import argparse
import asyncio
import signal
import grpc
import captions_pb2_grpc
from server.interceptors_srvr import AuthInterceptor
from server.service_impl_srvr import CaptionsServiceImpl
from jobs.queue_job import JobQueue
from config import get_settings


async def serve(host: str, port: int):
    settings = get_settings()
    queue = JobQueue()
    await queue.init()
    await queue.start_workers()

##    server = grpc.aio.server(interceptors=[AuthInterceptor()])
## Unlimited size
    server = grpc.aio.server(
				interceptors=[AuthInterceptor()],
				options=[
					('grpc.max_send_message_length', -1),
					('grpc.max_receive_message_length', -1)

					]
			)
    captions_pb2_grpc.add_CaptionsServiceServicer_to_server(
        CaptionsServiceImpl(queue),
        server
    )
    server.add_insecure_port(f"{host}:{port}")
    await server.start()
    print(f"[ytcms] gRPC server started on {host}:{port} (model={settings.model}, device={settings.device}, compute_type={settings.compute_type})")

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