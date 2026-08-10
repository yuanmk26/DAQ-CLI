# daq-cli v0.2.0 更新计划：帧格式升级（28B 头 + Δfine）+ TCM 触发链路

> 状态：**已全部实现（2026-08-10）**，含阶段 C。阶段 A/B/C 代码与测试已
> 完成，v0.2.0 文档与版本号已更新。落笔时间：2026-08-10。

## 1. 背景

固件侧两个项目在 2026-08 完成了两项关键改动，需要 daq-cli 配套升级：

| 固件改动 | 提交 | 对 daq-cli 的影响 |
| --- | --- | --- |
| **TCP_SENT 帧头 20B → 28B**（新增 `crossing_fine` / `accept_fine`，byte 19 = 格式版本） | ADC `64c2885` | 所有解析器、帧长公式、vendor 脚本过期 |
| **ADC 板 TCM 触发链路**（实时过阈 → M21 脉冲，新寄存器 `0x45~0x6C`，`Trigger_model=9`） | ADC `b02db46` | 需要新的配置/回读命令 |
| **TCM 板触发联动 v2**（8 路 EXT_TRG 接收、宽脉冲广播，新寄存器 `0x20~0x25`） | TCM `5550276` | 可选：TCM 板配置命令 |

固件侧参考文档（权威来源）：

- `FDU-ADC-250M-16ch/docs/tcp_sent_selected_channel_packet.md`（28B 帧格式）
- `FDU-ADC-250M-16ch/docs/delta_fine_timestamp.md`（Δfine 原理与解析示例）
- `FDU-ADC-250M-16ch/docs/rbcp_register_map.md`（0x45~0x6C 寄存器表）
- `FDU-ADC-250M-16ch/docs/changes/2026-08-06/*`（TCM 触发链路设计 + 测试指南）
- `FDU-ADC-250M-16ch/script/sipm_trigger_setup.py`（新测试脚本，功能模型）
- `FDU-TCM/docs/changes/2026-08-08/*`（TCM 侧设计 + 寄存器 0x20~0x25）

## 2. 目标版本与范围

版本号：**v0.2.0**（协议级改动，从 0.1.x 线独立出来）。

### 必做（本版本主题）

- **阶段 A**：28B 帧格式全面支持（解析 + 解码 + 聚合格式 + vendor 同步 + 测试）
- **阶段 B**：ADC 板 TCM 触发链路配置/回读命令（0x45~0x6C + Trigger_model=9）

### 选做（视时间）

- **阶段 C**：TCM 板触发联动配置命令（0x20~0x25）
- Δfine 在波形查看器/文本输出中的可视化

### 明确不做（记录，不在本版本）

- 级别 2：200M 锁相 20M（跨板 5ns 对齐）——固件侧已记录问题，未实现
- 原生硬件模块重写（RBCP/TCP 直连替代 legacy 封装）——保持"reuse before rewrite"
- 慢基线跟踪、符合计数（≥N 路触发）等固件侧演进项

## 3. 阶段 A：帧格式升级（28B 头 + fine 字段）

### A0. 同步 vendored legacy 脚本（先行，解除采集路径阻塞）

`src/daq_cli/_vendor/fdu_legacy/multi_board_acquire.py` 与 ADC 上游
`script/multi_board_acquire.py` 的差异仅约 30 行（不含注释），同步内容：

- `Frame` dataclass 增加 `crossing_fine: int = 0` / `accept_fine: int = 0`
- `FrameParser.parse_one`：`FF FE 01` 路径支持 28B 头，解析
  `crossing_fine = u32(header, 20)` / `accept_fine = u32(header, 24)`
- 同步后 legacy 多板采集（`legacy_multi_capture_runner.py` 经 importlib 加载此
  模块）立即获得 28B 帧支持

**同步策略**：与上游函数级一致，但 `FrameParser` 采用 **version 判别**（先读
20 字节、按 byte 19 决定是否再读 8 字节）而非上游的无条件 28B——上游文档
`delta_fine_timestamp.md` §9 本身建议按 byte 19 区分，且判别逻辑可防止
**新旧固件混用时旧板帧被误解析**。与上游的差异以注释标注，控制在 ~10 行内，
每次同步时按注释点合并。同步后跑 `tests/test_multi_wave_watch.py` 回归。

