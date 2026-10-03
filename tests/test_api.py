"""Tests for the PACEEX TCP API."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import call, patch

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "custom_components" / "paceex_bms")
)

from api import (
    CELLS_QUERY,
    QUERY_COOLDOWN,
    RECONNECT_COOLDOWN,
    SERIAL_QUERY,
    STATUS_QUERY,
    PaceexBmsApi,
    PaceexConnectError,
    PaceexConnectionError,
    PaceexProtocolError,
    PaceexReceiveError,
    _crc_modbus,
)


def make_frame(size: int, fill=None, query=STATUS_QUERY) -> bytes:
    """Build a valid PACEEX response frame for a request."""
    frame = bytearray(size)
    frame[0] = 0x9A
    frame[1:7] = query[1:7]
    frame[7] = size - 11
    if fill is not None:
        fill(frame)
    frame[-3:-1] = _crc_modbus(bytes(frame[:-3])).to_bytes(2, "big")
    frame[-1] = 0x9D
    return bytes(frame)


def fill_status(frame: bytearray) -> None:
    frame[29] = 80
    frame[30] = 99


def fill_cells(frame: bytearray) -> None:
    frame[11] = 16
    for index in range(16):
        frame[12 + index * 4 : 14 + index * 4] = (3300 + index).to_bytes(2, "big")


class FakeSocket:
    """Serve one scripted response for each request on a connection."""

    def __init__(self, responses=(), send_error=None, recv_chunk_size=None):
        self._responses = [bytes(response) for response in responses]
        self._response_index = 0
        self._active_response = bytearray()
        self._send_error = send_error
        self._recv_chunk_size = recv_chunk_size
        self.sent: list[bytes] = []
        self.closed = False

    def settimeout(self, _timeout: float) -> None:
        pass

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)
        if self._send_error is not None:
            raise self._send_error
        if self._response_index < len(self._responses):
            self._active_response = bytearray(self._responses[self._response_index])
            self._response_index += 1
        else:
            self._active_response = bytearray()

    def recv(self, size: int) -> bytes:
        if not self._active_response:
            return b""
        size = min(size, len(self._active_response))
        if self._recv_chunk_size is not None:
            size = min(size, self._recv_chunk_size)
        chunk = bytes(self._active_response[:size])
        del self._active_response[:size]
        return chunk

    def close(self) -> None:
        self.closed = True


class SessionTest(unittest.TestCase):
    """Test persistent TCP sessions and frame handling."""

    @patch("api.time.sleep")
    @patch("api.socket.create_connection")
    def test_read_status_uses_single_connection(self, create_connection, sleep) -> None:
        status = make_frame(62, fill_status)
        cells = make_frame(79, fill_cells, CELLS_QUERY)
        sock = FakeSocket([status, cells])
        create_connection.return_value = sock

        data = PaceexBmsApi("unused").read_status()

        self.assertEqual(data["cell_count"], 16)
        self.assertEqual(data["state_of_charge"], 80)
        self.assertEqual(create_connection.call_count, 1)
        self.assertEqual(sock.sent, [STATUS_QUERY, CELLS_QUERY])
        self.assertEqual(sleep.call_args_list, [call(QUERY_COOLDOWN)])
        self.assertTrue(sock.closed)

    @patch("api.time.sleep")
    @patch("api.socket.create_connection")
    def test_setup_validation_uses_single_connection(
        self, create_connection, sleep
    ) -> None:
        serial_payload = b"PACEEX-TEST"
        serial = bytearray(make_frame(12 + len(serial_payload), query=SERIAL_QUERY))
        serial[8] = len(serial_payload)
        serial[9 : 9 + len(serial_payload)] = serial_payload
        serial[-3:-1] = _crc_modbus(bytes(serial[:-3])).to_bytes(2, "big")
        status = make_frame(62, fill_status)
        cells = make_frame(79, fill_cells, CELLS_QUERY)
        sock = FakeSocket([bytes(serial), status, cells])
        create_connection.return_value = sock

        info, data = PaceexBmsApi("unused").read_device_info_and_status()

        self.assertEqual(info.serial_number, "PACEEX-TEST")
        self.assertEqual(data["state_of_charge"], 80)
        self.assertEqual(create_connection.call_count, 1)
        self.assertEqual(len(sock.sent), 3)
        self.assertEqual(
            sleep.call_args_list,
            [call(QUERY_COOLDOWN), call(QUERY_COOLDOWN)],
        )

    @patch("api.socket.create_connection")
    def test_frame_reader_ignores_internal_tail_byte(self, create_connection) -> None:
        frame = bytearray(make_frame(62, fill_status))
        frame[12] = 0x9D
        frame[-3:-1] = _crc_modbus(bytes(frame[:-3])).to_bytes(2, "big")
        sock = FakeSocket([bytes(frame)], recv_chunk_size=13)
        create_connection.return_value = sock

        result = PaceexBmsApi("unused")._query(STATUS_QUERY)

        self.assertEqual(result, bytes(frame))
        self.assertEqual(create_connection.call_count, 1)

    @patch("api.socket.create_connection")
    def test_frame_reader_handles_fragmented_tcp_response(
        self, create_connection
    ) -> None:
        frame = make_frame(62, fill_status)
        sock = FakeSocket([frame], recv_chunk_size=3)
        create_connection.return_value = sock

        result = PaceexBmsApi("unused")._query(STATUS_QUERY)

        self.assertEqual(result, frame)

    @patch("api.time.sleep")
    @patch("api.socket.create_connection")
    def test_reconnects_once_after_unexpected_response(
        self, create_connection, sleep
    ) -> None:
        wrong = bytearray(make_frame(62, fill_status))
        wrong[3] = 0x0B
        wrong[-3:-1] = _crc_modbus(bytes(wrong[:-3])).to_bytes(2, "big")
        right = make_frame(62, fill_status)
        create_connection.side_effect = [
            FakeSocket([bytes(wrong)]),
            FakeSocket([right]),
        ]

        result = PaceexBmsApi("unused")._query(STATUS_QUERY)

        self.assertEqual(result, right)
        self.assertEqual(create_connection.call_count, 2)
        self.assertEqual(sleep.call_args_list, [call(RECONNECT_COOLDOWN)])

    @patch("api.time.sleep")
    @patch("api.socket.create_connection")
    def test_reconnects_once_after_reset(self, create_connection, sleep) -> None:
        status = make_frame(62, fill_status)
        dead = FakeSocket(send_error=ConnectionResetError())
        live = FakeSocket([status])
        create_connection.side_effect = [dead, live]

        result = PaceexBmsApi("unused")._query(STATUS_QUERY)

        self.assertEqual(result, status)
        self.assertEqual(create_connection.call_count, 2)
        self.assertEqual(sleep.call_args_list, [call(RECONNECT_COOLDOWN)])

    @patch("api.time.sleep")
    @patch("api.socket.create_connection")
    def test_connect_failure_is_typed(self, create_connection, sleep) -> None:
        create_connection.side_effect = ConnectionRefusedError("refused")

        with self.assertRaises(PaceexConnectError) as ctx:
            PaceexBmsApi("unused")._query(STATUS_QUERY)

        self.assertIsInstance(ctx.exception, PaceexConnectionError)
        self.assertIn("refused", str(ctx.exception))

    @patch("api.time.sleep")
    @patch("api.socket.create_connection")
    def test_closed_connection_is_typed(self, create_connection, sleep) -> None:
        create_connection.side_effect = [FakeSocket(), FakeSocket()]

        with self.assertRaises(PaceexReceiveError) as ctx:
            PaceexBmsApi("unused")._query(STATUS_QUERY)

        self.assertIn("closed the connection", str(ctx.exception))
        self.assertEqual(create_connection.call_count, 2)

    @patch("api.time.sleep")
    @patch("api.socket.create_connection")
    def test_protocol_error_does_not_reconnect(self, create_connection, sleep) -> None:
        bad_tail = bytearray(make_frame(11))
        bad_tail[-1] = 0
        create_connection.return_value = FakeSocket([bytes(bad_tail)])

        with self.assertRaises(PaceexProtocolError):
            PaceexBmsApi("unused")._query(STATUS_QUERY)

        self.assertEqual(create_connection.call_count, 1)
        self.assertEqual(sleep.call_args_list, [])


# Frames captured from the master module of a 3-pack, 16-cell stack (no serial
# numbers or credentials are present in either frame).
MASTER_STATUS = bytes.fromhex(
    "9a00000a000000330300000000000014f1000077fb00007bb1000075306164000000010000"
    "000000000000010d0d1503100d1101040b6a03020b620bbf9d"
)
MASTER_CELLS = bytes.fromhex(
    "9a00000a020000440214f2100d130b660d140b670d130b640d140b6a0d1400000d1400000d14"
    "00000d1400000d1400000d1400000d1400000d1400000d1500000d1400000d1400000d120000"
    "d91e9d"
)


class StackDataTest(unittest.TestCase):
    """Test the stack-wide values decoded from real master frames."""

    def test_real_master_frames(self) -> None:
        data = PaceexBmsApi._parse_status(MASTER_STATUS, MASTER_CELLS)

        self.assertEqual(data["pack_count"], 3)
        self.assertEqual(data["rated_capacity"], 300.0)
        self.assertEqual(data["design_capacity"], 316.65)
        self.assertEqual(data["remaining_capacity"], 307.15)
        # Extremes across all packs, each with the pack and cell that holds it.
        self.assertEqual(data["system_max_cell_voltage"], 3.349)
        self.assertEqual(data["system_max_cell_voltage_pack"], 1)
        self.assertEqual(data["system_max_cell_voltage_index"], 13)
        self.assertEqual(data["system_min_cell_voltage"], 3.345)
        self.assertEqual(data["system_min_cell_voltage_pack"], 3)
        self.assertEqual(data["system_min_cell_voltage_index"], 16)
        self.assertEqual(data["system_cell_delta"], 0.004)
        self.assertAlmostEqual(data["system_max_temperature"], 19.05, delta=0.06)
        self.assertEqual(data["system_max_temperature_index"], 4)
        self.assertAlmostEqual(data["system_min_temperature"], 18.25, delta=0.06)
        self.assertEqual(data["system_min_temperature_pack"], 3)
        # Four cell temperatures; MOSFET/ambient slots are zero on this battery.
        self.assertAlmostEqual(data["temperature_cell_1"], 18.65, delta=0.06)
        self.assertAlmostEqual(data["temperature_cell_4"], 19.05, delta=0.06)
        self.assertNotIn("temperature_mosfet", data)
        self.assertNotIn("temperature_ambient", data)

    def test_slave_zero_status_reports_no_stack_values(self) -> None:
        """A slave answers the system query with zeros, which means 'unreported'."""
        zero_status = make_frame(62)
        data = PaceexBmsApi._parse_status(zero_status, MASTER_CELLS)

        for key in ("pack_count", "rated_capacity", "system_cell_delta"):
            self.assertNotIn(key, data)
        self.assertNotIn("system_max_temperature", data)
        self.assertEqual(data["cell_count"], 16)

    def test_short_status_frame_still_parses(self) -> None:
        """Older firmware may send a status frame without the trailing records."""
        data = PaceexBmsApi._parse_status(make_frame(40, fill_status), MASTER_CELLS)

        self.assertEqual(data["state_of_charge"], 80)
        self.assertNotIn("system_max_cell_voltage", data)


if __name__ == "__main__":
    unittest.main()
