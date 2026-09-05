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
pythonw suite.py
```

(`pythonw` abre sem janela de terminal; com `python` normal também funciona)

- Enviar imagem com preview fiel da telinha e enquadramento por mouse
  (arrastar posiciona, roda do mouse dá zoom, duplo clique reseta)
- Cor sólida e padrão de teste
- Slider de brilho (0-7)
- Slideshow de uma pasta com intervalo configurável
- Minimiza para a bandeja do sistema
- "Iniciar com o Windows" restaurando o último estado (imagem/slideshow/brilho/widget/contextual)
- "Modo contextual (jogos)": sobe o daemon `python -m watcher` como processo
  separado, que detecta jogo em foco / IA na GPU / standby e alimenta o motor
  `engine/`. O daemon abre a própria conexão USB, então a suíte fecha a dela
  antes de iniciar e faz reset USB ao parar. Qualquer outra ação da aba Tela
  para o daemon primeiro. O status da suíte mostra o modo atual lido de
  `watcher_status.json`; se o daemon morrer, o código aparece no status e o
  motivo fica em `watcher.log`.

## Daemon contextual (`watcher/`)

Roda em Windows e Linux (mesma máquina em dual boot, GPU NVIDIA).

```
python -m watcher            # daemon (fica rodando)
python -m watcher --status   # estado do daemon em execução
python -m watcher --once     # detecta o contexto uma vez e imprime
```

- Um único processo é dono do USB; a suíte só edita os JSONs, que o daemon
  recarrega sozinho quando o arquivo muda.
- Sobrevive a tela desconectada (espera e reconecta), firmware fora de
  sincronia (reset USB) e exceção no render (loga e segue).
- `watcher.log` rotativo (1 MB x 3) com troca de modo e uma linha "vivo" a
  cada 5 min; `watcher_status.json` atualizado a cada 2 s; instância única por
  `watcher.pid`.
- Detecção: layout do editor atribuído ao exe > jogo pela janela em foco
  (tela cheia + GPU acima do limite, ou exe na lista) > fallback por processos
  gráficos na GPU via NVML (Wayland) > IA (Ollama com GPU ocupada) > standby.
- No Linux, jogos Proton/Wine aparecem com o mesmo nome de exe do Windows
  (ex.: `cyberpunk2077.exe`), então a lista da aba Jogos vale nos dois.

### Windows

A suíte com "Iniciar com o Windows" já sobe o daemon no boot. Alternativa sem
suíte: `install\windows_task.ps1` registra uma tarefa agendada no logon que
reinicia o daemon se ele cair. Use um dos dois, não ambos.

### Linux

```
pip install pyusb pillow psutil pynvml
sudo apt install x11-utils libusb-1.0-0      # xprop/xwininfo p/ janela em foco
bash install/linux_install.sh
```

O script instala a regra udev (acesso sem root), o quirk que impede o kernel
de tratar a tela como pendrive (`usb-storage quirks=1908:0102:i`) e uma
unidade systemd de usuário com `Restart=always`. Fontes: Liberation Sans ou
DejaVu no lugar da Arial. GameMode (Feral), se instalado, conta como sinal de
jogo. O ícone do exe é API Win32; no Linux o painel usa a capa da Steam ou só
o título.

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
