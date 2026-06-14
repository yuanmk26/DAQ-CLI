import time
import lib
from lib import rbcp

I2C_CTR_EN      = 0b10000000 # I2C core enable bit
I2C_CTR_IEN     = 0b01000000 # I2C core interrupt enable bit.

I2C_TXR_WR      = 0b00000000 # writing to slave
I2C_TXR_RD      = 0b00000001 # reading from slave

I2C_CR_STA      = 0b10000000 # generate (repeated) start condition
I2C_CR_STO      = 0b01000000 # generate stop condition
I2C_CR_RD       = 0b00100000 # read from slave
I2C_CR_WR       = 0b00010000 # write to slave
I2C_CR_NACK     = 0b00001000 # when a receiver, sent ACK (ACK = '0') or NACK (ACK = '1')
I2C_CR_IACK     = 0b00000001 # Interrupt acknowledge. When set, clears a pending interrupt.

I2C_SR_NORXACK  = 0b10000000 # No acknowledge received from slave.
I2C_SR_BUSY     = 0b01000000 # I2C bus busy
I2C_SR_AL       = 0b00100000 # Arbitration lost
I2C_SR_TIP      = 0b00000010 # Transfer in progress
I2C_SR_IF       = 0b00000001 # Interrupt Flag

class I2CError(Exception):
    """
    I2C Error Exception class.
    """
    pass

