# 2026-08-12 TCM 触发链路配置陷阱清单

调试 FDU-ADC-250M-16ch + FDU-TCM 触发链路（Trigger_model=9）期间踩过的
配置陷阱。供 daq-cli 实现（`tcm`/`board tcm-link-*` 命令）和手动寄存器
调试参考。寄存器表来源：固件 `FDU-ADC-250M-16ch`（`rtl/RBCP.v`、
`rtl/tcm_trigger_link.v`）与 `FDU-TCM`（`rtl/RBCP_REG.v`、
`rtl/tcm_trigger_controller.v`）。

## 1. ADC 板侧（tcm_trigger_link 比较器链路）

### 1.1 过阈检测只响应上升沿 —— 配置顺序陷阱

`tcm_trigger_link` 对**同步后的 hit 电平上升沿**才产生脉冲（`hit_or_sync_2 &&
!hit_or_sync_d`）。若先写好 thr/polarity 再使能，且 ADC 输入电平一直
越阈（常量穿越），则不会产生任何上升沿 → 无脉冲。

**正确顺序**：

```text
1. 写 0x6B = 0x00         先关闭 enable
2. 写 0x45~0x64 阈值       配好全部 16 通道 thr
3. 写 0x67/0x68 极性
4. 最后写 0x6B = 0x01     再使能 → 产生 hit 上升沿 → 出脉冲
```

或使能后用**翻转 polarity/thr** 的方式主动制造边沿（`daq tcm-link-config`
应保证写序，手动 RBCP 调试时最容易踩）。

### 1.2 阈值寄存器映射（固件 05602a5 修复后，实测字节序）

| 寄存器 | 内容 |
| --- | --- |
| `0x45 + 2N` / `0x46 + 2N` | chN 阈值**低/高字节**（N=0..15，**0x45 存低字节、0x46 存高字节**） |
| `0x65`/`0x66` | mask[15:0]，bitN=chN 参与（**高字节在前**：0x65=高、0x66=低） |
| `0x67`/`0x68` | polarity[15:0]，bitN=chN（0=正 adc>thr，1=负 adc<thr；**高字节在前**） |
| `0x69`/`0x6A` | debounce（5ns 单位，高字节在前） |
| `0x6B` | enable（0x01=使能） |
| `0x6C` | pulse_width（5ns 单位，M21 脉冲宽） |

> ⚠️ **2026-08-12 实测陷阱（重大）**：阈值字节序与早期文档（"高字节在前"）
> **相反**——固件 `RBCP.v` 的 `TCM_THR = {x64..x46_Reg, x45_Reg}` 拼接使
> **x45 落在 [7:0]（低字节）**、x46 落在 [15:8]（高字节），与 mask/polarity
> 的 `{x65,x66}` 风格（x65 高字节）不一致。写 `0x45=0x06, 0x46=0xA4`
> 实际得到 thr=0xA406（42054）而非 1700——负极性下恒满足 → hit 恒 1 →
> 无上升沿 → **M21 永无脉冲**。daq-cli 已按实测字节序修复（fcc29be 之后
> 的 2026-08-12 提交）；**手动 RBCP 调试时 0x45 必须写低字节**。
> 另：**hit 沿必须在 enable=1 时发生**（固件 tcm_trigger_link.v 行 173），
> 制造测试沿的顺序：写 thr（不满足）→ enable → 翻转 thr（满足）→ 出脉冲。
>
> 历史坑：修复前固件拼接反转（ch0 在 MSB），daq-cli 按反转映射
> （`0x63-2N`）读写才与硬件一致；固件修复为 `0x45+2N` 后必须改回。
> 详见 `2026-08-12_tcm-thr-mapping-check.md`。

### 1.3 Trigger_model 与主触发阈值

| 模式 | 含义 |
| --- | --- |
| `Trigger_model=1` | 正沿内部触发 |
| `Trigger_model=2` | 负沿内部触发（旧固件 1/2 行为与文档相反，已修复） |
| `Trigger_model=3~6` | 正/负脉冲对（负脉冲触发建议 3~6，仅 2 容易在
  脉冲上升沿误触发） |
| `Trigger_model=9` | TCM 触发返回（宽 MOSI 脉冲 → 板内触发事件） |

`0x11~0x18` 主触发阈值只用于 mode 1~6；**mode 9 不用**，只看
TCM 链路（`0x45+2N`）过阈 + TCM 板广播。

### 1.4 调试寄存器（监控用，避免反复烧录）

