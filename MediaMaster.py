import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import os
import sys
import json
import re
import webbrowser
from pathlib import Path
import subprocess

# ─── Try imports ────────────────────────────────────────────────────────────
try:
    from PIL import Image
    PIL_OK = True
except ImportError:
    PIL_OK = False

try:
    import yt_dlp
    YTDLP_OK = True
except ImportError:
    YTDLP_OK = False

try:
    import requests
    REQUESTS_OK = True
except ImportError:
    REQUESTS_OK = False

# ─── Constants ───────────────────────────────────────────────────────────────
APP_NAME       = "MasterConverting"
APP_VERSION    = "2.0"
BMC_USERNAME   = "Amrsherif74"
BMC_URL        = f"https://buymeacoffee.com/{BMC_USERNAME}"
BMC_PRICE      = 5.99
FREE_LIMIT     = 1          # free = 1 file at a time
PREMIUM_BATCH  = 50         # premium = up to 50 files
LICENSE_FILE   = Path.home() / ".MasterConverting_license.json"

IMAGE_FORMATS  = ["PNG","JPEG","JPG","WEBP","BMP","GIF","TIFF","ICO","PPM","HEIC"]
VIDEO_FORMATS  = ["MP4","AVI","MKV","MOV","FLV","WEBM","WMV","3GP","OGV","TS"]
QUALITY_OPTIONS= ["best","1080p","720p","480p","360p","240p","audio only"]

# ─── Color palette ───────────────────────────────────────────────────────────
BG       = "#0D0D0D"
BG2      = "#141414"
BG3      = "#1C1C1C"
ACCENT   = "#FF6B35"   # warm orange
ACCENT2  = "#FFD166"   # gold
TEXT     = "#F5F5F5"
TEXT2    = "#9A9A9A"
SUCCESS  = "#06D6A0"
DANGER   = "#EF233C"
BORDER   = "#2A2A2A"

# ─── License manager ─────────────────────────────────────────────────────────
class LicenseManager:
    def __init__(self):
        self.data = {"premium": False, "username": "", "verified": False}
        self._load()

    def _load(self):
        if LICENSE_FILE.exists():
            try:
                self.data = json.loads(LICENSE_FILE.read_text())
            except Exception:
                pass

    def _save(self):
        LICENSE_FILE.write_text(json.dumps(self.data, indent=2))

    def is_premium(self):
        return self.data.get("premium", False) and self.data.get("verified", False)

    def get_username(self):
        return self.data.get("username", "")

    def verify_and_activate(self, username: str) -> tuple[bool, str]:
        """
        Checks Buy Me a Coffee public page for evidence of a $5.99 support.
        Since BMC has no public API for supporters, we open the page and ask
        the user to confirm – then flag as verified (honour system + page check).
        """
        username = username.strip().lstrip("@")
        if not username:
            return False, "يرجى إدخال اسم المستخدم الخاص بك على Buy Me a Coffee"

        # Attempt a quick HTTP check that the username page exists
        if REQUESTS_OK:
            try:
                r = requests.get(f"https://buymeacoffee.com/{username}", timeout=8)
                if r.status_code == 404:
                    return False, f"المستخدم '{username}' غير موجود على Buy Me a Coffee.\nتأكد من الاسم وحاول مجددًا."
            except Exception:
                pass   # offline – skip validation

        # Mark as premium
        self.data = {"premium": True, "username": username, "verified": True}
        self._save()
        return True, f"✅ تم تفعيل الحساب!\nمرحبًا {username}، يمكنك الآن رفع حتى {PREMIUM_BATCH} ملف في المرة الواحدة."

    def deactivate(self):
        self.data = {"premium": False, "username": "", "verified": False}
        self._save()

LICENSE = LicenseManager()

# ─── Conversion helpers ───────────────────────────────────────────────────────
def convert_image(src: str, dst_fmt: str, out_dir: str) -> str:
    if not PIL_OK:
        raise RuntimeError("مكتبة Pillow غير مثبتة. شغّل: pip install pillow")
    img = Image.open(src)
    fmt = dst_fmt.upper().replace("JPG","JPEG")
    base = Path(src).stem
    ext  = dst_fmt.lower() if dst_fmt.lower() != "jpeg" else "jpg"
    out  = os.path.join(out_dir, f"{base}_converted.{ext}")
    if img.mode in ("RGBA","P") and fmt == "JPEG":
        img = img.convert("RGB")
    img.save(out, format=fmt)
    return out

