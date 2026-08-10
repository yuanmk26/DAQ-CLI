from pathlib import Path
from types import SimpleNamespace
import unittest

from daq_cli.presentation.gui import formatting


class ParseIntListTests(unittest.TestCase):
    def test_single_value_broadcasts(self) -> None:
        self.assertEqual(formatting.parse_int_list("2700", 16, "thr"), [2700] * 16)

    def test_exact_count_accepted(self) -> None:
        values = formatting.parse_int_list("1, 2, 3, 4", 4, "t")
        self.assertEqual(values, [1, 2, 3, 4])

    def test_hex_values_accepted(self) -> None:
        values = formatting.parse_int_list("0x0A8C", 16, "thr")
        self.assertEqual(values, [0x0A8C] * 16)

    def test_wrong_count_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "1 个值（广播）或 16 个值"):
            formatting.parse_int_list("1,2", 16, "thr")

    def test_empty_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "为空"):
            formatting.parse_int_list("", 16, "thr")


class ResultFormattingTests(unittest.TestCase):
    def _device(self, name="dev1"):
        return SimpleNamespace(
            name=name, ip="192.168.10.10", rbcp_port=4660,
            tcp_port=24, board_id=0, role="adc",
        )

    def test_format_fields_layout(self) -> None:
        text = formatting.format_fields("标题", [("a", 1), ("b", "x")])
        self.assertIn("===== 标题 =====", text)
        self.assertIn("a: 1", text)
        self.assertIn("b: x", text)

    def test_format_board_info(self) -> None:
        result = SimpleNamespace(device=self._device(), source_profile=Path("p.yaml"))
        text = formatting.format_board_info(result)
        self.assertIn("Board Info: dev1", text)
        self.assertIn("ip: 192.168.10.10", text)
        self.assertIn("board_id: 0", text)

    def test_format_sysmon(self) -> None:
        result = SimpleNamespace(
            device=self._device(),
            source_profile=Path("p.yaml"),
            snapshot=SimpleNamespace(
                temperature_c=45.2, vccint_v=1.011, vccaux_v=1.802, vccbram_v=1.001
            ),
        )
        text = formatting.format_sysmon(result)
        self.assertIn("temperature_c: 45.2", text)
        self.assertIn("vccint_v: 1.011", text)

    def test_format_trigger_config(self) -> None:
        result = SimpleNamespace(
            device=self._device(),
            source_profile=Path("p.yaml"),
            trigger_mode=9,
            trigger_position=5,
            thresholds=(1950, 2400, 2300, 2300),
            send_start_delay=0,
            timestamp_clean_enabled=True,
            ext_trigger_enabled=False,
        )
        text = formatting.format_trigger_config(result)
        self.assertIn("trigger_mode: 9", text)
        self.assertIn("thresholds: 1950, 2400, 2300, 2300", text)

    def test_format_tcm_link_read_shows_enabled_channels_only(self) -> None:
        thresholds = [2700, 1800] + [0] * 14
        result = SimpleNamespace(
            device=self._device(),
            source_profile=Path("p.yaml"),
            thresholds=thresholds,
            mask=0x0003,
            polarity=0x0002,
            debounce=200,
            enable=True,
            pulse_width=20,
        )
        text = formatting.format_tcm_link_read(result)
        self.assertIn("mask: 0x0003 (2 ch)", text)
        self.assertIn("debounce: 200 x 5ns = 1.0 us", text)
        self.assertIn("thr ch00: 2700 (pos)", text)
        self.assertIn("thr ch01: 1800 (neg)", text)
        self.assertNotIn("thr ch02", text)

    def test_format_register_read_hex_dump(self) -> None:
        result = SimpleNamespace(
            device=self._device(),
            source_profile=Path("p.yaml"),
            address=0x10,
            data=bytes([0x0A, 0x8C, 0x01, 0x41]),
        )
        text = formatting.format_register_read(result)
        self.assertIn("Register 0x10", text)
        self.assertIn("0A 8C 01 41", text)

    def test_format_single_acquire_result(self) -> None:
        result = SimpleNamespace(
            device=self._device(),
            source_profile=Path("p.yaml"),
            requested_events=100,
            captured_events=100,
            send_mode=1,
            decode_enabled=True,
            decoded_events=100,
            decode_errors=0,
            json_output_enabled=True,
            text_output_enabled=False,
            text_output_events=0,
            text_output_files=0,
            run_output_dir=Path("out/run_00001"),
            raw_output_dir=Path("out/run_00001/raw"),
            json_output_dir=Path("out/run_00001/decoded"),
            text_output_dir=None,
            log_output_path=Path("out/run_00001/logs/capture.log"),
        )
        text = formatting.format_single_acquire_result(result)
        self.assertIn("captured_events: 100", text)
        self.assertIn(f"run_output_dir: {Path('out/run_00001')}", text)

    def test_format_single_progress(self) -> None:
        progress = SimpleNamespace(
            captured_events=12, requested_events=1000,
            packet_bytes=None, hit_mask=None, output_dir=None, event_rate_hz=5.2,
        )
        text = formatting.format_single_progress(progress)
        self.assertIn("12/1000", text)
        self.assertIn("5.2 ev/s", text)

    def test_format_tcm_trigger_read(self) -> None:
        tcm = SimpleNamespace(name="main", ip="192.168.10.16", rbcp_port=4660)
        text = formatting.format_tcm_trigger_read(
            tcm,
            source_profile=Path("p.yaml"),
            enable=True,
            mask=0x03,
            pulse_width=32,
            debounce=20,
            trig_sticky=True,
            pending=False,
            wide_pulse_active=False,
            last_trigger_channels=0x02,
        )
        self.assertIn("TCM Trigger Config: main", text)
        self.assertIn("mask: 0x03 (2 ch)", text)
        self.assertIn("pulse_width: 32 x 50ns = 1.6 us", text)
        self.assertIn("trig_sticky: True", text)
        self.assertIn("last_trigger_channels: 1", text)

    def test_board_config_options_from_form(self) -> None:
        options = formatting.board_config_options_from_form(
            adc_enabled=True,
            clock_enabled=False,
            trigger_enabled=True,
            tcp_mode2_enabled=False,
            trigger_mode=9,
            trigger_position=5,
            threshold_1=1,
            threshold_2=2,
            threshold_3=3,
            threshold_4=4,
            timestamp_clean_enabled=False,
            ext_trigger_enabled=True,
            send_mode=1,
        )
        self.assertEqual(options.trigger_mode, 9)
        self.assertEqual(options.trigger_thresholds, (1, 2, 3, 4))
        self.assertTrue(options.adc_enabled)
        self.assertFalse(options.clock_enabled)
        self.assertEqual(options.send_mode, 1)


if __name__ == "__main__":
    unittest.main()
