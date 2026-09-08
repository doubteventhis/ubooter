#!/usr/bin/env python3 

import os
import sys
import re
import time
import argparse
import select
import termios
import tty
import threading
from datetime import datetime

# pip install pyserial tftpy
import serial
import tftpy

# read and save bootlog output, add some to colors to useful strings
def read_bootlogs(ser):
    print(f"[*] Sending log output to BOOT_{file_name}.txt")

    while True:
        data = ser.read(1024)
        if data:
            text = data.decode('utf-8', errors='replace')
            
            # highlight anything that looks like a hex address in green
            text = re.sub(r'(0x[0-9A-Fa-f]+)', '\033[32m\\1\033[0m', text)

            # highlight interesting words in orange
            text = re.sub(r'(?i)\b(squashfs|linux|uboot|u-boot|grub|ext4|jffs2|mtdparts|ubifs|yaffs|initramfs|trx|busybox|openwrt|lede|buildroot|conf|config|mips|arm|x86|x64|kernel|rootfs|version|filesystem|ver.)\b', '\033[38;5;208m\\1\033[0m', text)

            # highlight possible boot-interruption prompts in red
            text = re.sub(
                r'(?i)\b(autobooting|press any key|hit any key|break(?:\s+sequence)?|in\s+\d+\s+seconds)\b', '\033[31m\\1\033[0m', text)
            
            print(text, end='')

            with open("BOOT_" + file_name, "a", encoding="utf-8") as f:
                f.write(text)


# read serial data until we see the specified pattern
def read_until_pattern(ser, pattern, timeout=None):
    buffer = b""
    start = time.time()

    while True:
        if timeout is not None and (time.time() - start > timeout):
            raise TimeoutError(f"Waited {timeout} seconds for {pattern.decode()}")
        
        chunk = ser.read(1024)

        if not chunk:
            continue
        buffer += chunk
        #print(f'buffer {buffer}')
        
        # adding this for the edge case where the bootloader string is dumped in plaintext from memory but does not indicate an actual bootloader prompt. this breaks the parsing in the script because it uses the prompt as a delimiter when parsing the serial output. so we'll make sure prompts are on a new line by themselves 
        if pattern == prompt:
            lines = buffer.splitlines()
            if lines and lines[-1].strip() == pattern.strip():
                return buffer

        else:
            if pattern in buffer:
                return buffer 


# enter an interactive shell
def interactive_shell(ser):
    print("[*] Entering interactive mode (Ctrl+C to exit)")
    ser.timeout = 0.1

    # save terminal settings
    old_settings = termios.tcgetattr(sys.stdin)
    tty.setcbreak(sys.stdin.fileno())

    try:
        while True:
            # check if there is data from serial port
            if ser.in_waiting:
                data = ser.read(ser.in_waiting)
                if data:
                    sys.stdout.write(data.decode(errors="ignore"))
                    sys.stdout.flush()

            # check if user typed something
            if sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
                user_input = os.read(sys.stdin.fileno(), 1)
                
                # catch control + c
                if user_input == b'\x03':  
                    break

                ser.write(user_input)

    except KeyboardInterrupt:
        print("\n[*] User exited.")

    finally:
        # restore terminal settings and close
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)


def enter_bootloader_shell(ser, no_reboot=False, dump=False):
    time.sleep(0.1)

    # already in a bootloader shell, just drop in
    if no_reboot:
        interactive_shell(ser)
    
    else:
        # read data until we see the trigger word, send the interrupt
        print(f'[*] Looking for trigger word "{trigger.decode()}"')
        read_until_pattern(ser, trigger)
        print(f'[+] Trigger word detected. Sending interrupt "{interrupt.decode().strip()}"')
        ser.write(interrupt + b"\n")

        # read data untill we see the bootloader prompt
        print(f'[*] Waiting for bootloader prompt "{prompt.decode()}"')
        read_until_pattern(ser, prompt)
        print(f"[+] Bootloader prompt detected")

        if not dump:
            interactive_shell(ser)


