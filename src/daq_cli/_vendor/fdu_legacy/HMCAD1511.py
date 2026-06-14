#!/usr/bin/python           
# This is spi_3wire.py file
# author: xiyangwang@ihep.ac.cn
# 2024-11-26 created
#NEW 20250515
from time import sleep
import lib
from lib import rbcp
from lib import spi_3wire
HMCAD1511 = spi_3wire.spi()



def ADC_SELECT(adc_name):
    # 创建 Rbcp 实例
    self = rbcp.Rbcp()
    
    # 定义 ADC 选择的位掩码
    adc_masks = {
        'ADCA': 0b0001,
        'ADCB': 0b0010,
        'ADCC': 0b0100,
        'ADCD': 0b1000,
    }
    
    # 检查输入是否有效
    if adc_name not in adc_masks:
        print(f"Invalid ADC name: {adc_name}. Please choose from {list(adc_masks.keys())}.")
        return
    sleep(0.2)
    # 设置打开指定的 ADC
    self.write(0x0F, bytes([adc_masks[adc_name]]))
    sleep(0.2)
    # 读取状态
    temp = self.read(0x0F, 1)
    
    # 输出读取到的状态，以二进制格式显示，补齐前导零
    print(f"{adc_name} SET Complete", format(temp[0], '04b'))  # 输出4位二进制，前导零

def SET_ADCA_HMCAD1511():

    # 1. 复位芯片
    HMCAD1511.write_addr16_data8(0x000001)  # 寄存器地址0x00，数据0x0001
    
    # 2. 进入电源下电模式
    HMCAD1511.write_addr16_data8(0x0F0200)  # PD寄存器
    
    # 3. 配置四通道模式 + 时钟分频 默认时钟频率为640MHz
    # 时钟频率为160MHz，因此配置四通道，分频系数为1  该寄存器值：0204 
    # 时钟频率为320MHz，因此配置二通道，分频系数为2  该寄存器值：0102 
    # 时钟频率为640MHz，因此配置单通道，分频系数为4  该寄存器值：0001 

    HMCAD1511.write_addr16_data8(0x310204)  # channel_num=100b, clk_divide=100b
    
    # 4. 输入选择配置
    #PCB #CH1 #CH2 #CH3 #CH4
    #SET  10   08    04   02
    
    #单通道模式下，从通道4输入(PCB上为通道1) 设置3A、3B为 1010
    #单通道模式下，从通道3输入(PCB上为通道2) 设置3A、3B为 0808
    #单通道模式下，从通道2输入(PCB上为通道3) 设置3A、3B为 0404
    #单通道模式下，从通道1输入(PCB上为通道4) 设置3A、3B为 0202
    #双通道模式下，从通道4输入(PCB上为通道1) 设置3A 1010  从通道3输入(PCB上为通道2) 设置3B 0808
    #双通道模式下，从通道2输入(PCB上为通道3) 设置3A 0404  从通道2输入(PCB上为通道4) 设置3B 0202

    #四通下默认对应PCB上通道设置 3A 0810 ; 3B 0204
    HMCAD1511.write_addr16_data8(0x3A0810)  # ADC1选择IP1/IN1 # ADC2选择IP2/IN2
    HMCAD1511.write_addr16_data8(0x3B0204)  # ADC3选择IP3/IN3 # ADC4选择IP4/IN4
    HMCAD1511.write_addr16_data8(0x24007F)  # 输出反相设置
    
    # 5. 增益配置
    HMCAD1511.write_addr16_data8(0x330000)  # ADC1粗调增益1x
    HMCAD1511.write_addr16_data8(0x2A0000)  # 1倍增益； 2倍增益(2222) 5倍增益(5555) 10倍增益(7777)
    
    # 6. LVDS配置
    HMCAD1511.write_addr16_data8(0x110000)  # LVDS驱动强度默认；
    HMCAD1511.write_addr16_data8(0x121555)  # LVDS默认不启动终端电阻；
    # HMCAD1511.write_addr16_data8(0x3000FF)  # 时钟驱动设置；
    HMCAD1511.write_addr16_data8(0x530001)  # 既不延时也不推迟(0000)；  延时(0020)提前(0010) ; 12bit(0001) 8bit(0000)
    HMCAD1511.write_addr16_data8(0x420020)  # 时钟相位90度(0040)；      270度(0000) 180度(0020) 0度(0050)

    # 7. 输出测试模式
    HMCAD1511.write_addr16_data8(0x261FAA)  # 用户设定值1
    HMCAD1511.write_addr16_data8(0x270A00)  # 用户设定值2
    # HMCAD1511.write_addr16_data8(0x250040)  # 自增加模式；  用户设定值跳跃(0020)  单一用户设定值(0010)
    # HMCAD1511.write_addr16_data8(0x450000)  # 不适用预设模式；      预设模式1(0001) 预设模式2(0002)    
    # HMCAD1511.read_addr16_data8 (0x260000)
    # 8. 激活芯片
    HMCAD1511.write_addr16_data8(0x0F0000)  # 退出电源下电

