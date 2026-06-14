#!/usr/bin/python           
# This is i2c.py file
# author: zhj@ihep.ac.cn
# 2019-06-18 created
import lib
from lib import rbcp

SYSMON_BASE_ADDR = 0x100

class sysmon(object):
    def __init__(self):
        self._rbcp = rbcp.Rbcp()

    def temperature(self):
        readout_bytes = self._rbcp.read(SYSMON_BASE_ADDR+0, 2)
        temp = (readout_bytes[0] << 8) + readout_bytes[1]
        temp = (temp>>6) * 501.3743 / 1024 -273.6777
        return temp

    def vccint(self):
        readout_bytes = self._rbcp.read(SYSMON_BASE_ADDR+2, 2)
        temp = (readout_bytes[0] << 8) + readout_bytes[1]
        temp = (temp>>6) / 1024 * 3
        return temp

    def vccaux(self):
        readout_bytes = self._rbcp.read(SYSMON_BASE_ADDR+4, 2)
        temp = (readout_bytes[0] << 8) + readout_bytes[1]
        temp = (temp>>6) / 1024 * 3
        return temp

    def vpvn(self):
        readout_bytes = self._rbcp.read(SYSMON_BASE_ADDR+6, 2)
        temp = (readout_bytes[0] << 8) + readout_bytes[1]
        temp = (temp>>6) / 1024 * 3
        return temp

    def vrefp(self):
        readout_bytes = self._rbcp.read(SYSMON_BASE_ADDR+8, 2)
        temp = (readout_bytes[0] << 8) + readout_bytes[1]
        temp = (temp>>6) / 1024 * 3
        return temp

    def vrefn(self):
        readout_bytes = self._rbcp.read(SYSMON_BASE_ADDR+10, 2)
        temp = (readout_bytes[0] << 8) + readout_bytes[1]
        temp = (temp>>6) / 1024 * 3
        return temp

    def vccbram(self):
        readout_bytes = self._rbcp.read(SYSMON_BASE_ADDR+12, 2)
        temp = (readout_bytes[0] << 8) + readout_bytes[1]
        temp = (temp>>6) / 1024 * 3
        return temp

    def temperature_max(self):
        readout_bytes = self._rbcp.read(SYSMON_BASE_ADDR+0x40, 2)
        temp = (readout_bytes[0] << 8) + readout_bytes[1]
        temp = (temp>>6) * 501.3743 / 1024 -273.6777
        return temp

    def vccint_max(self):
        readout_bytes = self._rbcp.read(SYSMON_BASE_ADDR+0x42, 2)
        temp = (readout_bytes[0] << 8) + readout_bytes[1]
        temp = (temp>>6) / 1024 * 3
        return temp

    def vccaux_max(self):
        readout_bytes = self._rbcp.read(SYSMON_BASE_ADDR+0x44, 2)
        temp = (readout_bytes[0] << 8) + readout_bytes[1]
        temp = (temp>>6) / 1024 * 3
        return temp

    def vccbram_max(self):
        readout_bytes = self._rbcp.read(SYSMON_BASE_ADDR+0x46, 2)
        temp = (readout_bytes[0] << 8) + readout_bytes[1]
        temp = (temp>>6) / 1024 * 3
        return temp

    def temperature_min(self):
        readout_bytes = self._rbcp.read(SYSMON_BASE_ADDR+0x48, 2)
        temp = (readout_bytes[0] << 8) + readout_bytes[1]
        temp = (temp>>6) * 501.3743 / 1024 -273.6777
        return temp

    def vccint_min(self):
        readout_bytes = self._rbcp.read(SYSMON_BASE_ADDR+0x4A, 2)
        temp = (readout_bytes[0] << 8) + readout_bytes[1]
        temp = (temp>>6) / 1024 * 3
        return temp

    def vccaux_min(self):
        readout_bytes = self._rbcp.read(SYSMON_BASE_ADDR+0x4C, 2)
        temp = (readout_bytes[0] << 8) + readout_bytes[1]
        temp = (temp>>6) / 1024 * 3
        return temp

    def vccbram_min(self):
        readout_bytes = self._rbcp.read(SYSMON_BASE_ADDR+0x4E, 2)
        temp = (readout_bytes[0] << 8) + readout_bytes[1]
        temp = (temp>>6) / 1024 * 3
        return temp
