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
    run_cli,
)
from factoryio_modbus_controller import (
    DEFAULT_MODBUS_PORT as CONTROLLER_DEFAULT_MODBUS_PORT,
    Controller,
    ModbusTCPClient,
)
from reset_lab_process import main as reset_lab_process_main
from simulator_monitor import (
    DEFAULT_MODBUS_PORT as HMI_DEFAULT_MODBUS_PORT,
    HMIState,
    HMIServer,
    ModbusExceptionError,
    ModbusPoller,
    make_handler,
    read_input_registers,
    read_snapshot,
)


class ModbusProcessTests(unittest.TestCase):
    def setUp(self):
        self.process = Process(auto_emitter=False)

    def test_reads_first_six_discrete_inputs(self):
        response = process_pdu(self.process, b"\x02\x00\x00\x00\x06")

        self.assertEqual(len(response), 3)
        self.assertEqual(response[0], 2)
        self.assertEqual(response[1], 1)
        self.assertEqual(response[2] & 0b00000010, 0b00000010)

    def test_reads_box_present_input(self):
        self.process.add_box()

        self.assertEqual(
            process_pdu(self.process, b"\x02\x00\x06\x00\x01"),
            b"\x02\x01\x01",
        )

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
        self.process.rotation_direction = 1
        self.process.request_counts[2] = 15
        self.process.drain_events()

        self.process.reset()

        self.assertEqual(
            self.process.read_inputs(),
            [False, True, False, False, False, False, False, False, False,
             False, False, False],
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

    def test_reset_script_pulses_start_on_local_simulator(self):
        server = ResetServer(("127.0.0.1", 0), self.process)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            with patch(
                "sys.argv",
                [
                    "reset_lab_process.py",
                    "--start",
                    "--port",
                    str(server.server_address[1]),
                ],
            ), redirect_stdout(StringIO()):
                reset_lab_process_main()
            self.assertTrue(self.process.read_inputs()[0])
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
        self.assertIn("Tank: level=25.0% temperature=20.0C", status)

    def test_writes_multiple_coils(self):
        with redirect_stdout(StringIO()) as output:
            response = process_pdu(
                self.process, b"\x0f\x00\x00\x00\x05\x01\x15"
            )

        self.assertEqual(response, b"\x0f\x00\x00\x00\x05")
        self.assertEqual(
            self.process.read_coils(0, COIL_COUNT),
            [True, False, True, False, True, False, False, False, False],
        )
        self.assertIn(
            "Received FC 15 write: address=0, count=5; outputs: "
            "Conveyor=ON, Grab=OFF, ExtendZ=ON, RotateCW=OFF, RotateCCW=ON",
            output.getvalue(),
        )

        with redirect_stdout(StringIO()) as repeated_output:
            process_pdu(self.process, b"\x0f\x00\x00\x00\x05\x01\x15")
        self.assertIn("Received FC 15 write:", repeated_output.getvalue())

    def test_rejects_addresses_outside_tutorial_io_map(self):
        self.assertEqual(
            process_pdu(self.process, b"\x02\x00\x0c\x00\x01"),
            b"\x82\x02",
        )
        self.assertEqual(
            process_pdu(self.process, b"\x01\x00\x09\x00\x01"),
            b"\x81\x02",
        )
        self.assertEqual(len(self.process.read_inputs()), INPUT_COUNT)

    def test_tank_fill_and_input_registers(self):
        self.assertEqual(
            process_pdu(self.process, b"\x04\x00\x00\x00\x02"),
            b"\x04\x04\x00\xfa\x00\xc8",
        )
        self.process.write_coils(5, [True])
        self.process.step(10.0, 2.0)

        self.assertEqual(self.process.read_input_registers(0, 2), [370, 200])
        self.assertFalse(self.process.read_inputs()[7])
        self.assertEqual(
            process_pdu(self.process, b"\x04\x00\x02\x00\x01"),
            b"\x84\x02",
        )

    def test_tank_interlocks_mixer_and_transfer_pump(self):
        self.process.tank_level = 50.0
        self.process.write_coils(6, [True, True])
        self.process.step(10.0, 2.0)

        self.assertEqual(self.process.tank_level, 50.0)
        self.assertFalse(self.process.read_inputs()[9])
        self.assertFalse(self.process.read_inputs()[10])

        self.process.write_coils(7, [False])
        self.process.step(12.0, 2.0)

        self.assertAlmostEqual(self.process.tank_temperature, 20.3)
        self.assertTrue(self.process.read_inputs()[9])

    def test_cli_can_manually_operate_tank_coils(self):
        with patch(
            "builtins.input",
            side_effect=["coil fillvalve on", "quit"],
        ), redirect_stdout(StringIO()) as output:
            run_cli(self.process)

        self.assertTrue(self.process.read_coils(5, 1)[0])
        self.assertIn("FillValve ON.", output.getvalue())

    def test_process_box_moves_and_is_detected(self):
        self.process.add_box()
        self.assertTrue(self.process.read_inputs()[6])
        self.process.write_coils(0, [True])
        self.process.step(10.0, 4.0)

        self.assertAlmostEqual(self.process.box_position, 0.6)
        self.assertFalse(self.process.read_inputs()[2])

        self.process.step(14.0, 3.0)

        self.assertTrue(self.process.read_inputs()[2])
        self.assertIn("Box reached the pickup sensor", self.process.drain_events())

    def test_auto_emitter_waits_until_held_box_is_released(self):
        self.process.set_auto_emitter(True)
        self.process.box_held = True
        self.process.last_emission = 0
        self.process.step(10.0, 0.05)

        self.assertIsNone(self.process.box_position)
        self.assertTrue(self.process.box_held)

        self.process.box_held = False
        self.process.step(10.05, 0.05)

        self.assertEqual(self.process.box_position, 0.0)
        self.assertFalse(self.process.box_held)

    def test_robot_detected_ignores_next_box_at_emitter_while_picker_holds_box(self):
        self.process.box_held = True
        self.process.box_position = 0.0
        self.process.z_down = True
        self.process.robot_angle = 0.0

        inputs = self.process.read_inputs()

        self.assertFalse(inputs[3])
        self.assertTrue(inputs[6])

    def test_rotating_input_tracks_active_motion(self):
        self.process.write_coils(3, [True])
        self.process.step(time.monotonic(), 1.0)

        self.assertTrue(self.process.read_inputs()[5])

        self.process.write_coils(3, [False])
        self.process.step(time.monotonic(), 0.05)

        self.assertFalse(self.process.read_inputs()[5])

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
        with redirect_stdout(StringIO()) as output:
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
        self.assertIn("Modbus client disconnected: 127.0.0.1:", output.getvalue())

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
            with redirect_stdout(StringIO()) as output:
                client.write_coils([True, False, True, False, True])
                self.assertIn(
                    "Received FC 15 write: transaction_id=0x0001; "
                    "address=0, count=5; outputs: "
                    "Conveyor=ON, Grab=OFF, ExtendZ=ON, RotateCW=OFF, RotateCCW=ON",
                    output.getvalue(),
                )
            self.assertEqual(
                self.process.read_coils(0, COIL_COUNT),
                [True, False, True, False, True, False, False, False, False],
            )
            self.assertEqual(self.process.request_counts[5], 0)
            self.assertEqual(self.process.request_counts[15], 1)
        finally:
            client.close()
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

    def test_python_controller_starts_and_stops_on_safety_door(self):
        class FakeClient:
            inputs = [True, True, False, False, False, False]
            coils = [False] * 5

            def read_inputs(self):
                return self.inputs

            def write_coils(self, values):
                self.coils = values.copy()

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
        self.assertEqual(client.coils, [False] * 5)

    def test_python_controller_retracts_after_pick_with_next_box_at_emitter(self):
        self.process.box_held = True
        self.process.box_position = 0.0
        self.process.z_down = True
        self.process.robot_angle = 0.0

        class LocalClient:
            def read_inputs(inner_self):
                return self.process.read_inputs()[:6]

            def write_coils(inner_self, values):
                self.process.write_coils(0, values)

        controller = Controller(
            LocalClient(), poll_interval=0.05, status_interval=0
        )
        controller.state = "PICK"
        controller.run_enabled = True
        controller.robot_detected_seen = True
        controller.coil_states = [False, True, True, False, False]

        with redirect_stdout(StringIO()):
            controller.scan(time.monotonic())

        self.assertEqual(controller.state, "RETRACT")
        self.assertEqual(
            self.process.read_coils(0, COIL_COUNT),
            [False, True, False, False, False, False, False, False, False],
        )

    def test_hmi_reads_current_modbus_inputs_and_coils(self):
        server = ModbusServer(("127.0.0.1", 0), self.process)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            with socket.create_connection(server.server_address, timeout=2) as client:
                inputs, coils, process_values, transaction_id = read_snapshot(
                    client, 0, 1
                )
                registers = read_input_registers(client, transaction_id, 1, 0, 2)
            self.assertEqual(
                inputs,
                dict(zip(INPUT_NAMES, [False, True, False, False, False, False, False,
                                       False, False, False, False, False])),
            )
            self.assertEqual(len(coils), COIL_COUNT)
            self.assertEqual(process_values["TankLevelPct"], 25.0)
            self.assertEqual(process_values["TankTemperatureC"], 20.0)
            self.assertEqual(registers, [250, 200])
            self.assertEqual(transaction_id, 3)
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

    def test_hmi_supports_legacy_six_input_map(self):
        connection = object()
        with patch(
            "simulator_monitor.read_bits",
            side_effect=[
                ModbusExceptionError(2, 2, 0, 7),
                ModbusExceptionError(2, 2, 0, 7),
                [False, True, False, False, False, False],
                ModbusExceptionError(1, 2, 0, 9),
                [True, False, False, False, False],
            ],
        ) as read:
            with patch(
                "simulator_monitor.read_input_registers",
                side_effect=ModbusExceptionError(4, 1, 0, 2),
            ):
                inputs, coils, process_values, next_transaction_id = read_snapshot(
                    connection, 10, 1
                )

        self.assertEqual(
            inputs,
            {
                "StartButton": False,
                "SafetyDoorClosed": True,
                "BoxAtSensor": False,
                "RobotDetected": False,
                "MovingZ": False,
                "Rotating": False,
                "BoxPresent": True,
                "TankLow": False,
                "TankHigh": False,
                "MixerRunning": False,
                "TransferFlow": False,
                "TankOverflow": False,
            },
        )
        self.assertTrue(coils["Conveyor"])
        self.assertIsNone(process_values["TankLevelPct"])
        self.assertEqual(next_transaction_id, 16)
        self.assertEqual(
            [call.args[1:] for call in read.call_args_list],
            [(10, 1, 2, 12, 0), (11, 1, 2, 7, 0), (12, 1, 2, 6, 0),
             (13, 1, 1, 9, 0), (14, 1, 1, 5, 0)],
        )

    def test_hmi_error_identifies_failing_modbus_request(self):
        error = ModbusExceptionError(1, 2, 0, 5)

        self.assertEqual(
            str(error),
            "Modbus FC 1 read at address 0, count 5: exception code 2",
        )

    def test_hmi_serves_dashboard_and_json_status(self):
        state = HMIState()
        state.update(
            {"StartButton": False, "SafetyDoorClosed": False,
             "BoxAtSensor": True, "RobotDetected": False,
             "MovingZ": False, "Rotating": False, "BoxPresent": True},
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
                self.assertIn("BoxPresent", page)
                self.assertIn("setInterval(refresh, 100)", page)
                self.assertIn(
                    'rotate(" + armAngleDegrees + ")',
                    page,
                )
                self.assertIn('setAttribute("y2", armLength)', page)
                self.assertIn('heldX + 19', page)
                self.assertIn("const zTransitionMs = 750;", page)
                self.assertIn(
                    "(data.coils.RotateCW || data.coils.RotateCCW) && data.coils.Grab;",
                    page,
                )
                self.assertIn(
                    "const nextZTarget = rotatingWithBox ? 0 : data.coils.ExtendZ ? 1 : 0;",
                    page,
                )
                self.assertIn(
                    "const easedProgress = 1 - Math.pow(1 - progress, 3);",
                    page,
                )
                self.assertIn("const dropLowering = held && armAngle >= 65 ?", page)
                self.assertIn(
                    "const heldY = 150 + 70 * Math.max(zLevel, dropLowering);",
                    page,
                )
                self.assertIn(
                    "(armAngle / 90) * 226",
                    page,
                )
                self.assertIn("LOWERING AT DROP", page)
                self.assertIn("POSITIONED OVER DROP", page)
                self.assertIn("const held = data.coils.Grab;", page)
                self.assertIn("RETRACTING WITH BOX", page)
                self.assertIn("rotatingWithBox && zLevel > 0.05", page)
                self.assertNotIn(
                    "const held = data.coils.Grab && !data.inputs.BoxAtSensor;",
                    page,
                )
                self.assertIn(
                    "lastData.coils.Grab &&\n"
                    "        !data.coils.Grab &&\n"
                    "        armAngle >= 88",
                    page,
                )
                self.assertIn("boxX = 140;", page)
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
        self.process.add_box()
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
            self.assertTrue(snapshot["inputs"]["BoxPresent"])
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
        self.assertEqual(CONTROLLER_DEFAULT_MODBUS_PORT, DEFAULT_MODBUS_PORT)
        self.assertEqual(HMI_DEFAULT_MODBUS_PORT, DEFAULT_MODBUS_PORT)


if __name__ == "__main__":
    unittest.main()
