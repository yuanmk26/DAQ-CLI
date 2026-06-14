# -*- coding:utf-8 -*-
"""
Multi-device Configuration Program - Using Environment Variable Method
"""

import os
import importlib
import sys
from time import sleep

# Device configuration list
DEVICES = [
    {"name": "Device_1", "ip": "192.168.10.10", "port": 4660, "send_start_delay_us": 0},
    {"name": "Device_2", "ip": "192.168.10.11", "port": 4660, "send_start_delay_us": 0},
    # {"name": "Device_3", "ip": "192.168.10.12", "port": 4660, "send_start_delay_us": 400},
    # {"name": "Device_4", "ip": "192.168.10.13", "port": 4660, "send_start_delay_us": 600},
    # {"name": "Device_5", "ip": "192.168.10.14", "port": 4660, "send_start_delay_us": 800},
    # {"name": "Device_6", "ip": "192.168.10.15", "port": 4660, "send_start_delay_us": 1000},
    # {"name": "Device_7", "ip": "192.168.10.16", "port": 4660, "send_start_delay_us": 1200},
    # {"name": "Device_8", "ip": "192.168.10.17", "port": 4660, "send_start_delay_us": 1400},
    # More devices can be added
]

# USER CONFIG: keep hardware bring-up steps narrow for TCP_SENT mode2 tests.
# The default path only writes trigger and TCP mode2 registers.
CONFIG_ADC = True
CONFIG_CLOCK = True
CONFIG_TRIGGER = True
CONFIG_TCP_MODE2 = True
CONFIG_SITCP_MAC = False
CONFIG_DONE_PULSE = False

