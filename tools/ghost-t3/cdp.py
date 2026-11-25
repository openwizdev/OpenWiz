"""A small Chrome DevTools Protocol client. One reader thread, no extra packages."""

import base64
import hashlib
import json
import os
import socket
import struct
import threading
import time

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class WebSocket:
    def __init__(self, url):
        if not url.startswith("ws://"):
            raise ValueError("url")
        hostport, _, path = url[5:].partition("/")
        host, _, port = hostport.partition(":")
        self.sock = socket.create_connection((host, int(port)), timeout=10)
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(request.encode())
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise OSError("closed")
            data += chunk
        header, self._buf = data.split(b"\r\n\r\n", 1)
        if b" 101 " not in header.split(b"\r\n", 1)[0]:
            raise OSError("upgrade")
        accept = next(
            (line.split(b":", 1)[1].strip() for line in header.split(b"\r\n")
             if line.lower().startswith(b"sec-websocket-accept:")),
            b"",
        )
        expect = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest())
        if accept != expect:
            raise OSError("accept")
        self._send_lock = threading.Lock()

    def send(self, text):
        payload = text.encode()
        mask = os.urandom(4)
        length = len(payload)
        if length < 126:
            head = bytes([0x81, 0x80 | length])
        elif length < 65536:
            head = bytes([0x81, 0xFE]) + struct.pack("!H", length)
        else:
            head = bytes([0x81, 0xFF]) + struct.pack("!Q", length)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        with self._send_lock:
            self.sock.sendall(head + mask + masked)

    def recv(self, timeout):
        self.sock.settimeout(timeout)
        try:
            if not self._buf:
                chunk = self.sock.recv(65536)
                if not chunk:
                    raise OSError("closed")
                self._buf += chunk
        except socket.timeout as error:
            raise TimeoutError("timeout") from error
        self.sock.settimeout(10)
        frames = []
        while True:
            opcode, fin, payload = self._frame()
            if opcode == 0x9:
                self._pong(payload)
                continue
            if opcode == 0x8:
                raise OSError("closed")
            if opcode in (0x1, 0x0):
                frames.append(payload)
            if fin and frames:
                return b"".join(frames).decode()

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    def _read(self, count):
        while len(self._buf) < count:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise OSError("closed")
            self._buf += chunk
        out, self._buf = self._buf[:count], self._buf[count:]
        return out

    def _frame(self):
        head = self._read(2)
        opcode, fin = head[0] & 0x0F, bool(head[0] & 0x80)
        length, masked = head[1] & 0x7F, bool(head[1] & 0x80)
        if length == 126:
            length = struct.unpack("!H", self._read(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._read(8))[0]
        mask = self._read(4) if masked else None
        payload = self._read(length)
        if mask:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        return opcode, fin, payload

    def _pong(self, payload):
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        frame = bytes([0x8A, 0x80 | len(payload)]) + mask + masked
        with self._send_lock:
            self.sock.sendall(frame)


class Cdp:
    def __init__(self, ws_url):
        self.ws = WebSocket(ws_url)
        self._id = 0
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._replies = {}
        self._handlers = []
        self._closed = False
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()

    def on_event(self, handler):
        with self._lock:
            self._handlers.append(handler)

    def call(self, method, params=None, timeout=10):
        with self._lock:
            self._id += 1
            ident = self._id
        self.ws.send(json.dumps({"id": ident, "method": method, "params": params or {}}))
        deadline = time.monotonic() + timeout
        with self._cv:
            while ident not in self._replies and not self._closed:
                if not self._cv.wait(timeout=max(0.01, deadline - time.monotonic())):
                    if time.monotonic() >= deadline:
                        raise TimeoutError(method)
            if ident not in self._replies:
                raise OSError("closed")
            message = self._replies.pop(ident)
        if "error" in message:
            raise RuntimeError("cdp refused")
        return message.get("result") or {}

    def close(self):
        self._closed = True
        self.ws.close()

    def _read(self):
        while not self._closed:
            try:
                raw = self.ws.recv(0.5)
            except TimeoutError:
                continue
            except (OSError, UnicodeError, json.JSONDecodeError):
                break
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue
            handlers = []
            with self._cv:
                if "id" in message:
                    self._replies[message["id"]] = message
                    self._cv.notify_all()
                else:
                    handlers = list(self._handlers)
            for handler in handlers:
                try:
                    handler(message)
                except Exception:
                    continue
        with self._cv:
            self._closed = True
            self._cv.notify_all()