def SET_ADCB_HMCAD1511():

    # 1. 复位芯片
    HMCAD1511.write_addr16_data8(0x000001)  # 寄存器地址0x00，数据0x0001
    
    # 2. 进入电源下电模式
    HMCAD1511.write_addr16_data8(0x0F0200)  # PD寄存器
    
    # 3. 配置四通道模式 + 时钟分频 默认时钟频率为640MHz
    # 时钟频率为160MHz，因此配置四通道，分频系数为1  该寄存器值：0204 00(分频值) 04(通道数)
    # 时钟频率为320MHz，因此配置二通道，分频系数为2  该寄存器值：0102 
    # 时钟频率为640MHz，因此配置单通道，分频系数为4  该寄存器值：0001 
    HMCAD1511.write_addr16_data8(0x310204 )  # channel_num=100b, clk_divide=100b
    
    # 4. 输入选择配置
    #PCB #CH1 #CH2 #CH3 #CH4
    #SET  10   08    04   02
    
    #单通道模式下，从通道1输入(PCB上为通道1) 设置3A、3B为 1010
    #单通道模式下，从通道1输入(PCB上为通道1) 设置3A、3B为 0808
    #单通道模式下，从通道1输入(PCB上为通道1) 设置3A、3B为 0404
    #单通道模式下，从通道1输入(PCB上为通道1) 设置3A、3B为 0202

    #双通道模式下，从通道1输入(PCB上为通道1) 设置3A 1010  从通道2输入(PCB上为通道2) 设置3B 0808
    #双通道模式下，从通道1输入(PCB上为通道3) 设置3A 0404  从通道2输入(PCB上为通道4) 设置3B 0202

    #四通下默认对应PCB上通道设置 3A 0810 ; 3B 0204
    HMCAD1511.write_addr16_data8(0x3A0810)  # ADC1选择IP1/IN1 # ADC2选择IP2/IN2
    HMCAD1511.write_addr16_data8(0x3B0204)  # ADC3选择IP3/IN3 # ADC4选择IP4/IN4
    HMCAD1511.write_addr16_data8(0x24007F)  # 输出反相设置24000F
    
    # 5. 增益配置
    HMCAD1511.write_addr16_data8(0x330000)  # ADC1粗调增益1x
    HMCAD1511.write_addr16_data8(0x2A0000)  # 1倍增益； 2倍增益(2222) 5倍增益(5555) 10倍增益(7777)
    
    # 6. LVDS配置
    HMCAD1511.write_addr16_data8(0x110000)  # LVDS驱动强度默认；
    HMCAD1511.write_addr16_data8(0x121555)  # LVDS默认不启动终端电阻；
    HMCAD1511.write_addr16_data8(0x530001)  # 既不延时也不推迟(0000)；  延时(0020)提前(0010)
    HMCAD1511.write_addr16_data8(0x420020)  # 时钟相位90度(0040)；      270度(0000) 180度(0020) 0度(0050)

    # 7. 输出测试模式
    HMCAD1511.write_addr16_data8(0x261F00)  # 用户设定值1
    HMCAD1511.write_addr16_data8(0x270A00)  # 用户设定值2
    # HMCAD1511.write_addr16_data8(0x250040)  # 自增加模式；  用户设定值跳跃(0020)  单一用户设定值(0010)
    # HMCAD1511.write_addr16_data8(0x450000)  # 不适用预设模式；      预设模式1(0001) 预设模式2(0002)    

    # 8. 激活芯片
    HMCAD1511.write_addr16_data8(0x0F0000)  # 退出电源下电