def dump_memory(ser):
    if chunk_size % 16 != 0:
        print("[!] Warning: Chunk size should be a multiple of 16 (e.g. 0x1000, 0x4000) when using \"md.b\"")
        sys.exit(1)

    time.sleep(0.1)
    enter_bootloader_shell(ser, False, True)

    print(f"[*] Starting memory dump from 0x{start_address:08x} to 0x{end_address:08x}")
    print(f"[*] Sending raw output to {file_name}.txt")

    with open(file_name + '.txt', "wb") as f:
        current_address = start_address
        total = end_address - start_address
        total_dumped = 0
        #words = chunk_size // 4 # for the stand "md" command
        #line_re = re.compile(rb'^([0-9A-Fa-f]{8}):((?: [0-9A-Fa-f]{8}){4})') # for the standard "md" command
        line_re = re.compile(rb'^([0-9A-Fa-f]{8}):((?: [0-9A-Fa-f]{2}){1,16})') # for "md.b" command
        
        print(f"[*] Starting dump with command: md.b 0x{current_address:08x} 0x{chunk_size:x}")

        # start looping through addresses to dump memory
        while current_address < end_address:
            cmd = f"md.b 0x{current_address:08x} 0x{chunk_size:x}\n".encode()

            # calc the expected memory addresses
            expected_addresses = set(range(current_address, current_address + chunk_size, 16))
            
            # set up retries in case we fail to dump a region or get improperly formatted text
            max_retries = 3
            for attempt in range(1, max_retries + 1):
                try:
                    received_addresses = set()

                    ser.reset_input_buffer()
                    ser.write(cmd)
                    time.sleep(0.1)

                    raw = read_until_pattern(ser, prompt, timeout)
                except TimeoutError as e:
                    print(f"\n[!] Attempt {attempt} timed out: {e}")
                    continue

                lines = raw.splitlines()

                for line in lines:

                    # first save the output to a file
                    f.write(line + b"\n")

                    # check if it's a valid line
                    match = line_re.match(line)
                    if not match:
                        continue
                    
                    dumped_address = int(match.group(1), 16)
                    received_addresses.add(dumped_address)

                # if we got all the expected regions of memory, write them to a file
                if received_addresses == expected_addresses:
                    for line in lines:
                        match = line_re.match(line)
                        if not match:
                            continue
                        addr = int(match.group(1), 16)

                        # first check the address is in range
                        if start_address <= addr <= end_address:
                            #print(line)
                            line_buffer.append(line)
                    break

                # try again
                else: 
                    print(f"\n[!] Trying chunk 0x{current_address:08x} again")
                    #print("Expected addresses:", sorted(expected_addresses))
                    #print("Received addresses:", sorted(received_addresses))
                    #print("Missing:", sorted(expected_addresses - received_addresses))
                    #print("Extra:", sorted(received_addresses - expected_addresses))
                    #print(raw)

            else:
                print(f"[!] Giving up on chunk at 0x{current_address:08x}. Writing what we have")
                print(f"[!] Missing addresses: {sorted(expected_addresses - received_addresses)}")
                f.write(raw)

            # progress tracker
            current_address += chunk_size
            total_dumped += chunk_size
            display_dumped = start_address + total_dumped
            percent = total_dumped / total * 100
            print(f"\rProgress: {display_dumped:#x}/{end_address:#x} ({percent:.1f}%)", end='', flush=True)

    print(f"\n[+] Dump complete, saving output to {file_name}.bin')

    bin_data = bytearray()

    for line in line_buffer:
        match = line_re.match(line)
        if not match:
            print(f"[!] Found bad data at {line}")
            continue

        bytestr = match.group(2).strip().split()
        for byte in bytestr:
            bin_data += bytes.fromhex(byte.decode())
    
    with open(file_name + '.bin', "wb") as g: 
        g.write(bin_data)

    print("[+] All done :)\n")
    

# starts a tftp server in the background
def start_tftp_server():
    def run_server():
        try:
            server = tftpy.TftpServer(tftp_root)
            print(f"[*] Starting TFTP server on 0.0.0.0:{tftp_port} (UDP), serving files from {tftp_root}")
            server.listen("0.0.0.0", tftp_port)
        except Exception as e:
            print(f"[!] Error starting TFTP server: {e}")

    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    return thread


def main():

    print("""         __                __           
  __  __/ /_  ____  ____  / /____  _____
 / / / / __ \/ __ \/ __ \/ __/ _ \/ ___/
/ /_/ / /_/ / /_/ / /_/ / /_/  __/ /    
\__,_/_.___/\____/\____/\__/\___/_/     
          """)

    # open serial connection
    ser = serial.Serial(serial_port, baud_rate, timeout=1)
    print(f'[*] Listening on {serial_port} @{baud_rate}bps')

    try:
        if tftp_server:
            start_tftp_server()

        if dump_firmware:
            dump_memory(ser)

        elif shell:
            interactive_shell(ser)

        elif bootloader_shell:
            if no_reboot:
                enter_bootloader_shell(ser, True, False)
       
            else:
                enter_bootloader_shell(ser)

        else:
            print("[*] No options specified. Will dump boot logs to screen")
            read_bootlogs(ser)

    except KeyboardInterrupt:
        print("\n[*] User exited.")
    
    except Exception as e:
        print(f"\n[!] An error occurred: {e}")

    finally:
        ser.close()


if __name__ == "__main__":
    
    # take in args
    parser = argparse.ArgumentParser(description="U-boot serial boot log monitor, interactive shell, and firmware dumper. Hook up the device to UART, start the script, and restart the device.", 
                                    epilog="""
Examples:
Examine bootlogs                    python3 ubooter.py --output bootlogs
Interactive shell                   python3 ubooter.py --shell --baud 115200 --port /dev/ttyUSB0
Dump firmware                       python3 ubooter.py --dump-firmware --start 0x9f000000 --end 0x9f400000
Bootloader shell and TFTP server    python3 ubooter.py --bootloader-shell --tftp-server --tftp-root ./tftp --prompt 'hornet> '
""",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    general = parser.add_argument_group('General options')
    general.add_argument("--port", default="/dev/ttyUSB0", metavar="", help="Serial device port (default: /dev/ttyUSB0)")
    general.add_argument("--baud", type=int, default=115200, metavar="", help="Baud rate (default: 115200)")
    general.add_argument("--output", default="dump", metavar="", help="Base output file name. A timestamp will be automatically appended (default: dump)")
    general.add_argument("--shell", action="store_true", help="Enter an interactive linux shell (default: False)")
    general.add_argument("--bootloader-shell", action="store_true", help="Enter an bootloader shell (default: False)")
    general.add_argument("--dump-firmware", action="store_true", help="Dump firmware using u-boot's md.b command (default: False)")

    boot = parser.add_argument_group('Bootloader interrupt options') 
    boot.add_argument("--trigger", default="Autobooting", metavar="", help="String that prompts sending the interrupt (default: Autobooting)")
    boot.add_argument("--interrupt", default="tpl", metavar="", help="Interrupt string (default: tpl)")
    boot.add_argument("--prompt", default="hb> ", metavar="", help="Bootloader prompt to look for after sending interrupt. Use the full prompt. Ex: 'hb> ' (default: hb> )")
    boot.add_argument("--no-reboot", action="store_true", help="Drop straight into the bootloader shell, if a reboot isn't needed (default: False)")

    firmware = parser.add_argument_group('Firmware dumping options')
    firmware.add_argument("--start", type=lambda x: int(x, 0), metavar="", default=0x9f000000, help="Start address in hex (default: 0x9f000000)")
    firmware.add_argument("--end", type=lambda x: int(x, 0), metavar="", default=0x9f400000, help="End address in hex (default: 0x9f400000)")
    firmware.add_argument("--chunk", type=lambda x: int(x, 0), metavar="", default=0x4000, help="Chunk size in bytes, should be a multiple of 16 (default: 0x4000)")
    firmware.add_argument("--timeout", type=int, default=20, metavar="", help="Timeout in seconds for each chunk during memory dumps (default: 20)")

    tftp = parser.add_argument_group('TFTP options')
    tftp.add_argument("--tftp-server", action="store_true", help="Start a TFTP server in the background (default: False)")
    tftp.add_argument("--tftp-root", default="./", metavar="", help="Root directory for the TFTP server (default: ./)")
    tftp.add_argument("--tftp-port", type=int, default="69", metavar="", help="Listening port for the TFTP server (default: 69)")

    args = parser.parse_args()
    start_address = args.start
    end_address = args.end
    chunk_size = args.chunk
    output_file = args.output
    trigger = args.trigger.encode()
    interrupt = args.interrupt.encode()
    prompt = args.prompt.encode()
    serial_port = args.port
    baud_rate = args.baud
    no_reboot = args.no_reboot
    timeout = args.timeout
    dump_firmware = args.dump_firmware
    shell = args.shell
    bootloader_shell = args.bootloader_shell
    tftp_server = args.tftp_server
    tftp_root = args.tftp_root
    tftp_port = args.tftp_port

    # file name
    timestamp = datetime.now().strftime("_%Y-%m-%d_%H-%M-%S")
    base, ext = os.path.splitext(output_file) 
    file_name = f"{base}{timestamp}" 

    line_buffer = []

    main()
