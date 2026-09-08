"""Decode coefficient commands as integers. Never opens a codec device."""


def decode_coefficient(nid: int, verb: int, parameter: int) -> dict:
    if not 0 <= nid <= 0xff or not 0 <= verb <= 0xfff or not 0 <= parameter <= 0xffff:
        raise ValueError('Operand outside the hwdep input range')
    if verb >> 8 not in (4, 5, 12, 13):
        raise ValueError('This decoder only accepts coefficient read/write verbs')
    word = (nid << 24) | (verb << 8) | parameter
    opcode = (word >> 8) & 0xf00
    effective = word & 0xffff
    return {'nid': f'0x{nid:02x}', 'hwdep_word': f'0x{word:08x}', 'canonical_verb': f'0x{opcode:03x}', 'effective_parameter': f'0x{effective:04x}', 'parameter_changed_by_overlap': effective != parameter, 'device_access': False}
