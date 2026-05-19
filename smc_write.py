#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
smc_write.py — minimal Intel Mac SMC fan control via IOKit + ctypes.
Must be run as root (use via AppleScript 'with administrator privileges').

Usage:
  python3 smc_write.py set <rpm>       # set min RPM for all fans
  python3 smc_write.py auto            # reset to auto (remove override)

Exit 0 = success, 1 = failure.
"""

import sys
import ctypes
import ctypes.util
import struct

# ── IOKit / CoreFoundation bindings ─────────────────────────────────────────

IOKit = ctypes.cdll.LoadLibrary(
    '/System/Library/Frameworks/IOKit.framework/IOKit')
CF = ctypes.cdll.LoadLibrary(
    '/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')

kIOMasterPortDefault        = ctypes.c_uint32(0)
kIOReturnSuccess            = 0
kSMCCmdReadBytes            = 5
kSMCCmdWriteBytes           = 6
kSMCCmdReadKeyInfo          = 9
KERNEL_INDEX_SMC            = 2

# ── SMC structs ──────────────────────────────────────────────────────────────

class SMCKeyInfo(ctypes.Structure):
    _fields_ = [('dataSize', ctypes.c_uint32),
                ('dataType', ctypes.c_uint32),
                ('dataAttributes', ctypes.c_uint8)]

class SMCVal(ctypes.Structure):
    _fields_ = [('key',          ctypes.c_char * 5),
                ('dataSize',     ctypes.c_uint32),
                ('dataType',     ctypes.c_char * 5),
                ('bytes',        ctypes.c_ubyte * 32),
                ('result',       ctypes.c_uint8),
                ('status',       ctypes.c_uint8),
                ('data8',        ctypes.c_uint8),
                ('data32',       ctypes.c_uint32),
                ('keyInfo',      SMCKeyInfo)]

# ── Low-level helpers ────────────────────────────────────────────────────────

def _open_smc():
    IOKit.IOServiceGetMatchingService.restype = ctypes.c_uint32
    IOKit.IOServiceMatching.restype           = ctypes.c_void_p
    service = IOKit.IOServiceGetMatchingService(
        kIOMasterPortDefault,
        IOKit.IOServiceMatching(b'AppleSMC')
    )
    if not service:
        return None, None
    conn = ctypes.c_uint32(0)
    ret = IOKit.IOServiceOpen(service, IOKit.mach_task_self_(), 0,
                              ctypes.byref(conn))
    IOKit.IOObjectRelease(service)
    return conn if ret == kIOReturnSuccess else None, ret


def _close_smc(conn):
    IOKit.IOServiceClose(conn)


def _smc_call(conn, cmd, val_in, val_out):
    size = ctypes.c_size_t(ctypes.sizeof(SMCVal))
    return IOKit.IOConnectCallStructMethod(
        conn,
        ctypes.c_uint32(KERNEL_INDEX_SMC),
        ctypes.byref(val_in),  size,
        ctypes.byref(val_out), ctypes.byref(size))


def _key_to_uint32(key):
    b = key.encode('ascii') if isinstance(key, str) else key
    return struct.unpack('>I', b.ljust(4, b'\x00')[:4])[0]


def _get_key_info(conn, key):
    val_in = SMCVal()
    val_out = SMCVal()
    val_in.key    = key.encode('ascii') if isinstance(key, str) else key
    val_in.data8  = kSMCCmdReadKeyInfo
    ret = _smc_call(conn, kSMCCmdReadKeyInfo, val_in, val_out)
    return ret, val_out.keyInfo


def _write_key(conn, key, data_bytes):
    ret, info = _get_key_info(conn, key)
    if ret != kIOReturnSuccess:
        return ret

    val_in = SMCVal()
    val_out = SMCVal()
    val_in.key          = key.encode('ascii') if isinstance(key, str) else key
    val_in.dataSize     = info.dataSize
    val_in.dataType     = struct.pack('>I', info.dataType)
    for i, b in enumerate(data_bytes[:32]):
        val_in.bytes[i] = b
    val_in.data8 = kSMCCmdWriteBytes
    return _smc_call(conn, kSMCCmdWriteBytes, val_in, val_out)


def _read_key(conn, key):
    ret, info = _get_key_info(conn, key)
    if ret != kIOReturnSuccess:
        return ret, None
    val_in = SMCVal()
    val_out = SMCVal()
    val_in.key      = key.encode('ascii') if isinstance(key, str) else key
    val_in.dataSize = info.dataSize
    val_in.data8    = kSMCCmdReadBytes
    ret = _smc_call(conn, kSMCCmdReadBytes, val_in, val_out)
    if ret == kIOReturnSuccess:
        raw = bytes(val_out.bytes[:info.dataSize])
        return ret, raw
    return ret, None


# ── Fan speed helpers ────────────────────────────────────────────────────────

def _rpm_to_fpe2(rpm):
    """Convert RPM to SMC FPE2 (16-bit fixed-point, 2 fractional bits)."""
    return struct.pack('>H', int(rpm) << 2)


def _fpe2_to_rpm(data):
    val = struct.unpack('>H', data[:2])[0]
    return val >> 2


def _num_fans(conn):
    ret, data = _read_key(conn, 'FNum')
    if ret == kIOReturnSuccess and data:
        return data[0]
    return 0


def set_fan_min_rpm(rpm):
    conn, err = _open_smc()
    if conn is None:
        print('Cannot open SMC (err={})'.format(hex(err or 0)))
        return False

    n = _num_fans(conn)
    if n == 0:
        n = 2  # assume 2 fans

    success = True
    for i in range(n):
        key = 'F{}Mn'.format(i)
        data = _rpm_to_fpe2(rpm)
        ret = _write_key(conn, key, data)
        if ret != kIOReturnSuccess:
            print('Write {} failed: {}'.format(key, hex(ret)))
            success = False
        else:
            print('Set {} = {} RPM'.format(key, rpm))

    _close_smc(conn)
    return success


def reset_auto():
    """Reset to macOS automatic fan control by setting min RPM to 0."""
    return set_fan_min_rpm(0)


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1].lower()
    if cmd == 'set' and len(sys.argv) >= 3:
        try:
            rpm = int(sys.argv[2])
        except ValueError:
            print('Invalid RPM value')
            sys.exit(1)
        ok = set_fan_min_rpm(rpm)
        sys.exit(0 if ok else 1)
    elif cmd == 'auto':
        ok = reset_auto()
        sys.exit(0 if ok else 1)
    else:
        print(__doc__)
        sys.exit(1)
