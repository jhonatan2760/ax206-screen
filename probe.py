"""Le as dimensoes reais do LCD direto do firmware (comando GETLCDPARAMS do dpf-ax)."""

from ax206 import AX206

lcd = AX206()
cmd = bytes([0xCD, 0, 0, 0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
data = lcd._scsi_cmd(cmd, read_len=5)
w = data[0] | (data[1] << 8)
h = data[2] | (data[3] << 8)
print(f"bytes: {list(data)}")
print(f"LCD reporta: {w} x {h}")
