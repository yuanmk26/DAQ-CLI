from __future__ import annotations

from daq_cli.presentation.gui import fonts


def test_font_size_pt_rounds_half_up():
    assert fonts.font_size_pt(11, 1.0) == 11
    assert fonts.font_size_pt(11, 1.15) == 13  # 12.65
    assert fonts.font_size_pt(11, 1.30) == 14  # 14.3
    assert fonts.font_size_pt(11, 1.50) == 17  # 16.5 -> 17


def test_window_geometry_caps_to_small_screen():
    assert fonts.window_geometry(1366, 768) == (1100, 676, 133, 30)


def test_window_geometry_grows_and_caps_with_dpi():
    width, height, x, y = fonts.window_geometry(1920, 1080, 1.5, 1.0)
    assert (width, height) == (1650, 950)
    assert (x, y) == (135, 43)


def test_nearest_font_scale():
    assert fonts.nearest_font_scale(1.14) == 1.15
    assert fonts.nearest_font_scale(1.44) == 1.50
    assert fonts.nearest_font_scale("not-a-number") == 1.0


def test_font_scale_persists(tmp_path):
    path = tmp_path / "gui.json"
    fonts.save_font_scale(1.30, path)
    assert fonts.load_font_scale(path) == 1.30


def test_corrupt_font_config_falls_back(tmp_path):
    path = tmp_path / "gui.json"
    path.write_text("{not json", encoding="utf-8")
    assert fonts.load_font_scale(path) == 1.0
