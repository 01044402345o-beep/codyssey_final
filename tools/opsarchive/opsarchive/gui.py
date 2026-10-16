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
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import commands, config, container as C, entropy, gcp, pins, render

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
        self.root.geometry("900x680")
        self.log_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self.busy = False
        self.settings = config.bootstrap()
        self.env_values = config.parse_env(self._read(config.env_path()))
        self.setting_vars: dict[str, tk.StringVar] = {}
        self._build()
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
            self.output.configure(state="normal")
            self.output.insert("end", text + "\n", tag)
            self.output.see("end")
            self.output.configure(state="disabled")
        self.root.after(120, self._drain)

    def ask_pass(self, prompt: str = "패스프레이즈") -> str:
        return simpledialog.askstring("opsarchive", prompt, show="*", parent=self.root) or ""

    def run(self, label: str, fn) -> None:
        """작업을 워커 스레드로 돌린다(패스프레이즈 입력은 메인 스레드에서 먼저 받는다)."""
        if self.busy:
            messagebox.showinfo("opsarchive", "다른 작업이 아직 돌고 있어요.")
            return
        self.busy = True
        self.log("▶ " + label, "head")

        def worker() -> None:
            try:
                result = fn()
                if isinstance(result, dict):
                    for key, value in result.items():
                        self.log("   %s: %s" % (key, value))
                elif result:
                    self.log("   " + str(result))
                self.log("✔ 끝", "ok")
            except Exception as exc:  # noqa: BLE001 — GUI 는 어떤 예외도 창을 닫지 않게
                code = getattr(exc, "code", "")
                self.log("✘ %s%s" % (type(exc).__name__, (": " + str(code)) if code else ""), "err")
                if str(exc):
                    self.log("   " + str(exc)[:400], "err")
            finally:
                self.busy = False

        threading.Thread(target=worker, name="opsarchive-gui", daemon=True).start()

    def _build(self) -> None:
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=8, pady=8)
        self._tab_overview(notebook)
        self._tab_settings(notebook)
        self._tab_keys(notebook)
        self._tab_render(notebook)
        self._tab_store(notebook)
        self._tab_verify(notebook)
        self._tab_log(notebook)

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
        ttk.Label(frame, text="무엇부터 할까요? 처음이면 ① selftest → ② keygen → ③ publish → ④ doctor 순서입니다.",
                  wraplength=820, justify="left").pack(anchor="w", padx=8, pady=6)
        self.overview = tk.Text(frame, height=22, wrap="word")
        self.overview.pack(fill="both", expand=True, padx=8, pady=4)
        bar = ttk.Frame(frame)
        bar.pack(fill="x", padx=8, pady=4)
        self._button(bar, "새로 고침", self.refresh_overview)
        self._button(bar, "설정 다시 읽기", self.reload_settings)

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
        ttk.Label(frame, text="① selftest 로 형식이 정상인지 먼저 확인하고, ② keygen 으로 봉투 키를 만듭니다.",
                  wraplength=820).pack(anchor="w", padx=8, pady=6)
        bar = ttk.Frame(frame)
        bar.pack(fill="x", padx=8)
        self._button(bar, "① selftest", lambda: self.run("selftest", commands.selftest))
        self._button(bar, "② keygen(봉투 키)", self.do_keygen)
        self._button(bar, "서명 키 만들기(anchor 용)", self.do_signkey)
        self._button(bar, "③ rotate(회전)", self.do_rotate)
        self._button(bar, "무작위 값 생성(OS 감지)", self.do_random)
        ttk.Label(frame, text="키 파일은 설정의 '개인키 폴더'에 만들어집니다. 파일을 잃으면 열 수 없으니 백업하세요.",
                  wraplength=820).pack(anchor="w", padx=8, pady=10)

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
        old = self.ask_pass("지금 개인키의 패스프레이즈")
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
        ttk.Label(frame, text="④ publish 로 공개키를 Render 환경변수에 올리고 재배포합니다(환경변수만 REST API).\n"
                             "⑤ doctor 로 로컬 키와 배포된 지문이 맞는지 확인합니다.",
                  wraplength=820, justify="left").pack(anchor="w", padx=8, pady=6)
        bar = ttk.Frame(frame)
        bar.pack(fill="x", padx=8)
        self._button(bar, "④ publish", self.do_publish)
        self._button(bar, "⑤ doctor", self.do_doctor)
        self._button(bar, "로그 관찰(observe)", self.do_observe)
        bar2 = ttk.Frame(frame)
        bar2.pack(fill="x", padx=8)
        self._button(bar2, "핀 만들기(개인키 역산)", self.do_pin)
        self._button(bar2, "핀 검사", self.do_pin_check)
        self._button(bar2, "IAM 검사(앱이 증거를 못 지우는지)", self.do_iam)

    def require(self, key: str) -> str:
        value = str(self.settings.get(key) or "").strip()
        if not value:
            raise commands.CommandError("설정_누락:" + key)
        return value

    def pick_key(self, kind: str = "admin") -> str:
        keys = config.key_files()[kind]
        if not keys:
            messagebox.showinfo("opsarchive", "%s 키가 없습니다. 키 탭에서 먼저 만드세요." % kind)
            return ""
        if len(keys) == 1:
            return keys[0]
        from tkinter import simpledialog as sd
        choice = sd.askstring("opsarchive", "키 파일 선택:\n" + "\n".join(keys))
        return choice if choice in keys else ""

    def do_publish(self) -> None:
        key_file = self.pick_key("admin")
        phrase = self.ask_pass("개인키 패스프레이즈")
        if not key_file or not phrase:
            return
        self.run("publish", lambda: commands.publish(
            self.require("service"), key_file, phrase, env_key=self.settings.get("env_key"),
            base_url=self.settings.get("base_url")))

    def do_doctor(self) -> None:
        key_file = self.pick_key("admin")
        phrase = self.ask_pass("개인키 패스프레이즈")
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
        phrase = self.ask_pass("개인키 패스프레이즈")
        if not key_file or not phrase:
            return
        sign_file = self.pick_key("sign")
        sign_phrase = self.ask_pass("서명키 패스프레이즈") if sign_file else ""
        signing = C.sign_public(C.load_private_key(sign_file, sign_phrase)) if sign_file else None
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
        ttk.Label(frame, text="봉인된 아카이브 목록을 보고, 개인키로 열어 내용을 확인합니다(개인정보 포함).",
                  wraplength=820).pack(anchor="w", padx=8, pady=6)
        bar = ttk.Frame(frame)
        bar.pack(fill="x", padx=8)
        self._button(bar, "목록(list)", self.do_list)
        self._button(bar, "복호화(decrypt)", self.do_decrypt)

    def do_list(self) -> None:
        self.run("list", lambda: {"아카이브": len(commands.list_archives(
            self.require("project_id"), self.require("sa_path")))})

    def do_decrypt(self) -> None:
        archive_id = simpledialog.askstring("opsarchive", "아카이브 ID", parent=self.root) or ""
        if not archive_id:
            return
        key_file = self.pick_key("admin")
        phrase = self.ask_pass("개인키 패스프레이즈")
        out_dir = self.settings.get("checkpoints_dir")
        if not key_file or not phrase:
            return
        self.run("decrypt", lambda: {"결과": str(commands.decrypt_archive(
            self.require("project_id"), self.require("sa_path"), archive_id, key_file, phrase,
            out_dir=out_dir))[:120]})

    # ------------------------------------------------------------ 탭 6: 검증
    def _tab_verify(self, notebook) -> None:
        frame = self._frame(notebook, "검증")
        ttk.Label(frame, text="체크포인트를 서명해 앵커하고(anchor), 서명·연속성·누락을 검증합니다.\n"
                             "사용자가 준 챌린지(증명 파일)가 있으면 함께 대조하세요.",
                  wraplength=820, justify="left").pack(anchor="w", padx=8, pady=6)
        bar = ttk.Frame(frame)
        bar.pack(fill="x", padx=8)
        self._button(bar, "anchor(서명)", self.do_anchor)
        self._button(bar, "verify-chain", self.do_verify)
        self._button(bar, "verify-chain + 챌린지", self.do_verify_challenge)

    def do_anchor(self) -> None:
        sign_file = self.pick_key("sign")
        phrase = self.ask_pass("서명키 패스프레이즈")
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
    def _tab_log(self, notebook) -> None:
        frame = self._frame(notebook, "로그")
        self.output = tk.Text(frame, wrap="word", state="disabled")
        self.output.pack(fill="both", expand=True, padx=8, pady=4)
        self.output.tag_configure("head", foreground="#0b6")
        self.output.tag_configure("ok", foreground="#06c")
        self.output.tag_configure("err", foreground="#c00")
        bar = ttk.Frame(frame)
        bar.pack(fill="x", padx=8, pady=4)
        self._button(bar, "복사", self.copy_log)
        self._button(bar, "지우기", self.clear_log)

    def copy_log(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self.output.get("1.0", "end"))
        self.log("로그를 클립보드에 복사했습니다.")

    def clear_log(self) -> None:
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
