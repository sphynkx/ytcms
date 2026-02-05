from __future__ import annotations

import os
import ssl
import grpc
from typing import Iterable, Iterator, Optional, Tuple

from proto import ytstorage_pb2, ytstorage_pb2_grpc


_CHUNK = 2_000_000


def _auth_md(token: str) -> list[tuple[str, str]]:
    tok = (token or "").strip()
    if not tok:
        return []
    return [("authorization", f"Bearer {tok}")]


def _make_channel(address: str, tls: bool) -> grpc.Channel:
    addr = (address or "").strip()
    if not addr:
        raise ValueError("ytstorage address is empty")

    if not tls:
        return grpc.insecure_channel(addr)

    # Minimal TLS setup (system CAs). If you later need custom CA/cert pinning, add env-driven loading here.
    creds = grpc.ssl_channel_credentials()
    return grpc.secure_channel(addr, creds)


def _normalize_rel(p: str) -> str:
    s = (p or "").replace("\\", "/").strip()
    s = s.lstrip("/")
    if s == "":
        return ""
    # avoid // and ./ segments
    parts = [x for x in s.split("/") if x and x != "."]
    return "/".join(parts)


def download_to_file(*, address: str, tls: bool, token: str, rel_path: str, dst_abs: str) -> int:
    rel = _normalize_rel(rel_path)
    if not rel:
        raise ValueError("rel_path is empty")

    os.makedirs(os.path.dirname(dst_abs) or ".", exist_ok=True)

    ch = _make_channel(address, tls)
    try:
        stub = ytstorage_pb2_grpc.StorageServiceStub(ch)
        md = _auth_md(token)

        req = ytstorage_pb2.ReadRequest(path=ytstorage_pb2.Path(rel_path=rel), offset=0, length=-1)
        total = 0
        with open(dst_abs, "wb") as f:
            for chunk in stub.Read(req, metadata=md):
                b = chunk.data
                if b:
                    f.write(b)
                    total += len(b)
        return total
    finally:
        try:
            ch.close()
        except Exception:
            pass


def mkdirs(*, address: str, tls: bool, token: str, rel_dir: str, exist_ok: bool = True) -> None:
    rel = _normalize_rel(rel_dir)
    ch = _make_channel(address, tls)
    try:
        stub = ytstorage_pb2_grpc.StorageServiceStub(ch)
        md = _auth_md(token)
        stub.Mkdirs(ytstorage_pb2.MkdirsRequest(path=ytstorage_pb2.Path(rel_path=rel), exist_ok=exist_ok), metadata=md)
    finally:
        try:
            ch.close()
        except Exception:
            pass


def upload_bytes(*, address: str, tls: bool, token: str, rel_path: str, payload: bytes, overwrite: bool = True) -> None:
    rel = _normalize_rel(rel_path)
    if not rel:
        raise ValueError("rel_path is empty")

    ch = _make_channel(address, tls)
    try:
        stub = ytstorage_pb2_grpc.StorageServiceStub(ch)
        md = _auth_md(token)

        def gen() -> Iterator[ytstorage_pb2.WriteEnvelope]:
            yield ytstorage_pb2.WriteEnvelope(
                header=ytstorage_pb2.WriteHeader(
                    path=ytstorage_pb2.Path(rel_path=rel),
                    overwrite=bool(overwrite),
                    append=False,
                    expected_size=len(payload),
                )
            )
            for i in range(0, len(payload), _CHUNK):
                yield ytstorage_pb2.WriteEnvelope(data=ytstorage_pb2.WriteData(data=payload[i : i + _CHUNK]))

        # server returns stream of WriteAck; we consume and ensure ok
        last_ack: Optional[ytstorage_pb2.WriteAck] = None
        for ack in stub.Write(gen(), metadata=md):
            last_ack = ack
            if not ack.ok:
                raise RuntimeError(f"ytstorage write failed: {ack.error}")

        if last_ack is None:
            raise RuntimeError("ytstorage write failed: no ack received")
    finally:
        try:
            ch.close()
        except Exception:
            pass