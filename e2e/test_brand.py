"""브랜드(마디 MADI) E2E — 앱 아이콘·매니페스트·이름이 실제로 연결돼 있는지.

아이콘 원본: Flutter 앱 assets/brand/madi_icon.png(1024). 웹용 크기는 그 원본을 줄인 것이다.

    cd backend && uvicorn app.main:app --port 8768
    python ../e2e/test_brand.py http://localhost:8768
"""
import struct
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))


def png_size(body):
    return struct.unpack(">II", body[16:24]) if body[:8] == b"\x89PNG\r\n\x1a\n" else None


with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 390, "height": 844})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/", wait_until="domcontentloaded")
    page.wait_for_timeout(800)

    check("문서 제목이 '마디 MADI'", page.title() == "마디 MADI", page.title())
    links = page.evaluate("""[...document.querySelectorAll('link[rel~="icon"], link[rel="apple-touch-icon"], link[rel="manifest"]')]
      .map(l => ({ rel: l.rel, href: l.getAttribute('href') }))""")
    hrefs = {l["href"] for l in links}
    check("파비콘·홈 화면 아이콘·매니페스트 링크", {"favicon-32.png", "icon-192.png", "apple-touch-icon.png", "manifest.json"} <= hrefs, str(links))

    want = {"favicon-32.png": 32, "icon-192.png": 192, "apple-touch-icon.png": 180, "icon-512.png": 512, "icon-monochrome-512.png": 512}
    for f, n in want.items():
        r = page.request.get(BASE + "/" + f)
        size = png_size(r.body()) if r.ok else None
        check(f"{f} 가 {n}x{n} PNG 로 열린다", r.ok and size == (n, n), f"{r.status} {size}")

    r = page.request.get(BASE + "/manifest.json")
    m = r.json() if r.ok else {}
    check("매니페스트: 이름 '마디'·standalone", m.get("short_name") == "마디" and m.get("display") == "standalone", str(m.get("short_name")))
    purposes = {i.get("purpose") for i in m.get("icons", [])}
    check("매니페스트: any·maskable·monochrome 아이콘", {"any", "maskable", "monochrome"} <= purposes, str(purposes))
    missing = [i["src"] for i in m.get("icons", []) if not page.request.get(BASE + "/" + i["src"]).ok]
    check("매니페스트의 아이콘 파일이 모두 있다", m.get("icons") and not missing, str(missing))

    brand = page.locator(".login .brand-row")
    check("로그인 화면에 아이콘 + '마디' + 태그라인", brand.count() == 1 and "마디" in brand.inner_text() and "여행을 잇는 한마디" in brand.inner_text()
          and page.evaluate("(() => { const i = document.querySelector('.login .brand-row img'); return !!i && i.complete && i.naturalWidth > 0; })()"))

    check("페이지 JS 오류 없음", not errors, "; ".join(errors[:3]))
    b.close()

print(f"\n{sum(ok for _, ok in results)}/{len(results)} passed")
sys.exit(0 if all(ok for _, ok in results) else 1)
