from __future__ import annotations

import threading
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from queue import Queue

from daq_cli.application.profile_service import ProfileService
from daq_cli.domain.device import DeviceConfig
from daq_cli.infrastructure.adapters.legacy_board_adapter import LegacyBoardAdapter
from daq_cli.infrastructure.wave_monitor import (
    BaseWaveMonitorSource,
    BaseMultiBoardWaveMonitorSource,
    compute_multi_board_viewer_queue_size,
    DemoMultiBoardWaveMonitorSource,
    DemoWaveMonitorSource,
    LiveWaveMonitorSource,
    MultiBoardWaveMonitorProducer,
    ReplayWaveMonitorSource,
    WaveMonitorProducer,
)


@dataclass(slots=True)
class WaveMonitorSession:
    source_label: str
    frame_queue: Queue[object]
    stop_event: threading.Event
    producer: WaveMonitorProducer


@dataclass(slots=True)
class MultiBoardWaveMonitorSession:
    source_label: str
    board_names: list[str]
    frame_queue: Queue[object]
    stop_event: threading.Event
    producer: MultiBoardWaveMonitorProducer


class LiveWaveMonitorContext(AbstractContextManager["WaveMonitorSession"]):
    def __init__(
        self,
        adapter: LegacyBoardAdapter,
        device: DeviceConfig,
        source: BaseWaveMonitorSource,
        original_send_mode: int,
    ) -> None:
        self._adapter = adapter
        self._device = device
        self._source = source
        self._original_send_mode = original_send_mode
        self._session: WaveMonitorSession | None = None

    def __enter__(self) -> WaveMonitorSession:
        self._adapter.write_send_mode(self._device, 1)
        self._session = _make_session(self._source)
        return self._session

    def __exit__(self, exc_type, exc, tb) -> bool | None:
        if self._session is not None:
            self._session.stop_event.set()
            self._session.producer.join(timeout=2.0)
        try:
            self._adapter.write_send_mode(self._device, self._original_send_mode)
        except Exception as restore_exc:
            print(f"Warning: failed to restore send_mode: {restore_exc}")
        return None


class OfflineWaveMonitorContext(AbstractContextManager["WaveMonitorSession"]):
    def __init__(self, source: BaseWaveMonitorSource) -> None:
        self._source = source
        self._session: WaveMonitorSession | None = None

    def __enter__(self) -> WaveMonitorSession:
        self._session = _make_session(self._source)
        return self._session

    def __exit__(self, exc_type, exc, tb) -> bool | None:
        if self._session is not None:
            self._session.stop_event.set()
            self._session.producer.join(timeout=2.0)
        return None


class OfflineMultiBoardWaveMonitorContext(
    AbstractContextManager["MultiBoardWaveMonitorSession"]
):
    def __init__(self, source: BaseMultiBoardWaveMonitorSource) -> None:
        self._source = source
        self._session: MultiBoardWaveMonitorSession | None = None

    def __enter__(self) -> MultiBoardWaveMonitorSession:
        self._session = _make_multi_board_session(self._source)
        return self._session

    def __exit__(self, exc_type, exc, tb) -> bool | None:
        if self._session is not None:
            self._session.stop_event.set()
            self._session.producer.join(timeout=2.0)
        return None


class MonitorService:
    """Wave monitor session setup and teardown."""

    def __init__(self, profile_service: ProfileService | None = None) -> None:
        self._profile_service = profile_service or ProfileService()

    def open_live_wave_session(
        self,
        device_name: str,
        profile_path: Path | str,
        tcp_timeout_s: float = 1.0,
    ) -> LiveWaveMonitorContext:
        profile = self._profile_service.load_profile(profile_path)
        try:
            device = profile.devices[device_name]
        except KeyError as exc:
            available = ", ".join(sorted(profile.devices)) or "<none>"
            raise ValueError(
                f"Unknown device '{device_name}'. Available devices: {available}"
            ) from exc
        adapter = LegacyBoardAdapter()
        original = adapter.read_tcp_mode2_config(device).send_mode
        source = LiveWaveMonitorSource(
            device=device,
            adc_length=int(profile.defaults.get("adc_length", 64)),
            tcp_timeout_s=tcp_timeout_s,
        )
        return LiveWaveMonitorContext(
            adapter=adapter,
            device=device,
            source=source,
            original_send_mode=original,
        )

    def open_demo_wave_session(self, device_name: str) -> OfflineWaveMonitorContext:
        return OfflineWaveMonitorContext(DemoWaveMonitorSource(device_name=device_name))

    def open_replay_wave_session(
        self, device_name: str, replay_path: Path
    ) -> OfflineWaveMonitorContext:
        return OfflineWaveMonitorContext(
            ReplayWaveMonitorSource(device_name=device_name, replay_path=replay_path)
        )

    def open_multi_board_demo_wave_session(
        self,
        events: int = 100,
        board_names: list[str] | None = None,
    ) -> OfflineMultiBoardWaveMonitorContext:
        return OfflineMultiBoardWaveMonitorContext(
            DemoMultiBoardWaveMonitorSource(
                board_names=board_names,
                events=events,
            )
        )


def _make_session(source: BaseWaveMonitorSource) -> WaveMonitorSession:
    frame_queue: Queue[object] = Queue(maxsize=1)
    stop_event = threading.Event()
    producer = WaveMonitorProducer(
        source=source,
        queue=frame_queue,
        stop_event=stop_event,
    )
    producer.start()
    return WaveMonitorSession(
        source_label=source.source_label,
        frame_queue=frame_queue,
        stop_event=stop_event,
        producer=producer,
    )


def _make_multi_board_session(
    source: BaseMultiBoardWaveMonitorSource,
) -> MultiBoardWaveMonitorSession:
    frame_queue: Queue[object] = Queue(
        maxsize=compute_multi_board_viewer_queue_size(len(source.board_names))
    )
    stop_event = threading.Event()
    producer = MultiBoardWaveMonitorProducer(
        source=source,
        queue=frame_queue,
        stop_event=stop_event,
    )
    producer.start()
    return MultiBoardWaveMonitorSession(
        source_label=source.source_label,
        board_names=source.board_names,
        frame_queue=frame_queue,
        stop_event=stop_event,
        producer=producer,
    )