class i2c(object):
    """Class for communicating with an I2C device using the adafruit-pureio pure
    python smbus library, or other smbus compatible I2C interface. Allows reading
    and writing 8-bit, 16-bit, and byte array values to registers
    on the device."""
    def __init__(self, device_address, base_address = 0x200, clk_freq = 200, i2c_freq = 100, tip_timeout = 1.0):

        self.CLK_FREQ_MHZ = clk_freq # MHz
        self.I2C_FREQ_KHZ = i2c_freq # kHz
        self.I2C_TIP_TIMEOUT_SEC = tip_timeout
        self.I2C_PRER_LO_ADDR = base_address
        self.I2C_PRER_HI_ADDR = base_address + 0x1
        self.I2C_CTR_ADDR     = base_address + 0x2
        self.I2C_RXR_ADDR     = base_address + 0x3
        self.I2C_TXR_ADDR     = base_address + 0x3
        self.I2C_CR_ADDR      = base_address + 0x4
        self.I2C_SR_ADDR      = base_address + 0x4

        """Create an instance of the I2C device at the specified address on the
        specified I2C bus number."""
        self._address = device_address
        self._rbcp = rbcp.Rbcp()

        clk_count = int(self.CLK_FREQ_MHZ*1000/5/self.I2C_FREQ_KHZ - 1) # I2C prescaler value
        prer_hi = (clk_count >> 8) & 0xFF
        prer_hi = bytes([prer_hi])
        prer_lo = clk_count & 0xFF
        prer_lo = bytes([prer_lo])
        
        if prer_lo != self._rbcp.write(self.I2C_PRER_LO_ADDR, prer_lo):
            raise IOError("UDP communication ERROR.")
            return -1

        self._rbcp.write(self.I2C_PRER_HI_ADDR, prer_hi)
        self._rbcp.write(self.I2C_CTR_ADDR, bytes([I2C_CTR_EN])) # enable

    def _wait_tip_clear(self):
        deadline = time.time() + self.I2C_TIP_TIMEOUT_SEC
        while True:
            status = self._rbcp.read(self.I2C_SR_ADDR, 1)[0]
            if not (status & I2C_SR_TIP):
                return status
            if time.time() >= deadline:
                try:
                    self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_STO|I2C_CR_IACK]))
                except Exception:
                    pass
                raise I2CError("I2C transfer timeout: TIP stuck")

        
    # write

    def write8(self, value, internal_addr_length = 0, internal_addr = 0):
        """Write an 8-bit value to the specified register."""
        value = value & 0xFF
        self._rbcp.write(self.I2C_TXR_ADDR, bytes([self._address|I2C_TXR_WR])) # present slave address, set write-bit
        self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_STA|I2C_CR_WR]))    # set command (start, write)
        self._wait_tip_clear()

        if (self._rbcp.read(self.I2C_SR_ADDR, 1)[0]) & I2C_SR_NORXACK:
            raise IOError("I2C ERROR: No acknowledge received")
            return -1

        if internal_addr_length == 1:
            internal_addr = internal_addr & 0xFF
            self._rbcp.write(self.I2C_TXR_ADDR, bytes([internal_addr]))      # present internal address
            self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_WR]))           # set command (write)
            self._wait_tip_clear()

        if internal_addr_length == 2:
            internal_high_addr = (internal_addr >> 8) & 0xFF
            self._rbcp.write(self.I2C_TXR_ADDR, bytes([internal_high_addr])) # present internal address
            self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_WR]))           # set command (write)
            self._wait_tip_clear()
            internal_low_addr = internal_addr & 0xFF
            self._rbcp.write(self.I2C_TXR_ADDR, bytes([internal_low_addr]))  # present internal address
            self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_WR]))           # set command (write)
            self._wait_tip_clear()


        self._rbcp.write(self.I2C_TXR_ADDR, bytes([value]))                  # present slave's data
        self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_WR|I2C_CR_STO]))    # set command (write, stop)
        self._wait_tip_clear()
        # if with_internal_addr:
        #     self._logger.debug("Wrote 0x%02X to register 0x%02X", value, internal_addr)
        # else:
        #     self._logger.debug("Wrote 0x%02X", value)

    def write16(self, value, internal_addr_length = 0, internal_addr = 0):
        """Write a 16-bit value to the specified register."""
        value = value & 0xFFFF

        self._rbcp.write(self.I2C_TXR_ADDR, bytes([self._address|I2C_TXR_WR])) # present slave address, set write-bit
        self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_STA|I2C_CR_WR]))    # set command (start, write)
        self._wait_tip_clear()

        if (self._rbcp.read(self.I2C_SR_ADDR, 1)[0]) & I2C_SR_NORXACK:
            raise IOError("I2C ERROR: No acknowledge received")
            return -1

        if internal_addr_length == 1:
            internal_addr = internal_addr & 0xFF
            self._rbcp.write(self.I2C_TXR_ADDR, bytes([internal_addr]))      # present internal address
            self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_WR]))           # set command (write)
            self._wait_tip_clear()

        if internal_addr_length == 2:
            internal_high_addr = (internal_addr >> 8) & 0xFF
            self._rbcp.write(self.I2C_TXR_ADDR, bytes([internal_high_addr])) # present internal address
            self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_WR]))           # set command (write)
            self._wait_tip_clear()
            internal_low_addr = internal_addr & 0xFF
            self._rbcp.write(self.I2C_TXR_ADDR, bytes([internal_low_addr]))  # present internal address
            self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_WR]))           # set command (write)
            self._wait_tip_clear()

        self._rbcp.write(self.I2C_TXR_ADDR, bytes([value & 0xFF]))           # present slave's data
        self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_WR]))               # set command (write)
        self._wait_tip_clear()

        self._rbcp.write(self.I2C_TXR_ADDR, bytes([(value >> 8) & 0xFF]))    # present slave's data
        self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_WR|I2C_CR_STO]))    # set command (write, stop)
        self._wait_tip_clear()
        # if with_internal_addr:
        #     self._logger.debug("Wrote 0x%04X to register pair 0x%02X, 0x%02X", value, internal_addr, internal_addr+1)
        # else:
        #     self._logger.debug("Wrote 0x%04X to register pair", value)

    def writeBytes(self, data, internal_addr_length = 0, internal_addr = 0):
        """
        Write to i2c Device.
        :type register: int
        :param register: Register address to write.
        :type data: bytes or bytearray or str
        :param data: Write data (Python byte like object).
        """
        data = rbcp.to_bytes(data)

        self._rbcp.write(self.I2C_TXR_ADDR, bytes([self._address|I2C_TXR_WR])) # present slave address, set write-bit
        self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_STA|I2C_CR_WR]))    # set command (start, write)
        self._wait_tip_clear()

        if (self._rbcp.read(self.I2C_SR_ADDR, 1)[0]) & I2C_SR_NORXACK:
            raise IOError("I2C ERROR: No acknowledge received")
            return -1

        if internal_addr_length == 1:
            internal_addr = internal_addr & 0xFF
            self._rbcp.write(self.I2C_TXR_ADDR, bytes([internal_addr]))      # present internal address
            self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_WR]))           # set command (write)
            self._wait_tip_clear()

        if internal_addr_length == 2:
            internal_high_addr = (internal_addr >> 8) & 0xFF
            self._rbcp.write(self.I2C_TXR_ADDR, bytes([internal_high_addr])) # present internal address
            self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_WR]))           # set command (write)
            self._wait_tip_clear()
            internal_low_addr = internal_addr & 0xFF
            self._rbcp.write(self.I2C_TXR_ADDR, bytes([internal_low_addr]))  # present internal address
            self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_WR]))           # set command (write)
            self._wait_tip_clear()

        for i in range(len(data)-1):
            self._rbcp.write(self.I2C_TXR_ADDR, bytes([data[i]]))            # present slave's data
            self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_WR]))           # set command (write)
            self._wait_tip_clear()

        self._rbcp.write(self.I2C_TXR_ADDR, bytes([data[len(data)-1]]))      # present slave's data
        self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_WR|I2C_CR_STO]))    # set command (write, stop)
        self._wait_tip_clear()
        # if with_internal_addr:
        #     self._logger.debug("Wrote to register 0x%02X: %s", internal_addr, data)
        # else:
        #     self._logger.debug("Wrote: %s", data)
        #

    ###########################################################################
    # read
    def read8(self, internal_addr_length = 0, internal_addr = 0):
        """Read an 8-bit value on the bus (without register)."""

        if internal_addr_length:
            self._rbcp.write(self.I2C_TXR_ADDR, bytes([self._address|I2C_TXR_WR])) # present slave address, set write-bit
            self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_STA|I2C_CR_WR]))    # set command (start, write)
            self._wait_tip_clear()

            if (self._rbcp.read(self.I2C_SR_ADDR, 1)[0]) & I2C_SR_NORXACK:
                raise IOError("I2C ERROR: No acknowledge received")
                return -1

            if internal_addr_length == 1:
                internal_addr = internal_addr & 0xFF
                self._rbcp.write(self.I2C_TXR_ADDR, bytes([internal_addr]))      # present internal address
                self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_WR]))           # set command (write)
                self._wait_tip_clear()

            if internal_addr_length == 2:
                internal_high_addr = (internal_addr >> 8) & 0xFF
                self._rbcp.write(self.I2C_TXR_ADDR, bytes([internal_high_addr])) # present internal address
                self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_WR]))           # set command (write)
                self._wait_tip_clear()
                # time.sleep(0.005)
                internal_low_addr = internal_addr & 0xFF
                self._rbcp.write(self.I2C_TXR_ADDR, bytes([internal_low_addr]))  # present internal address
                self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_WR]))           # set command (write)
                self._wait_tip_clear()
                # time.sleep(0.005)

        self._rbcp.write(self.I2C_TXR_ADDR, bytes([self._address|I2C_TXR_RD]))   # present slave address, set read-bit
        self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_STA|I2C_CR_WR]))        # set command (restart, write)
        self._wait_tip_clear()
        # time.sleep(0.005)

        if (self._rbcp.read(self.I2C_SR_ADDR, 1)[0]) & I2C_SR_NORXACK:
            raise IOError("I2C ERROR: No acknowledge received")
            return -1

        self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_RD|I2C_CR_NACK|I2C_CR_STO])) # set command (read, nack, stop)
        self._wait_tip_clear()
        result = self._rbcp.read(self.I2C_RXR_ADDR, 1)[0] & 0xFF
        # time.sleep(0.005)
        # if with_internal_addr:
        #     self._logger.debug("Read 0x%02X from register 0x%02X", result, internal_addr)
        # else:
        #     self._logger.debug("Read 0x%02X", result)
        return result
    def read16(self, internal_addr_length = 0, internal_addr = 0, little_endian=True):
        """Read an unsigned 16-bit value from the specified register, with the
        specified endianness (default little endian, or least significant byte
        first)."""

        if internal_addr_length:
            self._rbcp.write(self.I2C_TXR_ADDR, bytes([self._address|I2C_TXR_WR]))   # present slave address, set write-bit
            self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_STA|I2C_CR_WR]))        # set command (start, write)
            self._wait_tip_clear()

            if (self._rbcp.read(self.I2C_SR_ADDR, 1)[0]) & I2C_SR_NORXACK:
                raise IOError("I2C ERROR: No acknowledge received")
                return -1

            if internal_addr_length == 1:
                internal_addr = internal_addr & 0xFF
                self._rbcp.write(self.I2C_TXR_ADDR, bytes([internal_addr]))      # present internal address
                self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_WR]))           # set command (write)
                self._wait_tip_clear()

            if internal_addr_length == 2:
                internal_high_addr = (internal_addr >> 8) & 0xFF
                self._rbcp.write(self.I2C_TXR_ADDR, bytes([internal_high_addr])) # present internal address
                self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_WR]))           # set command (write)
                self._wait_tip_clear()
                internal_low_addr = internal_addr & 0xFF
                self._rbcp.write(self.I2C_TXR_ADDR, bytes([internal_low_addr]))  # present internal address
                self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_WR]))           # set command (write)
                self._wait_tip_clear()

        self._rbcp.write(self.I2C_TXR_ADDR, bytes([self._address|I2C_TXR_RD]))       # present slave address, set read-bit
        self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_STA|I2C_CR_WR]))            # set command (restart, write)
        self._wait_tip_clear()

        if (self._rbcp.read(self.I2C_SR_ADDR, 1)[0]) & I2C_SR_NORXACK:
            raise IOError("I2C ERROR: No acknowledge received")
            return -1

        self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_RD]))                       # set command (read)
        self._wait_tip_clear()
        temp = self._rbcp.read(self.I2C_RXR_ADDR, 1)[0]

        self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_RD|I2C_CR_NACK|I2C_CR_STO]))# set command (read, nack, stop)
        self._wait_tip_clear()
        result = ((self._rbcp.read(self.I2C_RXR_ADDR, 1)[0] << 8) + temp) & 0xFFFF
        # if with_internal_addr:
        #     self._logger.debug("Read 0x%04X from register pair 0x%02X, 0x%02X", result, internal_addr, internal_addr+1)
        # else:
        #     self._logger.debug("Read 0x%04X", result)

        # Swap bytes if using big endian because read_word_data assumes little
        # endian on ARM (little endian) systems.
        if not little_endian:
            result = ((result << 8) & 0xFF00) + (result >> 8)
        return result

    def readBytes(self, length, internal_addr_length = 0, internal_addr = 0):
        """Read a length number of bytes from the specified register.  Results
        will be returned as a bytearray."""

        if internal_addr_length:
            self._rbcp.write(self.I2C_TXR_ADDR, bytes([self._address|I2C_TXR_WR]))   # present slave address, set write-bit
            self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_STA|I2C_CR_WR]))        # set command (start, write)
            self._wait_tip_clear()

            if (self._rbcp.read(self.I2C_SR_ADDR, 1)[0]) & I2C_SR_NORXACK:
                raise IOError("I2C ERROR: No acknowledge received")
                return -1

            if internal_addr_length == 1:
                internal_addr = internal_addr & 0xFF
                self._rbcp.write(self.I2C_TXR_ADDR, bytes([internal_addr]))      # present internal address
                self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_WR]))           # set command (write)
                self._wait_tip_clear()

            if internal_addr_length == 2:
                internal_high_addr = (internal_addr >> 8) & 0xFF
                self._rbcp.write(self.I2C_TXR_ADDR, bytes([internal_high_addr])) # present internal address
                self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_WR]))           # set command (write)
                self._wait_tip_clear()
                internal_low_addr = internal_addr & 0xFF
                self._rbcp.write(self.I2C_TXR_ADDR, bytes([internal_low_addr]))  # present internal address
                self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_WR]))           # set command (write)
                self._wait_tip_clear()

        self._rbcp.write(self.I2C_TXR_ADDR, bytes([self._address|I2C_TXR_RD]))       # present slave address, set read-bit
        self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_STA|I2C_CR_WR]))            # set command (restart, write)
        self._wait_tip_clear()

        if (self._rbcp.read(self.I2C_SR_ADDR, 1)[0]) & I2C_SR_NORXACK:
            raise IOError("I2C ERROR: No acknowledge received")
            retrun -1

        result = bytes()

        for i in range(length-1):
            self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_RD]))                   # set command (read)
            self._wait_tip_clear()
            result += self._rbcp.read(self.I2C_RXR_ADDR, 1)

        self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_RD|I2C_CR_NACK|I2C_CR_STO]))# set command (start, write)
        self._wait_tip_clear()
        result += self._rbcp.read(self.I2C_RXR_ADDR, 1)
        # if with_internal_addr:
        #     self._logger.debug("Read the following from register 0x%02X: %s", internal_addr, results)
        # else:
        #     self._logger.debug("Read the following: %s", results)
        return result
    

    # write
    def swrite8(self, value, with_internal_addr = False, internal_addr = 0):
        """Write an 8-bit value to the specified register."""
        value = value & 0xFF
        internal_addr = internal_addr & 0xFF
        self._rbcp.write(self.I2C_TXR_ADDR, bytes([self._address|I2C_TXR_WR])) # present slave address, set write-bit
        self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_STA|I2C_CR_WR]))    # set command (start, write)
        self._wait_tip_clear()

        
        if (self._rbcp.read(self.I2C_SR_ADDR, 1)[0]) & I2C_SR_NORXACK:
            raise IOError("I2C ERROR: No acknowledge received")
            return -1

        if with_internal_addr:
            self._rbcp.write(self.I2C_TXR_ADDR, bytes([internal_addr]))      # present internal address
            self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_WR]))           # set command (write)
            self._wait_tip_clear()

        self._rbcp.write(self.I2C_TXR_ADDR, bytes([value]))                  # present slave's data
        self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_WR|I2C_CR_STO]))    # set command (write, stop)
        self._wait_tip_clear()
        # if with_internal_addr:
        #     self._logger.debug("Wrote 0x%02X to register 0x%02X", value, internal_addr)
        # else:
        #     self._logger.debug("Wrote 0x%02X", value)

    def swrite16(self, value, with_internal_addr = False, internal_addr = 0):
        """Write a 16-bit value to the specified register."""
        value = value & 0xFFFF
        internal_addr = internal_addr & 0xFF

        self._rbcp.write(self.I2C_TXR_ADDR, bytes([self._address|I2C_TXR_WR])) # present slave address, set write-bit
        self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_STA|I2C_CR_WR]))    # set command (start, write)
        self._wait_tip_clear()

        if (self._rbcp.read(self.I2C_SR_ADDR, 1)[0]) & I2C_SR_NORXACK:
            raise IOError("I2C ERROR: No acknowledge received")
            return -1

        if with_internal_addr:
            self._rbcp.write(self.I2C_TXR_ADDR, bytes([internal_addr]))      # present internal address
            self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_WR]))           # set command (write)
            self._wait_tip_clear()

        self._rbcp.write(self.I2C_TXR_ADDR, bytes([value & 0xFF]))           # present slave's data
        self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_WR]))               # set command (write)
        self._wait_tip_clear()

        self._rbcp.write(self.I2C_TXR_ADDR, bytes([(value >> 8) & 0xFF]))    # present slave's data
        self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_WR|I2C_CR_STO]))    # set command (write, stop)
        self._wait_tip_clear()
        # if with_internal_addr:
        #     self._logger.debug("Wrote 0x%04X to register pair 0x%02X, 0x%02X", value, internal_addr, internal_addr+1)
        # else:
        #     self._logger.debug("Wrote 0x%04X to register pair", value)

    def swriteBytes(self, data, with_internal_addr = False, internal_addr = 0):
        """
        Write to i2c Device.
        :type register: int
        :param register: Register address to write.
        :type data: bytes or bytearray or str
        :param data: Write data (Python byte like object).
        """
        data = rbcp.to_bytes(data)
        internal_addr = internal_addr & 0xFF

        self._rbcp.write(self.I2C_TXR_ADDR, bytes([self._address|I2C_TXR_WR])) # present slave address, set write-bit
        self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_STA|I2C_CR_WR]))    # set command (start, write)
        self._wait_tip_clear()

        if (self._rbcp.read(self.I2C_SR_ADDR, 1)[0]) & I2C_SR_NORXACK:
            raise IOError("I2C ERROR: No acknowledge received")
            return -1

        if with_internal_addr:
            self._rbcp.write(self.I2C_TXR_ADDR, bytes([internal_addr]))      # present internal address
            self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_WR]))           # set command (write)
            self._wait_tip_clear()

        for i in range(len(data)-1):
            self._rbcp.write(self.I2C_TXR_ADDR, bytes([data[i]]))            # present slave's data
            self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_WR]))           # set command (write)
            self._wait_tip_clear()

        self._rbcp.write(self.I2C_TXR_ADDR, bytes([data[len(data)-1]]))      # present slave's data
        self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_WR|I2C_CR_STO]))    # set command (write, stop)
        self._wait_tip_clear()
        # if with_internal_addr:
        #     self._logger.debug("Wrote to register 0x%02X: %s", internal_addr, data)
        # else:
        #     self._logger.debug("Wrote: %s", data)
        # 

    ###########################################################################
    # read
    def sread8(self, with_internal_addr = False, internal_addr = 0):
        """Read an 8-bit value on the bus (without register)."""
        internal_addr = internal_addr & 0xFF
        if with_internal_addr:
            self._rbcp.write(self.I2C_TXR_ADDR, bytes([self._address|I2C_TXR_WR])) # present slave address, set write-bit
            self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_STA|I2C_CR_WR]))    # set command (start, write)
            self._wait_tip_clear()

            if (self._rbcp.read(self.I2C_SR_ADDR, 1)[0]) & I2C_SR_NORXACK:
                raise IOError("I2C ERROR: No acknowledge received")
                return -1

            self._rbcp.write(self.I2C_TXR_ADDR, bytes([internal_addr]))          # present internal address
            self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_WR]))               # set command (write)
            self._wait_tip_clear()

        self._rbcp.write(self.I2C_TXR_ADDR, bytes([self._address|I2C_TXR_RD]))   # present slave address, set read-bit
        self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_STA|I2C_CR_WR]))        # set command (restart, write)
        self._wait_tip_clear()

        if (self._rbcp.read(self.I2C_SR_ADDR, 1)[0]) & I2C_SR_NORXACK:
            raise IOError("I2C ERROR: No acknowledge received")
            return -1

        self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_RD|I2C_CR_NACK|I2C_CR_STO])) # set command (read, nack, stop)
        self._wait_tip_clear()
        result = self._rbcp.read(self.I2C_RXR_ADDR, 1)[0] & 0xFF
        # if with_internal_addr:
        #     self._logger.debug("Read 0x%02X from register 0x%02X", result, internal_addr)
        # else:
        #     self._logger.debug("Read 0x%02X", result)
        return result

    def sread16(self, with_internal_addr = False, internal_addr = 0, little_endian=True):
        """Read an unsigned 16-bit value from the specified register, with the
        specified endianness (default little endian, or least significant byte
        first)."""
        internal_addr = internal_addr & 0xFF
        if with_internal_addr:
            self._rbcp.write(self.I2C_TXR_ADDR, bytes([self._address|I2C_TXR_WR]))   # present slave address, set write-bit
            self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_STA|I2C_CR_WR]))        # set command (start, write)
            self._wait_tip_clear()

            if (self._rbcp.read(self.I2C_SR_ADDR, 1)[0]) & I2C_SR_NORXACK:
                raise IOError("I2C ERROR: No acknowledge received")
                return -1

            self._rbcp.write(self.I2C_TXR_ADDR, bytes([internal_addr]))              # present internal address
            self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_WR]))                   # set command (write)
            self._wait_tip_clear()

        self._rbcp.write(self.I2C_TXR_ADDR, bytes([self._address|I2C_TXR_RD]))       # present slave address, set read-bit
        self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_STA|I2C_CR_WR]))            # set command (restart, write)
        self._wait_tip_clear()

        if (self._rbcp.read(self.I2C_SR_ADDR, 1)[0]) & I2C_SR_NORXACK:
            raise IOError("I2C ERROR: No acknowledge received")
            return -1

        self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_RD]))                       # set command (read)
        self._wait_tip_clear()
        temp = self._rbcp.read(self.I2C_RXR_ADDR, 1)[0] 

        self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_RD|I2C_CR_NACK|I2C_CR_STO]))# set command (read, nack, stop)
        self._wait_tip_clear()
        result = ((self._rbcp.read(self.I2C_RXR_ADDR, 1)[0] << 8) + temp) & 0xFFFF
        # if with_internal_addr:        
        #     self._logger.debug("Read 0x%04X from register pair 0x%02X, 0x%02X", result, internal_addr, internal_addr+1)
        # else:
        #     self._logger.debug("Read 0x%04X", result)

        # Swap bytes if using big endian because read_word_data assumes little
        # endian on ARM (little endian) systems.
        if not little_endian:
            result = ((result << 8) & 0xFF00) + (result >> 8)
        return result

    def sreadBytes(self, length, with_internal_addr = False, internal_addr = 0):
        """Read a length number of bytes from the specified register.  Results
        will be returned as a bytearray."""
        internal_addr = internal_addr & 0xFF
        if with_internal_addr:
            self._rbcp.write(self.I2C_TXR_ADDR, bytes([self._address|I2C_TXR_WR]))   # present slave address, set write-bit
            self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_STA|I2C_CR_WR]))        # set command (start, write)
            self._wait_tip_clear()

            if (self._rbcp.read(self.I2C_SR_ADDR, 1)[0]) & I2C_SR_NORXACK:
                raise IOError("I2C ERROR: No acknowledge received")
                return -1

            self._rbcp.write(self.I2C_TXR_ADDR, bytes([internal_addr]))              # present internal address
            self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_WR]))                   # set command (write)
            self._wait_tip_clear()

        self._rbcp.write(self.I2C_TXR_ADDR, bytes([self._address|I2C_TXR_RD]))       # present slave address, set read-bit
        self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_STA|I2C_CR_WR]))            # set command (restart, write)
        self._wait_tip_clear()

        if (self._rbcp.read(self.I2C_SR_ADDR, 1)[0]) & I2C_SR_NORXACK:
            raise IOError("I2C ERROR: No acknowledge received")
            retrun -1

        result = bytes()

        for i in range(length-1):
            self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_RD]))                   # set command (read)
            self._wait_tip_clear()
            result += self._rbcp.read(self.I2C_RXR_ADDR, 1) 

        self._rbcp.write(self.I2C_CR_ADDR, bytes([I2C_CR_RD|I2C_CR_NACK|I2C_CR_STO]))# set command (start, write)
        self._wait_tip_clear()
        result += self._rbcp.read(self.I2C_RXR_ADDR, 1) 
        # if with_internal_addr:
        #     self._logger.debug("Read the following from register 0x%02X: %s", internal_addr, results)
        # else:
        #     self._logger.debug("Read the following: %s", results)
        return result

    def register_write(self, value):
        # print("value: %2X"%value)
        temp0 = (value>>16) & 0xFF
        temp1 = (value>> 8) & 0xFF
        temp2 = (value>> 0) & 0xFF
        self.swrite8(temp0, True, 0x01)
        time.sleep(0.001)
        self.swrite8(temp2, True, temp1)
        time.sleep(0.001)
        #print("temp0: %02X"%temp0)
        #print("temp1: %02X"%temp1)
        #print("temp2: %02X"%temp2)

    def register_write1(self, value):
        # print("value: %2X"%value)
        temp0 = 0x0100|(value>>16) & 0xFF
        temp1 = value & 0xFFFF
        self.swrite16(temp0, False, 0)
        time.sleep(0.001)
        self.swrite16(temp1, False, 0)
        time.sleep(0.001)
        #print("temp0: %02X"%temp0)
        #print("temp1: %02X"%temp1)
        #print("temp2: %02X"%temp2)
           
    def register_write2(self, value):
        temp0 = (value>>8) & 0xFF
        temp1 = (value>>0) & 0xFF
        time.sleep(0.001)
        self.swrite8(temp1, True, temp0)
        time.sleep(0.001)
        #print("temp0: %02X"%temp0)
        #print("temp1: %02X"%temp1)
        #print("temp2: %02X"%temp2)

    def register_read(self,value):
        temp0 = (value>>16) & 0xFF
        temp1 = (value>> 8) & 0xFF
        self.swrite8(temp0, False, 0)
        time.sleep(0.005)
        self.swrite8(temp1, False, 0)
        time.sleep(0.005)
        result = self.read8(2, value)
        time.sleep(0.005)
        return result



    def register_read2(self,value):
        temp0 = value & 0xFF
        self.swrite8(temp0, False, 0)
        time.sleep(0.005)
        result = self.read8()
        time.sleep(0.005)
        return result
