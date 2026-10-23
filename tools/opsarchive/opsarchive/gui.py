"""opsarchive GUI — 관리자용 창(표준 라이브러리 tkinter).

왜 tkinter 인가: 이 저장소는 Windows 에서 `pip install -r requirements.txt` 인코딩 문제와
`.cmd` 실행 문제로 이미 한 번 넘어졌다. 표준 라이브러리만 쓰면 **설치 단계가 없다**:
`.\\venv\\Scripts\\python -m opsarchive gui` 로 바로 열린다.

CLI 와 같은 원칙을 지킨다
- 패스프레이즈는 **입력 창으로만** 받는다(명령줄·환경변수·로그 금지). 마스킹해서 보여준다.
- 개인키 **내용**은 어떤 화면에도 찍지 않는다(파일 이름·지문만).
- 모든 작업은 워커 스레드에서 돌고 출력은 로그 탭에 쌓인다(창이 멈추지 않게).
- 비밀은 `.env`, 상세 설정은 `settings.json` — GUI 에서 둘 다 편집한다.

실행
    cd tools/opsarchive
    .venv\\Scripts\\python -m opsarchive gui
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import commands, config, container as C, entropy, firebase, gcp, pins, render, users, workflow

ENV_FIELDS = ["RENDER_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS", "EVIDENCE_GH_TOKEN",
              "EVIDENCE_GH_REPO"]
SETTING_FIELDS = [
    ("service", "Render 서비스 이름"),
    ("base_url", "앱 주소(https://...)"),
    ("project_id", "Firebase 프로젝트 ID"),
    ("sa_path", "서비스 계정 JSON 경로"),
    ("env_key", "공개키 환경변수 이름"),
    ("generation", "키 세대(정수)"),
    ("key_dir", "개인키 폴더"),
    ("checkpoints_dir", "체크포인트 폴더"),
    ("pin_path", "핀 파일 경로"),
    ("tsa_url", "TSA 주소(선택)"),
    ("kms_key", "KMS 서명 키(선택, projects/.../cryptoKeyVersions/N)"),
]


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("opsarchive — 탈퇴 실패 증거 봉인")
        self.root.geometry("1180x780")          # 설명이 잘리지 않도록 넉넉하게 시작한다
        self.root.minsize(960, 620)
        self.log_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self.busy = False
        # 자동 실행·수동 실행이 같은 체크포인트 파일을 동시에 건드리지 않게 하는 상호배제 락.
        # _lock_owner 로 "누가 잡았는지"를 구분해, 중지와 워커 finally 가 겹쳐도 남의 락을 풀지 않는다.
        self.run_lock = threading.Lock()
        self._lock_guard = threading.Lock()
        self._lock_owner = ""
        self._lock_seq = 0
        # 서비스 목록은 워커 스레드가 불러온다 — 결과를 담을 창 참조와 토큰(다른 창의 결과 배제).
        self.service_window = None
        self.service_combo = None
        self.service_hint = None
        self.service_names_var = None
        self.service_names_loaded: list[str] = []
        self._service_seq = 0
        self.settings = config.bootstrap()
        self.env_values = config.parse_env(self._read(config.env_path()))
        self.setting_vars: dict[str, tk.StringVar] = {}
        self.step_status: dict[str, tk.StringVar] = {}
        self.last: dict[str, str] = {}
        self.last_rows: list = []
        self.log_window = None
        self.output = None
        self.log_lines: list = []               # 창을 닫아도 로그를 잃지 않게 메모리에 남긴다
        self._wrapped: list = []
        self._build()
        self.open_log_window()                  # 로그는 탭이 아니라 **별도 창**이다
        self.root.bind("<Configure>", self._rewrap_all, add="+")
        self.root.after(120, self._drain)
        self.refresh_overview()

    # ------------------------------------------------------------ 공통
    def _read(self, path: str) -> str:
        try:
            with open(path, "r", encoding="utf-8-sig") as fh:
                return fh.read()
        except OSError:
            return ""

    def log(self, text: str, tag: str = "info") -> None:
        self.log_queue.put((tag, text))

    def _drain(self) -> None:
        while True:
            try:
                tag, text = self.log_queue.get_nowait()
            except queue.Empty:
                break
            if tag == "refresh":
                self.refresh_steps()
                continue
            if tag == "status":
                self.status_var.set(text)          # 메인 창 아래 상태 줄(로그 창이 닫혀 있어도 보인다)
                continue
            if tag == "users":
                self._fill_users()                 # 워커가 불러온 사용자 목록·상세를 메인 스레드에서 반영
                continue
            if tag == "services":
                # 워커 스레드가 불러온 서비스 목록을 메인 스레드에서 창에 반영한다(Tk 규칙).
                self._apply_service_names(text)
                continue
            if self.output is None or not self.output.winfo_exists():
                self.log_lines.append((tag, text))    # 창이 닫혀 있어도 기록은 남긴다
                if len(self.log_lines) > 3000:
                    del self.log_lines[:1000]
                continue
            self.output.configure(state="normal")
            self.output.insert("end", text + "\n", tag)
            self.output.see("end")
            self.output.configure(state="disabled")
            self.log_lines.append((tag, text))
            if len(self.log_lines) > 3000:
                del self.log_lines[:1000]
        self.root.after(120, self._drain)

    def ask_pass(self, prompt: str = "패스프레이즈") -> str:
        return simpledialog.askstring("opsarchive", prompt, show="*", parent=self.root) or ""

    def ask_key_pass(self, key_file: str, prompt: str = "개인키 패스프레이즈") -> str:
        """패스프레이즈를 **그 자리에서 검증**하며 받는다(최대 3회).

        틀린 값을 그대로 넘기면 작업 전체가 key_mismatch 로 실패하고 처음부터 다시 해야 한다
        (실제로 사용자가 두 번 겪었다). 여기서 미리 열어 보고, 틀리면 이유를 보여주고 다시 묻는다.
        """
        for attempt in range(3):
            phrase = self.ask_pass(prompt if attempt == 0 else
                                   "%s — 이 키의 패스프레이즈가 아닙니다. 다시 입력하세요 (%d/3)"
                                   % (prompt, attempt + 1))
            if not phrase:
                return ""
            try:
                C.load_private_key(key_file, phrase)
                return phrase
            except C.ContainerError as exc:
                if exc.code == "key_mismatch":
                    continue                      # 다시 묻는다
                messagebox.showerror("opsarchive", "키 파일을 읽을 수 없습니다: %s" % exc.code)
                return ""
            except OSError as exc:
                messagebox.showerror("opsarchive", "키 파일을 열 수 없습니다: %s" % exc)
                return ""
        messagebox.showerror("opsarchive", "패스프레이즈를 3번 틀렸습니다.\n"
                                          "패스프레이즈를 잊었다면 키 탭 ③ 에서 **새 서명 키를 만드는** 편이 빠릅니다"
                                          "(아직 아카이브 서명이 없으면 잃는 것이 없습니다).")
        return ""

    def _acquire_run_lock(self, owner: str) -> bool:
        """동시 실행 상호배제 — 락을 **비차단**으로 잡는다(못 잡으면 로그만 남기고 False).

        자동 실행이 도는 동안 [이 노드 실행] 이 켜지면 둘 다 같은 체크포인트 파일에 쓰려다
        경합한다. 그래서 워커를 띄우기 **전에** 메인 스레드에서 락을 잡는다.
        """
        if not self.run_lock.acquire(blocking=False):
            self.log("다른 작업이 실행 중입니다 — 락을 잡지 못했습니다(owner=%s, locked=%s)"
                     % (owner, self.run_lock.locked()), "err")
            return False
        with self._lock_guard:
            self._lock_owner = owner
        self.log("실행 락 획득(owner=%s, locked=%s)." % (owner, self.run_lock.locked()))
        return True

    def _release_run_lock(self, owner: str) -> None:
        """**자기가 잡은 락만** 놓는다(자동 실행 중지와 워커 finally 가 겹쳐도 안전)."""
        with self._lock_guard:
            if self._lock_owner != owner:
                return
            self._lock_owner = ""
        try:
            self.run_lock.release()
        except RuntimeError:
            pass
        self.log("실행 락 반환(owner=%s, locked=%s)." % (owner, self.run_lock.locked()))

    def run(self, label: str, fn) -> None:
        """작업을 워커 스레드로 돌린다(패스프레이즈 입력은 메인 스레드에서 먼저 받는다)."""
        if self.busy:
            messagebox.showinfo("opsarchive", "다른 작업이 아직 돌고 있어요.")
            return
        self._lock_seq += 1
        owner = "run#%d:%s" % (self._lock_seq, label)
        if not self._acquire_run_lock(owner):
            # 자동 실행이 락을 쥐고 있거나 다른 워커가 돌고 있다 — 동시 실행을 막는다.
            self.log_queue.put(("status", "다른 작업이 실행 중입니다"))
            return
        self.busy = True
        self.log("▶ " + label, "head")
        self.log_queue.put(("status", "작업 중: " + label))

        def worker() -> None:
            try:
                result = fn()
                if isinstance(result, dict) and result.get("error"):
                    # rotate 처럼 "부분 성공 + error" 를 돌려주는 경우를 성공으로 보지 않는다.
                    self.last[label] = "✘ " + str(result.get("_state") or result["error"])
                    self.log("✘ 실패: %s" % result["error"], "err")
                    for key, value in result.items():
                        if not key.startswith("_"):
                            self.log("   %s: %s" % (key, value))
                    self.log_queue.put(("status", "✘ %s: %s" % (label, result.get("_state") or result["error"])))
                    return
                state = ""
                if isinstance(result, dict):
                    state = str(result.get("_state") or "")   # 성공이지만 덧붙일 상태(예: 배포됨·미확인)
                    for key, value in result.items():
                        if not key.startswith("_"):
                            self.log("   %s: %s" % (key, value))
                elif result:
                    self.log("   " + str(result))
                self.last[label] = "✔ " + (state or "완료")
                self.log("✔ 끝", "ok")
                self.log_queue.put(("status", "✔ %s %s" % (label, state or "완료")))
            except Exception as exc:  # noqa: BLE001 — GUI 는 어떤 예외도 창을 닫지 않게
                code = getattr(exc, "code", "")
                if code == "no_pin_file":
                    # 핀 파일이 아직 없을 때 "무엇을 먼저 해야 하는지"를 화면에 남긴다.
                    code = "no_pin_file — Render 탭 ⑤ [핀 만들기] 를 먼저 실행하세요 (핀 파일: %s)" % (
                        self.settings.get("pin_path") or "경로 미설정")
                self.last[label] = "✘ 실패: " + str(code or type(exc).__name__)
                self.log("✘ %s%s" % (type(exc).__name__, (": " + str(code)) if code else ""), "err")
                self.log_queue.put(("status", "✘ %s 실패: %s" % (label, code or type(exc).__name__)))
                if str(exc):
                    self.log("   " + str(exc)[:400], "err")
            finally:
                self.busy = False
                self._release_run_lock(owner)      # 성공·실패 어느 쪽이든 락을 놓는다
                # Tk 위젯은 메인 스레드에서만 만진다 — 큐를 통해 갱신을 요청한다.
                self.log_queue.put(("refresh", ""))

        threading.Thread(target=worker, name="opsarchive-gui", daemon=True).start()

    def _wrap(self, label, container, pad: int = 46) -> None:
        """창 너비에 맞춰 **줄바꿈 폭을 다시 계산**한다(가로로 잘리는 문제를 없앤다).

        wraplength 를 상수로 두면 창이 좁을 때 잘리고, 넓을 때는 과하게 접힌다. 컨테이너와
        루트 창의 <Configure> 에서 다시 잡는다.
        """
        self._wrapped.append((label, container, pad))

        def apply(event=None) -> None:
            width = getattr(event, "width", 0) or container.winfo_width()
            try:
                label.configure(wraplength=max(260, int(width) - pad))
            except tk.TclError:
                pass

        container.bind("<Configure>", apply, add="+")
        apply()

    def _rewrap_all(self, event=None) -> None:
        """창 크기가 바뀌면 등록된 모든 설명 라벨의 줄바꿈 폭을 다시 잡는다."""
        for label, container, pad in list(self._wrapped):
            try:
                width = container.winfo_width()
                label.configure(wraplength=max(260, int(width) - pad))
            except tk.TclError:
                self._wrapped.remove((label, container, pad))

    # ------------------------------------------------------------ 단계 카드(제목·상태·버튼 + 설명)
    def _step(self, parent, row: int, no: str, title: str, desc: str, key: str,
              button: str, command) -> None:
        """한 단계 = ① 줄: 번호·제목 + 현재 상태 + 실행 버튼  ② 줄: 설명(창 너비에 맞춰 줄바꿈)."""
        box = ttk.Frame(parent)
        box.grid(row=row, column=0, sticky="we", pady=(6, 2))
        box.columnconfigure(1, weight=1)
        ttk.Label(box, text="%s %s" % (no, title), font=("", 10, "bold")).grid(
            row=0, column=0, sticky="w", padx=(8, 10))
        var = tk.StringVar(value="—")
        self.step_status[key] = var
        ttk.Label(box, textvariable=var, foreground="#06c").grid(row=0, column=1, sticky="w")
        ttk.Button(box, text=button, command=command, width=22).grid(
            row=0, column=2, sticky="e", padx=8)
        label = ttk.Label(box, text=desc, justify="left")
        label.grid(row=1, column=0, columnspan=3, sticky="we", padx=(8, 8), pady=(0, 2))
        self._wrap(label, box)

    def _steps_frame(self, parent) -> ttk.Frame:
        frame = ttk.Frame(parent)
        frame.pack(fill="x", padx=4, pady=2)
        frame.columnconfigure(0, weight=1)
        return frame

    def _hint(self, parent) -> tk.StringVar:
        var = tk.StringVar(value="")
        label = ttk.Label(parent, textvariable=var, justify="left", foreground="#060")
        label.pack(anchor="w", padx=10, pady=(10, 4), fill="x")
        self._wrap(label, parent)
        return var

    def state(self, key: str) -> str:
        return self.last.get(key, "아직 안 함")

    def refresh_steps(self) -> None:
        """각 단계의 **현재 상태**를 실제 파일·설정에서 다시 계산한다(눈으로 확인 가능하게)."""
        keys = config.key_files()
        self.step_status.get("keygen", tk.StringVar()).set(
            "봉투 키 있음: " + os.path.basename(keys["admin"][0]) if keys["admin"] else "봉투 키 없음 — 먼저 만드세요")
        self.step_status.get("signkey", tk.StringVar()).set(
            "서명 키 있음: " + os.path.basename(keys["sign"][0]) if keys["sign"] else "서명 키 없음 — anchor 에 필요")
        self.step_status.get("selftest", tk.StringVar()).set(self.state("selftest"))
        self.step_status.get("random", tk.StringVar()).set("OS=%s · 명령 준비됨" % entropy.os_kind())
        has_env = bool(os.environ.get("RENDER_API_KEY"))
        self.step_status.get("publish", tk.StringVar()).set(
            "RENDER_API_KEY " + ("설정됨" if has_env else "없음(.env)") + " · " + self.state("publish"))
        self.step_status.get("doctor", tk.StringVar()).set(self.state("doctor"))
        self.step_status.get("observe", tk.StringVar()).set(self.state("observe"))
        pin_exists = os.path.exists(str(self.settings.get("pin_path") or ""))
        self.step_status.get("pin", tk.StringVar()).set(
            ("핀 파일 있음" if pin_exists else "핀 파일 없음") + " · " + self.state("pin"))
        self.step_status.get("pin-check", tk.StringVar()).set(self.state("pin-check"))
        self.step_status.get("iam", tk.StringVar()).set(self.state("iam-check"))
        self.step_status.get("redeploy", tk.StringVar()).set(self.state("재배포"))
        self.step_status.get("rules-status", tk.StringVar()).set(self.state("규칙 대조"))
        self.step_status.get("rules-dry", tk.StringVar()).set(self.state("규칙 검사"))
        self.step_status.get("rules-deploy", tk.StringVar()).set(self.state("규칙 배포"))
        if getattr(self, "rules_info", None) is not None:
            self.rules_info.set(self._rules_info_text())
        self._refresh_store_and_verify()
        self._update_hint()

    def _refresh_store_and_verify(self) -> None:
        """보관소·검증 탭의 상태 칸을 채운다(파일·설정만 보고 네트워크는 쓰지 않는다)."""
        picked = (self.archive_var.get() if getattr(self, "archive_var", None) else "") or ""
        self.step_status.get("list", tk.StringVar()).set(
            ("%d개" % len(self.last_rows)) if self.last_rows else self.state("목록"))
        self.step_status.get("pick", tk.StringVar()).set(
            ("선택: " + picked[:18] + ("…" if len(picked) > 18 else "")) if picked else "표에서 줄을 클릭하세요")
        self.step_status.get("decrypt", tk.StringVar()).set(self.state("복호화"))
        self._fill_tree(self.last_rows)

        self.step_status.get("vstatus", tk.StringVar()).set(self.state("검증 상태"))
        self.step_status.get("anchor", tk.StringVar()).set(self.state("anchor"))
        self.step_status.get("verify", tk.StringVar()).set(self.state("verify-chain"))
        self.step_status.get("challenge", tk.StringVar()).set(self.state("verify-chain"))
        if getattr(self, "store_hint", None) is not None:
            self.store_hint.set("아카이브가 0개여도 오류가 아닙니다(아직 탈퇴 실패 봉인이 없었다는 뜻). "
                                "카나리아(IAM 검사용)는 목록에서 빠집니다.")
        if getattr(self, "verify_hint", None) is not None:
            keys = config.key_files()
            self.verify_hint.set("다음 할 일: " + ("② anchor 로 지금 상태를 서명하세요(주기적으로 반복)" if keys["sign"]
                                                 else "키 탭 ③ 에서 서명 키를 먼저 만드세요")
                                 + " · 키를 회전했다면 **핀을 다시 만들고**(Render 탭 ⑤) 서명 키도 새 키를 고르세요"
                                 + " · anchor 가 key_mismatch 면 서명 키 패스프레이즈가 그 키의 것이 아닙니다")

    def _update_hint(self) -> None:
        keys = config.key_files()
        if not keys["admin"]:
            text = "다음 할 일: ① selftest 로 확인한 뒤 ② 봉투 키 만들기"
        elif not os.environ.get("RENDER_API_KEY"):
            text = "다음 할 일: .env 에 RENDER_API_KEY 를 넣으세요(설정 탭) → ③ 공개키 발행"
        elif self.last.get("publish", "").startswith("✘") or not self.last.get("publish"):
            text = "다음 할 일: ③ 공개키 발행 → ④ 지문 확인(doctor)"
        elif not keys["sign"]:
            text = "다음 할 일: 서명 키 만들기(검증 탭의 anchor 에 필요)"
        elif not os.path.exists(str(self.settings.get("pin_path") or "")):
            text = "다음 할 일: 핀 만들기 → 핀 검사 (그 뒤 IAM 검사·anchor)"
        else:
            text = "기본 설정 완료 — 검증 탭에서 anchor/verify-chain 을 주기적으로 돌리세요."
        for var in (getattr(self, "keys_hint", None), getattr(self, "render_hint", None)):
            if var is not None:
                var.set(text)

    def _build(self) -> None:
        # 아래 상태 줄을 먼저 자리잡게 하고, 노트북이 남은 공간을 채운다.
        bar = ttk.Frame(self.root)
        bar.pack(fill="x", side="bottom", padx=10, pady=(0, 8))
        self.status_var = tk.StringVar(value="준비됨")
        ttk.Label(bar, textvariable=self.status_var, foreground="#06c",
                  anchor="w").pack(side="left", fill="x", expand=True)
        ttk.Button(bar, text="로그 창 열기", command=self.open_log_window).pack(side="right")

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=8, pady=8, side="top")
        self._tab_overview(notebook)
        self._tab_settings(notebook)
        self._tab_keys(notebook)
        self._tab_render(notebook)
        self._tab_rules(notebook)
        self._tab_users(notebook)
        self._tab_store(notebook)
        self._tab_verify(notebook)

    def _frame(self, notebook: ttk.Notebook, title: str) -> ttk.Frame:
        frame = ttk.Frame(notebook)
        notebook.add(frame, text=title)
        return frame

    def _button(self, parent, text: str, command) -> ttk.Button:
        button = ttk.Button(parent, text=text, command=command)
        button.pack(side="left", padx=4, pady=4)
        return button

    def _entry(self, parent, label: str, key: str, row: int, browse: bool = False) -> None:
        ttk.Label(parent, text=label, width=24).grid(row=row, column=0, sticky="w", pady=2)
        var = tk.StringVar(value=str(self.settings.get(key, "")))
        ttk.Entry(parent, textvariable=var, width=58).grid(row=row, column=1, sticky="we", pady=2)
        self.setting_vars[key] = var
        if browse:
            ttk.Button(parent, text="찾아보기", command=lambda v=var: v.set(
                filedialog.askopenfilename(parent=self.root) or v.get())
            ).grid(row=row, column=2, padx=4)

    # ------------------------------------------------------------ 탭 1: 개요
    def _tab_overview(self, notebook) -> None:
        frame = self._frame(notebook, "개요")
        ttk.Label(frame, text="자동화 워크플로우 — 노드를 클릭해 값을 바꾸세요. [자동 반영] 이 켜져 있으면(기본) 바꾸는 즉시\n"
                             "정책에 저장하고, 서버 환경변수 노드는 Render 에 올려 재배포·반영 확인까지 합니다.",
                  justify="left").pack(anchor="w", padx=10, pady=(8, 2))
        canvas_box = ttk.Frame(frame)
        canvas_box.pack(fill="both", expand=True, padx=10, pady=4)
        canvas_box.columnconfigure(0, weight=1)
        canvas_box.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(canvas_box, height=340, background="#fbfbfd", highlightthickness=1,
                                highlightbackground="#dde")
        xbar = ttk.Scrollbar(canvas_box, orient="horizontal", command=self.canvas.xview)
        ybar = ttk.Scrollbar(canvas_box, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=xbar.set, yscrollcommand=ybar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="we")
        # 창이 좁으면 4번째 열이 잘렸다 — 스크롤바와 휠로 항상 닿을 수 있게 한다.
        self.canvas.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"))
        self.canvas.bind("<Shift-MouseWheel>",
                         lambda e: self.canvas.xview_scroll(int(-e.delta / 120), "units"))
        self.canvas.bind("<Button-1>", self._on_canvas_click)

        editor = ttk.LabelFrame(frame, text="선택한 노드")
        editor.pack(fill="x", padx=10, pady=4)
        self.node_title = ttk.Label(editor, text="노드를 클릭하세요", font=("", 10, "bold"))
        self.node_title.pack(anchor="w", padx=8, pady=(4, 0))
        self.node_desc = ttk.Label(editor, text="", justify="left")
        self.node_desc.pack(anchor="w", padx=8)
        self._wrap(self.node_desc, editor)
        self.node_value = tk.StringVar()
        self.value_box = ttk.Frame(editor)
        self.value_box.pack(anchor="w", padx=8, pady=4)
        bar = ttk.Frame(editor)
        bar.pack(fill="x", padx=8, pady=(0, 6))
        self._button(bar, "정책에 저장", self.save_node)
        self._button(bar, "Render에 반영", self.push_node_env)
        self._button(bar, "이 노드 실행", self.run_node)
        self._button(bar, "변경 모아 반영(재배포·확인)", self.apply_all_env)
        # 자동 반영 토글(기본 켜짐): 값을 바꾸면 정책에 저장하고 Render 에 올려 재배포·확인까지 한다.
        # 설정은 settings.json 의 auto_apply — CLI `auto-apply on|off` 와 같은 값. 환경변수 OPSARCHIVE_AUTO_APPLY 가 있으면 그게 우선.
        auto_bar = ttk.Frame(editor)
        auto_bar.pack(fill="x", padx=8, pady=(0, 6))
        self.auto_var = tk.BooleanVar(value=workflow.auto_apply_state()["on"])
        self.auto_button = ttk.Checkbutton(auto_bar, variable=self.auto_var, style="Toolbutton",
                                           command=self._toggle_auto_apply)
        self.auto_button.pack(side="left")
        self.auto_note = ttk.Label(auto_bar, text="")
        self.auto_note.pack(side="left", padx=8)
        self._auto_job = None
        self._refresh_auto_button()

        bar2 = ttk.Frame(frame)
        bar2.pack(fill="x", padx=10, pady=(0, 4))
        self._button(bar2, "plan 미리보기", self.show_plan)
        self._button(bar2, "자동 실행 시작", self.start_automation)
        self._button(bar2, "중지", self.stop_automation)
        self._button(bar2, "정책 파일 위치",
                     lambda: self.log(os.path.join(config.config_dir(), "workflow.json")))
        self.automation_stop = threading.Event()
        self.automation_thread = None
        self.policy = workflow.load()
        self.selected_node = ""
        self.node_boxes: dict = {}

        self.overview = tk.Text(frame, height=5, wrap="word")
        self.overview.pack(fill="x", padx=10, pady=(0, 6))
        bar3 = ttk.Frame(frame)
        bar3.pack(fill="x", padx=10, pady=(0, 8))
        self._button(bar3, "새로 고침", self.refresh_overview)
        self._button(bar3, "설정 다시 읽기", self.reload_settings)
        self._button(bar3, "정책 다시 읽기", self.reload_policy)

    # ------------------------------------------------------------ 마인드맵(캔버스)
    def reload_policy(self) -> None:
        self.policy = workflow.load()
        self.log("정책을 다시 읽었습니다: %s" % workflow.policy_path())
        self._redraw_mindmap()

    def _redraw_mindmap(self) -> None:
        """노드를 그룹별 열로 배치하고 기본 흐름을 화살표로 잇는다(클릭하면 아래에서 편집)."""
        if not hasattr(self, "canvas"):
            return
        self.canvas.delete("all")
        data = workflow.graph(self.policy)
        # graph() 의 groups[].nodes 는 **노드 id 목록**이다(id 문자열 또는 dict 둘 다 받아 준다).
        by_id = {}
        for item in data.get("nodes", []):
            if isinstance(item, dict) and item.get("id"):
                by_id[item["id"]] = item
        x = 16
        y = 14
        self.node_boxes = {}
        for group in data.get("groups", []):
            self.canvas.create_text(x + 4, y, text=group.get("name", ""), anchor="nw",
                                    fill="#557", font=("", 9, "bold"))
            ty = y + 22
            for entry in group.get("nodes", []):
                nid = entry if isinstance(entry, str) else str((entry or {}).get("id", ""))
                node = by_id.get(nid, {"id": nid, "label": nid})
                if not nid:
                    continue
                enabled = node.get("enabled", True)
                missing = node.get("missing") or []
                fill = "#e8f6ec" if enabled and not missing else ("#fdeaea" if missing else "#f1f1f5")
                outline = "#0a7" if nid == self.selected_node else ("#c66" if missing else "#bbc")
                width = 2 if nid == self.selected_node else 1
                self.canvas.create_rectangle(x, ty, x + 236, ty + 46, fill=fill, outline=outline,
                                             width=width, tags=("node", "n:" + nid))
                self.canvas.create_text(x + 8, ty + 10, text=node.get("label", nid), anchor="nw",
                                        width=220, font=("", 9, "bold"), tags=("node", "n:" + nid))
                state = node.get("state", "")
                if node.get("env"):
                    state = "%s · env %s" % (state, node["env"])
                self.canvas.create_text(x + 8, ty + 30, text=state[:40], anchor="nw",
                                        fill="#566", font=("", 8), tags=("node", "n:" + nid))
                self.node_boxes[nid] = (x, ty, x + 236, ty + 46)
                ty += 58
            x += 264
        for start, end in data.get("edges", []):
            a, b = self.node_boxes.get(start), self.node_boxes.get(end)
            if not a or not b:
                continue
            self.canvas.create_line(a[2], (a[1] + a[3]) // 2, b[0], (b[1] + b[3]) // 2,
                                    arrow="last", fill="#9ab", smooth=True, tags=("edge",))
        # 화살표를 **맨 뒤로** 내린다 — 노드 위에 겹쳐 그려지면 마우스 클릭을 가로채 보인다.
        self.canvas.tag_lower("edge")
        self.canvas.configure(scrollregion=self.canvas.bbox("all") or (0, 0, 800, 400))

    def _on_canvas_click(self, event) -> None:
        """클릭 판정은 **좌표로 직접** 한다(캔버스 항목 순서·화살표 겹침에 기대지 않는다)."""
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        hit = ""
        for nid, (x1, y1, x2, y2) in self.node_boxes.items():
            if x1 <= x <= x2 and y1 <= y <= y2:
                hit = nid                      # 정확히 겹치면 나중에 그린 노드가 이긴다
        if not hit:
            pad = 4                            # 가장자리 클릭 배려(노드 사이 간격은 8px)
            for nid, (x1, y1, x2, y2) in self.node_boxes.items():
                if x1 - pad <= x <= x2 + pad and y1 - pad <= y <= y2 + pad:
                    hit = nid
        if hit:
            self.selected_node = hit
            self._redraw_mindmap()
            self._show_node_editor()
        elif self.selected_node:
            self.selected_node = ""            # 노드 밖(화살표·빈 곳) 클릭 → 선택 해제
            self._redraw_mindmap()

    def _node_def(self, node_id: str) -> dict:
        for node in workflow.NODES:
            if node["id"] == node_id:
                return node
        return {}

    def _show_node_editor(self) -> None:
        node = self._node_def(self.selected_node)
        if not node:
            return
        self.node_title.configure(text="%s  (%s)" % (node.get("label", ""), self.selected_node))
        extra = ""
        if node.get("env"):
            extra = "\n서버 환경변수: %s%s" % (node["env"], " · [Render에 반영] 이 재배포와 반영 확인까지 한다" if node.get("redeploy") else "")
        if node.get("missing"):
            extra += "\n필수 설정 없음: %s" % ", ".join(node["missing"])
        self.node_desc.configure(text=(node.get("desc", "") or "") + extra)
        for child in self.value_box.winfo_children():
            child.destroy()
        kind = node.get("kind")
        current = self.policy.get(self.selected_node, node.get("default"))
        if kind == "toggle":
            self.node_value.set("1" if current in (True, 1, "1") else "0")
            ttk.Checkbutton(self.value_box, text="켜기", variable=self.node_value,
                            onvalue="1", offvalue="0", command=self._on_value_changed).pack(side="left")
        elif kind == "choice":
            options = [value for value, _label in node.get("options", [])]
            self.node_value.set(str(current))
            box = ttk.Combobox(self.value_box, textvariable=self.node_value, values=options,
                               width=16, state="readonly")
            box.pack(side="left")
            box.bind("<<ComboboxSelected>>", lambda _e: self._on_value_changed())
        elif kind == "number":
            self.node_value.set(str(current))
            self._entry_autosave(ttk.Entry(self.value_box, textvariable=self.node_value, width=12))
            ttk.Label(self.value_box, text="(%s ~ %s)" % (node.get("min"), node.get("max"))).pack(side="left", padx=6)
        elif kind == "text":
            self.node_value.set(str(current or ""))
            self._entry_autosave(ttk.Entry(self.value_box, textvariable=self.node_value, width=36))
            ttk.Label(self.value_box, text="예: %s" % node.get("placeholder", "")).pack(side="left", padx=6)
        elif kind == "secret":
            self.node_value.set("")
            ttk.Label(self.value_box, text="값은 저장하지 않습니다 — [Render에 반영] 을 누르면 가려진 칸으로 묻습니다.").pack(side="left")
        elif kind == "key":
            self.node_value.set("")
            ttk.Label(self.value_box, text="[Render에 반영] 또는 [이 노드 실행] = 공개키 발행(키 파일·패스프레이즈).").pack(side="left")
        else:
            self.node_value.set("")
            ttk.Label(self.value_box, text="값이 없는 실행 노드입니다 — [이 노드 실행] 을 누르세요.").pack(side="left")

    def save_node(self, quiet: bool = False) -> bool:
        """정책에 저장한다(workflow.set_value — CLI 와 같은 검증). 자동 반영이 켜져 있으면 Render 반영을 예약한다.

        quiet=True 는 값이 바뀔 때 자동으로 부르는 경로 — 바뀐 게 없으면 조용히 넘어가고 창을 띄우지 않는다."""
        node = self._node_def(self.selected_node)
        if not node:
            return False
        if node.get("kind") not in workflow.VALUE_KINDS:
            if not quiet:
                # 값이 없는 실행 노드에서 파일을 다시 쓰고 '저장했습니다'라고 하면 사실과 다르다.
                messagebox.showinfo("opsarchive", "값이 없는 실행 노드입니다 — [이 노드 실행] 을 쓰세요.")
            return False
        raw = self.node_value.get()
        try:
            parsed = workflow.parse_value(self.selected_node, raw)
        except ValueError as exc:
            if quiet:
                self.log("값을 저장하지 않았습니다(%s)" % exc, "err")
            else:
                messagebox.showerror("opsarchive", "받을 수 없는 값입니다: %s" % exc)
            return False
        if quiet and parsed == self.policy.get(self.selected_node):
            return False                         # 포커스만 옮겼을 때 — 저장·재배포하지 않는다
        self.policy, value, changed = workflow.set_value(self.policy, self.selected_node, raw)
        self.log("노드 '%s' = %s 로 저장했습니다 (%s)" % (self.selected_node, value, workflow.workflow_path()))
        self._redraw_mindmap()
        self._show_node_editor()
        if self.auto_var.get() and workflow.is_auto_target(self.selected_node) and changed:
            self._schedule_auto_apply()
        return changed

    def _on_value_changed(self) -> None:
        """편집기에서 값이 바뀌었다 — 자동 반영이 켜져 있을 때만 바로 저장한다(꺼져 있으면 [정책에 저장] 을 누른다)."""
        if self.auto_var.get():
            self.save_node(quiet=True)

    def _entry_autosave(self, entry) -> None:
        entry.pack(side="left")
        entry.bind("<Return>", lambda _e: self._on_value_changed())
        entry.bind("<FocusOut>", lambda _e: self._on_value_changed())

    AUTO_DELAY_MS = 1500     # 연달아 바꾸면 마지막 변경 뒤 한 번만 재배포한다

    def _schedule_auto_apply(self) -> None:
        if self._auto_job is not None:
            self.root.after_cancel(self._auto_job)
        self._auto_job = self.root.after(self.AUTO_DELAY_MS, self._auto_apply_now)
        self.log_queue.put(("status", "자동 반영 대기 중 — %.1f초 뒤 Render 에 올립니다" % (self.AUTO_DELAY_MS / 1000)))

    def _auto_apply_now(self) -> None:
        self._auto_job = None
        if not self.auto_var.get():
            return
        if self.busy:                            # 다른 작업이 끝나면 다시 시도(변경을 잃지 않는다)
            self._auto_job = self.root.after(1000, self._auto_apply_now)
            return
        self._apply_env(None, None, "자동 반영", ask=False)

    def _refresh_auto_button(self) -> None:
        state = workflow.auto_apply_state()
        self.auto_var.set(state["on"])
        self.auto_button.configure(text="자동 반영: %s" % ("켜짐" if state["on"] else "꺼짐"),
                                   state="disabled" if state["source"] == "env" else "normal")
        if state["source"] == "env":
            note = "환경변수 %s 로 고정됨" % workflow.AUTO_APPLY_ENV
        elif state["on"]:
            note = "값을 바꾸면 정책 저장 → Render 반영 → 재배포·확인(연달아 바꾸면 한 번만)"
        else:
            note = "값을 바꾼 뒤 [정책에 저장] · [Render에 반영] 을 직접 누릅니다"
        self.auto_note.configure(text=note)

    def _toggle_auto_apply(self) -> None:
        state = workflow.set_auto_apply(self.auto_var.get())
        self.log("자동 반영 %s%s" % ("켜짐" if state["on"] else "꺼짐", (" — " + state["note"]) if state.get("note") else ""))
        if not state["on"] and self._auto_job is not None:
            self.root.after_cancel(self._auto_job)
            self._auto_job = None
        self._refresh_auto_button()

    def push_node_env(self) -> None:
        """한 노드를 Render 에 반영한다 — 값 올리기 → (묻고) 재배포 → 다시 읽어 반영 확인까지."""
        node = self._node_def(self.selected_node)
        if not node or not node.get("env"):
            messagebox.showinfo("opsarchive", "이 노드는 서버 환경변수와 연결돼 있지 않습니다.")
            return
        if node.get("kind") == "key":
            self.do_publish()                     # 공개키는 키 파일에서 역산해 발행(환경변수·재배포·지문 대조)
            return
        secrets = None
        node_ids = [self.selected_node]
        if node.get("kind") == "secret":
            value = simpledialog.askstring("opsarchive", "%s 값을 붙여넣으세요(화면·파일·로그에 남지 않습니다)" % node["env"],
                                           show="*", parent=self.root) or ""
            if not value.strip():
                return
            secrets, node_ids = {node["env"]: value.strip()}, []
        elif node.get("kind") == "text" and not str(self.policy.get(self.selected_node) or "").strip():
            messagebox.showinfo("opsarchive", "값이 비어 있습니다 — 먼저 값을 넣고 [정책에 저장] 하세요.")
            return
        self._apply_env(node_ids, secrets, "Render 반영(%s)" % node["env"])

    def apply_all_env(self) -> None:
        """정책의 모든 환경변수 노드 중 **바뀐 것만** 올리고 한 번 재배포한 뒤 반영을 확인한다."""
        self._apply_env(None, None, "변경 모아 반영")

    def _apply_env(self, node_ids, secrets, label: str, ask: bool = True) -> None:
        if ask:
            answer = messagebox.askyesnocancel(
                "opsarchive", "바뀐 값을 Render 에 올립니다.\n\n[예] 올리고 재배포한 뒤 반영됐는지 확인(권장)\n"
                              "[아니요] 값만 올리기(재배포 전에는 앱에 적용되지 않음)\n[취소] 그만두기", parent=self.root)
            if answer is None:
                return
        else:
            answer = True                        # 자동 반영: 바뀐 것만 올리고 재배포·확인까지(묻지 않는다)
        if node_ids is None and self._auto_job is not None:
            # 모아 반영이 예약된 자동 반영을 대신한다 — 같은 변경으로 두 번 재배포하지 않게.
            self.root.after_cancel(self._auto_job)
            self._auto_job = None
        service = self.require("service")
        base_url = str(self.settings.get("base_url") or "")
        policy = dict(self.policy)

        def work() -> dict:
            result = workflow.apply_env(policy, service=service, node_ids=node_ids, secrets=secrets,
                                        redeploy=bool(answer), base_url=base_url)
            if result.get("verified"):
                result["_state"] = "반영 확인(Render 값 = 정책, 재배포 완료)" if result.get("redeployed") else "바뀐 값 없음"
            elif not answer and not result.get("error"):
                result["_state"] = "값만 올림 — 재배포 필요"
            return result

        self.run(label, work)

    def run_node(self) -> None:
        node = self._node_def(self.selected_node)
        if not node:
            return
        secrets = {}
        if self.selected_node == "pubkey":
            self.do_publish()
            return
        if self.selected_node == "anchor":
            sign_file = self.pick_key("sign")
            if not sign_file:
                return
            phrase = self.ask_key_pass(sign_file, "서명 키 패스프레이즈")
            if not phrase:
                return
            secrets = {"sign_key_file": sign_file, "passphrase": phrase}
        self.run("노드 실행: %s" % node.get("label", self.selected_node),
                 lambda: workflow.run_step(self.selected_node, self.policy, secrets=secrets,
                                           on_log=self.log))

    def show_plan(self) -> None:
        lines = ["이번 실행 계획:"]
        for step in workflow.plan(self.policy):
            lines.append("  %s %s%s" % ("✔" if step.get("ok") else "·", step.get("label"),
                                        ("" if step.get("ok") else "  — " + step.get("reason", ""))))
        text = "\n".join(lines)
        self.overview.configure(state="normal")
        self.overview.delete("1.0", "end")
        self.overview.insert("1.0", text)
        self.overview.configure(state="disabled")
        self.log(text)

    def start_automation(self) -> None:
        if getattr(self, "automation_thread", None) and self.automation_thread.is_alive():
            messagebox.showinfo("opsarchive", "이미 자동 실행이 돌고 있습니다.")
            return
        # 자동 실행이 도는 동안에는 수동 [이 노드 실행] 이 같은 체크포인트를 건드리지 못하게 락을 쥔다.
        if not self._acquire_run_lock("automation"):
            messagebox.showinfo("opsarchive", "다른 작업이 실행 중입니다 — 자동 실행을 시작할 수 없습니다.")
            return
        self.automation_stop = threading.Event()
        secrets = {}
        sign_files = config.key_files()["sign"]
        if sign_files:
            sign_file = self.pick_key("sign")
            phrase = self.ask_key_pass(sign_file, "서명 키 패스프레이즈") if sign_file else ""
            if sign_file and phrase:
                secrets = {"sign_key_file": sign_file, "passphrase": phrase}
        policy = dict(self.policy)

        def worker() -> None:
            try:
                result = workflow.automation_loop(policy, on_log=self.log,
                                                  stop_event=self.automation_stop, secrets=secrets)
                self.log("자동 실행 종료: %s" % result)
            except Exception as exc:      # noqa: BLE001
                self.log("자동 실행 실패: %s" % type(exc).__name__, "err")
            finally:
                self._release_run_lock("automation")   # 스스로 끝난 경우에도 락을 놓는다
                self.log_queue.put(("refresh", ""))

        self.automation_thread = threading.Thread(target=worker, name="opsarchive-auto", daemon=True)
        self.automation_thread.start()
        self.log("자동 실행을 시작했습니다(관리자 PC가 켜져 있는 동안만 돕니다).")

    def stop_automation(self) -> None:
        if getattr(self, "automation_stop", None):
            self.automation_stop.set()
            self.log("자동 실행 중지를 요청했습니다(현재 주기가 끝나면 멈춥니다).")
        # 락은 owner 문자열로 구분한다 — 여기서 놓아도 워커 finally 의 중복 반환은 무해하다.
        self._release_run_lock("automation")

    def reload_settings(self) -> None:
        self.settings = config.read_settings()
        for key, var in self.setting_vars.items():
            var.set(str(self.settings.get(key, "")))
        self.env_values = config.parse_env(self._read(config.env_path()))
        self.log("설정을 다시 읽었습니다.")
        self.refresh_overview()

    def refresh_overview(self) -> None:
        settings = self.settings
        keys = config.key_files()
        lines = [
            "설정 파일: %s" % config.settings_path(),
            "비밀 파일(.env): %s %s" % (config.env_path(), "(있음)" if os.path.exists(config.env_path()) else "(없음)"),
            "",
            "서비스: %s" % settings.get("service"),
            "앱 주소: %s" % settings.get("base_url"),
            "프로젝트: %s" % settings.get("project_id"),
            "서비스 계정: %s %s" % (settings.get("sa_path") or "(미설정)",
                                "(있음)" if settings.get("sa_path") and os.path.exists(str(settings.get("sa_path"))) else "(없음)"),
            "",
            "RENDER_API_KEY: %s" % ("설정됨" if os.environ.get("RENDER_API_KEY") else "없음 — .env 또는 아래 설정 탭"),
            "개인키 폴더: %s" % keys["dir"],
            "  · 봉투 키(X25519): %s" % (", ".join(os.path.basename(p) for p in keys["admin"]) or "없음 → 키 탭에서 keygen"),
            "  · 서명 키(Ed25519): %s" % (", ".join(os.path.basename(p) for p in keys["sign"]) or "없음 → 검증에서 필요"),
            "",
            "핀 파일: %s %s" % (settings.get("pin_path"),
                             "(있음)" if os.path.exists(str(settings.get("pin_path"))) else "(없음 → 발행 후 pin 만들기)"),
            "체크포인트: %s" % settings.get("checkpoints_dir"),
            "",
            "다음 할 일: 위 '없음' 항목을 채우고 키 탭 → Render 탭 순서로 진행하세요.",
        ]
        self.overview.configure(state="normal")
        self.overview.delete("1.0", "end")
        self.overview.insert("1.0", "\n".join(lines))
        self.overview.configure(state="disabled")
        self._redraw_mindmap()
        self.refresh_steps()

    # ------------------------------------------------------------ 탭 2: 설정
    def _tab_settings(self, notebook) -> None:
        frame = self._frame(notebook, "설정")
        grid = ttk.Frame(frame)
        grid.pack(fill="x", padx=8, pady=6)
        grid.columnconfigure(1, weight=1)
        for row, (key, label) in enumerate(SETTING_FIELDS):
            self._entry(grid, label, key, row, browse=(key in ("sa_path", "key_dir", "checkpoints_dir")))
        bar = ttk.Frame(frame)
        bar.pack(fill="x", padx=8)
        self._button(bar, "settings.json 저장", self.save_settings)
        self._button(bar, "Render 서비스 선택", self.pick_service)
        self._button(bar, "파일 위치 열기", lambda: self.log(config.settings_path()))

        ttk.Separator(frame).pack(fill="x", padx=8, pady=8)
        ttk.Label(frame, text=".env (비밀 값 — 커밋 금지. Render API 키는 대시보드에서만 발급됩니다)",
                  justify="left").pack(anchor="w", padx=8)
        self.env_text = tk.Text(frame, height=8, wrap="none")
        self.env_text.pack(fill="both", expand=True, padx=8, pady=4)
        self.env_text.insert("1.0", "\n".join("%s=%s" % (k, self.env_values.get(k, "")) for k in ENV_FIELDS))
        bar2 = ttk.Frame(frame)
        bar2.pack(fill="x", padx=8, pady=4)
        self._button(bar2, ".env 저장", self.save_env)
        self._button(bar2, ".env 다시 읽기", self.reload_settings)

    def save_settings(self) -> None:
        data = {key: var.get().strip() for key, var in self.setting_vars.items()}
        path = config.write_settings(data)
        self.settings = config.read_settings()
        self.log("설정을 저장했습니다: " + path)
        self.refresh_overview()

    def save_env(self) -> None:
        values = config.parse_env(self.env_text.get("1.0", "end"))
        path = config.save_env(values)
        config.load_env(path, override=True)
        self.log("비밀 값을 저장했습니다: %s (값은 화면·로그에 남기지 않습니다)" % path)

    # ------------------------------------------------------------ 탭 3: 키
    def _tab_keys(self, notebook) -> None:
        frame = self._frame(notebook, "키")
        ttk.Label(frame, text="위에서 아래로 한 줄씩 하시면 됩니다. 각 줄의 '상태' 칸이 지금 무엇이 준비됐는지 보여줍니다.",
                  wraplength=840).pack(anchor="w", padx=10, pady=(8, 0))
        steps = self._steps_frame(frame)
        self._step(steps, 0, "①", "형식 자체 점검",
                   "봉인·해제·변조 감지·키 잠금이 이 PC에서 정상인지 확인합니다. 키를 만들기 전에 한 번.",
                   "selftest", "selftest 실행",
                   lambda: self.run("selftest", commands.selftest))
        self._step(steps, 1, "②", "봉투 키 만들기",
                   "증거를 암호화할 때 쓰는 관리자 키쌍입니다. 개인키는 이 PC(설정의 개인키 폴더)에만 남습니다.",
                   "keygen", "keygen 실행", self.do_keygen)
        self._step(steps, 2, "③", "서명 키 만들기",
                   "체크포인트(anchor)에 서명하는 키입니다. 봉투 키와 용도가 달라 따로 만듭니다.",
                   "signkey", "signkey 실행", self.do_signkey)
        self._step(steps, 3, "④", "무작위 값 생성",
                   "OS를 감지해 CSPRNG 명령을 채웁니다(창에서 명령 수정 가능). 패스프레이즈로 쓰고 비밀번호 관리자에 보관하세요.",
                   "random", "무작위 값 창 열기", self.do_random)
        self._step(steps, 4, "⑤", "키 회전(선택)",
                   "키가 노출됐다고 판단될 때만 씁니다. 새 키를 만들고 발행하며, 옛 키 파일은 지우지 마세요(옛 아카이브를 열어야 합니다).",
                   "rotate", "rotate 실행", self.do_rotate)
        self.keys_hint = self._hint(frame)
        ttk.Label(frame, text="키 파일을 잃으면 그 키로 만든 아카이브는 영영 열 수 없습니다 — 오프라인 백업을 권합니다.",
                  wraplength=840, foreground="#a60").pack(anchor="w", padx=10, pady=(4, 10))

    def do_keygen(self) -> None:
        phrase = self.ask_pass("새 개인키 패스프레이즈(잃어버리면 복구 불가)")
        if not phrase:
            return
        again = self.ask_pass("확인을 위해 한 번 더")
        if phrase != again:
            messagebox.showerror("opsarchive", "두 입력이 다릅니다.")
            return
        self.run("keygen", lambda: commands.keygen(out_dir=self.settings.get("key_dir") or None,
                                                   passphrase=phrase))

    def do_random(self) -> None:
        """OS 를 감지해 CSPRNG 명령을 채우고, **고칠 수 있는 창**에서 값을 만든다.

        생성한 값은 화면·클립보드에만 둔다(파일·로그에 남기지 않는다). 패스프레이즈로 쓸 때는
        복사해서 키 만들기 창에 붙여 넣고, 비밀번호 관리자에 따로 보관하라고 안내한다.
        """
        kind = entropy.os_kind()
        window = tk.Toplevel(self.root)
        window.title("무작위 값 생성 — %s" % kind)
        window.geometry("760x340")
        ttk.Label(window, text="감지된 OS: %s\n명령은 직접 고칠 수 있습니다(셸에서 실행됩니다 — 값을 만드는 명령만 넣으세요)."
                  % kind, justify="left", wraplength=720).pack(anchor="w", padx=10, pady=6)
        command_var = tk.StringVar(value=entropy.default_command(length=32, encoding="chars", kind=kind))
        ttk.Label(window, text="명령").pack(anchor="w", padx=10)
        ttk.Entry(window, textvariable=command_var).pack(fill="x", padx=10)
        value_var = tk.StringVar(value="")
        ttk.Label(window, text="값(편집 가능 — 직접 입력해도 됩니다)").pack(anchor="w", padx=10, pady=(8, 0))
        ttk.Entry(window, textvariable=value_var).pack(fill="x", padx=10)
        status = ttk.Label(window, text="", wraplength=720, justify="left")
        status.pack(anchor="w", padx=10, pady=6)

        def make() -> None:
            try:
                made = entropy.generate(length=32, encoding="chars", command=command_var.get())
            except Exception as exc:      # noqa: BLE001
                status.configure(text="생성 실패: %s" % getattr(exc, "code", type(exc).__name__))
                return
            value_var.set(made["value"])
            status.configure(text="출처: %s%s" % (made["source"],
                                                 (" · " + made["note"]) if made["note"] else ""))
            self.log("무작위 값 생성(출처 %s, 길이 %d) — 값은 로그에 남기지 않습니다."
                     % (made["source"], len(made["value"])))

        def copy_value() -> None:
            self.root.clipboard_clear()
            self.root.clipboard_append(value_var.get())
            status.configure(text="클립보드에 복사했습니다. 비밀번호 관리자에 보관하세요(이 도구는 저장하지 않습니다).")

        bar = ttk.Frame(window)
        bar.pack(fill="x", padx=10, pady=8)
        ttk.Button(bar, text="생성", command=make).pack(side="left", padx=4)
        ttk.Button(bar, text="복사", command=copy_value).pack(side="left", padx=4)
        ttk.Button(bar, text="닫기", command=window.destroy).pack(side="left", padx=4)
        make()

    def do_signkey(self) -> None:
        phrase = self.ask_pass("새 서명 키 패스프레이즈")
        if not phrase:
            return
        self.run("signkey", lambda: commands.signkey(out_dir=self.settings.get("key_dir") or None,
                                                     passphrase=phrase))

    def do_rotate(self) -> None:
        key_file = self.pick_key("admin")
        if not key_file:
            return
        old = self.ask_key_pass(key_file, "지금 개인키의 패스프레이즈")
        if not old:
            return
        new = self.ask_pass("새 개인키 패스프레이즈")
        if not new or new != self.ask_pass("새 패스프레이즈 확인"):
            return
        self.run("rotate", lambda: commands.rotate(
            self.require("service"), key_file, old, out_dir=self.settings.get("key_dir") or None,
            env_key=self.settings.get("env_key"), base_url=self.settings.get("base_url"),
            pass_new=new))

    # ------------------------------------------------------------ 탭 4: Render
    def _tab_render(self, notebook) -> None:
        frame = self._frame(notebook, "Render")
        ttk.Label(frame, text="공개키를 Render 에 올려 앱이 증거를 봉인할 수 있게 만드는 단계입니다(위에서 아래로).",
                  wraplength=840).pack(anchor="w", padx=10, pady=(8, 0))
        steps = self._steps_frame(frame)
        self._step(steps, 0, "①", "공개키 발행",
                   "공개키만 Render 환경변수(EVIDENCE_PUBKEY)에 넣고 재배포합니다. 환경변수 변경만 REST API를 씁니다.",
                   "publish", "publish 실행", self.do_publish)
        self._step(steps, 1, "②", "지문 대조(doctor)",
                   "이 PC의 개인키 지문과 배포된 지문이 같은지 확인합니다. 다르면 그 키로는 복호화할 수 없습니다.",
                   "doctor", "doctor 실행", self.do_doctor)
        self._step(steps, 2, "③", "앱·저장소 상태",
                   "Render 환경변수, 앱 /health 의 지문·세대, 아카이브 개수를 한 번에 봅니다(네트워크를 쓰므로 버튼으로만).",
                   "remote", "상태 확인", self.check_remote_status)
        self._step(steps, 3, "④", "요청 로그 증인",
                   "앱이 지울 수 없는 플랫폼 로그의 /account/erase 요청 수와 체인 기록을 비교합니다(누락 탐지).",
                   "observe", "observe 실행", self.do_observe)
        self._step(steps, 4, "⑤", "핀 파일",
                   "개인키에서 역산한 지문을 저장소 **밖**(~/.opsarchive)에 기록합니다. "
                   "CI 가 읽는 값은 ⑨ 에서 Actions 변수로 올립니다.",
                   "pin", "핀 만들기", self.do_pin)
        self._step(steps, 5, "⑥", "핀 검사(로컬)",
                   "**로컬** 핀과 배포된 /health 의 지문·세대를 대조합니다. CI 는 같은 검사를 Actions 변수로 하므로, "
                   "변수가 낡았는지는 ⑩ 원격 대조로 확인하세요.",
                   "pin-check", "핀 검사 실행", self.do_pin_check)
        self._step(steps, 6, "⑦", "IAM 검사",
                   "앱 서비스 계정이 증거를 지울 수 있는지 시험합니다(목표: 만들 수는 있고 지울 수는 없다).",
                   "iam", "IAM 검사 실행", self.do_iam)
        self._step(steps, 7, "⑧", "재배포",
                   "워크플로우 env 노드를 [Render에 반영] 한 뒤 이 버튼으로 재배포합니다(환경변수는 재배포해야 실제로 적용됩니다). "
                   "환경변수 반영 뒤 이 버튼으로 재배포한다 — 재배포가 끝나면 ② doctor 로 지문을 다시 대조하세요.",
                   "redeploy", "재배포 실행", self.do_redeploy)
        self._step(steps, 8, "⑨", "핀을 Actions 변수로",
                   "핀의 공개값을 GitHub Actions 변수(vars.EVIDENCE_PIN_*)로 올립니다. "
                   "**키를 회전했으면 여기서 반드시 갱신하세요** — 그러지 않으면 CI 가 빨강이 됩니다.",
                   "pin-publish", "변수로 올리기", self.do_pin_publish)
        self._step(steps, 9, "⑩", "원격 변수 대조",
                   "원격 Actions 변수와 로컬 핀이 같은지 봅니다(다르면 ⑨ 로 올리세요). "
                   "로컬 ⑥ 은 초록인데 CI 는 빨강인 상태를 이 검사가 잡아냅니다.",
                   "pin-remote", "원격 대조 실행", self.do_pin_remote_check)
        self.render_hint = self._hint(frame)

    def check_remote_status(self) -> None:
        """Render 환경변수·앱 /health·아카이브 개수를 한 번에 점검한다(자동 폴링하지 않는다)."""
        def work() -> dict:
            out: dict = {}
            env_key = self.settings.get("env_key") or "EVIDENCE_PUBKEY"
            sid = render.service_id(self.require("service"))
            out["서비스"] = sid
            out[env_key] = "발행됨" if render.get_env(sid, env_key) else "없음(발행 전)"
            block = (commands.health(self.require("base_url")).get("evidence") or {})
            out["/health evidence"] = (
                "지문 %s… 세대 %s" % (str(block.get("fingerprint"))[:12], block.get("generation"))
            ) if block else "없음(발행 전이거나 앱 미배포)"
            sa = str(self.settings.get("sa_path") or "")
            if sa and os.path.exists(sa):
                try:
                    out["아카이브"] = "%d개" % len(commands.list_archives(self.require("project_id"), sa))
                except Exception as exc:      # noqa: BLE001
                    out["아카이브"] = "확인 실패(%s)" % getattr(exc, "code", type(exc).__name__)
            else:
                out["아카이브"] = "서비스 계정 JSON 경로 미설정(설정 탭)"
            return out

        self.run("상태 확인", work)

    def require(self, key: str) -> str:
        value = str(self.settings.get(key) or "").strip()
        if not value:
            raise commands.CommandError("설정_누락:" + key)
        return value

    def pick_service(self) -> None:
        """Render 서비스 이름 선택 — 목록은 **워커 스레드**에서 불러와 UI 를 멈추지 않는다.

        `render.service_names()` 는 최대 600초(render.CLI_TIMEOUT) 걸릴 수 있다. 예전에는 메인
        스레드에서 그대로 불러 창이 최대 10분 멈췄다. 이제 창을 **먼저** 띄우고 목록은 워커가
        불러와 큐로 넘긴다. 목록이 오기 전이라도 이름을 직접 입력해 [확인] 할 수 있고(기존 동작
        보존), 조회가 실패하면 창 안에 오류를 남기되 창은 계속 쓸 수 있다.
        """
        names_so_far = list(self.service_names_loaded or [])
        window = tk.Toplevel(self.root)
        window.title("Render 서비스 선택")
        window.geometry("640x220")
        window.transient(self.root)
        self._service_seq += 1
        token = self._service_seq
        self.service_token = token
        self.service_window = window

        hint = ttk.Label(window, text="서비스 목록 불러오는 중…", foreground="#666", justify="left")
        hint.pack(anchor="w", padx=12, pady=(10, 2))
        self.service_hint = hint
        ttk.Label(window, text="앱 주소(호스트)와 서비스 이름은 다를 수 있습니다 — 이름은 여기서 고르세요.",
                  foreground="#666").pack(anchor="w", padx=12)
        var = tk.StringVar(value=str(self.settings.get("service") or ""))
        self.service_names_var = var
        combo = ttk.Combobox(window, textvariable=var, values=names_so_far, width=60, state="normal")
        combo.pack(fill="x", padx=12, pady=8)
        self.service_combo = combo
        status = ttk.Label(window, text="", foreground="#060")
        status.pack(anchor="w", padx=12)

        def confirm() -> None:
            chosen = (var.get() or "").strip()
            if not chosen:
                return
            known = list(self.service_names_loaded or [])
            if known and chosen not in known:
                status.configure(text="⚠ 목록에 없는 이름입니다(그래도 저장할 수 있습니다).", foreground="#c00")
            self.settings["service"] = chosen
            if "service" in self.setting_vars:
                self.setting_vars["service"].set(chosen)
            try:
                config.write_settings(self.settings)
            except OSError:
                pass
            self.log("서비스 이름을 '%s' 로 저장했습니다." % chosen)
            window.destroy()

        bar = ttk.Frame(window)
        bar.pack(fill="x", padx=12, pady=10)
        ttk.Button(bar, text="목록 새로 고침", command=lambda: (window.destroy(), self.pick_service())).pack(side="left")
        ttk.Button(bar, text="확인", command=confirm).pack(side="right")
        ttk.Button(bar, text="취소", command=window.destroy).pack(side="right", padx=6)
        window.bind("<Return>", lambda _e: confirm())
        window.bind("<Escape>", lambda _e: window.destroy())

        def forget() -> None:
            # 창을 닫으면 참조를 비워, 뒤늦게 온 워커 결과가 죽은 위젯을 건드리지 않게 한다.
            if getattr(self, "service_window", None) is window:
                self.service_window = None
                self.service_combo = None
                self.service_hint = None
                self.service_names_var = None
            window.destroy()

        window.protocol("WM_DELETE_WINDOW", forget)

        self._load_service_names(token)
        self.root.wait_window(window)

    def _load_service_names(self, token: int) -> None:
        """서비스 목록 조회를 워커 스레드에 맡긴다(최대 600초 — 메인 스레드에서 부르면 창이 멈춘다)."""
        self.log_queue.put(("status", "서비스 목록 불러오는 중…"))

        def worker() -> None:
            names: list[str] = []
            error = ""
            try:
                names = [str(n) for n in render.service_names()]
            except Exception as exc:      # noqa: BLE001 — CLI 없음·미로그인 등을 화면에 보여준다
                error = "%s%s" % (getattr(exc, "code", ""), type(exc).__name__)
            payload = json.dumps({"token": token, "names": names, "error": error})
            # Tk 위젯은 만지지 않는다 — 큐에 결과만 넣으면 _drain 이 메인 스레드에서 반영한다.
            self.log_queue.put(("services", payload))

        threading.Thread(target=worker, name="opsarchive-services", daemon=True).start()

    def _apply_service_names(self, payload: str) -> None:
        """워커가 불러온 서비스 목록을 **메인 스레드에서만** 창 위젯에 반영한다(_drain 이 호출)."""
        try:
            data = json.loads(payload)
        except ValueError:
            data = {"names": [], "error": "parse_error"}
        if data.get("token") != getattr(self, "service_token", None):
            return                                    # 다른(닫힌) 창의 결과는 버린다
        names = [str(n) for n in data.get("names", [])]
        error = str(data.get("error", ""))
        self.service_names_loaded = names
        if error:
            self.log("서비스 목록 조회 실패: %s" % error, "err")
            self.log_queue.put(("status", "서비스 목록 조회 실패: %s" % error))
        else:
            self.log("서비스 목록 %d개를 불러왔습니다." % len(names))
            self.log_queue.put(("status", "서비스 목록 %d개를 불러왔습니다." % len(names)))
        window = getattr(self, "service_window", None)
        if window is None or not window.winfo_exists():
            return
        combo = getattr(self, "service_combo", None)
        if combo is not None and combo.winfo_exists():
            combo.configure(values=names)
        var = getattr(self, "service_names_var", None)
        if var is not None and not (var.get() or "").strip() and names:
            var.set(names[0])                         # 기존 동작: 기본 선택을 첫 항목으로
        hint = getattr(self, "service_hint", None)
        if hint is not None and hint.winfo_exists():
            if error:
                hint.configure(text="서비스 목록을 불러오지 못했습니다(%s) — 이름을 직접 입력해도 됩니다."
                                    % error, foreground="#c00")
            else:
                hint.configure(text="워크스페이스의 서비스 %d개 — 목록에서 고르세요(직접 입력도 됩니다)."
                                    % len(names), foreground="#666")

    def pick_key(self, kind: str = "admin") -> str:
        """키 파일 선택 창 — ① 드롭다운(자동 발견) ② 파일 열기 ③ 경로 직접 입력.

        파일 이름에는 키 id 가 들어 있고(admin-<id>.key / sign-<id>.key), 창은 **내용을 읽지 않는다**.
        종류가 어긋난 파일(예: 봉투 키 자리에 sign-)을 고르면 경고를 띄운다 — 그대로 쓰면 나중에
        `key_mismatch` 로 막히기 때문이다. 마지막 선택은 settings.json 에 기억한다.
        """
        found = config.key_files()
        candidates = [str(p) for p in (found.get(kind) or [])]
        remembered = str(self.settings.get("last_%s_key" % kind) or "")
        if remembered and remembered not in candidates:
            candidates.insert(0, remembered)
        if candidates and remembered in candidates:
            candidates.remove(remembered)
            candidates.insert(0, remembered)

        wanted = {"admin": ("봉투 키(X25519) — 증거 복호화용", "admin-"),
                  "sign": ("서명 키(Ed25519) — 체크포인트 서명용", "sign-")}.get(
                      kind, (kind, ""))
        label, prefix = wanted

        window = tk.Toplevel(self.root)
        window.title("키 파일 선택 — %s" % label)
        window.geometry("680x260")
        window.transient(self.root)
        ttk.Label(window, text="찾을 키: %s" % label, justify="left").pack(anchor="w", padx=12, pady=(10, 2))
        ttk.Label(window, text="발견된 키: %d개 (%s)" % (len(found.get(kind) or []),
                                                      found.get("dir", "")),
                  foreground="#666").pack(anchor="w", padx=12)

        var = tk.StringVar(value=remembered or (candidates[0] if candidates else ""))
        combo = ttk.Combobox(window, textvariable=var, values=candidates, width=72, state="normal")
        combo.pack(fill="x", padx=12, pady=6)
        info = ttk.Label(window, text="", wraplength=640, justify="left")
        info.pack(anchor="w", padx=12, pady=4)

        def refresh_info(*_args) -> None:
            path = (var.get() or "").strip()
            if not path:
                info.configure(text="경로가 비어 있습니다. 드롭다운에서 고르거나 [파일 열기]를 누르세요.",
                               foreground="#c00")
                return
            name = os.path.basename(path)
            exists = os.path.exists(path)
            parts = ["파일: %s" % name, "존재: %s" % ("예" if exists else "아니오")]
            if exists:
                try:
                    stat = os.stat(path)
                    parts.append("크기 %d바이트" % stat.st_size)
                except OSError:
                    pass
            if prefix and name and not name.startswith(prefix):
                parts.append("⚠ 이 창에서 기대하는 이름은 '%s…' 입니다 — 다른 종류의 키일 수 있습니다" % prefix)
            info.configure(text=" · ".join(parts),
                           foreground="#c00" if (not exists or (prefix and not name.startswith(prefix))) else "#060")

        def browse() -> None:
            chosen = filedialog.askopenfilename(
                parent=window, title="키 파일 선택",
                initialdir=str(self.settings.get("key_dir") or config.config_dir()),
                filetypes=[("opsarchive 키", "*.key"), ("모든 파일", "*.*")])
            if chosen:
                var.set(chosen)
                refresh_info()

        result = {"path": ""}

        def confirm() -> None:
            path = (var.get() or "").strip()
            if not path:
                messagebox.showinfo("opsarchive", "키 파일을 고르세요.", parent=window)
                return
            if not os.path.exists(path):
                if not messagebox.askyesno("opsarchive", "파일이 없습니다. 그래도 이 경로를 쓸까요?", parent=window):
                    return
            result["path"] = path
            window.destroy()

        bar = ttk.Frame(window)
        bar.pack(fill="x", padx=12, pady=10)
        ttk.Button(bar, text="파일 열기…", command=browse).pack(side="left")
        ttk.Button(bar, text="확인", command=confirm).pack(side="right")
        ttk.Button(bar, text="취소", command=window.destroy).pack(side="right", padx=6)
        combo.bind("<<ComboboxSelected>>", refresh_info)
        var.trace_add("write", refresh_info)
        window.bind("<Return>", lambda _e: confirm())
        window.bind("<Escape>", lambda _e: window.destroy())
        refresh_info()
        combo.focus_set()
        self.root.wait_window(window)

        if result["path"]:
            self.settings["last_%s_key" % kind] = result["path"]
            try:
                config.write_settings(self.settings)      # 다음에 열 때 미리 선택되게
            except OSError:
                pass
        return result["path"]

    def do_publish(self) -> None:
        key_file = self.pick_key("admin")
        if not key_file:
            return
        phrase = self.ask_key_pass(key_file, "개인키 패스프레이즈")
        if not key_file or not phrase:
            return
        def work() -> dict:
            result = commands.publish(
                self.require("service"), key_file, phrase, env_key=self.settings.get("env_key"),
                base_url=self.settings.get("base_url"), on_step=self.log)
            # 회전·재발행 뒤 CI 가 읽는 값(Actions 변수)은 자동으로 바뀌지 않는다 — 다음 행동을 알려준다.
            self.log("※ 개인키를 바꿨습니다 — CI 가 읽는 값은 Render 탭 ⑨ [변수로 올리기] 로 갱신하고, "
                     "⑩ [원격 대조] 로 확인하세요.")
            return result
        self.run("publish", work)

    def do_doctor(self) -> None:
        key_file = self.pick_key("admin")
        phrase = self.ask_key_pass(key_file, "개인키 패스프레이즈")
        if not key_file or not phrase:
            return
        self.run("doctor", lambda: commands.doctor(
            self.require("service"), key_file, phrase, base_url=self.settings.get("base_url"),
            env_key=self.settings.get("env_key"), project_id=self.settings.get("project_id"),
            pin_file=self.settings.get("pin_path")))

    def do_observe(self) -> None:
        self.run("observe", lambda: commands.observe_requests(
            self.require("project_id"), self.require("sa_path"), self.require("service"),
            since_minutes=60))

    def do_pin(self) -> None:
        key_file = self.pick_key("admin")
        if not key_file:
            return
        sign_files = config.key_files()["sign"]
        signing = None
        if sign_files:
            sign_file = self.pick_key("sign")
            if sign_file:
                phrase = self.ask_key_pass(sign_file, "서명 키 패스프레이즈")
                if phrase:
                    signing = C.sign_public(C.load_private_key(sign_file, phrase))
            if signing is None:
                # 서명 키 없는 핀은 anchor/verify-chain 을 못 쓰게 만든다 — 이 고리를 여기서 끊는다.
                if not messagebox.askyesno(
                        "opsarchive",
                        "서명 키를 넣지 않으면 검증 탭의 anchor/verify-chain 을 쓸 수 없습니다.\n"
                        "서명 키를 고르는 것을 권합니다. 그래도 서명 키 없이 핀을 만들까요?"):
                    return
        phrase = self.ask_key_pass(key_file, "개인키 패스프레이즈")
        if not phrase:
            return
        self.run("pin", lambda: commands.make_pin(
            key_file, phrase, health_url=self.require("base_url"), out=self.settings.get("pin_path"),
            generation=None, signing_public=signing))

    def do_pin_check(self) -> None:
        self.run("pin-check", lambda: commands.check_pin(self.settings.get("pin_path"),
                                                         health_url=self.require("base_url")))

    def _gh_repo(self) -> str:
        """Actions 변수를 올릴/대조할 저장소(환경변수 EVIDENCE_GH_REPO → 설정 → 기본 팀 저장소)."""
        return (self.settings.get("gh_repo") or os.environ.get("EVIDENCE_GH_REPO")
                or "01044402345o-beep/codyssey_final")

    def do_pin_publish(self) -> None:
        """핀의 공개값을 GitHub Actions 변수로 올린다(저장소 파일로는 올리지 않는다)."""
        repo = self._gh_repo()
        self.run("핀 변수 올리기", lambda: commands.pin_publish(
            self.settings.get("pin_path") or "", repo=repo))

    def do_pin_remote_check(self) -> None:
        """원격 Actions 변수와 로컬 핀의 드리프트를 본다(회전 뒤 갱신을 잊었는지)."""
        repo = self._gh_repo()
        self.run("원격 변수 대조", lambda: commands.pin_remote_check(
            self.settings.get("pin_path") or "", repo=repo))

    def do_iam(self) -> None:
        self.run("iam-check", lambda: commands.iam_check(self.require("project_id"),
                                                         self.require("sa_path")))

    def do_redeploy(self) -> None:
        """[Render에 반영] 으로 바꾼 환경변수를 실제로 적용하려면 재배포가 필요하다.

        `commands.deploy` 는 다른 에이전트가 붙이는 인터페이스라 아직 없을 수 있다 —
        존재를 확인하고, 없으면 로그만 남긴다(AttributeError 로 창이 닫히지 않게).
        """
        deploy = getattr(commands, "deploy", None)
        if not callable(deploy):
            self.log("재배포 명령이 아직 없습니다(commands.deploy 미구현).", "err")
            self.log_queue.put(("status", "재배포 명령이 아직 없습니다"))
            return

        def work() -> dict:
            result = deploy(self.require("service")) or {}
            note = str(result.get("note", ""))
            ok = bool(result.get("ok"))
            self.log("재배포 결과: %s" % (note or ("성공" if ok else "실패")))
            self.log_queue.put(("status", "재배포: " + (note or ("완료" if ok else "실패"))))
            return result

        self.run("재배포", work)

    # ------------------------------------------------------------ 탭: Firestore 규칙
    def _tab_rules(self, notebook) -> None:
        frame = self._frame(notebook, "Firestore 규칙")
        ttk.Label(frame, text="앱 계정 기록(users/{uid})의 보안 규칙입니다. 저장소의 firestore.rules 를 (default) 데이터베이스에 "
                              "배포하고, 배포된 규칙을 다시 읽어 같은지 확인합니다.",
                  wraplength=840).pack(anchor="w", padx=10, pady=(8, 0))
        self.rules_info = tk.StringVar(value=self._rules_info_text())
        info = ttk.Label(frame, textvariable=self.rules_info, justify="left", foreground="#444")
        info.pack(anchor="w", padx=10, pady=(6, 0), fill="x")
        self._wrap(info, frame)
        steps = self._steps_frame(frame)
        self._step(steps, 0, "①", "배포된 규칙과 대조",
                   "지금 배포된 규칙을 읽어(읽기 전용) 저장소 파일과 비교합니다. 다르면 차이를 로그에 보여 줍니다 — "
                   "누군가 콘솔에서 규칙을 고쳤거나, 저장소를 고치고 아직 배포하지 않은 상태입니다.",
                   "rules-status", "대조 실행", self.do_rules_status)
        self._step(steps, 1, "②", "문법 검사(dry-run)",
                   "배포하지 않고 규칙 파일을 컴파일만 해 봅니다.",
                   "rules-dry", "검사 실행", self.do_rules_dry)
        self._step(steps, 2, "③", "규칙 배포",
                   "확인 창에서 프로젝트를 한 번 더 확인한 뒤 배포합니다(되돌릴 수 없음 — 콘솔에서 고친 규칙은 덮어씁니다). "
                   "배포가 끝나면 ① 대조를 자동으로 돌려 반영됐는지 확인합니다.",
                   "rules-deploy", "규칙 배포", self.do_rules_deploy)

    def _rules_info_text(self) -> str:
        project = str(self.settings.get("project_id") or "(설정 탭에서 Firebase 프로젝트 ID 를 넣으세요)")
        rc = commands.firebaserc_default()
        try:
            target = firebase.rules_target(config.repo_root())
            where = target["rules_file"]
        except firebase.FirebaseError as exc:
            where = "규칙 파일을 찾지 못했습니다(%s)" % exc.code
        warn = ""
        if rc and self.settings.get("project_id") and rc != self.settings.get("project_id"):
            warn = "\n⚠ 설정의 프로젝트(%s)가 저장소 .firebaserc 기본값(%s)과 다릅니다 — 맞는 프로젝트인지 확인하세요." % (
                self.settings.get("project_id"), rc)
        return "대상 프로젝트: %s · 데이터베이스: (default)\n규칙 파일: %s%s" % (project, where, warn)

    def _log_rules(self, result: dict) -> None:
        for line in result.get("diff") or []:
            self.log("   " + line, "err" if line.startswith("-") else ("ok" if line.startswith("+") else "info"))
        if result.get("detail"):
            self.log("   firebase CLI: " + str(result["detail"]), "err")

    def do_rules_status(self) -> None:
        def work() -> dict:
            result = commands.rules_status(self.require("project_id"), self.require("sa_path"))
            self._log_rules(result)
            out = {k: v for k, v in result.items() if k != "diff"}
            if result["match"] is None:
                out["error"] = "배포본을 읽지 못함: " + result["reason"]
            elif not result["match"]:
                # 드리프트는 '완료'가 아니다 — 콘솔에서 바뀌었거나 저장소를 고치고 아직 배포하지 않았다.
                out["error"] = "rules_differ"
                out["_state"] = "배포본이 저장소와 다름(콘솔 수정 또는 미배포) — 로그의 차이 확인"
            else:
                out["_state"] = "일치(배포본 = 저장소)"
            return out

        self.run("규칙 대조", work)

    def do_rules_dry(self) -> None:
        def work() -> dict:
            result = commands.rules_deploy(self.require("project_id"), dry_run=True)
            self._log_rules(result)
            return result

        self.run("규칙 검사", work)

    def do_rules_deploy(self) -> None:
        project = self.require_ui("project_id")
        if not project:
            return
        try:
            local = firebase.local_rules(config.repo_root())
        except firebase.FirebaseError as exc:
            messagebox.showerror("opsarchive", "규칙 파일을 찾지 못했습니다: %s" % exc.code)
            return
        rc = commands.firebaserc_default()
        warn = ("\n\n⚠ 저장소 .firebaserc 기본값은 %s 입니다. 다른 프로젝트에 배포하려는 게 맞나요?" % rc) if rc and rc != project else ""
        if not messagebox.askyesno(
                "Firestore 규칙 배포",
                "프로젝트: %s\n데이터베이스: (default)\n파일: %s\nsha256: %s…\n\n"
                "배포하면 지금 규칙을 덮어씁니다(콘솔에서 고친 내용 포함). 되돌리려면 이전 파일로 다시 배포해야 합니다.%s\n\n배포할까요?"
                % (project, local["rules_file"], local["sha256"][:16], warn), icon="warning", parent=self.root):
            self.log("규칙 배포를 취소했습니다.")
            return
        sa = str(self.settings.get("sa_path") or "")

        def work() -> dict:
            result = commands.rules_deploy(project, sa)
            self._log_rules(result)
            out = {k: v for k, v in result.items() if k != "diff"}
            verified = result.get("verified")
            if result.get("error") == "deployed_rules_differ":
                out["_state"] = "배포했지만 배포본이 저장소와 다름 — 로그의 차이 확인"
            elif result.get("error") == "cli_timeout":
                out["_state"] = "시간 초과 — 배포됐을 수 있음, ① 대조로 확인"
            elif result.get("error"):
                out["_state"] = "배포 안 됨: " + str(result["error"])
            elif verified:
                out["_state"] = "반영 확인(배포본 = 저장소) · 적용까지 최대 1~10분"
            else:
                out["_state"] = "배포됨 · 반영은 확인 못 함(%s) — ① 대조로 확인" % (result.get("verify_reason") or "확인 불가")
            return out

        self.run("규칙 배포", work)

    def require_ui(self, key: str) -> str:
        value = str(self.settings.get(key) or "").strip()
        if not value:
            messagebox.showerror("opsarchive", "설정 탭에서 '%s' 를 먼저 넣으세요." % key)
        return value

    # ------------------------------------------------------------ 탭: 사용자 데이터
    def _tab_users(self, notebook) -> None:
        frame = self._frame(notebook, "사용자 데이터")
        ttk.Label(frame, text="계정별 기록(users/{uid})을 찾아보고 관리합니다. 개인정보입니다 — 사용자의 요청(열람·삭제)이나 장애 대응 때만 여세요.\n"
                              "상세 보기·통역 기록 내용·내보내기·삭제는 사유를 받아 이 PC의 열람 기록(~/.opsarchive/access-log.jsonl)에 남깁니다. "
                              "계정 삭제(탈퇴)는 여기서 하지 않습니다 — 앱의 탈퇴 흐름을 쓰세요.",
                  wraplength=840, foreground="#a60", justify="left").pack(anchor="w", padx=10, pady=(8, 4))
        bar = ttk.Frame(frame)
        bar.pack(fill="x", padx=10, pady=4)
        ttk.Label(bar, text="uid 또는 이메일").pack(side="left")
        self.user_query = tk.StringVar(value="")
        entry = ttk.Entry(bar, textvariable=self.user_query, width=42)
        entry.pack(side="left", padx=6)
        entry.bind("<Return>", lambda _e: self.do_user_find())
        ttk.Button(bar, text="찾기", command=self.do_user_find).pack(side="left", padx=2)
        ttk.Button(bar, text="목록 새로 고침", command=self.do_user_list).pack(side="left", padx=2)
        self.user_count = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self.user_count, foreground="#06c").pack(side="left", padx=10)

        columns = ("uid", "updated", "days", "weak", "trip", "ilog", "consent")
        titles = {"uid": "uid", "updated": "최근 변경", "days": "학습일", "weak": "복습",
                  "trip": "여행", "ilog": "통역 기록", "consent": "통역 저장 동의"}
        self.user_tree = ttk.Treeview(frame, columns=columns, show="headings", height=8)
        for name in columns:
            self.user_tree.heading(name, text=titles[name])
            self.user_tree.column(name, width=230 if name == "uid" else 95, anchor="w")
        self.user_tree.pack(fill="both", expand=True, padx=10, pady=4)
        self.user_tree.bind("<<TreeviewSelect>>", self._on_pick_user)

        acts = ttk.Frame(frame)
        acts.pack(fill="x", padx=10, pady=2)
        self.user_pick = tk.StringVar(value="")
        ttk.Label(acts, text="선택:").pack(side="left")
        ttk.Label(acts, textvariable=self.user_pick, width=34).pack(side="left", padx=4)
        for text, cmd in (("상세 보기", self.do_user_detail), ("통역 기록 내용", self.do_user_ilog),
                          ("JSON 내보내기", self.do_user_export), ("통역 기록 삭제", self.do_user_delete_ilog),
                          ("열람 기록", self.do_user_audit)):
            ttk.Button(acts, text=text, command=cmd).pack(side="left", padx=2)

        self.user_text = tk.Text(frame, height=12, wrap="word", state="disabled")
        self.user_text.pack(fill="both", expand=True, padx=10, pady=(4, 8))
        self.user_rows: list = []
        self.user_detail_text = ""

    def _on_pick_user(self, _event=None) -> None:
        selection = self.user_tree.selection()
        if selection:
            values = self.user_tree.item(selection[0], "values")
            if values:
                self.user_pick.set(values[0])

    def _fill_users(self) -> None:
        """사용자 표·상세 칸을 다시 채운다(메인 스레드에서만 — Tk 규칙)."""
        if not hasattr(self, "user_tree"):
            return
        for item in self.user_tree.get_children():
            self.user_tree.delete(item)
        for r in self.user_rows:
            self.user_tree.insert("", "end", values=(
                r["uid"], r["updated"], r["study_days"], r["weak"], "있음" if r["trip"] else "—",
                ("%d대화·%d문장" % (r["ilog_sessions"], r["ilog_lines"])) if r["ilog_sessions"] else "—",
                "동의" if r["ilog_consent"] else "—"))
        self.user_count.set("%d명" % len(self.user_rows) if self.user_rows else "")
        self.user_text.configure(state="normal")
        self.user_text.delete("1.0", "end")
        self.user_text.insert("end", self.user_detail_text)
        self.user_text.configure(state="disabled")

    def _users(self) -> "users.Users":
        return users.Users(self.require("project_id"), self.require("sa_path"))

    def _picked_uid(self) -> str:
        uid = (self.user_pick.get() or "").strip()
        if not uid:
            messagebox.showinfo("opsarchive", "표에서 사용자를 고르거나 위에서 찾으세요.")
        return uid

    def _ask_reason(self, what: str) -> str:
        reason = simpledialog.askstring("사유 입력", "%s 사유를 적어 주세요(열람 기록에 남습니다).\n예: 사용자 열람 요청 10/22, 장애 #123" % what,
                                        parent=self.root) or ""
        if len(" ".join(reason.split())) < 2:
            if reason:
                messagebox.showinfo("opsarchive", "사유를 두 글자 이상 적어 주세요.")
            return ""
        return reason

    def _show_user_text(self, text: str) -> None:
        self.user_detail_text = text
        self.log_queue.put(("users", ""))

    def do_user_list(self) -> None:
        def work() -> dict:
            rows = self._users().list_users()
            self.user_rows = rows
            self._show_user_text("목록에는 요약만 나옵니다. 줄을 고르고 [상세 보기] 를 누르세요.")
            return {"사용자": "%d명" % len(rows)}

        self.run("사용자 목록", work)

    def do_user_find(self) -> None:
        query = (self.user_query.get() or "").strip()
        if not query:
            return

        def work() -> dict:
            uid = users.find_uid(self.require("project_id"), self.require("sa_path"), query)
            store = self._users()
            doc = store.get(uid)
            self.user_rows = [users.summarize(uid, doc)] if doc else []
            self.user_pick_value = uid
            self._show_user_text(("찾음: %s — [상세 보기] 로 자세히 봅니다." % uid) if doc else
                                 "uid %s 의 계정 기록 문서가 없습니다(로그인 기록이 없거나 탈퇴)." % uid)
            return {"uid": uid, "문서": "있음" if doc else "없음"}

        self.run("사용자 찾기", work)
        self.root.after(300, self._apply_found_pick)

    def _apply_found_pick(self) -> None:
        if self.busy:
            self.root.after(300, self._apply_found_pick)
            return
        uid = getattr(self, "user_pick_value", "")
        if uid:
            self.user_pick.set(uid)
            self.user_pick_value = ""

    def do_user_detail(self) -> None:
        uid = self._picked_uid()
        reason = uid and self._ask_reason("상세 보기")
        if not reason:
            return

        def work() -> dict:
            auth: object = None
            try:
                auth = users.auth_lookup(self.require("project_id"), self.require("sa_path"), uid=uid)
            except (users.UserError, gcp.GcpError) as exc:
                auth = "조회 못 함(%s) — 서비스 계정에 Firebase Authentication 조회 권한이 필요합니다" % exc.code
            info = users.detail(self._users(), uid, reason, auth=auth)
            self._show_user_text(self._format_detail(info))
            return {"uid": uid, "문서": "있음" if info["document"] else "없음", "탈퇴 흔적": info["tombstone"]}

        self.run("사용자 상세", work)

    @staticmethod
    def _format_detail(info: dict) -> str:
        auth = info.get("auth")
        lines = ["uid: %s" % info["uid"]]
        if isinstance(auth, dict):
            lines.append("계정: %s · %s · 로그인 방식 %s · 가입 %s · 최근 로그인 %s%s" % (
                auth["email"] or "(이메일 없음)", auth["name"] or "(이름 없음)", ",".join(p for p in auth["providers"] if p) or "-",
                auth["created"], auth["last_login"], " · 사용 중지됨" if auth["disabled"] else ""))
        elif auth is None:
            lines.append("계정: Authentication 에 없음(탈퇴했거나 삭제됨)")
        else:
            lines.append("계정: " + str(auth))
        lines.append("탈퇴 흔적(deleted/uid): %s" % ("있음 — 앱이 이 계정의 읽기·쓰기를 거부합니다" if info["tombstone"] else "없음"))
        if not info["document"]:
            lines.append("계정 기록 문서: 없음")
            return "\n".join(lines)
        s = info["summary"]
        lines.append("문서: 만든 시각 %s · 최근 변경 %s · %d바이트%s" % (s["created"], s["updated"], s["bytes"],
                                                            (" · 깨진 필드 " + ",".join(s["broken"])) if s["broken"] else ""))
        p = info["progress"]
        lines.append("학습: %d일(%s ~ %s) · 마지막 화면 %s" % (p["study_days"], p["first"] or "-", p["last"] or "-", p["screen"] or "-"))
        lines.append("복습 목록 %d개: %s" % (s["weak"], ", ".join(x for x in p["weak"] if x) or "-"))
        c = info["consent"]
        lines.append("말하기 동의: %s (버전 %s, %s)" % ("예" if c["voice"] else "아니요", c["version"], c["at"] or "-"))
        t = info["trip"]
        lines.append("여행: " + ("%s · %s · 학습 시작 %s" % (t["country"], " / ".join(t["cities"]), t["study_start"]) if t else "없음"))
        il = info["ilog"]
        if il:
            lines.append("통역 기록: 동의 %s(버전 %s) · %d대화" % (il["consent_at"], il["consent_version"], len(il["sessions"])))
            for x in il["sessions"][:30]:
                lines.append("   · %s · %s · %d문장" % (x["at"], x["route"] or "여행 없이", x["lines"]))
            lines.append("   (문장 본문은 [통역 기록 내용] 으로 따로 봅니다 — 상대방 말이 들어 있습니다)")
        else:
            lines.append("통역 기록: 없음(계정 저장에 동의하지 않았거나 지웠음)")
        return "\n".join(lines)

    def do_user_ilog(self) -> None:
        uid = self._picked_uid()
        reason = uid and self._ask_reason("통역 기록 내용 보기(상대방 말 포함)")
        if not reason:
            return

        def work() -> dict:
            text = users.ilog_text(self._users(), uid, reason)
            self._show_user_text(text)
            return {"uid": uid}

        self.run("통역 기록 내용", work)

    def do_user_export(self) -> None:
        uid = self._picked_uid()
        reason = uid and self._ask_reason("내보내기(열람 요구 대응)")
        if not reason:
            return
        out = filedialog.asksaveasfilename(parent=self.root, defaultextension=".json",
                                           initialfile="user-%s.json" % users.uid_hash(uid)[:8],
                                           filetypes=[("JSON", "*.json")])
        if not out:
            return

        def work() -> dict:
            auth = None
            try:
                auth = users.auth_lookup(self.require("project_id"), self.require("sa_path"), uid=uid)
            except (users.UserError, gcp.GcpError):
                auth = None
            result = users.export(self._users(), uid, reason, out, auth=auth)
            self._show_user_text("내보냈습니다: %s\n개인정보가 든 파일입니다 — 전달한 뒤 지우세요." % out)
            return result

        self.run("사용자 내보내기", work)

    def do_user_delete_ilog(self) -> None:
        uid = self._picked_uid()
        if not uid:
            return
        typed = simpledialog.askstring(
            "통역 기록 삭제",
            "이 사용자의 서버 통역 기록(ilog)을 지웁니다. 되돌릴 수 없습니다. 진도·여행은 그대로입니다.\n"
            "계속하려면 uid 를 그대로 입력하세요:\n%s" % uid, parent=self.root) or ""
        if typed.strip() != uid:
            if typed:
                messagebox.showinfo("opsarchive", "uid 가 달라 취소했습니다.")
            return
        reason = self._ask_reason("통역 기록 삭제")
        if not reason:
            return

        def work() -> dict:
            result = users.delete_ilog(self._users(), uid, reason)
            self._show_user_text(("삭제했습니다. " if result["deleted"] else "") + result["note"])
            return result

        self.run("통역 기록 삭제", work)

    def do_user_audit(self) -> None:
        rows = users.read_audit(50)
        text = "\n".join("%s  %-20s uid#%s  %s  [%s] %s" % (r.get("at", ""), r.get("action", ""), r.get("uid_hash", ""),
                                                          r.get("admin", ""), r.get("result", ""), r.get("reason", ""))
                         for r in reversed(rows))
        self.user_detail_text = "열람 기록(최근 50건, %s)\n" % users.audit_path() + (text or "(아직 없음)")
        self._fill_users()

    # ------------------------------------------------------------ 탭 5: 보관소
    def _tab_store(self, notebook) -> None:
        frame = self._frame(notebook, "보관소")
        ttk.Label(frame, text="탈퇴 실패 때 앱이 봉인해 둔 증거입니다. 목록을 보고, 개인키로 열어 내용을 확인합니다.",
                  wraplength=840).pack(anchor="w", padx=10, pady=(8, 0))
        steps = self._steps_frame(frame)
        self._step(steps, 0, "①", "목록 새로 고침",
                   "봉인된 아카이브 목록을 아래 표에 채웁니다(IAM 검사용 카나리아는 제외).",
                   "list", "목록 새로 고침", self.do_list)
        self._step(steps, 1, "②", "아카이브 선택",
                   "표에서 줄을 클릭하면 그 id 가 선택됩니다. 직접 입력하거나 붙여넣어도 됩니다.",
                   "pick", "선택 지우기", self.clear_archive_pick)
        self._step(steps, 2, "③", "복호화(열기)",
                   "이 PC의 **개인키로만** 열립니다. 내용에는 사용자 개인정보가 들어 있습니다 — 필요한 때만 여세요.",
                   "decrypt", "복호화 실행", self.do_decrypt)
        self.store_hint = self._hint(frame)

        pick = ttk.Frame(frame)
        pick.pack(fill="x", padx=10)
        ttk.Label(pick, text="선택한 id", width=12).pack(side="left")
        self.archive_var = tk.StringVar(value="")
        ttk.Entry(pick, textvariable=self.archive_var, width=46).pack(side="left", padx=4)
        ttk.Label(pick, text="만료(TTL) 전에 확인하세요", foreground="#a60").pack(side="left", padx=8)

        columns = ("id", "created", "trigger", "key", "size", "expire")
        titles = {"id": "아카이브 id", "created": "만든 시각", "trigger": "사유",
                  "key": "키 id", "size": "크기", "expire": "만료"}
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", height=8)
        for name in columns:
            self.tree.heading(name, text=titles[name])
            self.tree.column(name, width=200 if name == "id" else 110, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=10, pady=8)
        self.tree.bind("<<TreeviewSelect>>", self._on_pick_archive)
        ttk.Label(frame, text="복호화하면 사용자 개인정보가 화면·파일에 나타납니다(출력 폴더는 설정의 체크포인트 폴더).",
                  wraplength=840, foreground="#a60").pack(anchor="w", padx=10, pady=(0, 8))

    def _on_pick_archive(self, _event=None) -> None:
        selection = self.tree.selection()
        if selection:
            values = self.tree.item(selection[0], "values")
            if values:
                self.archive_var.set(values[0])
                self.log("선택한 아카이브: %s" % values[0])

    def clear_archive_pick(self) -> None:
        self.archive_var.set("")

    def _fill_tree(self, rows: list) -> None:
        """표를 다시 채운다(메인 스레드에서만 호출 — Tk 규칙)."""
        if not hasattr(self, "tree"):
            return
        for item in self.tree.get_children():
            self.tree.delete(item)
        for row in rows:
            created = ""
            try:
                created = time.strftime("%Y-%m-%d %H:%M", time.localtime(float(row.get("created_at", 0) or 0)))
            except (ValueError, OSError):
                created = str(row.get("created_at", ""))
            expire = ""
            try:
                expire = time.strftime("%Y-%m-%d", time.localtime(float(row.get("expire_at", 0) or 0)))
            except (ValueError, OSError):
                expire = ""
            self.tree.insert("", "end", values=(row.get("_id", ""), created, row.get("trigger", ""),
                                                str(row.get("key_id", ""))[:12],
                                                "%s B" % row.get("size", "?"), expire))

    def do_list(self) -> None:
        def work() -> dict:
            rows = commands.list_archives(self.require("project_id"), self.require("sa_path"))
            self.last_rows = rows
            return {"아카이브": "%d개" % len(rows),
                    "최신": (rows[0].get("_id", "") if rows else "없음")}

        self.run("목록", work)

    def do_decrypt(self) -> None:
        archive_id = (self.archive_var.get() or "").strip()
        if not archive_id:
            archive_id = simpledialog.askstring("opsarchive", "아카이브 id(표에서 고르면 자동 입력)",
                                                parent=self.root) or ""
        if not archive_id:
            return
        key_file = self.pick_key("admin")
        if not key_file:
            return
        phrase = self.ask_key_pass(key_file, "개인키 패스프레이즈")
        if not phrase:
            return
        out_dir = self.settings.get("checkpoints_dir")

        def work() -> dict:
            report = commands.decrypt_archive(self.require("project_id"), self.require("sa_path"),
                                             archive_id, key_file, phrase, out_dir=out_dir)
            keys = ", ".join(sorted(report.keys())[:12]) if isinstance(report, dict) else ""
            return {"열림": "예", "최상위 키": keys or "(요약 없음)",
                    "저장 위치": report.get("_written", "(요약만)") if isinstance(report, dict) else ""}

        self.run("복호화", work)

    def _tab_verify(self, notebook) -> None:
        frame = self._frame(notebook, "검증")
        ttk.Label(frame, text="증거가 **사라지거나 순서가 바뀌지 않았는지**를 관리자가 앱 밖에서 확인하는 단계입니다.\n"
                             "anchor 는 지금 상태를 서명해 봉인하는 일이고, verify-chain 은 그 서명들을 검사합니다.",
                  wraplength=840, justify="left").pack(anchor="w", padx=10, pady=(8, 0))
        steps = self._steps_frame(frame)
        self._step(steps, 0, "①", "서명 키·핀 상태",
                   "서명 키가 있고 핀에 그 공개키가 들어 있는지 봅니다(없으면 핀을 다시 만들어야 합니다).",
                   "vstatus", "상태 확인", self.do_verify_status)
        self._step(steps, 1, "②", "체크포인트 만들기(anchor)",
                   "지금 저장소의 (아카이브·시도 항목) 개수와 머리를 서명해 앵커합니다. 주기적으로 돌리세요.",
                   "anchor", "anchor 실행", self.do_anchor)
        self._step(steps, 2, "③", "체인 검증(verify-chain)",
                   "서명·seq 연속성·개수 롤백·체인 갈래·**앵커 뒤 사라진 아카이브**를 검사합니다.",
                   "verify", "verify 실행", self.do_verify)
        self._step(steps, 3, "④", "챌린지 대조(사용자 증명)",
                   "사용자가 보낸 챌린지가 앵커 범위 안에 있는지 봅니다 — 없으면 **누락 의심**입니다.",
                   "challenge", "챌린지로 검증", self.do_verify_challenge)
        self._step(steps, 4, "⑤", "KMS 서명 키 점검·핀에 넣기",
                   "설정의 KMS 키(Ed25519)로 시험 서명을 해 보고, 그 공개키를 핀의 **자동 서명 키**로 넣습니다. "
                   "넣은 뒤 Render 탭 ⑨ 로 Actions 변수를 다시 올려야 자동 앵커(CI)가 검증할 수 있습니다.",
                   "kms", "KMS 점검·핀 추가", self.do_kms_pin_add)
        self._step(steps, 5, "⑥", "자동 앵커 검증(Firestore)",
                   "자동 앵커(CI)가 Firestore 에 쌓은 체크포인트와 로컬 체크포인트를 함께 검증하고, "
                   "마지막 체크포인트가 13시간보다 오래됐으면(자동 앵커가 멈춤) 실패로 알립니다.",
                   "verify-auto", "자동 앵커 검증", self.do_verify_auto)
        self._step(steps, 6, "⑦", "KMS 서명 감사 대조(누가 서명했나)",
                   "Cloud 감사 로그의 KMS 서명 기록(누가·언제)을 체크포인트와 맞춰 봅니다. 짝이 없는 서명은 **무단 서명 의심**, "
                   "실패한 요청은 **누가 시도했는지** 보여 줍니다. KMS 데이터 액세스 로그가 켜져 있어야 하고, "
                   "서비스 계정에 roles/logging.privateLogViewer 가 필요합니다.",
                   "kms-audit", "감사 대조(7일)", self.do_kms_audit)
        self.verify_hint = self._hint(frame)

    def do_verify_status(self) -> None:
        def work() -> dict:
            out: dict = {}
            pin_path = str(self.settings.get("pin_path") or "")
            try:
                pin = pins.read(config.resolve(pin_path))
                out["핀"] = "armed=%s 세대=%s" % (pin.get("armed"), pin.get("generation"))
                out["핀에 서명 키"] = "있음" if pin.get("signing_public_key") else \
                    "없음 — Render 탭 ⑤ 핀 만들기에서 **서명 키를 골라** 다시 만드세요"
            except FileNotFoundError:
                out["핀"] = "없음 — Render 탭 ⑤ 핀 만들기"
            except Exception as exc:      # noqa: BLE001
                out["핀"] = "읽기 실패(%s)" % getattr(exc, "code", type(exc).__name__)
            keys = config.key_files()
            out["서명 키 파일"] = os.path.basename(keys["sign"][0]) if keys["sign"] else "없음 — 키 탭 ③"
            directory = config.resolve(str(self.settings.get("checkpoints_dir") or ""))
            seqs = sorted(int(n[:-5]) for n in (os.listdir(directory) if os.path.isdir(directory) else [])
                          if n.endswith(".json") and n[:-5].isdigit())
            out["체크포인트"] = ("%d개 (마지막 seq %d)" % (len(seqs), seqs[-1])) if seqs else "없음 — ② anchor 실행"
            out["앵커 목록 파일"] = "있음" if os.path.isdir(os.path.join(directory, "anchors")) else "없음"
            try:
                entries = gcp.Firestore(self.require("project_id"), self.require("sa_path")).list(
                    "evidence_entries", page_size=300)
                out["체인 시도·결과 항목"] = "%d개" % len(entries)
            except Exception as exc:      # noqa: BLE001
                out["체인 항목"] = "확인 실패(%s)" % getattr(exc, "code", type(exc).__name__)
            return out

        self.run("검증 상태", work)

    def do_anchor(self) -> None:
        sign_file = self.pick_key("sign")
        phrase = self.ask_key_pass(sign_file, "서명 키 패스프레이즈")
        if not sign_file or not phrase:
            return
        self.run("anchor", lambda: commands.anchor(
            self.require("project_id"), self.require("sa_path"), sign_file, phrase,
            out_dir=self.settings.get("checkpoints_dir")))

    def do_verify(self, challenge: str = "") -> None:
        self.run("verify-chain", lambda: commands.verify_chain(
            self.require("project_id"), self.require("sa_path"), self.settings.get("pin_path"),
            out_dir=self.settings.get("checkpoints_dir"), challenge=challenge))

    def do_kms_pin_add(self) -> None:
        kms_key = str(self.settings.get("kms_key") or "").strip()
        if not kms_key:
            messagebox.showerror("opsarchive", "설정 탭에서 'KMS 서명 키' 를 먼저 넣으세요.")
            return
        if not messagebox.askyesno("opsarchive", "KMS 키로 시험 서명을 하고, 그 공개키를 핀의 자동 서명 키로 넣습니다.\n\n%s\n\n계속할까요?" % kms_key,
                                   parent=self.root):
            return
        self.run("KMS 핀 추가", lambda: commands.kms_pin_add(
            self.settings.get("pin_path") or "", kms_key, self.require("sa_path")))

    def do_verify_auto(self) -> None:
        self.run("자동 앵커 검증", lambda: commands.verify_chain(
            self.require("project_id"), self.require("sa_path"), self.settings.get("pin_path"),
            out_dir=self.settings.get("checkpoints_dir"), source="both", max_age_hours=13))

    def do_kms_audit(self) -> None:
        kms_key = str(self.settings.get("kms_key") or "").strip()
        if not kms_key:
            messagebox.showerror("opsarchive", "설정 탭에서 'KMS 서명 키' 를 먼저 넣으세요.")
            return
        self.run("KMS 감사 대조", lambda: commands.kms_audit_check(
            self.require("project_id"), self.require("sa_path"), kms_key, days=7,
            pin_path=self.settings.get("pin_path") or "", out_dir=self.settings.get("checkpoints_dir") or ""))

    def do_verify_challenge(self) -> None:
        value = simpledialog.askstring("opsarchive", "사용자가 제시한 챌린지(16진수)", parent=self.root) or ""
        if value:
            self.do_verify(value.strip().lower())

    # ------------------------------------------------------------ 탭 7: 로그
    # ------------------------------------------------------------ 로그 창(별도 창)
    def open_log_window(self) -> None:
        """로그는 메인 창의 탭이 아니라 **별도 창**이다(작업 화면을 가리지 않고, 크게 볼 수 있다)."""
        if self.log_window is not None and self.log_window.winfo_exists():
            self.log_window.deiconify()
            self.log_window.lift()
            return
        window = tk.Toplevel(self.root)
        window.title("opsarchive — 로그")
        window.geometry("760x520+1220+80")
        window.transient(self.root)
        self.log_window = window
        output = tk.Text(window, wrap="word", state="disabled")
        output.pack(fill="both", expand=True, padx=8, pady=6)
        output.tag_configure("head", foreground="#0b6")
        output.tag_configure("ok", foreground="#06c")
        output.tag_configure("err", foreground="#c00")
        self.output = output
        for tag, text in self.log_lines:          # 다시 열면 이전 로그를 되살린다
            output.configure(state="normal")
            output.insert("end", text + "\n", tag)
            output.configure(state="disabled")
        if self.log_lines:
            output.see("end")
        bar = ttk.Frame(window)
        bar.pack(fill="x", padx=8, pady=(0, 8))
        self._button(bar, "복사", self.copy_log)
        self._button(bar, "지우기", self.clear_log)
        ttk.Label(bar, text="이 창을 닫아도 작업은 계속됩니다 — '로그 창 열기'로 다시 엽니다.",
                  foreground="#666").pack(side="right", padx=6)

    def copy_log(self) -> None:
        if self.output is None or not self.output.winfo_exists():
            self.open_log_window()
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self.output.get("1.0", "end"))
        self.log("로그를 클립보드에 복사했습니다.")

    def clear_log(self) -> None:
        if self.output is None or not self.output.winfo_exists():
            self.open_log_window()
            return
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.configure(state="disabled")


def run() -> int:
    try:
        root = tk.Tk()
    except Exception as exc:  # noqa: BLE001 — 창을 못 여는 환경이면 CLI 를 안내한다
        print("GUI 를 열 수 없습니다(%s). CLI 로 실행하세요: python -m opsarchive selftest" % type(exc).__name__)
        return 2
    App(root)
    root.mainloop()
    return 0
