"""Tests for signal-engine service HTTP response robustness."""

import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from services.signal_engine_service import SignalEngineHandler


class _BrokenPipeWriter:
    def write(self, _data):
        raise BrokenPipeError("client disconnected")


class _DummyHandler:
    def __init__(self):
        self.wfile = _BrokenPipeWriter()
        self.sent_status = None
        self.headers = []

    def send_response(self, status):
        self.sent_status = status

    def send_header(self, name, value):
        self.headers.append((name, value))

    def end_headers(self):
        pass

    _is_client_disconnect_error = staticmethod(SignalEngineHandler._is_client_disconnect_error)


def test_is_client_disconnect_error_recognizes_socket_disconnects():
    assert SignalEngineHandler._is_client_disconnect_error(BrokenPipeError()) is True
    assert SignalEngineHandler._is_client_disconnect_error(ConnectionResetError()) is True
    assert SignalEngineHandler._is_client_disconnect_error(RuntimeError("other")) is False


def test_json_response_does_not_raise_on_broken_pipe():
    handler = _DummyHandler()

    # Should not raise even when client disconnects while writing response.
    SignalEngineHandler._json_response(handler, 200, {"ok": True})

    assert handler.sent_status == 200
    assert any(name == "Content-Type" for name, _ in handler.headers)