def SET_ADCC_HMCAD1511():

    # 1. 复位芯片
    HMCAD1511.write_addr16_data8(0x000001)  # 寄存器地址0x00，数据0x0001
    
    # 2. 进入电源下电模式
    HMCAD1511.write_addr16_data8(0x0F0200)  # PD寄存器
    
    # 3. 配置四通道模式 + 时钟分频 默认时钟频率为640MHz
    # 时钟频率为160MHz，因此配置四通道，分频系数为1  该寄存器值：0204 00(分频值) 04(通道数)
    # 时钟频率为320MHz，因此配置二通道，分频系数为2  该寄存器值：0102 
    # 时钟频率为640MHz，因此配置单通道，分频系数为4  该寄存器值：0001 
    HMCAD1511.write_addr16_data8(0x310204 )  # channel_num=100b, clk_divide=100b
    
    # 4. 输入选择配置
    #PCB #CH1 #CH2 #CH3 #CH4
    #SET  10   08    04   02
    
    #单通道模式下，从通道1输入(PCB上为通道1) 设置3A、3B为 1010
    #单通道模式下，从通道1输入(PCB上为通道1) 设置3A、3B为 0808
    #单通道模式下，从通道1输入(PCB上为通道1) 设置3A、3B为 0404
    #单通道模式下，从通道1输入(PCB上为通道1) 设置3A、3B为 0202

    #双通道模式下，从通道1输入(PCB上为通道1) 设置3A 1010  从通道2输入(PCB上为通道2) 设置3B 0808
    #双通道模式下，从通道1输入(PCB上为通道3) 设置3A 0404  从通道2输入(PCB上为通道4) 设置3B 0202

    #四通下默认对应PCB上通道设置 3A 0810 ; 3B 0204
    HMCAD1511.write_addr16_data8(0x3A0810)  # ADC1选择IP1/IN1 # ADC2选择IP2/IN2
    HMCAD1511.write_addr16_data8(0x3B0204)  # ADC3选择IP3/IN3 # ADC4选择IP4/IN4
    HMCAD1511.write_addr16_data8(0x24007F)  # 输出反相设置24000F
    
    # 5. 增益配置
    HMCAD1511.write_addr16_data8(0x330000)  # ADC1粗调增益1x
    HMCAD1511.write_addr16_data8(0x2A0000)  # 1倍增益； 2倍增益(2222) 5倍增益(5555) 10倍增益(7777)
    
    # 6. LVDS配置
    HMCAD1511.write_addr16_data8(0x110000)  # LVDS驱动强度默认；
    HMCAD1511.write_addr16_data8(0x121555)  # LVDS默认不启动终端电阻；
    HMCAD1511.write_addr16_data8(0x530001)  # 既不延时也不推迟(0000)；  延时(0020)提前(0010)
    HMCAD1511.write_addr16_data8(0x420020)  # 时钟相位90度(0040)；      270度(0000) 180度(0020) 0度(0050)

    # 7. 输出测试模式
    HMCAD1511.write_addr16_data8(0x261F00)  # 用户设定值1
    HMCAD1511.write_addr16_data8(0x270A00)  # 用户设定值2
    # HMCAD1511.write_addr16_data8(0x250040)  # 自增加模式；  用户设定值跳跃(0020)  单一用户设定值(0010)
    # HMCAD1511.write_addr16_data8(0x450000)  # 不适用预设模式；      预设模式1(0001) 预设模式2(0002)    

    # 8. 激活芯片
    HMCAD1511.write_addr16_data8(0x0F0000)  # 退出电源下电

