# 2026-08-12 TCM 链路阈值映射排查报告（固件 05602a5 复测）

## 1. 背景

四板 AND 测试发现固件问题（见 FDU-ADC-250M-16ch
`docs/changes/2026-08-11/2026-08-11_tcm-link-hardware-issues.md`），
固件 `05602a5` 已修复：
- TCM_THR 拼接反转（`0x45+2N` = chN）
- crossing_fine 快照语义
- 事件窗口 64→256 采样

复测确认修复生效（阈值映射、窗口、fine 快照均正常），但出现新问题：
**TCM 链路比较器（tcm_trigger_link）看不到窄信号**。

## 2. 复测观测（四板均有相同现象）

| 观测 | 结果 |
| --- | --- |
| `Trigger_model=1`（板内自触发） | ✅ 触发正常；事件波形 ch0 min=1373（下探 573 counts） |
| ram1 数据（CLK_125M_90 域）在 mode 1 事件帧 | ✅ 可见 1373 |
| TCM 链路比较器（同 CLK_125M_90 域）thr=1700/1800/1900 | ❌ 全不触发 |
| TCM 链路 thr=2000（基线 1943 < 2000 恒穿越） | ✅ 触发 |
| TCM 链路 0xFFFF | ✅ 触发 |

## 3. 固件侧排查（仿真验证，结论：固件正常）

针对"比较器看不到信号"做了仿真验证（`tb/tcm_trigger_link_cdc_tb.v`，
真实 80M 帧周期 12.5ns + 相位扫描）：

```text
FRAME_NS=12.5 WIDTH=1: phases=26 hit_seen=25 pulse_lost=1
  hit_but_no_pulse@[]        ← 只要比较器采到信号，脉冲必出
```

- 比较器 25/26 相位能看到 1 帧宽（12.5ns）过阈信号
- 唯一丢失的 phase 0 为注入与采样沿重合的边界（数据本身未采到，非 CDC）
- **"hit 置位但无脉冲" = 0**：80M→200M 两级同步不吞 12.5ns 脉冲
- 时钟核对：CLK_125M（0°）与 CLK_125M_90（180°）posedge 与 negedge 同一时刻；
  比较器与 ram1 同域同时刻采样同一 AdcDataSum，数据切片位段逐位核对一致

**结论：固件侧（比较器/CDC/数据路径）无问题。**

## 4. 高度可疑：daq-cli legacy 反转映射未随固件同步

问题文档第 2 节明确记录：

> daq-cli 已按**有效映射**（`0x63-2N`）读写阈值（`legacy_board_adapter.py`），
> 硬件验证通过。**固件修复后**需要把 daq-cli 的映射改回文档映射
> （`0x45+2N`）——代码注释已标注位置。

固件 `05602a5` 已修复拼接（`0x45+2N` = chN），推测 daq-cli 仍在用旧反转
映射（`0x63-2N`）写阈值，导致：

```text
daq-cli 配 ch0 阈值 1700 → 实际写入 0x63/0x64（旧反转）
修复后固件读 ch0 阈值 = 0x45/0x46 = daq-cli 写的"ch15"值 = 0
→ ch0 阈值实际为 0 → 负极性 adc<0 永不成立 → 永不触发
```

**这解释了全部观测**：
- thr=1700~1900 不触发（ch0 阈值实为 0）
- thr=2000 触发（若全通道配 2000，反转后 ch0 阈值=2000 → 基线恒穿越）
- 0xFFFF 触发（全通道，反转无影响）
- 仿真正常（tb 用正确映射）

## 5. 验证步骤（区分固件/上位机）

绕过 daq-cli，用原始 RBCP 直接写 ch0 阈值：

```python
# 直接写 0x45/0x46 = 1700（0x06A4），负极性
tcm.write(0x45, bytes([0x06]))
tcm.write(0x46, bytes([0xA4]))
```

- **M21 立即出脉冲** → 固件正常，确认是 daq-cli 映射错位
- 仍无脉冲 → 固件侧继续排查（需示波器核对比较器输入）

同时检查 daq-cli 实际写入的寄存器：读回 0x45~0x64，看 ch0 位置（0x45/0x46）
的值是否为配置值。

## 6. daq-cli 侧需要做的事

1. `legacy_board_adapter.py` 的阈值映射改回文档映射（`0x45+2N` = chN）
2. 新增配置文件/版本标记，标识固件是否含 `05602a5`（避免新旧固件混用错位）
3. 回归：`daq tcm-link-config/show` 回读与写入一致

## 7. 相关文件

- 固件问题文档：`FDU-ADC-250M-16ch/docs/changes/2026-08-11/2026-08-11_tcm-link-hardware-issues.md`
- 固件修复：`FDU-ADC-250M-16ch` 提交 `05602a5`
- CDC 验证 tb：`FDU-ADC-250M-16ch/tb/tcm_trigger_link_cdc_tb.v`