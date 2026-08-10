# GUI 板卡 tab：mode 9 寄存器全量面板计划

> 状态：计划文档，尚未开始实现。落笔时间：2026-08-10。
> 背景：现有「TCM 触发 (mode 9)」区是一键配置（只暴露 position/send-mode），
> 用户要求把所有涉及的寄存器全部拿出来逐项可设。

## 1. 寄存器清单（mode 9 全量）

按功能分三组，面板上每组一个 LabelFrame：

### A. 触发源组

| 寄存器 | 名称 | 格式 | 备注 |
| --- | --- | --- | --- |
| `0x10` | Trigger_model | 8bit | mode 9 = TCM 触发 |
| `0x19` | Trigger_position | 8bit | 建议 0~10（链路延迟 ~397ns） |
| `0x06` bit1 | Time_clean | 1bit | 时间戳清零使能 |
| `0x06` bit2 | EXT_Trigger_en | 1bit | **mode 9 必须关**（否则覆盖触发源） |
| `0x1B~0x1D` | SEND_START_DELAY | 24bit | 发送起始延迟 |

### B. 过阈链路组（TCM，0x45~0x6C）

| 寄存器 | 名称 | 格式 | 备注 |
| --- | --- | --- | --- |
| `0x45~0x64` | 16 路过阈阈值 | 16×16bit | 高字节在前，12-bit 有效 |
| `0x65~0x66` | mask[15:0] | 16bit | bitN=chN 参与 |
| `0x67~0x68` | polarity[15:0] | 16bit | 0=正(adc>thr)，1=负(adc<thr) |
| `0x69~0x6A` | debounce | 16bit | 5ns 单位，默认 200=1µs |
| `0x6B` | enable | 8bit | bit0=过阈脉冲输出使能 |
| `0x6C` | pulse_width | 8bit | 5ns 单位，默认 20=100ns |

### C. 数据格式组

| 寄存器 | 名称 | 格式 | 备注 |
| --- | --- | --- | --- |
| `0x42` | Send_mode | 8bit | 0~3 数据格式 |
| `0x43` | Integ_pre_samples | 8bit | 特征积分预采样 |
| `0x44` | Integ_post_samples | 8bit | 特征积分后采样 |

### 明确不放（写进面板说明，防止误解）

- `0x11~0x18` 主触发阈值：只用于内部触发模式 1~6，**mode 9 不使用**
- `0x20~0x3F` hit 阈值 + `0x40/0x41` hit 极性：数据侧通道选择（决定 hit_mask），
  与触发源无关，不属于 mode 9 面板（mode 1 全通道场景也不需要）

## 2. 交互设计

```
┌─ TCM 触发 (mode 9) 寄存器 ────────────────────────────────────────┐
│ A. 触发源                                                         │
│   0x10 Trigger_model      [9]     0x19 Trigger_position  [5]      │
│   0x06 Time_clean         ☐       0x06 EXT_Trigger_en    ☐ (mode9 必须关) │
│   0x1B~1D SEND_START_DELAY [0]                                    │
│ B. 过阈链路 (TCM)                                                 │
│   0x45~64 阈值（2 列 × 8 行 grid）:  ch00[____] ch08[____]        │
│                                     ch01[____] ch09[____] ...     │
│   0x65~66 mask [0x0003]   0x67~68 polarity [0x0000]               │
│   0x69~6A debounce [200]  0x6C pulse_width [20]  0x6B enable ☑    │
│ C. 数据格式                                                       │
│   0x42 send_mode [__]  0x43 integ_pre [__]  0x44 integ_post [__]  │
│                                                                   │
│ [应用全部并回读验证]  [回读刷新]                                  │
└───────────────────────────────────────────────────────────────────┘
```

- **应用全部**：读面板全部字段 → 按组调 service → 各组回读验证 → 结果显示
  每组写入值与回读值
- **回读刷新**：读 trigger config + tcm-link config + tcp-mode2 config →
  把当前值填回面板（改字段前先点刷新，避免覆盖未读到的值）
- 面板始终显示完整配置（不做"部分写"diff），应用时全量写——与 CLI
  `tcm-link-config` 的全量写语义一致，行为可预期
- EXT_Trigger_en 默认不勾 + 灰色提示文字"mode 9 下必须关闭"

## 3. 与现有 UI 的关系（关键决策）

当前板卡 tab 已有「TCM 触发链路」表单（mask/polarity/thr/debounce/width/
enable 六个字段），与面板 B 组**字段重复**。两个方案：

| 方案 | 说明 |
| --- | --- |
| **A. 合并（建议）** | 删掉旧「TCM 触发链路」表单，字段并入 mode 9 面板 B 组。理由：0x45~0x6C 的配置场景就是为触发联动服务，两处重复维护会漂移。tcm-link 与触发模式独立这个事实仍由 CLI `tcm-link-show/config` 覆盖。 |
| B. 并存 | 旧表单保留（可独立配置 tcm-link 而不动触发模式），面板只加触发源组 + 数据组，B 组引用旧表单。UI 重复但语义分离。 |

建议 A；若用户实际有"非 mode 9 场景单独配 tcm-link"的需求选 B。

## 4. 代码改动

| 文件 | 改动 |
| --- | --- |
| `application/board_service.py` | 增加 `write_registers(device_name, profile_path, address, data)` 透传 adapter（现只有 read；0x43/0x44 行需要；顺带为将来 CLI reg-write 留口） |
| `presentation/gui/formatting.py` | 纯函数：`mode9_readback_to_values(...)`（回读结果→表单值映射）、`mode9_values_to_params(...)`（表单→各组 service 参数）；可单测 |
| `presentation/gui/boards_tab.py` | 重构 mode 9 区为全量面板；按方案 A 移除旧 TCM 链路表单；应用/刷新走 `_run_task` busy 机制 |
| `tests/test_gui_formatting.py` | 新纯函数测试（映射/解析/校验） |
| `tests/test_board_send_mode.py` | `BoardService.write_registers` 透传测试 |

## 5. 测试与验证

- 纯函数单测：回读→表单、表单→参数、非法值（thr 超 16bit、polarity 超
  0xFFFF）报错
- 服务透传测试：write_registers
- GUI 冒烟：面板构建、回读刷新填值（mock adapter 结果）、应用走
  `_run_task`；现有 141 测试回归全绿
- 板级验证（文档提示，不自动执行）：刷新显示与 `tcm-link-show` 一致；
  应用后 `trigger-show` 确认 mode 9/position/ext-trigger

## 6. 实施顺序

1. `BoardService.write_registers` + 测试
2. `formatting.py` 纯函数 + 测试
3. `boards_tab.py` 面板重构（含旧表单移除）
4. GUI 冒烟 + 全量回归
5. 文档（usage.md 板卡 tab 说明更新）