### A1. `src/daq_cli/infrastructure/tcp_sent_protocol.py`

- `HEADER_BYTES = 20` 常量拆为：
  - `FORMAT_VERSION_LEGACY = 0`（20B 头）、`FORMAT_VERSION_FINE = 1`（28B 头）
  - `header_bytes_for(format_version) -> 20 | 28`
- `frame_total_size(...)` 增加 `format_version` 参数（默认 0，保持调用方兼容
  或显式传参）

### A2. `src/daq_cli/infrastructure/tcp_sent_decode.py`

- `DecodedTcpSentEvent` 增加字段：
  - `format_version: int`（0=旧 20B，1=新 28B）
  - `crossing_fine: int | None` / `accept_fine: int | None`（旧帧为 None）
  - `delta_fine: int | None` 属性（`(accept - crossing) & 0xFFFFFFFF`，
    仅当两字段非 None；回绕安全，语义见 delta_fine_timestamp.md）
- `decode_tcp_sent_packet` 按 **byte 19** 判别版本：
  - `= 1` → 28B 头，解析 fine 字段
  - `= 0` → 20B 头，fine 字段为 None（旧 capture 文件仍可解码）
- `to_json_dict()` 输出 `format_version` / `crossing_fine` / `accept_fine` /
  `delta_fine`（旧帧为 null）

### A3. `src/daq_cli/infrastructure/multi_board_decode.py` + vendor 聚合写入

聚合文件（FDUAGGR1）当前 BOARD chunk 只存 feature/waveform bytes，**fine
字段在聚合时丢失**，需要格式版本升级：

- `FILE_HEADER_FMT` 的 `version` 字段：v1 → v2
- `BOARD_HEADER_FMT`（`<IHHIIQHHHHIIQ`）追加两个 `I`（crossing_fine、
  accept_fine）→ v2 chunk；`_build_board_record` 同步写入（vendor 侧）
- `multi_board_decode.py` 读取端：按文件头 version 选择 v1/v2 两种
  BOARD_HEADER_FMT 解析（**老 .aggr 文件仍可读**）
- `MultiBoardChunkRecord` 增加 `crossing_fine` / `accept_fine` 字段
- `build_board_packet`：fine 字段存在时重建 28B 头（byte 19=1，写 fine），
  否则重建 20B 头（byte 19=0）——保证解码路径一致

### A4. 采集与输出链路

- `src/daq_cli/infrastructure/adapters/legacy_capture_runner.py`（live
  single 采集 watch 路径，~830-880 行）：`_fill(HEADER_BYTES)` / `MODE2_MAGIC`
  / `frame_total_size` 调用全部改为 version 判别（先读 20 字节、按 byte 19
  定头长）
- `src/daq_cli/infrastructure/wave_monitor.py`（`daq monitor wave` live 路径，
  `_try_parse_frame` ~296-311 行）：**硬编码 `20`**（`len(buffer) < 20`、
  `frame_bytes = 20 + payload_bytes`、`payload = raw[20:]`）→ 改为按 byte 19
  判别、支持 28B 头，否则新固件下每帧少读 8 字节、波形偏移
- `legacy_multi_capture_runner.py` live watch 传递链（显式）：vendor
  `FrameParser` 解析出的 fine 字段 → `build_board_packet`（A3 已支持透传）→
  原生解码器 → 查看器/文本输出。**fine 字段必须跨过 packet 重建这一跳**
- `src/daq_cli/infrastructure/text_event_writer.py`：TXT 事件增加
  `format_version` / `crossing_fine` / `accept_fine` / `delta_fine` 行
- JSON 输出（decode_service / acquire_service）自动随 A2 的 to_json_dict 生效

### A5. 测试（硬件无关）

- `tests/test_decode.py` 新增：
  - 28B 头 mode 0/1/2/3 各一组的构造 fixture（手工构造字节，帧长公式
    `28 + ...`）
  - `format_version` 判别：同一字节流 byte 19 置 0/1 分别解析
  - `delta_fine` 无符号回绕用例（crossing > accept 时）
  - 旧 20B fixture 回归（现有用例保持全绿）
- `tests/test_multi_wave_watch.py`：聚合 v2 round-trip、v1 老文件读取兼容
- `monitoring_samples/`：保留旧 sample（20B，验证兼容），新增一个 28B sample