def configure_device():
    """
    Configure a single device (using IP and port from environment variables)
    This function contains all the original configuration logic
    """
    # Read current device information from environment variables
    device_ip = os.environ.get('SITCP_DEVICE_IP', '192.168.10.10')
    device_port = int(os.environ.get('SITCP_UDP_PORT', '4660'))
    device_name = os.environ.get('SITCP_DEVICE_NAME', 'Unknown_Device')
    send_start_delay_us = float(os.environ.get('SITCP_SEND_START_DELAY_US', '0'))
    
    print(f"\nConfiguring device: {device_name} ({device_ip}:{device_port})")
    print("=" * 60)
    
    # Import modules (will use IP from environment variables)
    from lib import rbcp
    from lib import sysmon
    import FPGA_CTRL
    if CONFIG_ADC or CONFIG_CLOCK:
        import mux
    if CONFIG_ADC:
        import HMCAD1511
    if CONFIG_CLOCK:
        import si5345_16ch
    
    # Create objects (will use IP from environment variables)
    self = rbcp.Rbcp(device_ip=device_ip)
    sysmon_read = sysmon.sysmon()
    trigger = FPGA_CTRL.FPGAControl()
    
    # ==================== 1. Read SiTCP Information ====================
    print("\n### SiTCP Device Information ###")

    if CONFIG_SITCP_MAC:
        # Keep this disabled during mode2-only tests to avoid unrelated writes.
        self.write(0xFFFFFF12, bytes([3]))
        self.write(0xFFFFFF13, bytes([0b00000010]))
        self.write(0xFFFFFF14, bytes([0b00000001]))
        self.write(0xFFFFFF15, bytes([0b00000001]))
        self.write(0xFFFFFF16, bytes([0b00000001]))
        self.write(0xFFFFFF17, bytes([0b00000001]))
    
    # Read IP address
    IP_Address = self.read(0xFFFFFF18, 4)
    ip_str = ".".join(str(byte) for byte in IP_Address)
    print(f"IP Address: {ip_str}")
    
    # Read MAC address
    MAC_Address = self.read(0xFFFFFF12, 6)
    mac_str = ":".join("{:02x}".format(byte) for byte in MAC_Address)
    print(f"MAC Address: {mac_str}")
    
    # Read TCP port
    TCP_Port = self.read(0xFFFFFF1C, 2)
    print(f"TCP Port: {TCP_Port[0]*256 + TCP_Port[1]}")
    
    # Read RBCP port
    RBCP_Port = self.read(0xFFFFFF22, 2)
    print(f"UDP Port: {RBCP_Port[0]*256 + RBCP_Port[1]}")
    
    # Read compilation date and version
    temp = self.read(0, 4)
    year = "20" + hex(temp[0]).lstrip("0x")
    month = hex(temp[1]).lstrip("0x")
    day = hex(temp[2]).lstrip("0x")
    hour = hex(temp[3]).lstrip("0x")
    print(f"Compilation Date: {year}-{month}-{day} {hour}:00")
    
    temp = self.read(4, 1)
    print(f"Firmware Version: {temp[0]}")
    
    temp = self.read(5, 7)
    print(f"IP_SET 192.168.10.: {temp[0]+10}")
    
    # ==================== 2. Read FPGA Information ====================
    print("\n### FPGA Information ###")
    print(f"FPGA Temperature: {sysmon_read.temperature():.2f} °C")
    print(f"FPGA vccint Voltage: {sysmon_read.vccint():.2f} V")
    print(f"FPGA vccaux Voltage: {sysmon_read.vccaux():.2f} V")
    print(f"FPGA vccbram Voltage: {sysmon_read.vccbram():.2f} V")
    
    # ==================== 3. Configure I2C Devices ====================
    if CONFIG_ADC or CONFIG_CLOCK:
        print("\n### Configuring I2C Devices ###")
        device_addr_offset = 0
        TCA9548_ADDR = (0x74 + device_addr_offset) << 1

        tca9548 = mux.mux(TCA9548_ADDR, 0X200)
        tca9548.disable_all()
        tca9548.enable_FMC()
        tca9548.enable_NC()

        temp = tca9548.read()
        print(f"I2C Device Selection: {temp}")
    else:
        print("\n### Skipping I2C Device Configuration ###")
    
    # ==================== 4. Configure ADC ====================
    if CONFIG_ADC:
        print("\n### Configuring ADC ###")

        HMCAD1511.ADC_SELECT('ADCA')
        HMCAD1511.SET_ADCA_HMCAD1511()
        print("ADCA configuration completed")

        HMCAD1511.ADC_SELECT('ADCB')
        HMCAD1511.SET_ADCB_HMCAD1511()
        print("ADCB configuration completed")

        HMCAD1511.ADC_SELECT('ADCC')
        HMCAD1511.SET_ADCC_HMCAD1511()
        print("ADCC configuration completed")

        HMCAD1511.ADC_SELECT('ADCD')
        HMCAD1511.SET_ADCD_HMCAD1511()
        print("ADCD configuration completed")
    else:
        print("\n### Skipping ADC Configuration ###")
    
    # ==================== 5. Configure Clock ====================
    if CONFIG_CLOCK:
        print("\n### Configuring Clock ###")
        si5345_16ch.SET_SI5345()
        print("Clock configuration completed")
        sleep(1)
    else:
        print("\n### Skipping Clock Configuration ###")
    
    # ==================== 6. Send Configuration Completion Signal ====================
    if CONFIG_DONE_PULSE:
        raise RuntimeError("CONFIG_DONE_PULSE is disabled because 0x1A is ADC_CONFIG")
    else:
        print("\n### Skipping Configuration Completion Signal (0x1A is ADC_CONFIG) ###")
    
    # ==================== 7. Configure Trigger ====================
    if CONFIG_TRIGGER:
        print("\n### Configuring Trigger ###")

        # Set thresholds
        trigger.set_threshold(1950, 2400, 2300, 2300)

        # Set trigger mode
        trigger.timestamp_clean_en('disable')

        trigger.ext_trigger_en('disable')

        # Set trigger mode to 0
        trigger.trigger_model(1)

        # Set trigger position
        trigger.trigger_postion(40)

        send_start_delay_reg = int(round(send_start_delay_us * 200))
        if send_start_delay_reg < 0 or send_start_delay_reg > 0xFFFFFF:
            raise ValueError(f"Invalid SEND_START_DELAY setting for {device_name}: {send_start_delay_us} us")
        trigger.set_send_start_delay(send_start_delay_reg)
        print(f"SEND_START_DELAY: {send_start_delay_us} us (reg={send_start_delay_reg})")

        #position = (512-trigger_postion*2*4) 16ch
        #position = (2048-trigger_postion*8*4) 8ch

        # Read trigger information
        trigger_model, trigger_postion, thresholds = trigger.read_trigger_info()
        print(f"Read Trigger Mode: {trigger_model}")
        print(f"Read Trigger Position: {trigger_postion}")
        print(f"Read Thresholds: {thresholds}")
    else:
        print("\n### Skipping Trigger Configuration ###")

    # ==================== 8. Configure TCP hit selection ====================
    if CONFIG_TCP_MODE2:
        print("\n### Configuring TCP Hit Selection ###")
        self.write(0x42, bytes([0]))
        self.write(0x43, bytes([4]))
        self.write(0x44, bytes([12]))
        trigger.set_hit_thresholds([0] * 16)
        trigger.set_hit_polarity([0] * 16)
        hit_thresholds, hit_polarities = trigger.read_hit_config()
        send_mode = self.read(0x42, 1)[0] & 0x03
        integ_pre_samples = self.read(0x43, 1)[0] & 0x7f
        integ_post_samples = self.read(0x44, 1)[0] & 0x7f
        print(f"Read Send Mode: {send_mode}")
        print(f"Read Integration Samples: pre={integ_pre_samples}, post={integ_post_samples}")
        print(f"Read Hit Thresholds: {hit_thresholds}")
        print(f"Read Hit Polarities: {hit_polarities}")
    else:
        print("\n### Skipping TCP Hit Selection ###")

    print("Selected configuration steps completed")
    
    # # ==================== 9. Verify Configuration ====================
    # print("\n### Verifying Configuration ###")
    
    # # Read several key registers to verify configuration
    # temp = self.read(0x06, 1)
    # print(f"Trigger Control Register: {format(temp[0], '08b')}")
    
    # temp = self.read(0x1A, 1)
    # print(f"Configuration Completion Register: {format(temp[0], '04b')}")
    
    # print(f"\nDevice {device_name} configuration completed!")
    # print("=" * 60)
    
    return True


