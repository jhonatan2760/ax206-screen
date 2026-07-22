# ax206-screen

Driver e suíte de configuração para telinhas LCD de suporte de GPU baseadas no chip
Appotech AX206 (vendidas no AliExpress como "GPU bracket com display AIDA64"),
substituindo o AIDA64 por software próprio e aberto.

## Hardware

- Chip: Appotech AX206 com firmware dpf-ax ("USB-Display", VID `1908` PID `0102`)
- LCD: 240x320 (vertical), RGB565 big-endian
- Conexão: micro-USB → header USB 2.0 da placa-mãe
- Driver Windows: libusb-win32 (já instalado pelo pacote do fabricante)

## Nota de depuração (2026-07-22)

Uma faixa no rodapé ficava sem cobrir. Causa raiz: byte extra após o código do comando
no CBW (off-by-one), deslocando as coordenadas do rect — o firmware clone clampava e
desenhava menos linhas. Descoberto capturando o tráfego do AIDA64 com USBPcap e
comparando byte a byte. O layout correto do comando (igual dpf-ax `scsi.c`):
`cd 00 00 00 00 06 <cmd> <params...>` — params começam no byte 7, sem padding.
O mesmo bug existia no set_brightness. Enviar o payload do blit numa única escrita
(URBs de 64 KB) também é o que o AIDA64 faz.

## Protocolo

Comandos SCSI vendor-specific (opcode `0xCD`) encapsulados em USB Mass Storage
Bulk-Only (CBW/CSW). Sub-comandos usados:

- `0x12` blit: retângulo (x0,y0,x1,y1) + pixels RGB565
- `0x01` set property: brilho (property 1, valor 0-7)
- `count=2, sub 0x00` get params: retorna largura/altura (240x320)

## Suíte de configuração (GUI)

```
python suite.py
```

- Enviar imagem com preview, cor sólida e padrão de teste
- Slider de brilho (0-7)
- Slideshow de uma pasta com intervalo configurável
- Minimiza para a bandeja do sistema
- "Iniciar com o Windows" restaurando o último estado (imagem/slideshow/brilho)

## CLI

```
python send_image.py foto.jpg              # envia imagem (redimensiona/corta pra 240x320)
python send_image.py foto.jpg --rotate 90  # rotaciona antes de enviar
python send_image.py --brightness 5        # brilho 0-7
python send_image.py --test                # barras de cores pra teste
python send_image.py --fill 000000         # cor sólida (limpar tela)
```

## Requisitos

- Windows com o driver libusb-win32 da tela instalado (vem no pacote do fabricante,
  ou instale com [Zadig](https://zadig.akeo.ie/) apontando pro dispositivo "USB-Display")
- Python 3.10+ e `pip install pyusb pillow pystray`
- O AIDA64 não pode estar rodando ao mesmo tempo (disputa o mesmo dispositivo USB)

## Arquivos

- `ax206.py` — driver (classe `AX206`: `blit`, `set_brightness`, `show_image`)
- `suite.py` — suíte de configuração com interface gráfica
- `send_image.py` — CLI
- `probe.py` — consulta dimensões do LCD no firmware (diagnóstico)
- `parse_pcap.py` — extrai comandos SCSI de capturas USBPcap (diagnóstico)