## 4. 阶段 B：ADC 板 TCM 触发链路（0x45~0x6C）

寄存器速查（ADC 板，高字节在前）：

| 地址 | 内容 | 复位值 |
| --- | --- | --- |
| `0x45~0x64` | 16 路实时过阈阈值 `thr[15:0]`（ch0@45/46 … ch15@63/64） | 全 0 |
| `0x65~0x66` | 通道掩码 `mask[15:0]` | 0 |
| `0x67~0x68` | 极性 `polarity[15:0]`（0=正 adc>thr，1=负 adc<thr） | 0 |
| `0x69~0x6A` | 去抖间隔（5ns 单位） | 200 = 1µs |
| `0x6B` | 使能（bit0） | 0 |
| `0x6C` | M21 脉冲宽度（5ns 单位） | 20 = 100ns |

### B1. `src/daq_cli/infrastructure/adapters/legacy_board_adapter.py`

仿现有 `read_trigger_config`（直连 rbcp 读）模式新增：

- `read_tcm_link_config(device)` → 回读 16 阈值 + mask/polarity/debounce/
  enable/width，返回 dataclass `LegacyTcmLinkReadResult`
- `write_tcm_link_config(device, thresholds, mask, polarity, debounce,
  pulse_width, enable)` → 顺序写寄存器（先阈值/掩码/极性，最后 0x6B 使能，
  与测试指南一致）
- `patched_trigger_model` 边界 0~8 放宽到 0~9

### B2. `src/daq_cli/application/board_service.py`

- `read_tcm_link_config(device_name, profile_path)` → 调 adapter，返回
  presentation 友好结构
- `configure_tcm_link(...)` → 校验（mask/polarity ≤ 0xFFFF、阈值 ≤ 0xFFFF、
  debounce/width 范围）→ 写 → 回读验证（与 `configure_board` 风格一致）
- `BoardConfigOptions.trigger_mode` 校验范围放宽到 0~9

### B3. CLI（`src/daq_cli/cli/board.py` + printers）

设计决定：**独立子命令**，不并入 `daq board config`（避免 config 命令
参数爆炸）：

- `daq board tcm-link-show <device>` — 回读展示（16 阈值 + mask/polarity/
  debounce/width/enable + 触发模式建议提示）
- `daq board tcm-link-config <device>` — 写配置，选项：
  `--mask`、`--polarity`、`--thr`（1 值广播或 16 个逗号分隔值，仿
  sipm_trigger_setup.py）、`--debounce`、`--width`、`--enable/--disable`
- `presentation/console/printers.py` 增加对应打印函数

### B4. 采集侧联动（Trigger_model=9）

- `daq board config --trigger-mode 9` 现在可用（B1/B2 放行）
- 文档提示：TCM 链路联调时 `--trigger-position 0~10`（实测 D≈397ns，
  公式 `TP ≤ 64 - D/8ns`，见 ADC 测试指南 §5）
- 不新增采集命令；多板采集配合 TCM 广播触发按现有 timestamp 聚合路径工作

## 5. 阶段 C（选做）：TCM 板触发联动配置（FDU-TCM 0x20~0x25）

> **前提条件**：TCM v2 固件（`5550276`）先通过板级联调验证（TCM 仓库测试
> 指南中的单板/联调用例全部通过）后才启动本阶段；避免基于未验证固件开发。

| 地址 | 内容 |
| --- | --- |
| `0x20` | TRG_CTRL（bit0 使能，bit1 清 sticky） |
| `0x21` | TRG_IN_MASK（8 路参与掩码） |
| `0x22` | 宽脉冲宽度（20M 周期，默认 32） |
| `0x23` | 去抖（20M 周期，默认 20） |
| `0x24` | TRG_STATUS（sticky/pending/宽脉冲输出中） |
| `0x25` | TRG_CHAN（最近触发通道掩码） |

- `domain/` 增加 TCM 设备模型（profile 已有 `tcm:` 段：ip/rbcp_port）
- 新命令组 `daq tcm show / config`（或并入 `daq board` 前缀区分？——建议
  独立 `daq tcm`，语义清晰）
- 配置模型 `config_models.py` 增加 TCM 选项

## 6. 阶段 D：文档与发布

- `docs/firmware-compatibility.md`：28B 帧格式、0x45~0x6C、0x20~0x25、
  `Trigger_model=9`、Δfine 语义更新
