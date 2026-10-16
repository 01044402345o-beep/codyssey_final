"""opsarchive CLI — 관리자 전용. 앱과 독립 프로세스로 돈다.

패스프레이즈는 **절대 명령줄 인자로 받지 않는다**(프로세스 목록에 남는다). TTY 프롬프트로만 받는다.

    python -m opsarchive selftest
    python -m opsarchive keygen [--dir ~/.opsarchive]
    python -m opsarchive publish --service <name> --key <file> [--base-url <url>]
    python -m opsarchive doctor  --service <name> --key <file> [--base-url <url>]
    python -m opsarchive rotate  --service <name> --key <file> [--base-url <url>]
    python -m opsarchive list    --project <id> --sa <json> [--limit 200]
    python -m opsarchive decrypt --project <id> --sa <json> --id <archive> --key <file> [--out <dir>]
    python -m opsarchive tui
"""

from __future__ import annotations

import argparse
import json
import sys

from . import VERSION, commands
from . import chain, config, container as C, firebase, gcp, pins, render, witness


def _print(data: object) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="opsarchive", description="탈퇴 실패 증거 봉인 도구")
    parser.add_argument("--version", action="version", version="opsarchive " + VERSION)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("selftest", help="로컬 왕복 검증(봉인·해제·변조·키 잠금)")

    p = sub.add_parser("keygen", help="관리자 키쌍 생성(개인키는 잠가서 저장)")
    p.add_argument("--dir", default="", help="개인키 저장 디렉터리(기본 ~/.opsarchive)")

    for name, help_text in (("publish", "공개키를 Render 환경변수에 발행하고 재배포"),
                            ("doctor", "로컬 키와 배포된 공개키 지문 대조"),
                            ("rotate", "새 키 생성·발행(옛 개인키는 보관)")):
        q = sub.add_parser(name, help=help_text)
        q.add_argument("--service", required=True, help="Render 서비스 이름(또는 ID)")
        q.add_argument("--key", required=True, help="개인키 파일 경로")
        q.add_argument("--env-key", default=commands.DEFAULT_ENV_KEY)
        q.add_argument("--base-url", default="", help="앱 주소(/health 지문 대조)")
        q.add_argument("--pin", default="", help="핀 파일 경로(doctor: /health 와 대조)")
        q.add_argument("--no-redeploy", action="store_true", help="재배포를 건너뛴다(publish/rotate)")

    q = sub.add_parser("pin", help="개인키에서 역산한 지문으로 핀 파일을 만든다(관리자 오프라인)")
    q.add_argument("--key", required=True, help="개인키 파일 경로")
    q.add_argument("--out", default="security/evidence-key-pin.json")
    q.add_argument("--health-url", required=True, help="앱 주소(핀에 기록)")
    q.add_argument("--generation", type=int, default=None, help="세대(기본: 기존+1)")
    q.add_argument("--commit", default="", help="회전을 일으킨 커밋 sha")
    q.add_argument("--note", default="")
    q.add_argument("--sign-key", default="", help="서명 키 파일(주면 그 공개키도 핀에 넣는다)")

    q = sub.add_parser("signkey", help="관리자 서명 키(Ed25519) 생성 — 체크포인트 서명용")
    q.add_argument("--dir", default="", help="저장 디렉터리(기본 ~/.opsarchive)")

    q = sub.add_parser("anchor", help="아카이브 체인을 확인하고 체크포인트를 서명해 앵커한다")
    q.add_argument("--project", required=True)
    q.add_argument("--sa", required=True)
    q.add_argument("--sign-key", required=True, help="서명 키 파일 경로")
    q.add_argument("--out", default="checkpoints")

    q = sub.add_parser("observe", help="플랫폼 접근 로그(앱 밖 증인)와 체인 시도 항목을 비교한다")
    q.add_argument("--project", required=True)
    q.add_argument("--sa", required=True)
    q.add_argument("--service", required=True, help="Render 서비스 이름")
    q.add_argument("--path", default="/account/erase")
    q.add_argument("--minutes", type=int, default=60, help="관측 창(분)")
    q.add_argument("--tolerance", type=int, default=0, help="한 요청이 여러 줄로 찍히는 플랫폼 보정")

    q = sub.add_parser("verify-chain", help="체크포인트 서명·연속성·사라진 아카이브·챌린지를 검증한다")
    q.add_argument("--project", required=True)
    q.add_argument("--sa", required=True)
    q.add_argument("--pin", default="security/evidence-key-pin.json")
    q.add_argument("--out", default="checkpoints")
    q.add_argument("--challenge", default="",
                   help="사용자가 제시한 챌린지(영수증). 앵커 범위 안에 있는지 본다")

    q = sub.add_parser("pin-check", help="핀 파일과 배포된 /health 를 대조한다(CI 와 같은 검사)")
    q.add_argument("--pin", default="security/evidence-key-pin.json")
    q.add_argument("--health-url", default="", help="핀에 기록된 주소를 덮어쓴다")

    q = sub.add_parser("iam-check", help="앱 서비스 계정이 증거를 지울 수 있는지 시험한다(카나리아)")
    q.add_argument("--project", required=True)
    q.add_argument("--sa", required=True, help="앱 서비스 계정 JSON 경로")

    q = sub.add_parser("list", help="봉인 아카이브 목록(Firestore)")
    q.add_argument("--project", required=True)
    q.add_argument("--sa", required=True, help="서비스 계정 JSON 경로")
    q.add_argument("--limit", type=int, default=200)
    q.add_argument("--json", action="store_true", help="원본 JSON 출력")

    q = sub.add_parser("decrypt", help="아카이브를 내려받아 개인키로 연다")
    q.add_argument("--project", required=True)
    q.add_argument("--sa", required=True)
    q.add_argument("--id", required=True, dest="archive_id")
    q.add_argument("--key", required=True)
    q.add_argument("--out", default="", help="평문을 저장할 디렉터리(없으면 요약만)")

    sub.add_parser("tui", help="rich 기반 화면(없으면 안내만)")
    sub.add_parser("gui", help="관리자 창(tkinter — 설치 필요 없음). 키·발행·검증을 버튼으로")
    return parser