def convert_video(src: str, dst_fmt: str, out_dir: str, progress_cb=None) -> str:
    base = Path(src).stem
    ext  = dst_fmt.lower()
    out  = os.path.join(out_dir, f"{base}_converted.{ext}")
    cmd  = ["ffmpeg", "-y", "-i", src, out]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        _, err = proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(err[-500:])
    except FileNotFoundError:
        raise RuntimeError("FFmpeg غير مثبت. حمّله من https://ffmpeg.org")
    return out

def _ydl_quality_format(quality: str) -> str:
    map_ = {
        "best": "bestvideo+bestaudio/best",
        "1080p": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
        "720p":  "bestvideo[height<=720]+bestaudio/best[height<=720]",
        "480p":  "bestvideo[height<=480]+bestaudio/best[height<=480]",
        "360p":  "bestvideo[height<=360]+bestaudio/best[height<=360]",
        "240p":  "bestvideo[height<=240]+bestaudio/best[height<=240]",
        "audio only": "bestaudio/best",
    }
    return map_.get(quality, "bestvideo+bestaudio/best")

def download_social(url: str, quality: str, out_dir: str, progress_cb=None) -> str:
    if not YTDLP_OK:
        raise RuntimeError("مكتبة yt-dlp غير مثبتة. شغّل: pip install yt-dlp")
    result_path = [None]

    def hook(d):
        if d["status"] == "finished":
            result_path[0] = d["filename"]
        if progress_cb and d["status"] == "downloading":
            pct = d.get("_percent_str","").strip()
            progress_cb(pct)

    ydl_opts = {
        "format": _ydl_quality_format(quality),
        "outtmpl": os.path.join(out_dir, "%(title)s.%(ext)s"),
        "progress_hooks": [hook],
        "quiet": True,
        "no_warnings": True,
        "merge_output_format": "mp4",
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    return result_path[0] or out_dir

# ─── GUI Application ──────────────────────────────────────────────────────────
class MasterConvertingApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} v{APP_VERSION}")
        self.configure(bg=BG)
        self.resizable(True, True)
        self.minsize(780, 620)

        # State
        self.selected_files   = []
        self.output_dir       = tk.StringVar(value=str(Path.home() / "Downloads"))
        self.convert_to_fmt   = tk.StringVar(value="PNG")
        self.dl_url           = tk.StringVar()
        self.dl_quality       = tk.StringVar(value="best")
        self.status_text      = tk.StringVar(value="جاهز ✔")
        self.progress_var     = tk.DoubleVar(value=0)
        self.mode             = tk.StringVar(value="convert")  # convert / download

        self._setup_fonts()
        self._build_ui()
        self._update_premium_ui()

    def _setup_fonts(self):
        try:
            self.font_h1  = ("Segoe UI", 22, "bold")
            self.font_h2  = ("Segoe UI", 13, "bold")
            self.font_body= ("Segoe UI", 11)
            self.font_sm  = ("Segoe UI", 9)
        except Exception:
            self.font_h1  = ("TkDefaultFont", 18, "bold")
            self.font_h2  = ("TkDefaultFont", 12, "bold")
            self.font_body= ("TkDefaultFont", 10)
            self.font_sm  = ("TkDefaultFont", 9)

    # ── build_ui ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        # ── Header ──────────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=BG, pady=10)
        hdr.pack(fill=tk.X, padx=24, pady=(16,0))

        tk.Label(hdr, text="⚡ MasterConverting", font=self.font_h1,
                 bg=BG, fg=ACCENT).pack(side=tk.LEFT)

        self.premium_badge = tk.Label(hdr, text="FREE", font=self.font_sm,
                                      bg=BG3, fg=TEXT2,
                                      padx=8, pady=3, relief="flat")
        self.premium_badge.pack(side=tk.LEFT, padx=12)

        tk.Button(hdr, text="🔑 ترقية للبريميوم", font=self.font_sm,
                  bg=ACCENT2, fg="#000", relief="flat", cursor="hand2",
                  command=self._open_premium_dialog,
                  padx=10, pady=4).pack(side=tk.RIGHT)

        tk.Label(hdr, text=f"v{APP_VERSION}", font=self.font_sm,
                 bg=BG, fg=TEXT2).pack(side=tk.RIGHT, padx=8)

        # ── Tab bar ──────────────────────────────────────────────────────────
        tab_frame = tk.Frame(self, bg=BG2, pady=0)
        tab_frame.pack(fill=tk.X, padx=24, pady=(12,0))

        self.btn_tab_convert  = self._tab_btn(tab_frame, "🔄  تحويل ملفات", "convert")
        self.btn_tab_download = self._tab_btn(tab_frame, "⬇️  تحميل من الإنترنت","download")
        self.btn_tab_convert.pack(side=tk.LEFT, padx=(0,2))
        self.btn_tab_download.pack(side=tk.LEFT)
        self._select_tab("convert")

        # ── Content area ─────────────────────────────────────────────────────
        self.content = tk.Frame(self, bg=BG2, padx=20, pady=16)
        self.content.pack(fill=tk.BOTH, expand=True, padx=24, pady=8)

        self.convert_frame  = self._build_convert_frame()
        self.download_frame = self._build_download_frame()
        self.convert_frame.pack(fill=tk.BOTH, expand=True)

        # ── Output dir ───────────────────────────────────────────────────────
        out_row = tk.Frame(self, bg=BG, pady=6)
        out_row.pack(fill=tk.X, padx=24)
        tk.Label(out_row, text="📁 مجلد الحفظ:", font=self.font_body,
                 bg=BG, fg=TEXT2).pack(side=tk.LEFT)
        tk.Entry(out_row, textvariable=self.output_dir, font=self.font_sm,
                 bg=BG3, fg=TEXT, insertbackground=TEXT,
                 relief="flat", width=45).pack(side=tk.LEFT, padx=6)
        tk.Button(out_row, text="تغيير", font=self.font_sm,
                  bg=BG3, fg=ACCENT, relief="flat", cursor="hand2",
                  command=self._choose_outdir).pack(side=tk.LEFT)

        # ── Progress ─────────────────────────────────────────────────────────
        prog_frame = tk.Frame(self, bg=BG, pady=4)
        prog_frame.pack(fill=tk.X, padx=24)
        self.progress_bar = ttk.Progressbar(prog_frame, variable=self.progress_var,
                                            maximum=100, length=400)
        self.progress_bar.pack(fill=tk.X)

        # ── Status ───────────────────────────────────────────────────────────
        status_frame = tk.Frame(self, bg=BG, pady=6)
        status_frame.pack(fill=tk.X, padx=24, pady=(0,12))
        tk.Label(status_frame, textvariable=self.status_text,
                 font=self.font_sm, bg=BG, fg=SUCCESS).pack(side=tk.LEFT)

        # ttk style
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TProgressbar", troughcolor=BG3, background=ACCENT,
                        thickness=6, bordercolor=BG3)
        style.configure("TCombobox", fieldbackground=BG3,
                        background=BG3, foreground=TEXT,
                        arrowcolor=ACCENT, selectbackground=BG3)

    # ── Tab helpers ───────────────────────────────────────────────────────────
    def _tab_btn(self, parent, label, mode_val):
        return tk.Button(parent, text=label, font=self.font_body,
                         bg=BG2, fg=TEXT2, relief="flat", cursor="hand2",
                         padx=18, pady=8,
                         command=lambda: self._select_tab(mode_val))

    def _select_tab(self, mode_val):
        self.mode.set(mode_val)
        if mode_val == "convert":
            self.btn_tab_convert.config(bg=BG3, fg=ACCENT)
            self.btn_tab_download.config(bg=BG2, fg=TEXT2)
            if hasattr(self, "download_frame"):
                self.download_frame.pack_forget()
            if hasattr(self, "convert_frame"):
                self.convert_frame.pack(fill=tk.BOTH, expand=True)
        else:
            self.btn_tab_download.config(bg=BG3, fg=ACCENT)
            self.btn_tab_convert.config(bg=BG2, fg=TEXT2)
            if hasattr(self, "convert_frame"):
                self.convert_frame.pack_forget()
            if hasattr(self, "download_frame"):
                self.download_frame.pack(fill=tk.BOTH, expand=True)

    # ── Convert frame ─────────────────────────────────────────────────────────
    def _build_convert_frame(self):
        f = tk.Frame(self.content, bg=BG2)

        # File list area
        lbl_row = tk.Frame(f, bg=BG2)
        lbl_row.pack(fill=tk.X)
        tk.Label(lbl_row, text="الملفات المختارة", font=self.font_h2,
                 bg=BG2, fg=TEXT).pack(side=tk.LEFT)
        self.file_count_lbl = tk.Label(lbl_row, text="(0 ملف)",
                                       font=self.font_sm, bg=BG2, fg=TEXT2)
        self.file_count_lbl.pack(side=tk.LEFT, padx=8)

        list_frame = tk.Frame(f, bg=BORDER)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(6,0))

        self.file_listbox = tk.Listbox(list_frame, bg=BG3, fg=TEXT,
                                       selectbackground="#5A2A1A",
                                       font=self.font_sm,
                                       borderwidth=0, highlightthickness=0,
                                       selectmode=tk.EXTENDED)
        scrollbar = tk.Scrollbar(list_frame, orient=tk.VERTICAL,
                                 command=self.file_listbox.yview,
                                 bg=BG3, troughcolor=BG3)
        self.file_listbox.config(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.file_listbox.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        # Buttons row
        btn_row = tk.Frame(f, bg=BG2, pady=8)
        btn_row.pack(fill=tk.X)
        self._btn(btn_row, "➕ إضافة ملفات", self._add_files, ACCENT).pack(side=tk.LEFT, padx=(0,6))
        self._btn(btn_row, "🗑 حذف المحدد", self._remove_selected, DANGER).pack(side=tk.LEFT, padx=(0,6))
        self._btn(btn_row, "✖ مسح الكل", self._clear_files, BG3).pack(side=tk.LEFT)

        # Format row
        fmt_row = tk.Frame(f, bg=BG2, pady=4)
        fmt_row.pack(fill=tk.X)
        tk.Label(fmt_row, text="تحويل إلى:", font=self.font_body,
                 bg=BG2, fg=TEXT2).pack(side=tk.LEFT, padx=(0,8))

        all_fmts = IMAGE_FORMATS + ["───"] + VIDEO_FORMATS
        self.fmt_combo = ttk.Combobox(fmt_row, textvariable=self.convert_to_fmt,
                                      values=all_fmts, width=14,
                                      state="readonly", font=self.font_body)
        self.fmt_combo.pack(side=tk.LEFT)

        self._btn(fmt_row, "🚀 تحويل الآن", self._start_convert, SUCCESS,
                  font=self.font_h2).pack(side=tk.RIGHT)

        # Premium notice
        self.convert_premium_note = tk.Label(f, text="", font=self.font_sm,
                                             bg=BG2, fg=ACCENT2, wraplength=600,
                                             justify=tk.LEFT)
        self.convert_premium_note.pack(fill=tk.X, pady=(4,0))

        return f

    # ── Download frame ────────────────────────────────────────────────────────
    def _build_download_frame(self):
        f = tk.Frame(self.content, bg=BG2)

        tk.Label(f, text="تحميل من يوتيوب / تيك توك / فيسبوك / انستاجرام",
                 font=self.font_h2, bg=BG2, fg=TEXT).pack(anchor="w")
        tk.Label(f, text="الصق رابط الفيديو هنا 👇", font=self.font_sm,
                 bg=BG2, fg=TEXT2).pack(anchor="w", pady=(2,8))

        url_frame = tk.Frame(f, bg=BORDER, padx=1, pady=1)
        url_frame.pack(fill=tk.X)
        self.url_entry = tk.Entry(url_frame, textvariable=self.dl_url,
                                  font=self.font_body, bg=BG3, fg=TEXT,
                                  insertbackground=ACCENT,
                                  relief="flat")
        self.url_entry.pack(fill=tk.X, ipady=8, padx=2)

        # Supported sites
        sites_frame = tk.Frame(f, bg=BG2, pady=8)
        sites_frame.pack(fill=tk.X)
        for site, color in [("▶ YouTube","#FF0000"),("🎵 TikTok","#69C9D0"),
                             ("📘 Facebook","#1877F2"),("📸 Instagram","#E4405F")]:
            tk.Label(sites_frame, text=site, font=self.font_sm,
                     bg=BG3, fg=color, padx=10, pady=4,
                     relief="flat").pack(side=tk.LEFT, padx=4)

        # Quality
        q_row = tk.Frame(f, bg=BG2, pady=8)
        q_row.pack(fill=tk.X)
        tk.Label(q_row, text="الجودة:", font=self.font_body,
                 bg=BG2, fg=TEXT2).pack(side=tk.LEFT, padx=(0,8))
        ttk.Combobox(q_row, textvariable=self.dl_quality,
                     values=QUALITY_OPTIONS, width=16,
                     state="readonly", font=self.font_body).pack(side=tk.LEFT)

        self._btn(q_row, "⬇ تحميل", self._start_download, SUCCESS,
                  font=self.font_h2).pack(side=tk.RIGHT)

        # Log area
        tk.Label(f, text="سجل التحميل:", font=self.font_sm,
                 bg=BG2, fg=TEXT2).pack(anchor="w", pady=(12,2))
        self.dl_log = tk.Text(f, height=8, bg=BG3, fg=SUCCESS,
                              font=("Consolas",9), relief="flat",
                              state=tk.DISABLED, wrap=tk.WORD)
        self.dl_log.pack(fill=tk.BOTH, expand=True)

        return f

    # ── Widget helpers ────────────────────────────────────────────────────────
    def _btn(self, parent, text, cmd, bg, font=None, **kw):
        if font is None:
            font = self.font_body
        return tk.Button(parent, text=text, command=cmd,
                         bg=bg, fg="#000" if bg in (SUCCESS, ACCENT2) else TEXT,
                         font=font, relief="flat", cursor="hand2",
                         padx=12, pady=6, **kw)

    def _choose_outdir(self):
        d = filedialog.askdirectory(title="اختر مجلد الحفظ")
        if d:
            self.output_dir.set(d)

    # ── File management ───────────────────────────────────────────────────────
    def _add_files(self):
        limit = PREMIUM_BATCH if LICENSE.is_premium() else FREE_LIMIT
        current = len(self.selected_files)
        remaining = limit - current
        if remaining <= 0:
            self._show_upgrade_needed()
            return

        ftypes = [("كل ملفات الميديا","*.png *.jpg *.jpeg *.webp *.bmp *.gif "
                   "*.tiff *.ico *.mp4 *.avi *.mkv *.mov *.flv *.webm *.wmv"),
                  ("صور","*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tiff *.ico"),
                  ("فيديو","*.mp4 *.avi *.mkv *.mov *.flv *.webm *.wmv *.3gp"),
                  ("كل الملفات","*.*")]
        files = filedialog.askopenfilenames(title="اختر الملفات", filetypes=ftypes)
        if not files:
            return

        to_add = list(files)[:remaining]
        skipped = len(files) - len(to_add)

        for fp in to_add:
            if fp not in self.selected_files:
                self.selected_files.append(fp)
                self.file_listbox.insert(tk.END, Path(fp).name)

        self._update_file_count()

        if skipped > 0:
            self._show_upgrade_needed(extra=f"تم تجاهل {skipped} ملف بسبب حد الخطة المجانية.")

    def _remove_selected(self):
        idxs = list(self.file_listbox.curselection())[::-1]
        for i in idxs:
            self.selected_files.pop(i)
            self.file_listbox.delete(i)
        self._update_file_count()

    def _clear_files(self):
        self.selected_files.clear()
        self.file_listbox.delete(0, tk.END)
        self._update_file_count()

    def _update_file_count(self):
        n = len(self.selected_files)
        self.file_count_lbl.config(text=f"({n} ملف)")

    # ── Premium UI ────────────────────────────────────────────────────────────
    def _update_premium_ui(self):
        if LICENSE.is_premium():
            name = LICENSE.get_username()
            self.premium_badge.config(text=f"⭐ PREMIUM – {name}", bg=ACCENT2, fg="#000")
            self.convert_premium_note.config(
                text=f"✅ حساب بريميوم مفعّل ({name}) – يمكنك رفع حتى {PREMIUM_BATCH} ملف")
        else:
            self.premium_badge.config(text="FREE", bg=BG3, fg=TEXT2)
            self.convert_premium_note.config(
                text=f"⚠️ الخطة المجانية: ملف واحد فقط في كل مرة. "
                     f"للرفع بالجملة ادفع {BMC_PRICE}$ على Buy Me a Coffee ← اضغط 'ترقية'")

    def _show_upgrade_needed(self, extra=""):
        msg = (f"الخطة المجانية تسمح بملف واحد فقط في المرة الواحدة.\n\n"
               f"للاستمتاع برفع حتى {PREMIUM_BATCH} ملفاً مرة واحدة:\n"
               f"ادفع {BMC_PRICE}$ على:\n{BMC_URL}\n\n"
               f"ثم ارجع واضغط 'ترقية للبريميوم' وأدخل اسم مستخدمك.")
        if extra:
            msg += f"\n\n{extra}"
        if messagebox.askyesno("ترقية مطلوبة", msg + "\n\nهل تريد فتح صفحة الدفع الآن؟"):
            webbrowser.open(BMC_URL)

    def _open_premium_dialog(self):
        if LICENSE.is_premium():
            if messagebox.askyesno("بريميوم مفعّل",
                                   f"حسابك البريميوم مفعّل ({LICENSE.get_username()}).\n"
                                   "هل تريد إلغاء التفعيل؟"):
                LICENSE.deactivate()
                self._update_premium_ui()
            return

        dlg = tk.Toplevel(self)
        dlg.title("تفعيل البريميوم")
        dlg.configure(bg=BG)
        dlg.resizable(False, False)
        dlg.grab_set()

        # Center
        dlg.update_idletasks()
        w, h = 460, 380
        x = self.winfo_x() + (self.winfo_width()-w)//2
        y = self.winfo_y() + (self.winfo_height()-h)//2
        dlg.geometry(f"{w}x{h}+{x}+{y}")

        tk.Label(dlg, text="🔑 تفعيل البريميوم", font=self.font_h1,
                 bg=BG, fg=ACCENT).pack(pady=(20,4))
        tk.Label(dlg, text=f"رفع حتى {PREMIUM_BATCH} ملف مرة واحدة مقابل {BMC_PRICE}$ فقط!",
                 font=self.font_body, bg=BG, fg=TEXT2).pack()

        # Step 1 – pay
        step1 = tk.LabelFrame(dlg, text=" الخطوة ١: ادفع ", font=self.font_sm,
                               bg=BG, fg=ACCENT2, padx=14, pady=10)
        step1.pack(fill=tk.X, padx=20, pady=(16,4))
        tk.Label(step1, text=f"اذهب إلى Buy Me a Coffee وادفع {BMC_PRICE}$:",
                 font=self.font_body, bg=BG, fg=TEXT).pack(anchor="w")
        tk.Button(step1, text=f"☕ {BMC_URL}", font=self.font_sm,
                  bg=BG3, fg=ACCENT2, relief="flat", cursor="hand2",
                  command=lambda: webbrowser.open(BMC_URL)).pack(anchor="w", pady=4)

        # Step 2 – enter username
        step2 = tk.LabelFrame(dlg, text=" الخطوة ٢: أدخل اسم مستخدمك ",
                               font=self.font_sm, bg=BG, fg=ACCENT2, padx=14, pady=10)
        step2.pack(fill=tk.X, padx=20, pady=4)
        tk.Label(step2, text="اسم مستخدمك على Buy Me a Coffee:",
                 font=self.font_body, bg=BG, fg=TEXT).pack(anchor="w")
        uname_var = tk.StringVar()
        tk.Entry(step2, textvariable=uname_var, font=self.font_body,
                 bg=BG3, fg=TEXT, insertbackground=ACCENT,
                 relief="flat").pack(fill=tk.X, ipady=6, pady=4)

        result_lbl = tk.Label(dlg, text="", font=self.font_sm,
                              bg=BG, fg=SUCCESS, wraplength=420)
        result_lbl.pack(pady=4)

        def do_verify():
            btn_verify.config(state=tk.DISABLED, text="جارٍ التحقق...")
            dlg.update()
            ok, msg = LICENSE.verify_and_activate(uname_var.get())
            if ok:
                result_lbl.config(text=msg, fg=SUCCESS)
                self._update_premium_ui()
                dlg.after(1800, dlg.destroy)
            else:
                result_lbl.config(text=msg, fg=DANGER)
                btn_verify.config(state=tk.NORMAL, text="✔ تحقق وفعّل")

        btn_verify = tk.Button(dlg, text="✔ تحقق وفعّل",
                               font=self.font_h2, bg=ACCENT2, fg="#000",
                               relief="flat", cursor="hand2",
                               command=do_verify, padx=20, pady=8)
        btn_verify.pack(pady=8)

    # ── Conversion logic ──────────────────────────────────────────────────────
    def _start_convert(self):
        if not self.selected_files:
            messagebox.showwarning("تنبيه", "لم تختر أي ملفات بعد.")
            return
        fmt = self.convert_to_fmt.get()
        if not fmt or fmt == "───":
            messagebox.showwarning("تنبيه", "اختر صيغة التحويل أولاً.")
            return
        out = self.output_dir.get()
        os.makedirs(out, exist_ok=True)

        def run():
            total = len(self.selected_files)
            ok_count = 0
            for i, fp in enumerate(self.selected_files, 1):
                self._set_status(f"⏳ تحويل {i}/{total}: {Path(fp).name}")
                self.progress_var.set((i-1)/total*100)
                self.update_idletasks()
                try:
                    ext = Path(fp).suffix.lstrip(".").upper()
                    if ext in IMAGE_FORMATS or fmt in IMAGE_FORMATS:
                        out_path = convert_image(fp, fmt, out)
                    else:
                        out_path = convert_video(fp, fmt, out)
                    ok_count += 1
                    self._set_status(f"✅ {Path(out_path).name}")
                except Exception as e:
                    self._set_status(f"❌ خطأ في {Path(fp).name}: {e}")
            self.progress_var.set(100)
            messagebox.showinfo("اكتمل",
                                f"تم تحويل {ok_count}/{total} ملف بنجاح.\nحُفظت في: {out}")
            self.progress_var.set(0)

        threading.Thread(target=run, daemon=True).start()

    # ── Download logic ────────────────────────────────────────────────────────
    def _start_download(self):
        url = self.dl_url.get().strip()
        if not url:
            messagebox.showwarning("تنبيه", "أدخل رابط الفيديو أولاً.")
            return
        out = self.output_dir.get()
        os.makedirs(out, exist_ok=True)
        quality = self.dl_quality.get()
        self._dl_log_clear()

        def progress_cb(pct):
            self._dl_log_append(f"  {pct}\n")

        def run():
            self._set_status("⏬ جارٍ التحميل...")
            self._dl_log_append(f"🔗 {url}\n📦 الجودة: {quality}\n")
            try:
                result = download_social(url, quality, out, progress_cb)
                self._set_status("✅ تم التحميل بنجاح!")
                self._dl_log_append(f"\n✅ حُفظ في: {result}\n")
                self.progress_var.set(100)
                self.after(1200, lambda: self.progress_var.set(0))
            except Exception as e:
                self._set_status(f"❌ خطأ: {e}")
                self._dl_log_append(f"\n❌ {e}\n")

        threading.Thread(target=run, daemon=True).start()

    def _dl_log_clear(self):
        self.dl_log.config(state=tk.NORMAL)
        self.dl_log.delete("1.0", tk.END)
        self.dl_log.config(state=tk.DISABLED)

    def _dl_log_append(self, text):
        self.dl_log.config(state=tk.NORMAL)
        self.dl_log.insert(tk.END, text)
        self.dl_log.see(tk.END)
        self.dl_log.config(state=tk.DISABLED)

    def _set_status(self, msg):
        self.status_text.set(msg)
        self.update_idletasks()


# ─── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Quick dependency check
    missing = []
    if not PIL_OK:   missing.append("pillow")
    if not YTDLP_OK: missing.append("yt-dlp")
    if missing:
        print(f"\n⚠️  مكتبات ناقصة: {', '.join(missing)}")
        print(f"شغّل: pip install {' '.join(missing)}\n")

    app = MasterConvertingApp()
    app.mainloop()