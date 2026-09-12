#!/usr/bin/env python3
"""Парсер каталога валют BestChange. Поддерживает 2 формата входа:
  1) обычный HTML списка направлений (<a href="/slug-to-..." id="alc..">Name <span>TICK</span>);
  2) сохранённый вид DevTools/Inspect (атрибуты обёрнуты в <span class="html-attribute-value">,
     теги экранированы &lt;span&gt;). Именно так часто «сохраняют» страницу.

Валюта берётся по ЛЕВОМУ якорю (alc<id>): слаг из href /<self>-to-…, + name + ticker.
Категория — по ближайшему заголовку группы (glc) выше; верхний блок без заголовка = «Криптовалюты».

Выход: currencies.json {categories:[...], currencies:{slug:{id,name,ticker,category}}}.
Запуск: python3 parse_catalog.py <файл.html> [-o currencies.json]
"""
import html as htmlmod
import json
import re
import sys

# --- обычный формат ---
LC_PLAIN = re.compile(
    r'<a\s+href="/([^"?]+?)-to-[^"]*\.html"\s+id="alc(\d+)"[^>]*>\s*([^<]+?)\s*<span>\s*([^<]+?)\s*</span>',
    re.S | re.I)
GRP_PLAIN = re.compile(r'id="tlc\d+"[^>]*class="[^"]*glc[^"]*"[^>]*>\s*([^<]+?)\s*<', re.S | re.I)

# --- формат DevTools (подсвеченный) ---
LC_DEV = re.compile(
    r'bestchange\.com/([a-z0-9-]+?)-to-[a-z0-9-]+\.html"'      # 1 слаг (в реальном href)
    r'.{0,220}?>alc(\d+)</span>'                                # 2 id (привязка к alc — это lc-якорь)
    r".{0,300}?clk\(\d+, 'lc'\)</span>\"&gt;</span>\s*([^<]+?)\s*"   # 3 name
    r'<span[^>]*>&lt;span&gt;</span>([A-Za-z0-9]+)',            # 4 ticker
    re.S)
GRP_DEV = re.compile(r'>glc</span>".{0,120}?&gt;</span>([^<]+?)<span[^>]*>&lt;/td&gt;', re.S)


def parse(text):
    dev = 'html-attribute-value' in text
    lc_re = LC_DEV if dev else LC_PLAIN
    gr_re = GRP_DEV if dev else GRP_PLAIN

    groups = [(m.start(), htmlmod.unescape(m.group(1).strip())) for m in gr_re.finditer(text)]
    cats = []
    for _, n in groups:
        if n not in cats:
            cats.append(n)

    def cat_at(pos):
        cur = "Криптовалюты"
        for gpos, n in groups:
            if gpos < pos:
                cur = n
            else:
                break
        return cur

    curr = {}
    for m in lc_re.finditer(text):
        slug = m.group(1)
        curr[slug] = {"id": int(m.group(2)),
                      "name": htmlmod.unescape(m.group(3).strip()),
                      "ticker": htmlmod.unescape(m.group(4).strip()),
                      "category": cat_at(m.start())}
    return (["Криптовалюты"] + cats) if curr else cats, curr


def main():
    if len(sys.argv) < 2:
        raise SystemExit("использование: parse_catalog.py <файл.html> [-o out.json]")
    src = sys.argv[1]
    out = sys.argv[sys.argv.index("-o") + 1] if "-o" in sys.argv else "currencies.json"
    text = open(src, encoding="utf-8", errors="replace").read()
    cats, curr = parse(text)
    json.dump({"categories": cats, "currencies": curr},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"валют: {len(curr)} · категорий: {len(cats)} → {out}")
    if cats:
        print("категории:", ", ".join(cats))
    for s, c in list(curr.items())[:6]:
        print(f"  {s} -> id={c['id']} {c['name']} [{c['ticker']}] ({c['category']})")


if __name__ == "__main__":
    main()
