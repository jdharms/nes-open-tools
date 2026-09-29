"""Run a ROM's `InitializeSram` under py65, to see what a new save holds."""

from py65.devices.mpu6502 import MPU

HEADER = 0x10
BANK = 0x4000
INITIALIZE_SRAM = 0xACBC
#: where the harness's return address lands when InitializeSram returns
RETURN = 0x0002


def new_save(rom: bytes) -> bytes:
    """Run InitializeSram from bank 9 over blank SRAM; return $6000-$7FFF after.

    Bank 9 is mapped at $8000 and the fixed bank at $C000, which is all the routine
    and the fixed-bank helpers it calls need.
    """
    mpu = MPU()
    memory = mpu.memory
    memory[0x8000:0xC000] = rom[HEADER + 9 * BANK : HEADER + 10 * BANK]
    memory[0xC000:0x10000] = rom[HEADER + 15 * BANK : HEADER + 16 * BANK]
    mpu.sp = 0xFD
    for byte in ((RETURN - 1) >> 8, (RETURN - 1) & 0xFF):
        memory[0x0100 + mpu.sp] = byte
        mpu.sp -= 1
    mpu.pc = INITIALIZE_SRAM
    for _ in range(200_000):
        if mpu.pc == RETURN:
            return bytes(memory[0x6000:0x8000])
        if mpu.pc < 0x8000:
            raise AssertionError(f"InitializeSram left ROM at ${mpu.pc:04X}")
        mpu.step()
    raise AssertionError("InitializeSram did not return")