def main(argv: list[str] | None = None) -> int:
    config.bootstrap()                     # .env 를 환경변수로 올리고 settings.json 을 읽는다
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "selftest":
            _print(commands.selftest())
            return 0
        if args.cmd == "keygen":
            made = commands.keygen(out_dir=args.dir or None)
            made.pop("path", None)          # 경로는 로컬 정보 — 화면에는 지문과 공개키만
            _print(made)
            return 0
        if args.cmd in ("publish", "doctor", "rotate"):
            phrase = commands.ask_passphrase(prompt="개인키 패스프레이즈: ")
            if args.cmd == "publish":
                _print(commands.publish(args.service, args.key, phrase, env_key=args.env_key,
                                        redeploy=not args.no_redeploy, base_url=args.base_url))
            elif args.cmd == "doctor":
                _print(commands.doctor(args.service, args.key, phrase, base_url=args.base_url,
                                       env_key=args.env_key, pin_file=args.pin))
            else:
                _print(commands.rotate(args.service, args.key, phrase, env_key=args.env_key,
                                       base_url=args.base_url,
                                       redeploy=not args.no_redeploy))
            return 0
        if args.cmd == "pin":
            phrase = commands.ask_passphrase(prompt="개인키 패스프레이즈: ")
            signing = None
            if args.sign_key:
                signing = C.sign_public(C.load_private_key(
                    args.sign_key, commands.ask_passphrase(prompt="서명키 패스프레이즈: ")))
            _print(commands.make_pin(args.key, phrase, health_url=args.health_url, out=args.out,
                                     generation=args.generation, commit=args.commit, note=args.note,
                                     signing_public=signing))
            return 0
        if args.cmd == "signkey":
            made = commands.signkey(out_dir=args.dir or None)
            made.pop("path", None)
            _print(made)
            return 0
        if args.cmd == "anchor":
            phrase = commands.ask_passphrase(prompt="서명키 패스프레이즈: ")
            _print(commands.anchor(args.project, args.sa, args.sign_key, phrase, out_dir=args.out))
            return 0
        if args.cmd == "observe":
            result = commands.observe_requests(args.project, args.sa, args.service,
                                               path=args.path, since_minutes=args.minutes,
                                               tolerance=args.tolerance)
            _print(result)
            return 0 if result.get("ok") else 1
        if args.cmd == "verify-chain":
            result = commands.verify_chain(args.project, args.sa, args.pin, out_dir=args.out,
                                           challenge=args.challenge)
            _print(result)
            return 0 if result.get("ok") else 1
        if args.cmd == "pin-check":
            result = commands.check_pin(args.pin, health_url=args.health_url)
            _print(result)
            return 0 if result.get("ok") in (True, None) else 1
        if args.cmd == "iam-check":
            result = commands.iam_check(args.project, args.sa)
            _print(result)
            return 0 if result.get("verdict") == "ok" else 1
        if args.cmd == "list":
            pre = commands.firebase_preflight(args.project)
            if not pre["firebase_cli"]:
                print("참고: firebase CLI 가 없어 사전 점검을 건너뜁니다(읽기는 서비스 계정으로 계속).", file=sys.stderr)
            rows = commands.list_archives(args.project, args.sa, limit=args.limit)
            if args.json:
                _print(rows)
            else:
                for row in rows:
                    print("%s  %sB  key=%s  %s  %s초 전" % (
                        row.get("_id", ""), row.get("size", "?"), row.get("key_id", "?"),
                        row.get("trigger", "?"), row.get("age_seconds", "?")))
            return 0
        if args.cmd == "decrypt":
            phrase = commands.ask_passphrase(prompt="개인키 패스프레이즈: ")
            report = commands.decrypt_archive(args.project, args.sa, args.archive_id, args.key,
                                              phrase, out_dir=args.out or None)
            _print(report)
            return 0
        if args.cmd == "tui":
            from . import tui
            return tui.run()
        if args.cmd == "gui":
            from . import gui
            return gui.run()
    except (commands.CommandError, render.RenderError, gcp.GcpError, firebase.FirebaseError,
            pins.PinError, chain.ChainError, C.ContainerError, witness.WitnessError) as exc:
        # 원인을 **코드로** 보여준다(RenderError 만 던지면 운영자가 원인을 알 수 없다 —
        # 실제로 그 때문에 막힌 사례가 있었다). 값에는 토큰·개인키가 담기지 않는다.
        print("실패: " + (getattr(exc, "code", "") or type(exc).__name__), file=sys.stderr)
        return 3
    except Exception as exc:            # noqa: BLE001 — 값만 남긴다(스택에 비밀을 싣지 않는다)
        print("실패: %s" % type(exc).__name__, file=sys.stderr)
        return 3
    return 2
