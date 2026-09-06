"""
Driver para tela AX206 (Appotech) com firmware dpf-ax — "USB-Display" VID 1908 PID 0102.
Protocolo: comandos SCSI vendor-specific (0xCD) encapsulados em USB Mass Storage
Bulk-Only (CBW/CSW). Pixels em RGB565.

Baseado no protocolo aberto do projeto dpf-ax (lcd4linux drv_dpf / libdpf).
"""

import struct
import sys

import usb.core
import usb.util

VID = 0x1908
PID = 0x0102

USBCMD_SETPROPERTY = 0x01
USBCMD_BLIT = 0x12
PROPERTY_BRIGHTNESS = 0x01
PROPERTY_ORIENTATION = 0x10


class AX206Error(Exception):
    pass


class AX206:
    WIDTH = 240
    HEIGHT = 320

    def __init__(self):
        self.dev = usb.core.find(idVendor=VID, idProduct=PID)
        if self.dev is None:
            raise AX206Error(
                "Tela nao encontrada (VID 1908 PID 0102). "
                "Verifique o cabo USB e se o AIDA64 nao esta rodando."
            )
        if sys.platform != "win32":
            # Linux: a tela se apresenta como pendrive e o kernel liga o
            # usb-storage nela; precisa soltar antes de falar direto
            try:
                if self.dev.is_kernel_driver_active(0):
                    self.dev.detach_kernel_driver(0)
            except (usb.core.USBError, NotImplementedError):
                pass
        try:
            self.dev.set_configuration()
        except usb.core.USBError:
            pass  # ja configurado
        cfg = self.dev.get_active_configuration()
        intf = cfg[(0, 0)]
        self.ep_out = usb.util.find_descriptor(
            intf,
            custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
            == usb.util.ENDPOINT_OUT,
        )
        self.ep_in = usb.util.find_descriptor(
            intf,
            custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
            == usb.util.ENDPOINT_IN,
        )
        if self.ep_out is None or self.ep_in is None:
            raise AX206Error("Endpoints bulk nao encontrados.")
        self._tag = 0

    def close(self):
        """Libera a interface USB para outros processos/instancias."""
        usb.util.dispose_resources(self.dev)

    # ---- camada mass-storage (CBW/CSW) ----

    def _scsi_cmd(self, cmd16, data_out=None, read_len=0):
        self._tag = (self._tag + 1) & 0xFFFFFFFF
        data_len = len(data_out) if data_out else read_len
        flags = 0x80 if read_len else 0x00
        cbw = struct.pack(
            "<4sIIBBB16s",
            b"USBC",
            self._tag,
            data_len,
            flags,
            0,          # LUN
            16,         # tamanho do comando
            bytes(cmd16),
        )
        self.ep_out.write(cbw, timeout=1000)
        result = None
        if data_out:
            # uma escrita unica: o driver divide em URBs de 64 KB, igual ao AIDA64.
            # (chunks menores fazem o firmware clone perder bytes nas emendas)
            self.ep_out.write(bytes(data_out), timeout=10000)
        elif read_len:
            result = self.ep_in.read(read_len, timeout=3000)
        csw = self.ep_in.read(13, timeout=3000)
        if bytes(csw[:4]) != b"USBS":
            raise AX206Error("CSW invalido — dispositivo fora de sincronia.")
        if csw[12] != 0:
            raise AX206Error(f"Comando SCSI falhou (status {csw[12]}).")
        return result

    # ---- comandos do dpf-ax ----

    def blit(self, x, y, width, height, rgb565_data):
        """Escreve um retangulo de pixels RGB565 na tela."""
        x2, y2 = x + width - 1, y + height - 1
        cmd = bytes(
            [
                0xCD, 0, 0, 0,
                0, 6, USBCMD_BLIT,
                x & 0xFF, x >> 8,
                y & 0xFF, y >> 8,
                x2 & 0xFF, x2 >> 8,
                y2 & 0xFF, y2 >> 8,
                0,
            ]
        )
        self._scsi_cmd(cmd, data_out=rgb565_data)

    def set_brightness(self, level):
        """Brilho 0..7."""
        level = max(0, min(7, int(level)))
        cmd = bytes(
            [
                0xCD, 0, 0, 0,
                0, 6, USBCMD_SETPROPERTY,
                PROPERTY_BRIGHTNESS & 0xFF, PROPERTY_BRIGHTNESS >> 8,
                level & 0xFF, level >> 8,
                0, 0, 0, 0, 0,
            ]
        )
        self._scsi_cmd(cmd)

    def set_orientation(self, value):
        """Orientacao 0..3 (rotacao do controlador LCD)."""
        cmd = bytes(
            [
                0xCD, 0, 0, 0,
                0, 6, USBCMD_SETPROPERTY,
                PROPERTY_ORIENTATION & 0xFF, PROPERTY_ORIENTATION >> 8,
                value & 0xFF, value >> 8,
                0, 0, 0, 0, 0,
            ]
        )
        self._scsi_cmd(cmd)

    # ---- conveniencia ----

    @staticmethod
    def image_to_rgb565(img, big_endian=True):
        """Converte PIL.Image (RGB) em bytes RGB565."""
        if img.mode != "RGB":
            img = img.convert("RGB")
        out = bytearray(img.width * img.height * 2)
        i = 0
        for r, g, b in img.getdata():
            pix = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            if big_endian:
                out[i] = pix >> 8
                out[i + 1] = pix & 0xFF
            else:
                out[i] = pix & 0xFF
                out[i + 1] = pix >> 8
            i += 2
        return bytes(out)

    def show_image(self, img, rotate=0, big_endian=True):
        """Redimensiona/rotaciona uma PIL.Image e manda pra tela inteira."""
        from PIL import ImageOps

        if rotate:
            img = img.rotate(-rotate, expand=True)
        img = ImageOps.fit(img.convert("RGB"), (self.WIDTH, self.HEIGHT))
        self.blit(0, 0, self.WIDTH, self.HEIGHT, self.image_to_rgb565(img, big_endian))
