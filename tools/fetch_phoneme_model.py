#!/usr/bin/env python3
"""음소 노드용 모델(317MB, Apache-2.0)을 받는다. 저장소에는 넣지 않는다.

    python tools/fetch_phoneme_model.py

리비전을 고정하고(c69750f5), 받은 파일의 크기·SHA256 이 다르면 버린다.
이미 맞는 파일이 있으면 다시 받지 않는다. 표준 라이브러리만 쓴다.
"""
from __future__ import annotations

import hashlib
import os
import sys
import urllib.request
from pathlib import Path

REPO = "onnx-community/wav2vec2-lv-60-espeak-cv-ft-ONNX"
REVISION = "c69750f5043e5e1f8a71ab95dd3b98338c280c92"
URL = f"https://huggingface.co/{REPO}/resolve/{REVISION}/onnx/model_quantized.onnx"
SIZE = 317_712_852
SHA256 = "3d1479b5c70836645a4310902479f7f7e8bbc8c16c58745d918804f4f6f9d120"
OUT = Path(__file__).resolve().parent.parent / "backend" / "app" / "acoustic" / "data" / "model_quantized.onnx"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ok(path: Path) -> bool:
    return path.is_file() and path.stat().st_size == SIZE and sha256(path) == SHA256


def main() -> int:
    if ok(OUT):
        print(f"ok   {OUT.name} (이미 있음, 해시 일치)")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    part = OUT.with_suffix(".onnx.part")
    print(f"get  {URL}\n     → {OUT}  ({SIZE / 1e6:.0f}MB)", flush=True)
    done = 0
    with urllib.request.urlopen(URL, timeout=60) as res, open(part, "wb") as f:
        while True:
            chunk = res.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if done % (32 << 20) < (1 << 20):
                print(f"     {done / 1e6:5.0f} / {SIZE / 1e6:.0f}MB", flush=True)
    if part.stat().st_size != SIZE or sha256(part) != SHA256:
        part.unlink(missing_ok=True)
        print("FAIL 크기 또는 SHA256 불일치 — 파일을 버렸다", file=sys.stderr)
        return 1
    os.replace(part, OUT)
    print(f"done {OUT.name} (SHA256 확인)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
