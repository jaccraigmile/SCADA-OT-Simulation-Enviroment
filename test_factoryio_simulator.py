from contextlib import redirect_stdout
from io import StringIO
import json
import socket
import struct
import threading
import time
import unittest
from unittest.mock import patch
from urllib.request import urlopen

from factoryio_simulator import (
    COIL_COUNT,
    DEFAULT_MODBUS_PORT,
    INPUT_NAMES,
    INPUT_COUNT,
    ModbusServer,
    Process,
    ResetServer,
    process_pdu,
)
from factoryio_modbus_controller import Controller, ModbusTCPClient
from reset_lab_process import main as reset_lab_process_main
from simulator_monitor import (
    HMIState,
    HMIServer,
    ModbusPoller,
    make_handler,
    read_snapshot,
)


class ModbusProcessTests(unittest.TestCase):
    def setUp(self):
        self.process = Process(auto_emitter=False)

    def test_reads_six_discrete_inputs(self):
        response = process_pdu(self.process, b"\x02\x00\x00\x00\x06")

        self.assertEqual(len(response), 3)
        self.assertEqual(response[0], 2)
        self.assertEqual(response[1], 1)
        self.assertEqual(response[2] & 0b00000010, 0b00000010)

    def test_reads_and_writes_coils(self):
        response = process_pdu(self.process, b"\x05\x00\x00\xff\x00")
        read_response = process_pdu(self.process, b"\x01\x00\x00\x00\x05")

        self.assertEqual(response, b"\x05\x00\x00\xff\x00")
        self.assertEqual(read_response, b"\x01\x01\x01")
        self.assertEqual(len(self.process.read_coils(0, COIL_COUNT)), COIL_COUNT)

    def test_coil_changes_are_reported_as_activity(self):
        process_pdu(self.process, b"\x05\x00\x00\xff\x00")

        self.assertIn("Output Conveyor -> ON", self.process.drain_events())

    def test_process_reset_restores_all_startup_state(self):
        self.process.set_door(False)
        self.process.set_auto_emitter(False)
        self.process.add_box()
        self.process.write_coils(0, [True] * COIL_COUNT)
        self.process.start_button_until = time.monotonic() + 10
        self.process.box_held = True
        self.process.boxes_removed = 7
        self.process.z_down = True
        self.process.z_transition_until = time.monotonic() + 10
        self.process.robot_angle = 1.0
        self.process.rotation_transition_until = time.monotonic() + 10
        self.process.rotation_direction = 1
        self.process.request_counts[2] = 15
        self.process.drain_events()

        self.process.reset()

        self.assertEqual(
            self.process.read_inputs(),
            [False, True, False, False, False, False],
        )
        self.assertEqual(self.process.read_coils(0, COIL_COUNT), [False] * COIL_COUNT)
        self.assertIsNone(self.process.box_position)
        self.assertFalse(self.process.box_held)
        self.assertEqual(self.process.boxes_removed, 0)
        self.assertTrue(self.process.auto_emitter)
        self.assertFalse(self.process.z_down)
        self.assertEqual(self.process.robot_angle, 0.0)
        self.assertEqual(self.process.rotation_direction, 0)
        self.assertEqual(self.process.request_counts, [0] * 16)
        self.assertEqual(self.process.drain_events(), [])

    def test_reset_script_resets_local_simulator(self):
        server = ResetServer(("127.0.0.1", 0), self.process)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        self.process.set_door(False)
        try:
            with patch(
                "sys.argv",
                [
                    "reset_lab_process.py",
                    "--confirm",
                    "--port",
                    str(server.server_address[1]),
                ],
            ), redirect_stdout(StringIO()):
                reset_lab_process_main()
            self.assertTrue(self.process.read_inputs()[1])
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

    def test_live_status_shows_process_and_io_names(self):
        status = self.process.live_status()

        self.assertIn("Door: CLOSED", status)
        self.assertIn("StartButton=off", status)
        self.assertIn("SafetyDoorClosed=ON", status)
        self.assertIn("Conveyor=off", status)

    def test_writes_multiple_coils(self):
        response = process_pdu(self.process, b"\x0f\x00\x00\x00\x05\x01\x15")

        self.assertEqual(response, b"\x0f\x00\x00\x00\x05")
        self.assertEqual(
            self.process.read_coils(0, COIL_COUNT),
            [True, False, True, False, True],
        )

    def test_rejects_addresses_outside_tutorial_io_map(self):
        self.assertEqual(
            process_pdu(self.process, b"\x02\x00\x06\x00\x01"),
            b"\x82\x02",
        )
        self.assertEqual(
            process_pdu(self.process, b"\x01\x00\x05\x00\x01"),
            b"\x81\x02",
        )
        self.assertEqual(len(self.process.read_inputs()), INPUT_COUNT)

    def test_process_box_moves_and_is_detected(self):
        self.process.add_box()
        self.process.write_coils(0, [True])
        self.process.step(10.0, 4.0)

        self.assertTrue(self.process.read_inputs()[2])
        self.assertIn("Box reached the pickup sensor", self.process.drain_events())

    def test_open_door_prevents_process_motion(self):
        self.process.add_box()
        self.process.write_coils(0, [True])
        self.process.set_door(False)
        self.process.step(10.0, 4.0)

        self.assertEqual(self.process.box_position, 0.0)

    def test_server_handles_openplc_modbus_tcp_request(self):
        server = ModbusServer(("127.0.0.1", 0), self.process)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            with socket.create_connection(server.server_address, timeout=2) as client:
                request = struct.pack(">HHHB", 0x1234, 0, 6, 1)
                client.sendall(request + b"\x02\x00\x00\x00\x06")
                response = client.recv(64)
            self.assertEqual(
                response,
                struct.pack(">HHHB", 0x1234, 0, 4, 1) + b"\x02\x01\x02",
            )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

    def test_python_controller_reads_and_writes_simulator(self):
        server = ModbusServer(("127.0.0.1", 0), self.process)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        client = ModbusTCPClient(*server.server_address, unit_id=1, timeout=2)
        try:
            client.connect()
            self.assertEqual(
                client.read_inputs(),
                [False, True, False, False, False, False],
            )
            client.write_coil(0, True)
            self.assertEqual(self.process.read_coils(0, 1), [True])
        finally:
            client.close()
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

    def test_python_controller_starts_and_stops_on_safety_door(self):
        class FakeClient:
            inputs = [True, True, False, False, False, False]
            coils = [False] * COIL_COUNT

            def read_inputs(self):
                return self.inputs

            def write_coil(self, address, value):
                self.coils[address] = value

        client = FakeClient()
        controller = Controller(client, poll_interval=0.05, status_interval=0)
        with redirect_stdout(StringIO()):
            controller.scan(1.0)
        self.assertEqual(controller.state, "FEED")
        self.assertTrue(client.coils[0])

        client.inputs = [False, False, False, False, False, False]
        with redirect_stdout(StringIO()):
            controller.scan(2.0)
        self.assertEqual(controller.state, "WAIT_START")
        self.assertFalse(controller.run_enabled)
        self.assertEqual(client.coils, [False] * COIL_COUNT)

    def test_hmi_reads_current_modbus_inputs_and_coils(self):
        server = ModbusServer(("127.0.0.1", 0), self.process)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            with socket.create_connection(server.server_address, timeout=2) as client:
                inputs, coils, transaction_id = read_snapshot(client, 0, 1)
            self.assertEqual(
                inputs,
                dict(zip(INPUT_NAMES, [False, True, False, False, False, False])),
            )
            self.assertEqual(len(coils), COIL_COUNT)
            self.assertEqual(transaction_id, 2)
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

    def test_hmi_serves_dashboard_and_json_status(self):
        state = HMIState()
        state.update(
            {"StartButton": False, "SafetyDoorClosed": False,
             "BoxAtSensor": True, "RobotDetected": False,
             "MovingZ": False, "Rotating": False},
            {"Conveyor": True, "Grab": False, "ExtendZ": False,
             "RotateCW": False, "RotateCCW": False},
        )
        server = HMIServer(("127.0.0.1", 0), make_handler(state))
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        base_url = f"http://{server.server_address[0]}:{server.server_address[1]}"
        try:
            with urlopen(base_url + "/", timeout=2) as response:
                page = response.read().decode("utf-8")
                self.assertEqual(response.status, 200)
                self.assertIn("Process overview", page)
                self.assertIn("Read-only HMI", page)
            with urlopen(base_url + "/api/status", timeout=2) as response:
                payload = json.loads(response.read())
            self.assertTrue(payload["connected"])
            self.assertFalse(payload["inputs"]["SafetyDoorClosed"])
            self.assertTrue(payload["coils"]["Conveyor"])
            self.assertIsNone(payload["error"])
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

    def test_hmi_poller_updates_live_state_from_simulator(self):
        self.process.write_coils(0, [True])
        server = ModbusServer(("127.0.0.1", 0), self.process)
        server_thread = threading.Thread(target=server.serve_forever)
        server_thread.start()
        state = HMIState()
        poller = ModbusPoller(
            state,
            server.server_address[0],
            server.server_address[1],
            unit_id=1,
            interval=0.01,
            timeout=1,
        )
        poller.start()
        try:
            deadline = time.monotonic() + 2
            while not state.get()["connected"] and time.monotonic() < deadline:
                time.sleep(0.01)
            snapshot = state.get()
            self.assertTrue(snapshot["connected"])
            self.assertTrue(snapshot["inputs"]["SafetyDoorClosed"])
            self.assertTrue(snapshot["coils"]["Conveyor"])
            self.assertIsNotNone(snapshot["updated_at"])
        finally:
            poller.stop()
            poller.join(timeout=2)
            server.shutdown()
            server_thread.join(timeout=2)
            server.server_close()

    def test_factory_io_default_modbus_port(self):
        self.assertEqual(DEFAULT_MODBUS_PORT, 502)


if __name__ == "__main__":
    unittest.main()
