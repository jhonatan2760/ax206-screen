"""
Envia uma imagem para a tela do suporte de GPU (AX206).

Uso:
  python send_image.py foto.jpg
  python send_image.py foto.jpg --rotate 90       # tela em pe (240x320)
  python send_image.py foto.jpg --brightness 5
  python send_image.py --test                     # padrao de teste de cores
  python send_image.py --fill 000000              # tela preta (limpar)
"""

import argparse
import sys

from PIL import Image

from ax206 import AX206, AX206Error


def test_pattern(w, h):
    """Barras de cor pra validar o formato de pixel."""
    img = Image.new("RGB", (w, h))
    colors = [
        (255, 0, 0), (0, 255, 0), (0, 0, 255),
        (255, 255, 0), (255, 0, 255), (0, 255, 255),
        (255, 255, 255), (0, 0, 0),
    ]
    px = img.load()
    band = w // len(colors)
    for x in range(w):
        c = colors[min(x // band, len(colors) - 1)]
        for y in range(h):
            px[x, y] = c
    return img


def main():
    ap = argparse.ArgumentParser(description="Envia imagem para a tela AX206 do suporte de GPU")
    ap.add_argument("image", nargs="?", help="arquivo de imagem (jpg/png/...)")
    ap.add_argument("--rotate", type=int, default=0, choices=[0, 90, 180, 270])
    ap.add_argument("--brightness", type=int, help="0 a 7")
    ap.add_argument("--test", action="store_true", help="mostra padrao de cores")
    ap.add_argument("--fill", metavar="RRGGBB", help="preenche a tela com uma cor solida (hex)")
    ap.add_argument("--little-endian", action="store_true", help="usa RGB565 little-endian")
    args = ap.parse_args()

    try:
        lcd = AX206()
    except AX206Error as e:
        print(f"Erro: {e}")
        sys.exit(1)

    if args.brightness is not None:
        lcd.set_brightness(args.brightness)
        print(f"Brilho ajustado para {args.brightness}")

    big_endian = not args.little_endian

    if args.fill:
        rgb = args.fill.lstrip("#")
        r, g, b = (int(rgb[i : i + 2], 16) for i in (0, 2, 4))
        img = Image.new("RGB", (lcd.WIDTH, lcd.HEIGHT), (r, g, b))
        lcd.show_image(img, big_endian=big_endian)
        print(f"Tela preenchida com #{rgb}")
    elif args.test:
        img = test_pattern(lcd.WIDTH, lcd.HEIGHT)
        lcd.show_image(img, rotate=args.rotate, big_endian=big_endian)
        print("Padrao de teste enviado: barras vermelho, verde, azul, amarelo, magenta, ciano, branco, preto (esq->dir)")
    elif args.image:
        img = Image.open(args.image)
        lcd.show_image(img, rotate=args.rotate, big_endian=big_endian)
        print(f"Imagem enviada: {args.image}")
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
