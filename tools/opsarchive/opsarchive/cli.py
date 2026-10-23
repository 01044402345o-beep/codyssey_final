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
import os
import sys

from . import VERSION, commands, kms
from . import chain, config, container as C, entropy, firebase, gcp, pins, render, witness


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
    q.add_argument("--out", default=config.read_settings().get("pin_path") or "",
                   help="핀 파일 경로(기본: 저장소 밖 ~/.opsarchive/evidence-key-pin.json)")
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
    q.add_argument("--sign-key", default="", help="서명 키 파일 경로(--kms-key 를 쓰면 필요 없음)")
    q.add_argument("--out", default="checkpoints")
    q.add_argument("--kms-key", default="", help="Cloud KMS 키 버전(projects/.../cryptoKeyVersions/N) — 이 키로 서명")
    q.add_argument("--store", choices=["local", "firestore"], default="local",
                   help="체크포인트를 둘 곳(firestore = evidence_checkpoints, 만들기만 가능)")

    q = sub.add_parser("kms-check", help="Cloud KMS 서명 키 점검(알고리즘·공개키·시험 서명)")
    q.add_argument("--kms-key", required=True)
    q.add_argument("--sa", required=True, help="서비스 계정 JSON 또는 env:<토큰 변수>")

    q = sub.add_parser("kms-pin-add", help="KMS 공개키를 핀의 자동 서명 키로 넣는다(관리자가 직접)")
    q.add_argument("--kms-key", required=True)
    q.add_argument("--sa", required=True)
    q.add_argument("--pin", default=config.read_settings().get("pin_path") or "")

    q = sub.add_parser("kms-audit", help="KMS 서명 감사 대조 — 감사 로그의 서명(누가·언제)과 체크포인트를 맞춰 짝 없는 서명을 찾는다")
    q.add_argument("--project", required=True)
    q.add_argument("--sa", required=True, help="roles/logging.privateLogViewer 가 있는 계정")
    q.add_argument("--kms-key", required=True)
    q.add_argument("--days", type=float, default=7)
    q.add_argument("--pin", default=config.read_settings().get("pin_path") or "")

    q = sub.add_parser("auto-anchor", help="(CI) 체크포인트 검증 → KMS 로 새 체크포인트(Firestore). 핀은 Actions 변수")
    q.add_argument("--project", required=True)
    q.add_argument("--sa", required=True, help="CI 는 env:GCP_ACCESS_TOKEN")
    q.add_argument("--kms-key", required=True)
    q.add_argument("--max-age-hours", type=float, default=13, help="마지막 체크포인트가 이보다 오래되면 실패")

    q = sub.add_parser("env-set", help="Render 환경변수 하나를 올린다(값은 파일/표준입력으로만 받는다)")
    q.add_argument("--service", required=True)
    q.add_argument("--key", required=True, help="변수 이름(예: FIREBASE_SERVICE_ACCOUNT_JSON)")
    q.add_argument("--from-file", default="", help="값이 담긴 파일 경로(권장)")
    q.add_argument("--stdin", action="store_true", help="표준입력에서 값을 읽는다")

    q = sub.add_parser("env-read", help="환경변수가 설정돼 있는지 확인한다(값은 길이만)")
    q.add_argument("--service", required=True)
    q.add_argument("--key", required=True)

    q = sub.add_parser("deploy", help="Render 서비스를 이름으로 찾아 재배포한다")
    q.add_argument("--service", required=True, help="Render 서비스 이름(또는 ID)")
    q.add_argument("--timeout", type=int, default=300, help="배포 대기 시간(초)")

    # 정책(마인드맵 노드) — GUI 와 같은 함수. 자동 반영이 켜져 있으면 값을 바꾸는 즉시 Render 에 올리고 재배포·확인한다.
    sub.add_parser("policy-show", help="정책 노드 값과 자동 반영 상태")
    q = sub.add_parser("policy-set", help="노드 값을 바꿔 정책에 저장(자동 반영이 켜져 있으면 Render 반영·재배포·확인까지)")
    q.add_argument("node", help="노드 ID(예: daily_cap)")
    q.add_argument("value", help="값(토글은 on/off)")
    q.add_argument("--service", default="", help="Render 서비스 이름(비우면 settings.json)")
    g = q.add_mutually_exclusive_group()
    g.add_argument("--apply", dest="apply", action="store_true", default=None, help="자동 반영 설정과 관계없이 반영")
    g.add_argument("--no-apply", dest="apply", action="store_false", help="정책에만 저장")
    q = sub.add_parser("policy-apply", help="정책과 Render(또는 Cloud Run)를 대조해 바뀐 것만 올리고 재배포·확인(변경 모아 반영)")
    q.add_argument("--service", default="")
    q.add_argument("--no-redeploy", action="store_true", help="값만 올린다(Render 만 — Cloud Run 은 값 변경이 곧 새 리비전)")
    q.add_argument("--target", choices=["render", "cloudrun"], default="render",
                   help="cloudrun: settings.json 의 project_id·cloudrun_region·cloudrun_service(또는 --service)")
    q = sub.add_parser("auto-apply", help="자동 반영 켜기/끄기/상태(settings.json; 환경변수 OPSARCHIVE_AUTO_APPLY 가 우선)")
    q.add_argument("mode", choices=["on", "off", "status"])

    q = sub.add_parser("rules-status", help="저장소 firestore.rules 와 배포된 규칙을 대조한다(읽기 전용)")
    q.add_argument("--project", required=True)
    q.add_argument("--sa", required=True, help="서비스 계정 JSON(Firebase Rules 읽기 권한)")

    q = sub.add_parser("rules-deploy", help="firestore.rules 를 그 프로젝트에 배포하고 반영을 확인한다(되돌릴 수 없음)")
    q.add_argument("--project", required=True)
    q.add_argument("--sa", default="", help="있으면 배포 뒤 배포본을 다시 읽어 저장소 파일과 대조한다")
    q.add_argument("--dry-run", action="store_true", help="문법 검사만 하고 배포하지 않는다")
    q.add_argument("--yes", action="store_true", help="확인 질문 없이 배포(자동화용)")

    q = sub.add_parser("pin-publish", help="핀의 공개값을 GitHub Actions 변수로 올린다(저장소 파일로는 올리지 않는다)")
    q.add_argument("--pin", default=config.read_settings().get("pin_path") or "")
    q.add_argument("--repo", default=os.environ.get("EVIDENCE_GH_REPO", "01044402345o-beep/codyssey_final"))
    q.add_argument("--dry-run", action="store_true", help="올리지 않고 어떤 변수가 등록될지 보기만 한다")

    q = sub.add_parser("pin-remote-check", help="원격 Actions 변수와 로컬 핀을 대조한다")
    q.add_argument("--pin", default=config.read_settings().get("pin_path") or "")
    q.add_argument("--repo", default=os.environ.get("EVIDENCE_GH_REPO", "01044402345o-beep/codyssey_final"))

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
    q.add_argument("--pin", default=config.read_settings().get("pin_path") or "",
                   help="핀 파일 경로(기본: 저장소 밖 ~/.opsarchive/evidence-key-pin.json)")
    q.add_argument("--out", default="checkpoints")
    q.add_argument("--challenge", default="",
                   help="사용자가 제시한 챌린지(영수증). 앵커 범위 안에 있는지 본다")
    q.add_argument("--source", choices=["local", "firestore", "both"], default="local",
                   help="체크포인트를 읽을 곳(firestore = 자동 앵커가 쌓은 것)")
    q.add_argument("--max-age-hours", type=float, default=0, help="마지막 체크포인트가 이보다 오래되면 실패(0=검사 안 함)")

    q = sub.add_parser("pin-check", help="핀 파일과 배포된 /health 를 대조한다(CI 와 같은 검사)")
    q.add_argument("--pin", default=config.read_settings().get("pin_path") or "",
                   help="핀 파일 경로(기본: 저장소 밖 ~/.opsarchive/evidence-key-pin.json)")
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

    q = sub.add_parser("rand", help="OS 를 감지해 CSPRNG 명령으로 무작위 값을 만든다")
    q.add_argument("--length", type=int, default=32)
    q.add_argument("--encoding", choices=["hex", "base64", "chars"], default="hex")
    q.add_argument("--command", default=None, help="직접 지정할 명령(비우면 OS 기본값, 빈 문자열이면 파이썬 secrets)")
    q.add_argument("--show-command", action="store_true", help="실행한 명령도 출력")
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
            if args.kms_key:
                _print(commands.anchor(args.project, args.sa, "", "", out_dir=args.out,
                                       kms_key=args.kms_key, target=args.store))
                return 0
            if not args.sign_key:
                print("--sign-key 또는 --kms-key 가 필요합니다.", file=sys.stderr)
                return 2
            phrase = commands.ask_passphrase(prompt="서명키 패스프레이즈: ")
            _print(commands.anchor(args.project, args.sa, args.sign_key, phrase, out_dir=args.out,
                                   target=args.store))
            return 0
        if args.cmd == "kms-check":
            _print(commands.kms_check(args.kms_key, args.sa))
            return 0
        if args.cmd == "kms-pin-add":
            _print(commands.kms_pin_add(args.pin, args.kms_key, args.sa))
            return 0
        if args.cmd == "kms-audit":
            result = commands.kms_audit_check(args.project, args.sa, args.kms_key, days=args.days, pin_path=args.pin)
            _print(result)
            return 1 if result.get("error") else 0
        if args.cmd == "auto-anchor":
            result = commands.auto_anchor(args.project, args.sa, args.kms_key, max_age_hours=args.max_age_hours)
            _print(result)
            return 0 if result.get("anchored") else 1
        if args.cmd == "env-set":
            # 값은 **절대 명령줄 인자로 받지 않는다**(셸 히스토리·프로세스 목록에 남는다).
            value = ""
            source = ""
            if args.from_file:
                path = config.resolve(args.from_file)      # 저장소 상대 경로도 허용
                try:
                    with open(path, "r", encoding="utf-8-sig") as fh:
                        value = fh.read()
                    source = path
                except OSError as exc:
                    print("실패: no_value_file('%s') — %s" % (path, exc.strerror or "열 수 없음"),
                          file=sys.stderr)
                    print("힌트: .env 의 GOOGLE_APPLICATION_CREDENTIALS 경로를 쓰려면 --from-file 을 생략하세요.",
                          file=sys.stderr)
                    return 3
            elif args.stdin:
                value, source = sys.stdin.read(), "stdin"
            elif os.environ.get(args.key):
                # .env(또는 셸 환경)에 같은 이름이 있으면 그것을 쓴다 — 같은 값을 두 번 입력하지 않게.
                # (PowerShell 세션에는 .env 값이 없다. 그래서 `$env:X | ...` 는 빈 값이 됐다.)
                value, source = os.environ[args.key], ".env/환경변수 %s" % args.key
            elif args.key == "FIREBASE_SERVICE_ACCOUNT_JSON" and os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
                # .env 에 이미 적어 둔 서비스 계정 경로를 기본값으로 쓴다(같은 경로를 또 입력하지 않게).
                path = config.resolve(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
                try:
                    with open(path, "r", encoding="utf-8-sig") as fh:
                        value = fh.read()
                    source = path
                except OSError as exc:
                    print("실패: no_value_file('%s') — %s" % (path, exc.strerror or "열 수 없음"),
                          file=sys.stderr)
                    return 3
            else:
                print("실패: --from-file <파일> 또는 --stdin 을 쓰세요(값을 인자로 받지 않습니다)",
                      file=sys.stderr)
                return 2
            result = commands.env_set(args.service, args.key, value.strip())
            result["source"] = source
            _print(result)
            return 0
        if args.cmd == "env-read":
            _print(commands.env_read(args.service, args.key))
            return 0
        if args.cmd in ("policy-show", "policy-set", "policy-apply", "auto-apply"):
            from . import workflow
            settings = config.read_settings()
            if args.cmd == "auto-apply":
                _print(workflow.auto_apply_state() if args.mode == "status" else workflow.set_auto_apply(args.mode == "on"))
                return 0
            policy = workflow.load()
            if args.cmd == "policy-show":
                _print({"auto_apply": workflow.auto_apply_state(), "policy": policy, "path": workflow.workflow_path()})
                return 0
            service = args.service or settings.get("service") or ""
            if args.cmd == "policy-set":
                try:
                    result = workflow.commit_change(policy, args.node, args.value, service=service,
                                                    base_url=str(settings.get("base_url") or ""), apply=args.apply)
                except ValueError as exc:
                    _print({"error": str(exc)})
                    return 2
            elif args.target == "cloudrun":
                result = workflow.apply_env_cloudrun(
                    policy, project=str(settings.get("project_id") or ""), region=str(settings.get("cloudrun_region") or ""),
                    service=args.service or str(settings.get("cloudrun_service") or ""))
            else:
                result = workflow.apply_env(policy, service=service, redeploy=not args.no_redeploy,
                                            base_url=str(settings.get("base_url") or ""))
            _print(result)
            bad = (result.get("render") or result).get("error") if isinstance(result, dict) else None
            return 1 if bad else 0
        if args.cmd == "deploy":
            result = commands.deploy(args.service, timeout=args.timeout)
            _print(result)
            return 0 if result.get("ok") else 1
        if args.cmd == "rules-status":
            result = commands.rules_status(args.project, args.sa)
            _print(result)
            return 0 if result.get("match") else 1
        if args.cmd == "rules-deploy":
            if not args.dry_run and not args.yes:
                print("프로젝트 %s 에 firestore.rules 를 배포합니다. 계속하려면 프로젝트 ID 를 그대로 입력하세요: " % args.project,
                      end="", file=sys.stderr)
                if input().strip() != args.project:
                    print("취소했습니다.", file=sys.stderr)
                    return 1
            result = commands.rules_deploy(args.project, args.sa, dry_run=args.dry_run)
            _print(result)
            return 1 if result.get("error") else 0
        if args.cmd == "pin-publish":
            _print(commands.pin_publish(args.pin, repo=args.repo, dry_run=args.dry_run))
            return 0
        if args.cmd == "pin-remote-check":
            result = commands.pin_remote_check(args.pin, repo=args.repo)
            _print(result)
            return 0 if result.get("ok") else 1
        if args.cmd == "observe":
            result = commands.observe_requests(args.project, args.sa, args.service,
                                               path=args.path, since_minutes=args.minutes,
                                               tolerance=args.tolerance)
            _print(result)
            return 0 if result.get("ok") else 1
        if args.cmd == "verify-chain":
            result = commands.verify_chain(args.project, args.sa, args.pin, out_dir=args.out,
                                           challenge=args.challenge, source=args.source,
                                           max_age_hours=args.max_age_hours)
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
        if args.cmd == "rand":
            made = entropy.generate(length=args.length, encoding=args.encoding,
                                    command=args.command)
            if args.show_command or args.command is None:
                print("# OS=%s 출처=%s 명령=%s" % (made["os"], made["source"], made["command"]),
                      file=sys.stderr)
            if made["note"]:
                print("# %s" % made["note"], file=sys.stderr)
            print(made["value"])
            return 0
        if args.cmd == "gui":
            from . import gui
            return gui.run()
    except (commands.CommandError, render.RenderError, gcp.GcpError, firebase.FirebaseError, kms.KmsError,
            pins.PinError, chain.ChainError, C.ContainerError, witness.WitnessError) as exc:
        # 원인을 **코드로** 보여준다(RenderError 만 던지면 운영자가 원인을 알 수 없다 —
        # 실제로 그 때문에 막힌 사례가 있었다). 값에는 토큰·개인키가 담기지 않는다.
        print("실패: " + (getattr(exc, "code", "") or type(exc).__name__), file=sys.stderr)
        return 3
    except Exception as exc:            # noqa: BLE001 — 값만 남긴다(스택에 비밀을 싣지 않는다)
        # 타입만 찍으면 원인을 알 수 없다(실제로 그 때문에 막혔다). 메시지를 잘라서 함께 보여준다.
        print("실패: %s: %s" % (type(exc).__name__, str(exc)[:300]), file=sys.stderr)
        return 3
    return 2
