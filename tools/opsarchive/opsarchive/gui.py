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

import os
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import commands, config, container as C, entropy, gcp, pins, render, workflow

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
]


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("opsarchive — 탈퇴 실패 증거 봉인")
        self.root.geometry("1180x780")          # 설명이 잘리지 않도록 넉넉하게 시작한다
        self.root.minsize(960, 620)
        self.log_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self.busy = False
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

    def run(self, label: str, fn) -> None:
        """작업을 워커 스레드로 돌린다(패스프레이즈 입력은 메인 스레드에서 먼저 받는다)."""
        if self.busy:
            messagebox.showinfo("opsarchive", "다른 작업이 아직 돌고 있어요.")
            return
        self.busy = True
        self.log("▶ " + label, "head")
        self.log_queue.put(("status", "작업 중: " + label))

        def worker() -> None:
            try:
                result = fn()
                if isinstance(result, dict) and result.get("error"):
                    # rotate 처럼 "부분 성공 + error" 를 돌려주는 경우를 성공으로 보지 않는다.
                    self.last[label] = "✘ " + str(result["error"])
                    self.log("✘ 실패: %s" % result["error"], "err")
                    for key, value in result.items():
                        self.log("   %s: %s" % (key, value))
                    return
                if isinstance(result, dict):
                    for key, value in result.items():
                        self.log("   %s: %s" % (key, value))
                elif result:
                    self.log("   " + str(result))
                self.last[label] = "✔ 완료"
                self.log("✔ 끝", "ok")
                self.log_queue.put(("status", "✔ %s 완료" % label))
            except Exception as exc:  # noqa: BLE001 — GUI 는 어떤 예외도 창을 닫지 않게
                code = getattr(exc, "code", "")
                self.last[label] = "✘ 실패: " + str(code or type(exc).__name__)
                self.log("✘ %s%s" % (type(exc).__name__, (": " + str(code)) if code else ""), "err")
                self.log_queue.put(("status", "✘ %s 실패: %s" % (label, code or type(exc).__name__)))
                if str(exc):
                    self.log("   " + str(exc)[:400], "err")
            finally:
                self.busy = False
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
        ttk.Label(frame, text="자동화 워크플로우 — 노드를 클릭해 값을 바꾸고 [정책에 저장] 하면 다음 실행부터 반영됩니다.\n"
                             "서버 정책(환경변수)을 바꾸는 노드는 [Render에 반영] 뒤 재배포가 필요합니다.",
                  justify="left").pack(anchor="w", padx=10, pady=(8, 2))
        self.canvas = tk.Canvas(frame, height=360, background="#fbfbfd", highlightthickness=1,
                                highlightbackground="#dde")
        self.canvas.pack(fill="both", expand=True, padx=10, pady=4)
        self.canvas.bind("<Button-1>", self._on_canvas_click)

        editor = ttk.LabelFrame(frame, text="선택한 노드")
        editor.pack(fill="x", padx=10, pady=4)
        self.node_title = ttk.Label(editor, text="노드를 클릭하세요", font=("", 10, "bold"))
        self.node_title.pack(anchor="w", padx=8, pady=(4, 0))
        self.node_desc = ttk.Label(editor, text="", justify="left")
        self.node_desc.pack(anchor="w", padx=8)
        self._wrap(self.node_desc, editor)
        self.value_box = ttk.Frame(editor)
        self.value_box.pack(anchor="w", padx=8, pady=4)
        bar = ttk.Frame(editor)
        bar.pack(fill="x", padx=8, pady=(0, 6))
        self._button(bar, "정책에 저장", self.save_node)
        self._button(bar, "Render에 반영", self.push_node_env)
        self._button(bar, "이 노드 실행", self.run_node)

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
        x = 16
        y = 14
        self.node_boxes = {}
        for group in data.get("groups", []):
            self.canvas.create_text(x + 4, y, text=group.get("name", ""), anchor="nw",
                                    fill="#557", font=("", 9, "bold"))
            ty = y + 22
            for node in group.get("nodes", []):
                nid = node["id"]
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
                                    arrow="last", fill="#9ab", smooth=True)
        self.canvas.configure(scrollregion=self.canvas.bbox("all") or (0, 0, 800, 400))

    def _on_canvas_click(self, event) -> None:
        items = self.canvas.find_overlapping(event.x - 1, event.y - 1, event.x + 1, event.y + 1)
        for item in items:
            for tag in self.canvas.gettags(item):
                if tag.startswith("n:"):
                    self.selected_node = tag[2:]
                    self._redraw_mindmap()
                    self._show_node_editor()
                    return

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
            extra = "\n서버 환경변수: %s%s" % (node["env"], " · 반영 후 재배포 필요" if node.get("redeploy") else "")
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
                            onvalue="1", offvalue="0").pack(side="left")
        elif kind == "choice":
            options = [value for value, _label in node.get("options", [])]
            self.node_value.set(str(current))
            ttk.Combobox(self.value_box, textvariable=self.node_value, values=options,
                         width=16, state="readonly").pack(side="left")
        elif kind == "number":
            self.node_value.set(str(current))
            ttk.Entry(self.value_box, textvariable=self.node_value, width=12).pack(side="left")
            ttk.Label(self.value_box, text="(%s ~ %s)" % (node.get("min"), node.get("max"))).pack(side="left", padx=6)
        else:
            self.node_value.set("")
            ttk.Label(self.value_box, text="값이 없는 실행 노드입니다 — [이 노드 실행] 을 누르세요.").pack(side="left")

    def save_node(self) -> None:
        node = self._node_def(self.selected_node)
        if not node:
            return
        if node.get("kind") in ("toggle", "choice", "number"):
            value = self.node_value.get()
            if node["kind"] == "toggle":
                value = value in ("1", "True", "true")
            elif node["kind"] == "number":
                try:
                    value = int(value)
                except ValueError:
                    messagebox.showerror("opsarchive", "숫자를 입력하세요.")
                    return
            self.policy[self.selected_node] = value
        path = workflow.save(self.policy)
        self.log("노드 '%s' 값을 저장했습니다 (%s)" % (self.selected_node, path))
        self._redraw_mindmap()
        self._show_node_editor()

    def push_node_env(self) -> None:
        node = self._node_def(self.selected_node)
        if not node or not node.get("env"):
            messagebox.showinfo("opsarchive", "이 노드는 서버 환경변수와 연결돼 있지 않습니다.")
            return
        self.run("Render 반영(%s)" % node["env"], lambda: workflow.push_env(
            self.selected_node, self.policy, service=self.require("service")))

    def run_node(self) -> None:
        node = self._node_def(self.selected_node)
        if not node:
            return
        secrets = {}
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
                self.log_queue.put(("refresh", ""))

        self.automation_thread = threading.Thread(target=worker, name="opsarchive-auto", daemon=True)
        self.automation_thread.start()
        self.log("자동 실행을 시작했습니다(관리자 PC가 켜져 있는 동안만 돕니다).")

    def stop_automation(self) -> None:
        if getattr(self, "automation_stop", None):
            self.automation_stop.set()
            self.log("자동 실행 중지를 요청했습니다(현재 주기가 끝나면 멈춥니다).")

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
                   "개인키에서 역산한 지문을 저장소 파일에 기록합니다. 이후 핀 검사·CI 가 '예상 밖 키'를 잡습니다.",
                   "pin", "핀 만들기", self.do_pin)
        self._step(steps, 5, "⑥", "핀 검사",
                   "핀 파일과 배포된 /health 의 지문·세대를 대조합니다(CI cron 과 같은 검사).",
                   "pin-check", "핀 검사 실행", self.do_pin_check)
        self._step(steps, 6, "⑦", "IAM 검사",
                   "앱 서비스 계정이 증거를 지울 수 있는지 시험합니다(목표: 만들 수는 있고 지울 수는 없다).",
                   "iam", "IAM 검사 실행", self.do_iam)
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
        """Render 서비스 이름 선택 — 워크스페이스 목록에서 골라 settings.json 에 넣는다.

        이름을 손으로 적으면 밑줄/하이픈 차이로 `not_found` 가 나기 쉽다(실제로 그렇게 막혔다).
        목록에서 고르면 그 실수가 사라지고, 직접 입력도 허용한다.
        """
        names: list[str] = []
        error = ""
        try:
            names = render.service_names()
        except Exception as exc:      # noqa: BLE001 — CLI 없음·미로그인 등을 화면에 보여준다
            error = "%s%s" % (getattr(exc, "code", ""), type(exc).__name__)

        window = tk.Toplevel(self.root)
        window.title("Render 서비스 선택")
        window.geometry("640x200")
        window.transient(self.root)
        ttk.Label(window, text="워크스페이스의 서비스 %d개%s" % (len(names), (" — 조회 실패(%s)" % error) if error else "")).pack(
            anchor="w", padx=12, pady=(10, 2))
        ttk.Label(window, text="앱 주소(호스트)와 서비스 이름은 다를 수 있습니다 — 이름은 여기서 고르세요.",
                  foreground="#666").pack(anchor="w", padx=12)
        var = tk.StringVar(value=str(self.settings.get("service") or (names[0] if names else "")))
        ttk.Combobox(window, textvariable=var, values=names, width=60, state="normal").pack(fill="x", padx=12, pady=8)
        status = ttk.Label(window, text="", foreground="#060")
        status.pack(anchor="w", padx=12)

        def confirm() -> None:
            chosen = (var.get() or "").strip()
            if not chosen:
                return
            if names and chosen not in names:
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
        self.root.wait_window(window)

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
        self.run("publish", lambda: commands.publish(
            self.require("service"), key_file, phrase, env_key=self.settings.get("env_key"),
            base_url=self.settings.get("base_url"), on_step=self.log))

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
            generation=int(self.settings.get("generation") or 1), signing_public=signing))

    def do_pin_check(self) -> None:
        self.run("pin-check", lambda: commands.check_pin(self.settings.get("pin_path"),
                                                         health_url=self.require("base_url")))

    def do_iam(self) -> None:
        self.run("iam-check", lambda: commands.iam_check(self.require("project_id"),
                                                         self.require("sa_path")))

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
                    "evidence_chain/entries", page_size=300)
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
