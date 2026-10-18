#!/usr/bin/env python3
"""Transport Deep Dive helper.
  daily.py build CONTENT.html YYYY-MM-DD   -> TransportDeepDive_DATE.pdf + pages.json (item id -> PDF page)
  daily.py publish YYYY-MM-DD [keep_days]  -> remove PDFs older than keep_days (default 7), rebuild index.html, commit, push
Run from the repo root. Requires python3 playwright, pdftotext (poppler), node/npm."""
import sys, os, re, json, subprocess, datetime, glob, shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_DIR = '/tmp/ddfonts'

def ensure_fonts():
    p = f'{FONT_DIR}/node_modules/@fontsource/noto-sans-thai/files'
    if not os.path.isdir(p):
        os.makedirs(FONT_DIR, exist_ok=True)
        subprocess.run(['npm', 'init', '-y'], cwd=FONT_DIR, capture_output=True)
        subprocess.run(['npm', 'i', '@fontsource/noto-sans-thai@5'], cwd=FONT_DIR, check=True, capture_output=True)
    return p

def thai_date(s):
    y, m, d = map(int, s.split('-'))
    months = ['มกราคม','กุมภาพันธ์','มีนาคม','เมษายน','พฤษภาคม','มิถุนายน','กรกฎาคม','สิงหาคม','กันยายน','ตุลาคม','พฤศจิกายน','ธันวาคม']
    return f'{d} {months[m-1]} {y+543}'

def build(content_path, date):
    fo = ensure_fonts()
    ff = ''
    for w in (400, 600, 700):
        for sub, rng in (('thai', 'U+0E01-0E5B,U+200C-200D,U+25CC'),
                         ('latin', 'U+0000-00FF,U+2013-2014,U+2018-201D,U+2022,U+2026,U+2212,U+25A0,U+25CF')):
            f = f'{fo}/noto-sans-thai-{sub}-{w}-normal.woff2'
            if os.path.exists(f):
                ff += f'@font-face{{font-family:"NST";font-weight:{w};src:url("file://{f}");unicode-range:{rng}}}\n'
    css = open(f'{ROOT}/tools/style.css', encoding='utf8').read()
    body = open(content_path, encoding='utf8').read()
    html = f'''<!doctype html><html lang="th"><head><meta charset="utf-8"><style>{ff}{css}</style></head><body>
<div class="wrap"><div class="cover"><h1 style="font-family:var(--f-display);font-size:28px;margin:0">Transport Deep Dive</h1>
<p style="margin:0;color:var(--muted)">ประจำวันที่ {thai_date(date)} · TMS Transport Management Division</p></div>
{body}</div></body></html>'''
    tmp = f'{ROOT}/_build.html'
    open(tmp, 'w', encoding='utf8').write(html)
    out = f'{ROOT}/TransportDeepDive_{date}.pdf'
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        exe = '/opt/pw-browsers/chromium'
        b = p.chromium.launch(executable_path=exe) if os.path.exists(exe) else p.chromium.launch()
        pg = b.new_page()
        pg.goto('file://' + tmp)
        pg.wait_for_timeout(800)
        pg.pdf(path=out, format='A4', print_background=True,
               margin={'top': '14mm', 'bottom': '14mm', 'left': '12mm', 'right': '12mm'})
        b.close()
    os.remove(tmp)
    n = int(re.search(r'Pages:\s+(\d+)', subprocess.run(['pdfinfo', out], capture_output=True, text=True).stdout).group(1))
    ids = re.findall(r'data-item="(\d+\.\d+)"', body)
    pages = {}
    for i in range(1, n + 1):
        t = subprocess.run(['pdftotext', '-f', str(i), '-l', str(i), out, '-'], capture_output=True, text=True).stdout
        for it in ids:
            if it not in pages and re.search(r'#' + re.escape(it) + r'(?!\d)', t):
                pages[it] = i
    json.dump({'pdf': os.path.basename(out), 'total_pages': n, 'pages': pages, 'missing': [i for i in ids if i not in pages]},
              open(f'{ROOT}/pages.json', 'w'), ensure_ascii=False, indent=1)
    print(json.dumps({'pdf': os.path.basename(out), 'size_kb': os.path.getsize(out) // 1024, 'total_pages': n,
                      'pages': pages, 'missing': [i for i in ids if i not in pages]}, ensure_ascii=False))

def publish(date, keep=7):
    today = datetime.date.fromisoformat(date)
    for f in glob.glob(f'{ROOT}/TransportDeepDive_*.pdf'):
        m = re.search(r'_(\d{4}-\d{2}-\d{2})\.pdf$', f)
        if m and (today - datetime.date.fromisoformat(m.group(1))).days > keep:
            subprocess.run(['git', 'rm', '-q', '-f', f], cwd=ROOT, check=True)
            print('removed', os.path.basename(f))
    files = sorted((os.path.basename(f) for f in glob.glob(f'{ROOT}/TransportDeepDive_*.pdf')), reverse=True)
    li = '\n'.join(f'<li><a href="{f}">{f[len("TransportDeepDive_"):-4]}</a></li>' for f in files)
    open(f'{ROOT}/index.html', 'w', encoding='utf8').write(
        f'<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>Transport Deep Dive</title><body style="font-family:sans-serif;max-width:560px;margin:24px auto;padding:0 16px">'
        f'<h1>Transport Deep Dive</h1><p>รายงานย้อนหลัง {keep} วัน</p><ul>{li}</ul></body>')
    if os.path.exists(f'{ROOT}/pages.json'):
        os.remove(f'{ROOT}/pages.json')
    env = dict(os.environ)
    run = lambda *a: subprocess.run(['git', '-c', 'user.name=Transport Deep Dive Bot', '-c', 'user.email=noreply@anthropic.com', *a],
                                    cwd=ROOT, env=env, capture_output=True, text=True)
    run('add', '-A')
    msg = f'Deep Dive {date}\n\nCo-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>'
    c = run('commit', '-m', msg)
    print(c.stdout.strip() or c.stderr.strip())
    for attempt in range(2):
        r = run('push', 'origin', 'HEAD:main')
        if r.returncode == 0:
            print('pushed'); return
        run('pull', '--rebase', 'origin', 'main')
    print('PUSH FAILED', r.stderr); sys.exit(1)

if __name__ == '__main__':
    a = sys.argv[1:]
    if a[:1] == ['build'] and len(a) == 3: build(a[1], a[2])
    elif a[:1] == ['publish'] and len(a) >= 2: publish(a[1], int(a[2]) if len(a) > 2 else 7)
    else: print(__doc__); sys.exit(2)
