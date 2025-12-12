import grpc
from typing import Any, Callable
from security.auth_sec import validate_token

class AuthInterceptor(grpc.aio.ServerInterceptor):
    async def intercept_service(
        self,
        continuation: Callable,
        handler_call_details: grpc.HandlerCallDetails
    ) -> Any:
        md = dict(handler_call_details.invocation_metadata or [])

        method_name = handler_call_details.method
        if method_name and method_name.startswith("/grpc.reflection.v1alpha.ServerReflection"):
             return await continuation(handler_call_details)
        
        if not validate_token(md):
            def deny_unary(request, context):
                context.abort(grpc.StatusCode.UNAUTHENTICATED, "Invalid token")
            def deny_stream(request_iterator, context):
                context.abort(grpc.StatusCode.UNAUTHENTICATED, "Invalid token")
            info = await continuation(handler_call_details)
            if info is None:
                return None
            if info.request_streaming and info.response_streaming:
                return grpc.aio.stream_stream_rpc_method_handler(deny_stream)
            if info.request_streaming:
                return grpc.aio.stream_unary_rpc_method_handler(deny_stream)
            if info.response_streaming:
                return grpc.aio.unary_stream_rpc_method_handler(deny_unary)
            return grpc.aio.unary_unary_rpc_method_handler(deny_unary)
        return await continuation(handler_call_details)