#!/usr/bin/env python3
"""Hugging Face Space(Docker)에 올릴 음소 노드 폴더를 만든다. 노드에 필요한 파일만 복사한다.

    python tools/make_hf_space.py <출력 폴더>

만든 폴더를 Space 저장소에 그대로 올린다(git push 또는 웹 업로드). 토큰은 Space Settings → Secrets 에
PHONEME_TOKEN 으로 넣는다 — 폴더에는 넣지 않는다. 자세한 순서: backend/phoneme-node/FALLBACK.md
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = [
    "backend/phoneme-node/requirements-phoneme.txt",
    "backend/app/__init__.py",
    "backend/app/phonemes.py",
    "backend/app/speech_compare.py",
    "tools/fetch_phoneme_model.py",
]
DIRS = ["backend/app/acoustic", "backend/app/lexicon"]
SKIP = {"__pycache__"}
SKIP_SUFFIX = (".onnx", ".part", ".pyc")

README = """---
title: MADI phoneme node
emoji: 🔊
colorFrom: gray
colorTo: green
sdk: docker
app_port: 7860
pinned: false
---

마디(MADI) 음소 노드 — 말하기 녹음에서 실제 소리 기준 음소를 찾는다(wav2vec2-lv-60-espeak-cv-ft int8, Apache-2.0).
`/healthz`(공개), `/phoneme-check`(X-Phoneme-Token 필요). 음성은 저장하지 않는다.
Settings → Secrets 에 `PHONEME_TOKEN`(24자 이상)을 넣어야 시작한다.
"""


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    out = Path(sys.argv[1]).resolve()
    if out.exists() and any(out.iterdir()):
        print(f"{out} 가 비어 있지 않다 — 빈 폴더를 지정하라")
        return 2
    out.mkdir(parents=True, exist_ok=True)
    for f in FILES:
        (out / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / f, out / f)
    for d in DIRS:
        for src in (ROOT / d).rglob("*"):
            if src.is_dir() or SKIP & set(src.parts) or src.name.endswith(SKIP_SUFFIX):
                continue
            dst = out / src.relative_to(ROOT)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    shutil.copy2(ROOT / "backend/phoneme-node/Dockerfile", out / "Dockerfile")   # Space 는 루트의 Dockerfile 을 쓴다
    (out / "README.md").write_text(README, encoding="utf-8")
    n = sum(1 for p in out.rglob("*") if p.is_file())
    print(f"done: {out} ({n} files) — Space(SDK: Docker)에 올리고 Secrets 에 PHONEME_TOKEN 을 넣는다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