| 寄存器 | 内容 |
| --- | --- |
| `0x6D`/`0x6E` | dbg_status：[12]trig_reg [11]hit_or_sync2 [10]hit_or_sample [7:0]hit |
| `0x70`~`0x77` | dbg_bus[63:0]：pulse_cnt/debounce_cnt/fine_cnt[15:0]/trig_sticky/
  enable/trig_reg/sync2/hit_or/sync1/sync_d/trig_pulse_sync2/hit[15:0] |
| `0x78` | dbg_clear（写 bit0=1 清 trig_sticky） |
| `0x7A`/`0x7B` | dbg_ts[15:0]：[12]align_ack [11]mosi_high_cnt[0]
  [10]tcm_trigger_toggle_ts [9]tcm_present_sync [8:0]timestamp_counter |

> 读 0x7A/0x7B 判断 20M 域活性：**连读两次，timestamp_counter 递增**。
> 历史坑：曾漏接顶层 `dbg_ts` 端口导致读到恒 0（悬空拉 GND），
> 误判"20M 域死亡"——用新固件前先确认综合无
> `Synth 8-7023 ... only N given` 警告。

### 1.5 Trigger_position 实测标定（mode 9 + 四板重合，2026-08-12）

窗口为 256 采样 = **512 值**（每采样 A/B 双相，解码器输出 512 值）。
`Trigger_position`（0x19）与事件窗口内信号位置呈线性关系（实测）：

```text
信号位置(值) ≈ 404 - 2 × position
```

| position | 信号位置（512 值窗口） | 占比 |
| --- | --- | --- |
| 0 | 391~405 | 79%（偏后） |
| 40 | 311~331 | 62% |
| **74（推荐）** | **244~264** | **50%（窗口中间）** |
| 160 | 80~91 | 16%（偏前） |

**四板统一设 position=74**：信号居中，脉冲前后基线完整。dev4 信号
位置略提前 ~14 值（链路延迟略短），不影响。

> 注意：TCM 链路延迟 D≈120 采样（1.5μs）是固定的，position 只是平移
> 窗口；标定只对当前链路拓扑有效，换线缆/拓扑后需重新标定。

## 2. TCM 板侧

### 2.1 `0x20` enable 与 clear_sticky 同字节

`0x20`：bit0=enable，bit1=clear_sticky。

- **清 sticky 直接写 0x00 会把 enable 一起清掉** → 链路静默。
- 正确：先写 `0x03`（enable+clear 同时），再写 `0x01`（仅 enable）。

### 2.2 `0x25` status 位定义（易读错）

```text
bit7 bit6   bit5     bit4    bit3      bit2        bit1     bit0
 0    0    GRP_OK    0   COLLECTING  WIDE_ACTIVE  PENDING  sticky
```

- **sticky 在 bit0**（不是 bit2！bit2 是 WIDE_ACTIVE）。
- 曾把 bit2 当 sticky 误读，导致误判"TCM 未收到脉冲"。

### 2.3 mask 是 ext_trg 索引，不是板卡号

ADC 板 M21 接 TCM 板的 **ext_trg3** → TCM `0x21` mask 应写 **0x08**
（bit3），不是 0x01。TRG_CHAN（`0x26`）读回 0x08 为正常。

### 2.4 `0x18` align busy 卡住阻塞触发广播

`0x18`：bit0=align_start，bit1=align_clear。

- align 等 ack 超时（100ms）后停在 ST_CLEAR，**busy 保持=1**，
  阻塞后续触发广播。
- 手动触发前先写 `0x18=0x02`（clear）→ `0x18=0x00`。
- `0x19`：bit0=ALIGN_BUSY bit1=align_done_sticky bit2=align_timeout_sticky
  bit3=ALIGN_DONE bit4=ALIGN_TIMEOUT。

### 2.5 align ack 调试寄存器

| 寄存器 | 内容 |
| --- | --- |
| `0x1A` | ALIGN_ONLINE_MASK（锁存的在线板掩码） |
| `0x1B` | ALIGN_ACK_MASK（已回 ack 的板） |
| `0x1C` | ALIGN_MISSING_ACK_MASK（缺 ack 的板） |

## 3. 已知未决问题（2026-08-12 实测）

- online=0x0F（DCM0~3 在线），但 align 后 ack_mask=0x04——
  **仅 DCM2 的 MISO ack 被 TCM 收到**，DCM0/1/3（含 IP14=DCM3）
  缺失。IP14 侧 dbg_ts align_ack=1（已置位），说明 ADC 板固件/20M 域
  正常，问题在 MISO 回传物理链路（线缆/连接器/差分对），待排查。
- 处理顺序建议：先确认线缆 DCM3 口 MISO 对，再接示波器对比
  DCM2/DCM3 两口的 MISO 波形。
