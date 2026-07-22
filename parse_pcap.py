"""Extrai comandos SCSI (CBW) enviados a tela AX206 de uma captura USBPcap."""

import struct
import sys
from collections import Counter

PCAP = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\jhona\aida_capture.pcap"

f = open(PCAP, "rb")
gh = f.read(24)
assert gh[:4] in (b"\xd4\xc3\xb2\xa1", b"\xa1\xb2\xc3\xd4"), "nao e pcap"

cmds = []          # (device, endpoint, cb16, datalen_declarado)
seq = []           # sequencia de eventos OUT do device alvo
counter = Counter()
n = 0
target_dev = None

while True:
    ph = f.read(16)
    if len(ph) < 16:
        break
    ts_s, ts_us, incl, orig = struct.unpack("<IIII", ph)
    pkt = f.read(incl)
    n += 1
    if len(pkt) < 27:
        continue
    (hlen,) = struct.unpack_from("<H", pkt, 0)
    if hlen < 27 or hlen > len(pkt):
        continue
    bus, dev = struct.unpack_from("<HH", pkt, 17)
    endpoint = pkt[21]
    transfer = pkt[22]
    (dlen,) = struct.unpack_from("<I", pkt, 23)
    data = pkt[hlen : hlen + dlen]
    # bulk transfer = 3
    if transfer != 3 or not data:
        continue
    if data[:4] == b"USBC":
        # CBW: sig(4) tag(4) datalen(4) flags(1) lun(1) cblen(1) cb(16)
        cb = data[15:31]
        dl = struct.unpack_from("<I", data, 8)[0]
        flags = data[12]
        cmds.append((dev, endpoint, cb, dl, flags))
        counter[(dev, cb[:16].hex())] += 1
        if target_dev is None and cb[0] == 0xCD:
            target_dev = dev
        seq.append(("CBW", dev, endpoint, cb.hex(), dl, flags))
    else:
        seq.append(("DATA", dev, endpoint, data[:24].hex(), len(data), None))

print(f"{n} pacotes, {len(cmds)} CBWs")
print(f"device alvo (0xcd): {target_dev}")
print("\n== comandos unicos (device, cb) x contagem ==")
for (dev, cb), cnt in counter.most_common(40):
    print(f"dev{dev}  {cb}  x{cnt}")
