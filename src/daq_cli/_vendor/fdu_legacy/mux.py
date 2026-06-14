#PCA9545

from lib import i2c

MUX_CR_UCLK     = 0b00000001 # I2C for User Clock
MUX_CR_FMC      = 0b00000010 # I2C for I2C
MUX_CR_NC       = 0b00000100 # I2C for NC
MUX_CR_EEPROM   = 0b00001000 # I2C for EEPROM
MUX_CR_SFP      = 0b00010000 # I2C for SFP
MUX_CR_HDMI     = 0b00100000 # I2C for HMDI
MUX_CR_DDR3     = 0b01000000 # I2C for DDR3
MUX_CR_SI5324   = 0b10000000 # I2C for SI5324


class mux(object):
    def __init__(self, device_address = 0x74 << 1 , base_address = 0x200, clk_freq = 200, i2c_freq = 100):
        self._i2c = i2c.i2c(device_address, base_address, clk_freq, i2c_freq)

    def enable_all(self):
        self._i2c.write8(0b11111111)

    def disable_all(self):
        self._i2c.write8(0)

# I2C for User Clock
    def enable_UCLK(self):
        temp = self._i2c.read8()
        temp |= MUX_CR_UCLK
        self._i2c.write8(temp)

    def disable_UCLK(self):
        temp = self._i2c.read8()
        temp &= ~MUX_CR_UCLK
        self._i2c.write8(temp)

# I2C for I2C
    def enable_FMC(self):
        temp = self._i2c.read8()
        temp |= MUX_CR_FMC
        self._i2c.write8(temp)

    def disable_FMC(self):
        temp = self._i2c.read8()
        temp &= ~MUX_CR_FMC
        self._i2c.write8(temp)
        
# I2C for NC
    def enable_NC(self):
        temp = self._i2c.read8()
        temp |= MUX_CR_NC
        self._i2c.write8(temp)

    def disable_NC(self):
        temp = self._i2c.read8()
        temp &= ~MUX_CR_NC
        self._i2c.write8(temp)

# I2C for EEPROM
    def enable_EEPROM(self):
        temp = self._i2c.read8()
        temp |= MUX_CR_EEPROM
        self._i2c.write8(temp)

    def disable_EEPROM(self):
        temp = self._i2c.read8()
        temp &= ~MUX_CR_EEPROM
        self._i2c.write8(temp)

# I2C for SFP
    def enable_SFP(self):
        temp = self._i2c.read8()
        temp |= MUX_CR_SFP
        self._i2c.write8(temp)

    def disable_SFP(self):
        temp = self._i2c.read8()
        temp &= ~MUX_CR_SFP
        self._i2c.write8(temp)
        
# I2C for HMDI
    def enable_HMDI(self):
        temp = self._i2c.read8()
        temp |= MUX_CR_HDMI
        self._i2c.write8(temp)

    def disable_HMDI(self):
        temp = self._i2c.read8()
        temp &= ~MUX_CR_HDMI
        self._i2c.write8(temp)

# I2C for DDR3
    def enable_DDR3(self):
        temp = self._i2c.read8()
        temp |= MUX_CR_DDR3
        self._i2c.write8(temp)

    def disable_DDR3(self):
        temp = self._i2c.read8()
        temp &= ~MUX_CR_DDR3
        self._i2c.write8(temp)

# I2C for SI5324
    def enable_SI5324(self):
        temp = self._i2c.read8()
        temp |= MUX_CR_SI5324
        self._i2c.write8(temp)

    def disable_SI5324(self):
        temp = self._i2c.read8()
        temp &= ~MUX_CR_SI5324
        self._i2c.write8(temp)
        
# I2C RD for PCA9545
    def read(self):
        temp = bin(self._i2c.read8())[2:]
        temp = temp.zfill(8)  # 填充前导零，确保二进制表示是8位
        return temp
        #print("I2C SET = ",temp )
    
#################################################################
# my_mux = mux()
# my_mux.enable_down()
# my_mux.read()