# Ubooter
U-boot serial boot log monitor, interactive shell, and firmware dumper. 
```
General options:
  --port              Serial device port (default: /dev/ttyUSB0)
  --baud              Baud rate (default: 115200)
  --output            Base output file name. A timestamp will be automatically appended (default: dump)
  --shell             Enter an interactive linux shell (default: False)
  --bootloader-shell  Enter an bootloader shell (default: False)
  --dump-firmware     Dump firmware using u-boot's md.b command (default: False)

Bootloader interrupt options:
  --trigger           String that prompts sending the interrupt (default: Autobooting)
  --interrupt         Interrupt string (default: tpl)
  --prompt            Bootloader prompt to look for after sending interrupt. Use the full prompt. Ex: 'hb> ' (default: hb> )
  --no-reboot         Drop straight into the bootloader shell, if a reboot isn't needed (default: False)

Firmware dumping options:
  --start             Start address in hex (default: 0x9f000000)
  --end               End address in hex (default: 0x9f400000)
  --chunk             Chunk size in bytes, should be a multiple of 16 (default: 0x4000)
  --timeout           Timeout in seconds for each chunk during memory dumps (default: 20)

TFTP options:
  --tftp-server       Start a TFTP server in the background (default: False)
  --tftp-root         Root directory for the TFTP server (default: ./)
  --tftp-port         Listening port for the TFTP server (default: 69)

Examples:
Examine bootlogs                    python3 ubooter.py --output bootlogs
Interactive shell                   python3 ubooter.py --shell --baud 115200 --port /dev/ttyUSB0
Dump firmware                       python3 ubooter.py --dump-firmware --start 0x9f000000 --end 0x9f400000
Bootloader shell and TFTP server    python3 ubooter.py --bootloader-shell --tftp-server --tftp-root ./tftp --prompt 'hornet> '
```

# Usage
Hook up the device to UART, start the script, and restart the device.

## Read only
Monitor bootlogs to highlight interesting keywords, memory addresses, partition information, and software
```
python3 ubooter.py
```
![uboot6](https://github.com/user-attachments/assets/70f1d57e-8fd0-4c68-b1da-c583f145418e)
![image](https://github.com/user-attachments/assets/d92c7221-146e-4810-b9b3-ecb7a3530114)




## Standard UART shell
Drop into a standard linux shell over UART. Can be used like minicom, picocom, screen, etc
```
python3 ubooter.py --shell
```
![ubooter1](https://github.com/user-attachments/assets/ccc128aa-2d6d-4876-a25f-78f4a15c8bd6)


## Bootloader shell
Attempt to interrupt the boot process and drop into an interactive bootloader shell. Useful for changing environment variables, loading new images over TFTP, or dumping raw memory using the bootloader’s commands
```
python3 ubooter.py --bootloader-shell --tftp-server --tftp-root tftp/
```
![image](https://github.com/user-attachments/assets/7c244156-dc29-49df-b07d-b8610aaa4510)



## Firmware dump
Automated dumping of the specified regions of memory (kernel, rootfs, config, etc) directly from the bootloader using u-boot's "md" command. Useful for reverse engineering the firmware on another machine
```
python3 ubooter.py --dump-firmware --start 0x9f000000 --end 0x9f400000
```
![uboot5](https://github.com/user-attachments/assets/96efe64e-22e9-4cd3-a7d9-520220540473)







# Features
- Built in TFTP server can run in the background to load in custom firmware or binaries
- Attempts to verify memory dumps and recover from a bad read


