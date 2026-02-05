import grpc
from typing import Any, Callable

from security.auth_sec import validate_token


class AuthInterceptor(grpc.ServerInterceptor):
    def intercept_service(
        self,
        continuation: Callable[[grpc.HandlerCallDetails], Any],
        handler_call_details: grpc.HandlerCallDetails,
    ) -> Any:
        md = dict(handler_call_details.invocation_metadata or [])
        method_name = handler_call_details.method or ""

        # Allow reflection/health/info without auth
        if method_name.startswith("/grpc.reflection.v1alpha.ServerReflection"):
            return continuation(handler_call_details)
        if method_name.startswith("/grpc.health.v1.Health/"):
            return continuation(handler_call_details)
        if method_name.startswith("/grpc.health.v1.Info/"):
            return continuation(handler_call_details)

        info = continuation(handler_call_details)
        if info is None:
            return None

        if validate_token(md):
            return info

        # Deny handlers depending on streaming flags
        def deny_unary(request, context):
            context.abort(grpc.StatusCode.UNAUTHENTICATED, "Invalid token")

        def deny_stream(request_iterator, context):
            context.abort(grpc.StatusCode.UNAUTHENTICATED, "Invalid token")

        if info.request_streaming and info.response_streaming:
            return grpc.stream_stream_rpc_method_handler(deny_stream)
        if info.request_streaming:
            return grpc.stream_unary_rpc_method_handler(deny_stream)
        if info.response_streaming:
            return grpc.unary_stream_rpc_method_handler(deny_unary)
        return grpc.unary_unary_rpc_method_handler(deny_unary)