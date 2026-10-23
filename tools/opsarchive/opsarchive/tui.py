"""opsarchive TUI — rich 가 있으면 메뉴, 없으면 안내만 하고 종료한다.

메뉴는 CLI 와 **같은 함수**를 부른다(화면만 다르다). 패스프레이즈는 여기서도 TTY 로만 받는다.
"""

from __future__ import annotations

import sys

from . import commands


MENU = [
    ("1", "selftest — 로컬 왕복 검증"),
    ("2", "keygen — 관리자 키쌍 생성"),
    ("3", "publish — 공개키를 Render 에 발행"),
    ("4", "doctor — 로컬 키와 배포 지문 대조"),
    ("5", "list — 봉인 아카이브 목록"),
    ("6", "decrypt — 아카이브 열기"),
    ("7", "auto-apply — 자동 반영(정책 → Render) 켜기/끄기"),
    ("8", "policy-set — 노드 값 바꾸기(자동 반영이 켜져 있으면 Render 까지)"),
    ("q", "종료"),
]


def run() -> int:
    try:
        from rich.console import Console
        from rich.prompt import Prompt
        from rich.table import Table
    except ImportError:
        print("rich 가 없어 TUI 를 열 수 없습니다. CLI 로 실행하세요(예: python -m opsarchive selftest).")
        return 2

    console = Console()
    while True:
        table = Table(title="opsarchive — 탈퇴 실패 증거 봉인")
        table.add_column("키", style="bold")
        table.add_column("명령")
        for key, label in MENU:
            table.add_row(key, label)
        console.print(table)
        choice = Prompt.ask("선택", default="q").strip()
        try:
            if choice == "1":
                console.print_json(data=commands.selftest())
            elif choice == "2":
                console.print_json(data=commands.keygen())
            elif choice in ("3", "4"):
                service = Prompt.ask("Render 서비스 이름")
                key_file = Prompt.ask("개인키 파일 경로")
                base_url = Prompt.ask("앱 주소(비우면 건너뜀)", default="")
                phrase = commands.ask_passphrase()
                if choice == "3":
                    console.print_json(data=commands.publish(service, key_file, phrase, base_url=base_url))
                else:
                    console.print_json(data=commands.doctor(service, key_file, phrase, base_url=base_url))
            elif choice == "5":
                project = Prompt.ask("Firebase 프로젝트 ID")
                sa = Prompt.ask("서비스 계정 JSON 경로")
                for row in commands.list_archives(project, sa):
                    console.print(row.get("_id"), row.get("trigger"), row.get("age_seconds"))
            elif choice == "6":
                project = Prompt.ask("Firebase 프로젝트 ID")
                sa = Prompt.ask("서비스 계정 JSON 경로")
                archive_id = Prompt.ask("아카이브 ID")
                key_file = Prompt.ask("개인키 파일 경로")
                out = Prompt.ask("평문 저장 디렉터리(비우면 요약만)", default="")
                console.print_json(data=commands.decrypt_archive(
                    project, sa, archive_id, key_file, commands.ask_passphrase(), out_dir=out or None))
            elif choice == "7":
                from . import workflow
                state = workflow.auto_apply_state()
                console.print("지금: %s (%s)" % ("켜짐" if state["on"] else "꺼짐", state["source"]))
                mode = Prompt.ask("바꿀 값", choices=["on", "off", "그대로"], default="그대로")
                if mode != "그대로":
                    console.print_json(data=workflow.set_auto_apply(mode == "on"))
            elif choice == "8":
                from . import config, workflow
                settings = config.read_settings()
                node = Prompt.ask("노드 ID(예: daily_cap)")
                value = Prompt.ask("값(토글은 on/off)")
                try:
                    console.print_json(data=workflow.commit_change(
                        workflow.load(), node, value, service=str(settings.get("service") or ""),
                        base_url=str(settings.get("base_url") or "")))
                except ValueError as exc:
                    console.print("[red]실패:[/red] " + str(exc))
            elif choice == "q":
                return 0
        except commands.CommandError as exc:
            console.print("[red]실패:[/red] " + exc.code)
        except Exception as exc:        # noqa: BLE001
            console.print("[red]실패:[/red] " + type(exc).__name__)
    return 0


if __name__ == "__main__":              # pragma: no cover — 직접 실행용
    sys.exit(run())
