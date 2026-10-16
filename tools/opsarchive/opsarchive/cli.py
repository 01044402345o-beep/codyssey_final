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
        q.add_argument("--no-redeploy", action="store_true", help="재배포를 건너뛴다(publish/rotate)")

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
    return parser


def main(argv: list[str] | None = None) -> int:
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
                                       env_key=args.env_key))
            else:
                _print(commands.rotate(args.service, args.key, phrase, env_key=args.env_key,
                                       base_url=args.base_url,
                                       redeploy=not args.no_redeploy))
            return 0
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
    except commands.CommandError as exc:
        print("실패: " + exc.code, file=sys.stderr)
        return 3
    except Exception as exc:            # noqa: BLE001 — 값만 남긴다(스택에 비밀을 싣지 않는다)
        print("실패: %s" % type(exc).__name__, file=sys.stderr)
        return 3
    return 2