def SET_ADCD_HMCAD1511():

    # 1. 复位芯片
    HMCAD1511.write_addr16_data8(0x000001)  # 寄存器地址0x00，数据0x0001
    
    # 2. 进入电源下电模式
    HMCAD1511.write_addr16_data8(0x0F0200)  # PD寄存器
    
    # 3. 配置四通道模式 + 时钟分频 默认时钟频率为640MHz
    # 时钟频率为160MHz，因此配置四通道，分频系数为1  该寄存器值：0204 00(分频值) 04(通道数)
    # 时钟频率为320MHz，因此配置二通道，分频系数为2  该寄存器值：0102 
    # 时钟频率为640MHz，因此配置单通道，分频系数为4  该寄存器值：0001 
    HMCAD1511.write_addr16_data8(0x310204 )  # channel_num=100b, clk_divide=100b
    
    # 4. 输入选择配置
    #PCB #CH1 #CH2 #CH3 #CH4
    #SET  10   08    04   02
    
    #单通道模式下，从通道1输入(PCB上为通道1) 设置3A、3B为 1010
    #单通道模式下，从通道1输入(PCB上为通道1) 设置3A、3B为 0808
    #单通道模式下，从通道1输入(PCB上为通道1) 设置3A、3B为 0404
    #单通道模式下，从通道1输入(PCB上为通道1) 设置3A、3B为 0202

    #双通道模式下，从通道1输入(PCB上为通道1) 设置3A 1010  从通道2输入(PCB上为通道2) 设置3B 0808
    #双通道模式下，从通道1输入(PCB上为通道3) 设置3A 0404  从通道2输入(PCB上为通道4) 设置3B 0202

    #四通下默认对应PCB上通道设置 3A 0810 ; 3B 0204
    HMCAD1511.write_addr16_data8(0x3A0810)  # ADC1选择IP1/IN1 # ADC2选择IP2/IN2
    HMCAD1511.write_addr16_data8(0x3B0204)  # ADC3选择IP3/IN3 # ADC4选择IP4/IN4
    HMCAD1511.write_addr16_data8(0x24007F)  # 输出反相设置24000F
    
    # 5. 增益配置
    HMCAD1511.write_addr16_data8(0x330000)  # ADC1粗调增益1x
    HMCAD1511.write_addr16_data8(0x2A0000)  # 1倍增益； 2倍增益(2222) 5倍增益(5555) 10倍增益(7777)
    
    # 6. LVDS配置
    HMCAD1511.write_addr16_data8(0x110000)  # LVDS驱动强度默认；
    HMCAD1511.write_addr16_data8(0x121555)  # LVDS默认不启动终端电阻；
    HMCAD1511.write_addr16_data8(0x530001)  # 既不延时也不推迟(0000)；  延时(0020)提前(0010)
    HMCAD1511.write_addr16_data8(0x420020)  # 时钟相位90度(0040)；      270度(0000) 180度(0020) 0度(0050)

    # 7. 输出测试模式
    HMCAD1511.write_addr16_data8(0x261F00)  # 用户设定值1
    HMCAD1511.write_addr16_data8(0x270A00)  # 用户设定值2
    # HMCAD1511.write_addr16_data8(0x250040)  # 自增加模式；  用户设定值跳跃(0020)  单一用户设定值(0010)
    # HMCAD1511.write_addr16_data8(0x450000)  # 不适用预设模式；      预设模式1(0001) 预设模式2(0002)    

    # 8. 激活芯片
    HMCAD1511.write_addr16_data8(0x0F0000)  # 退出电源下电
# if __name__ == "__main__":
#     # 执行ADC配置
#      while True:
#         ADC_SELECT('ADCA')
#         # SET_ADCA_HMCAD1511()
#         # 目前读取函数无法正常使用
#         # 验证配置（示例读取寄存器0x31）
#         # reg_value = HMCAD1511.read_addr16_data8(0x26)
#         HMCAD1511.write_addr16_data8(0x0F0200)  # PD寄存器
#         # print(f"Register 0x31 value: 0x{reg_value:04X}")