def clear_modules():
    """
    Clear imported modules to force re-import
    """
    modules_to_clear = ['mux', 'si5345_16ch', 'HMCAD1511', 'FPGA_CTRL']
    
    for module_name in modules_to_clear:
        if module_name in sys.modules:
            del sys.modules[module_name]


def main():
    """
    Main function: Configure all devices
    """
    print("Multi-device Configuration Program Starting")
    print("=" * 60)
    
    total_devices = len(DEVICES)
    successful_devices = 0
    
    for i, device_info in enumerate(DEVICES, 1):
        try:
            print(f"\n[{i}/{total_devices}] Preparing to configure device: {device_info['name']}")
            
            # Set environment variables for current device
            os.environ['SITCP_DEVICE_NAME'] = device_info['name']
            os.environ['SITCP_DEVICE_IP'] = device_info['ip']
            os.environ['SITCP_UDP_PORT'] = str(device_info['port'])
            os.environ['SITCP_SEND_START_DELAY_US'] = str(device_info.get('send_start_delay_us', 0))
            
            print(f"Environment variables set: IP={device_info['ip']}, PORT={device_info['port']}")
            
            # Clear imported modules to force re-import
            clear_modules()
            
            # Re-import rbcp module to ensure new environment variables are used
            if 'lib.rbcp' in sys.modules:
                importlib.reload(sys.modules['lib.rbcp'])
            
            # Configure current device
            if configure_device():
                successful_devices += 1
                print(f"Device {device_info['name']} configured successfully!")
            else:
                print(f"Device {device_info['name']} configuration failed!")
                
        except Exception as e:
            print(f"Error configuring device {device_info['name']}: {str(e)}")
            import traceback
            traceback.print_exc()
        
        # Delay between devices to avoid conflicts
        if i < total_devices:
            print("\n" + "-" * 40)
            print("Waiting 2 seconds before configuring next device...")
            sleep(2)
    
    # Output summary
    print("\n" + "=" * 60)
    print("Configuration Completion Summary")
    print("=" * 60)
    print(f"Total Devices: {total_devices}")
    print(f"Successfully Configured: {successful_devices}")
    print(f"Failed Devices: {total_devices - successful_devices}")
    
    if successful_devices == total_devices:
        print("\nAll devices configured successfully!")
    else:
        print(f"\n{total_devices - successful_devices} devices failed configuration. Please check connections and settings.")
    
    # Clean up environment variables
    os.environ.pop('SITCP_DEVICE_NAME', None)
    os.environ.pop('SITCP_DEVICE_IP', None)
    os.environ.pop('SITCP_UDP_PORT', None)
    os.environ.pop('SITCP_SEND_START_DELAY_US', None)
    
    print("\nProgram execution completed!")


def test_single_device():
    """
    Test a single device
    """
    print("Single Device Test Mode")
    
    # Set test device
    test_device = {"name": "Test_Device", "ip": "192.168.10.10", "port": 4660, "send_start_delay_us": 0}
    
    # Set environment variables
    os.environ['SITCP_DEVICE_NAME'] = test_device['name']
    os.environ['SITCP_DEVICE_IP'] = test_device['ip']
    os.environ['SITCP_UDP_PORT'] = str(test_device['port'])
    os.environ['SITCP_SEND_START_DELAY_US'] = str(test_device['send_start_delay_us'])
    
    print(f"Test Device: {test_device['name']} ({test_device['ip']}:{test_device['port']})")
    
    # Clear modules
    clear_modules()
    
    # Re-import rbcp
    if 'lib.rbcp' in sys.modules:
        importlib.reload(sys.modules['lib.rbcp'])
    
    # Execute configuration
    try:
        configure_device()
        print("\nSingle device test successful!")
    except Exception as e:
        print(f"\nSingle device test failed: {str(e)}")
        import traceback
        traceback.print_exc()
    
    # Clean up environment variables
    os.environ.pop('SITCP_DEVICE_NAME', None)
    os.environ.pop('SITCP_DEVICE_IP', None)
    os.environ.pop('SITCP_UDP_PORT', None)
    os.environ.pop('SITCP_SEND_START_DELAY_US', None)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Multi-device Configuration Program')
    parser.add_argument('--test', action='store_true', help='Single device test mode')
    parser.add_argument('--ip', type=str, default='192.168.10.10', help='Test device IP address')
    parser.add_argument('--port', type=int, default=4660, help='Test device port')
    
    args = parser.parse_args()
    
    if args.test:
        # Single device test mode
        DEVICES = [{"name": "Test_Device", "ip": args.ip, "port": args.port}]
        test_single_device()
    else:
        # Multi-device configuration mode
        main()
