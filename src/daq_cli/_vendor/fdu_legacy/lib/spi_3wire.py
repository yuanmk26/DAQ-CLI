#!/usr/bin/python           
# This is spi_3wire.py file
# author: xiyangwang@ihep.ac.cn
# 2024-11-26 created
# 2025-05-26 对该代码修改，发送8位地址与16位数据

import time
import lib
from lib import rbcp

SPI_WR_EN = 0b00000001
SPI_RD_EN = 0b00000010
SPI_WR_DIS = 0b00000000

class SPIError(Exception):
    """
    SPI Error Exception class.
    """
    pass

class spi(object):
    """Class for communicating with an SPI device using the adafruit-pureio pure
    python smbus library, or other smbus compatible SPI interface. Allows reading
    and writing 8-bit, 16-bit, and byte array values to registers
    on the device."""
    def __init__(self, clk_freq = 200, spi_freq = 2000):

        self.CLK_FREQ_MHZ = clk_freq # MHz
        self.SPI_FREQ_KHZ = spi_freq # kHz

        self.SPI_Tx0_ADDR = 0x08
        self.SPI_Tx1_ADDR = 0x09
        self.SPI_Tx2_ADDR = 0x0A
        
        self.SPI_Rx0_ADDR = 0x08
        self.SPI_Rx1_ADDR = 0x09
        self.SPI_Rx2_ADDR = 0x0D
        self.SPI_Rx3_ADDR = 0x07

        self.SPI_WR_ADDR  = 0x0C
        self.SPI_RD_ADDR  = 0x0C
        
        self.SPI_DIVIDER_ADDR    =  0x0B

        self.SPI_BUSY_ADDR         = 0x0E
        self.SPI_CFGDONE_ADDR      = 0x0E
        """Create an instance of the I2C device at the specified address on the
        specified I2C bus number."""

        self._rbcp = rbcp.Rbcp()
    
        clk_count = int(self.CLK_FREQ_MHZ * 1000 / 2 / self.SPI_FREQ_KHZ - 1)
        DIVIDER = bytes([clk_count & 0xFF])
    
        if DIVIDER != self._rbcp.write(self.SPI_DIVIDER_ADDR, DIVIDER):
            raise IOError("UDP communication ERROR")
    
    def write_reg(self, value, read_write):
        # W0 = 0b0
        # W1 = 0b0
        # W2 = 0b1 if read_write == 'read' else 0b0
        # value = (value & 0x1FFFFF) | (W2 << 23) | (W1 << 22) | (W0 << 21)
        address = (value >> 16) & 0xFF
        data_h = (value >> 8) & 0xFF
        data_l = value & 0xFF
        self._rbcp.write(self.SPI_Tx0_ADDR, bytes([address]))
        self._rbcp.write(self.SPI_Tx1_ADDR, bytes([data_h]))
        self._rbcp.write(self.SPI_Tx2_ADDR, bytes([data_l]))
        if read_write == 'write':
            #print("address:",  hex(address_l), "Write data:", hex(data))
            self._rbcp.write(self.SPI_WR_ADDR, bytes([SPI_WR_EN]))
        else:
            self._rbcp.write(self.SPI_RD_ADDR, bytes([SPI_RD_EN]))
        if self._rbcp.read(self.SPI_CFGDONE_ADDR, 1)[0] == 0:
            self._rbcp.write(self.SPI_WR_ADDR, bytes([SPI_WR_DIS]))        
    
    def write_addr16_data8(self, value):
        self.write_reg(value, 'write')
    
    def read_addr16_data8(self, value):
        self.write_reg(value, 'read')
        data_h = self._rbcp.read(self.SPI_Rx2_ADDR, 1)[0]
        data_l = self._rbcp.read(self.SPI_Rx3_ADDR, 1)[0]
        result = (data_h << 8) | data_l
        print("address:",  hex((value >> 16) & 0xFF), "read  data:", hex(result))
        return result

