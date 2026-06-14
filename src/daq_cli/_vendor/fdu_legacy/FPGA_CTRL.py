import lib
from lib import rbcp



class FPGAControl:
    def __init__(self):
        self.rbcp = rbcp.Rbcp()

    def set_threshold(self, *thresholds):
        if len(thresholds) != 4:
            print("Error: Incorrect number of threshold values provided")
            return
        for i, threshold in enumerate(thresholds):
            reg_addr = 0x11 + i*2
            high_byte = (threshold >> 8) & 0xFF
            low_byte = threshold & 0xFF
            self.rbcp.write(reg_addr, bytes([high_byte]))
            self.rbcp.write(reg_addr + 1, bytes([low_byte]))

    def set_hit_thresholds(self, thresholds):
        if len(thresholds) != 16:
            print("Error: Incorrect number of hit threshold values provided")
            return

        for i, threshold in enumerate(thresholds):
            if threshold < 0 or threshold > 0xFFFF:
                print(f"Error: Invalid hit threshold for channel {i}")
                return

        for i, threshold in enumerate(thresholds):
            reg_addr = 0x20 + i*2
            high_byte = (threshold >> 8) & 0xFF
            low_byte = threshold & 0xFF
            self.rbcp.write(reg_addr, bytes([high_byte]))
            self.rbcp.write(reg_addr + 1, bytes([low_byte]))

    def set_hit_polarity(self, polarities):
        if len(polarities) != 16:
            print("Error: Incorrect number of hit polarity values provided")
            return

        for i, polarity in enumerate(polarities):
            if polarity not in (0, 1):
                print(f"Error: Invalid hit polarity for channel {i}")
                return

        polarity_low = 0
        polarity_high = 0
        for i, polarity in enumerate(polarities):
            if i < 8:
                polarity_low |= (polarity & 0x1) << i
            else:
                polarity_high |= (polarity & 0x1) << (i - 8)

        self.rbcp.write(0x40, bytes([polarity_high]))
        self.rbcp.write(0x41, bytes([polarity_low]))

    def read_hit_config(self):
        thresholds = []
        for i in range(16):
            reg_addr = 0x20 + i*2
            high_byte = self.rbcp.read(reg_addr, 1)
            low_byte = self.rbcp.read(reg_addr + 1, 1)
            thresholds.append((high_byte[0] << 8) | low_byte[0])

        polarity_high = self.rbcp.read(0x40, 1)[0]
        polarity_low = self.rbcp.read(0x41, 1)[0]
        polarities = []
        for i in range(16):
            if i < 8:
                polarities.append((polarity_low >> i) & 0x1)
            else:
                polarities.append((polarity_high >> (i - 8)) & 0x1)

        return thresholds, polarities


    def ADC_SYNC(self, mode):
        if mode < 0 or mode > 8:
            print("Error: Invalid trigger mode")
            return
        self.rbcp.write(0x1A, bytes([mode]))

    def set_send_start_delay(self, value):
        if value < 0 or value > 0xFFFFFF:
            print("Error: Invalid SEND_START_DELAY value")
            return
        byte_2 = (value >> 16) & 0xFF
        byte_1 = (value >> 8) & 0xFF
        byte_0 = value & 0xFF
        self.rbcp.write(0x1B, bytes([byte_2]))
        self.rbcp.write(0x1C, bytes([byte_1]))
        self.rbcp.write(0x1D, bytes([byte_0]))

    def ext_trigger_en(self, mode):
        mode_lower = mode.lower()
        
        if mode_lower == "enable":
            current_value = self.rbcp.read(0x06, 1)[0]
            new_value = current_value | (1 << 2)
            self.rbcp.write(0x06, bytes([new_value]))
            print("EXT_Trigger_en set to 1 (enabled)")
            
        elif mode_lower == "disable":
            current_value = self.rbcp.read(0x06, 1)[0]
            new_value = current_value & ~(1 << 2)
            self.rbcp.write(0x06, bytes([new_value]))
            print("EXT_Trigger_en set to 0 (disabled)")
            
        else:
            print(f"Error: Invalid mode '{mode}'. Please use 'enable' or 'disable'")


    def timestamp_clean_en(self, mode):
        """
        控制时间戳清零使能（Timestamp_clean_en）
        
        参数:
        mode (str): "enable" 或 "disable"，不区分大小写
        
        功能:
        - enable: 将0x06寄存器的第1位（bit1）设置为1
        - disable: 将0x06寄存器的第1位（bit1）设置为0
        """
        mode_lower = mode.lower()
        
        if mode_lower == "enable":
            # 读取当前寄存器值
            current_value = self.rbcp.read(0x06, 1)[0]
            # 设置第1位为1，其他位保持不变
            new_value = current_value | (1 << 1)
            # 写回寄存器
            self.rbcp.write(0x06, bytes([new_value]))
            print("Timestamp_clean_en set to 1 (enabled)")
            
        elif mode_lower == "disable":
            # 读取当前寄存器值
            current_value = self.rbcp.read(0x06, 1)[0]
            # 设置第1位为0，其他位保持不变
            new_value = current_value & ~(1 << 1)
            # 写回寄存器
            self.rbcp.write(0x06, bytes([new_value]))
            print("Timestamp_clean_en set to 0 (disabled)")
            
        else:
            print(f"Error: Invalid mode '{mode}'. Please use 'enable' or 'disable'")


    def trigger_model(self, mode):
        if mode < 0 or mode > 8:
            print("Error: Invalid trigger mode")
            return
        self.rbcp.write(0x10, bytes([mode]))

    def trigger_postion(self, trigger_postion):
        if trigger_postion < 0 or trigger_postion > 255:
            print("Error: Invalid trigger trigger_postion")
            return
        self.rbcp.write(0x19, bytes([trigger_postion]))

    def read_trigger_info(self):
        trigger_model = self.rbcp.read(0x10, 1)
        trigger_postion = self.rbcp.read(0x19, 1)
        thresholds = []
        for i in range(4):
            reg_addr = 0x11 + i*2
            low_byte = self.rbcp.read(reg_addr + 1, 1)
            high_byte = self.rbcp.read(reg_addr, 1)
            threshold = (high_byte[0] << 8) | low_byte[0]
            thresholds.append(threshold)
        return trigger_model[0], trigger_postion[0], thresholds
    

# # 实例化FPGAControl对象
# fpga_ctrl = FPGAControl()

# # 设置阈值
# fpga_ctrl.set_threshold(2100, 2100, 3000, 3000)

# # 设置触发模式
# fpga_ctrl.trigger_model(7)

# # 读取触发信息
# trigger_model, thresholds = fpga_ctrl.read_trigger_info()
# print(f"Trigger Model: {trigger_model}")
# print(f"Thresholds: {thresholds}")