- `docs/usage.md`：两个新命令 + TCM 链路联调流程（含 TP 标定提示）
- `README.md`：命令列表随新命令同步更新（现有列表会过期）
- `profiles/example.yaml` / 模板：可选 `defaults.tcm_link` 配置段（阈值/掩码/
  极性默认值）
- `CLAUDE.md`：命令表、固件契约段更新
- 版本：`pyproject.toml` + `__init__.py` → 0.2.0；`CHANGELOG.md` 记录
- 发布：`build_release.ps1` → tag v0.2.0 → GitHub Release（流程不变）

## 7. 关键设计决策

| # | 决策 | 理由 |
| --- | --- | --- |
| D1 | 帧版本按 **byte 19** 判别（0=20B 头，1=28B 头） | 固件文档明确定义（`>=1 时 byte 20..27 有效`），与 `delta_fine_timestamp.md` §9 一致；旧帧 byte 19 恒为 0，判别无歧义 |
| D2 | 原生解码器（A1/A2）与 vendor 脚本（A0）**统一按 byte 19 做 version 判别**，都支持 v0/v1 双版本；与上游（无条件 28B）的差异以注释标注 | 过渡期新旧固件可能混用（TCM 触发链路逐步烧录），无条件 28B 会让旧板帧被误解析；固件侧文档 §9 本身建议按 byte 19 区分。代价是每次同步上游时多一个 ~10 行的手动合并点 |
| D3 | 聚合格式升级为 v2（BOARD chunk 加 2×u32 fine 字段），读取端兼容 v1 | fine 字段在聚合时是有效数据，不应丢失；版本号字段已存在，升级无破坏 |
| D4 | TCM 链路用独立子命令 `tcm-link-show` / `tcm-link-config` | `daq board config` 已有 4 个 step 开关 + 8 个选项，再加 6 个会失控；独立命令职责清晰 |
| D5 | `--thr` 支持单值广播或 16 值列表 | 与 sipm_trigger_setup.py 行为一致（测试脚本已获认可） |

## 8. 风险与兼容性

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| 旧固件板子 + 新软件采集（过渡期混用） | live 采集解析错乱 | 所有实时/离线路径（A2/A4/vendor）统一 byte 19 判别，新旧固件帧均可解析 |
| 老 capture 文件 / 老 .aggr 文件不可读 | 历史数据丢失 | 原生解码双版本 + 聚合 v1 兼容读取 |
| vendor 脚本与上游漂移 | 后续同步困难 | 同步后 diff 控制在几十行，CHANGELOG 记录同步基线提交 |
| 28B 帧长的 mode 1（28+4096）超大帧 | 无，现有缓冲逻辑按 total_bytes 分配 | 不涉及 |
| TCM 链路配置写错（阈值方向反） | M21 持续脉冲 | 配置后强制回读展示 + 文档提示极性方向（正方向阈值在基线上方） |

## 9. 测试策略

1. **硬件无关单测**（本版本核心验证）：构造字节 fixture 覆盖 28B 各 mode、
   版本判别、回绕；聚合 v1/v2 双向
2. **回归**：现有 6 个测试文件全绿（旧 20B fixture 保留）
3. **板级联调清单**（文档产出，不自动执行）：
   - ADC 固件 `64c2885+`，单板 `tcm-link-config` 配置 → 回读一致
   - `Trigger_model=9` + 信号发生器注入 MOSI 宽脉冲 → 事件帧 `FF FE 01 09`，
     fine 字段非零且 Δfine 稳定（参考 ADC 测试指南 4.7~4.9）
   - TCM 板 v2 + 多板：`daq acquire multi` 按 timestamp 聚合，complete 率正常

## 10. 实施顺序（建议）

```
阶段 A: A0（vendor 同步 + 回归）→ A1/A2（协议 + 解码）→ A3（聚合 v2）
        → A4（采集链路）→ A5（测试）         [可独立提交、独立验证]
阶段 B: B1（adapter）→ B2（service）→ B3（CLI + printer）→ B4（mode 9）
阶段 C: 选做，在 A/B 全部绿之后
阶段 D: 文档 + 版本 + 发布
```

每步完成后 `python -m pytest` 全绿再进入下一步；A 阶段完成即是一个可发布的
中间状态（老数据兼容 + 新帧支持）。
