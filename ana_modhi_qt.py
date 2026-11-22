# -*- coding: utf-8 -*-
"""
أنا مذيع — نسخة Qt كاملة الإتاحة (PyQt6 أو PySide6).

كل عناصر التفاعل عناصر Qt حقيقية (QPushButton, QLineEdit, QCheckBox,
QRadioButton, QComboBox, QSlider, QListWidget, QTextEdit) لها اسم مقروء
للقارئ الشاشة، والتنقل يتم بمفتاح Tab وحده، وEnter/مسافة للتفعيل،
والأسهم داخل القوائم والمربعات الحقيقية فقط.

    python ana_modhi_qt.py
    python ana_modhi_qt.py --selftest     (جولة على كل الشاشات)
    python ana_modhi_qt.py --dump-a11y out.json
"""

import ctypes
import inspect
import json
import os
import subprocess
import sys
import time

try:
    from PyQt6.QtCore import Qt, QTimer, QObject, pyqtSignal
    from PyQt6.QtGui import QAction, QFont, QIcon, QKeySequence, QPixmap
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QLabel, QPushButton, QLineEdit,
        QCheckBox, QRadioButton, QComboBox, QSlider, QListWidget, QListWidgetItem,
        QTextEdit, QGroupBox, QButtonGroup, QVBoxLayout, QHBoxLayout, QScrollArea,
        QFrame,
    )
    BINDING = "PyQt6"
except ImportError:  # pragma: no cover
    from PySide6.QtCore import Qt, QTimer, QObject, pyqtSignal
    from PySide6.QtGui import QAction, QFont, QIcon, QKeySequence, QPixmap
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QLabel, QPushButton, QLineEdit,
        QCheckBox, QRadioButton, QComboBox, QSlider, QListWidget, QListWidgetItem,
        QTextEdit, QGroupBox, QButtonGroup, QVBoxLayout, QHBoxLayout, QScrollArea,
        QFrame,
    )
    BINDING = "PySide6"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ana_recorder  # noqa: E402
import ana_stt      # noqa: E402
from ana_data import (  # noqa: E402
    AUDIO_DIR, BULLETINS, CHALLENGES, CHILD_SENTENCES, EMOTIONS, FONT_FAMILY,
    GUIDE_SECTIONS, HELP_TEXT, IMG_DIR, LETTERS, LISTEN_QUIZ, MAX_STARS, MAX_TOTAL,
    PROGRESS_FILE, SCALE_FACTORS, SELFCHECK, SOUNDS, STOP_QUIZ, THEMES,
    load_progress, rotated,
)

SELFTEST = "--selftest" in sys.argv
DUMP = "--dump-a11y" in sys.argv
PROBE = "--probe" in sys.argv
CHECK_STT = "--check-stt" in sys.argv
# لوحة تشخيص التفريغ: للتطوير فقط، لا تظهر للأطفال إطلاقاً.
DEBUG_STT = ("--debug-stt" in sys.argv
             or bool(os.environ.get("ANOMODHI_DEBUG_STT")))


def probe_report():
    """تقرير تشخيصي للنسخة المُوزَّعة: ماذا رآه البرنامج على هذا الجهاز.

    يُستدعى بـ --probe ويطبع ثم يخرج بلا فتح نافذة، ليبين لصاحب الدعم
    أيّ جزء مفقود: نموذج التفريغ، الأصول، أو مجلد التسجيلات.
    """
    def line(label, value):
        sys.stdout.write("%-22s %s\n" % (label + ":", value))
        sys.stdout.flush()

    line("النسخة", getattr(sys, "frozen", False) and "مجمَّدة" or "من المصدر")
    line("الملف التنفيذي", sys.executable)
    for name, folder in (("مجلد الصوت", AUDIO_DIR), ("مجلد الصور", IMG_DIR)):
        n = len(os.listdir(folder)) if os.path.isdir(folder) else 0
        line(name, "%s (%d ملفاً)" % (folder, n) if n else "مفقود: %s" % folder)
    line("مجلد التسجيلات", ana_recorder.recording_dir())
    try:
        line("نموذج vosk", ana_stt._vosk_model_dir() or "مفقود")
        line("محرّكات التفريغ", ", ".join(n for n, _ in ana_stt.engines()) or "لا شيء")
    except Exception as exc:
        line("التفريغ", "تعذّر الفحص: %s: %s" % (type(exc).__name__, exc))
    try:
        ok, name, detail = ana_stt.available()
        line("جاهزية التفريغ", "نعم (%s)" % name if ok else "لا — %s" % detail)
    except Exception:
        pass
    line("ملف التقدّم", PROGRESS_FILE)


def check_stt_report():
    """يفحص التفريغ فعلياً: يحمّل النموذج ويفرّغ ملفاً صوتياً إن أُعطي.

    فحص المسارات وحده لا يكفي: المطلوب إثبات أن vosk حمّل مكتبته الأصلية
    والنموذج فعلاً، فلا يفشل عند الطفل على جهاز آخر.
    """
    path = None
    if CHECK_STT:
        i = sys.argv.index("--check-stt")
        if i + 1 < len(sys.argv) and not sys.argv[i + 1].startswith("--"):
            path = sys.argv[i + 1]
    names = [n for n, _ in ana_stt.engines()]
    sys.stdout.write("المحرّكات: %s\n" % (", ".join(names) or "لا شيء"))
    if "vosk-ar" not in names:
        sys.stdout.write("نتيجة: لا يوجد vosk، فتفريغ c1/c7 غير متاح.\n")
        return
    t0 = time.time()
    try:
        from vosk import Model, SetLogLevel
        SetLogLevel(-1)
        Model(ana_stt._vosk_model_dir())
    except Exception as exc:
        sys.stdout.write("نتيجة: فشل تحميل النموذج — %s: %s\n"
                         % (type(exc).__name__, exc))
        return
    sys.stdout.write("تحميل النموذج: %.1f ثانية\n" % (time.time() - t0))
    if not path:
        sys.stdout.write("نتيجة: النموذج يعمل. (مرّر مسار WAV لتجربة تفريغ.)\n")
        return
    try:
        t0 = time.time()
        text = ana_stt._run_vosk(path, ana_stt.MODEL, ana_stt.LANGUAGE)
        sys.stdout.write("تفريغ %s في %.1f ثانية:\n%s\n"
                         % (os.path.basename(path), time.time() - t0,
                            "  «%s»" % text if text else "  (فارغ)"))
    except Exception as exc:
        sys.stdout.write("نتيجة: فشل التفريغ — %s: %s\n"
                         % (type(exc).__name__, exc))


# ---------------------------------------------------------- نطق عصبي أونلاين
# صوت سلمى المصرية العصبي عبر حزمة edge-tts (تحتاج إنترنت و pip install edge-tts).
# عند غياب الحزمة أو فشل الاتصال يرجع التطبيق تلقائياً لمحرك ويندوز (WinRT/SAPI).
import asyncio
import queue
import tempfile
import threading

try:
    import edge_tts as _edge_tts
    _HAS_EDGE_TTS = True
except Exception:
    _edge_tts = None
    _HAS_EDGE_TTS = False


class _EdgeTtsWorker:
    """خيط نطق عصبي: يحوّل النص إلى MP3 عبر edge-tts ثم يشغّله عبر winmm.

    say() يلغي أي نطق سابق (سلوك QUEUE_FLUSH)، وعند فشل التحويل يمرر النص
    إلى دالة الرجوع الاحتياطي (محرك ويندوز) حتى لا يضيع على المستخدم.
    """
    VOICE = "ar-EG-SalmaNeural"

    def __init__(self, on_fallback):
        self._q = queue.Queue()
        self._on_fallback = on_fallback
        self._gen = 0
        self._lock = threading.Lock()
        self._alive = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def say(self, rate_pct, text):
        with self._lock:
            self._gen += 1
            gen = self._gen
        self._mci("close anatts")
        self._q.put((gen, rate_pct, text))

    def stop(self):
        with self._lock:
            self._gen += 1
        self._mci("close anatts")
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass

    def shutdown(self):
        self.stop()
        self._alive = False
        self._q.put((-1, 0, ""))

    @staticmethod
    def _mci(cmd):
        try:
            ctypes.windll.winmm.mciSendStringW(cmd, None, 0, None)
        except Exception:
            pass

    def _run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        tmp = os.path.join(tempfile.gettempdir(), "ana_modhi_salma.mp3")
        while True:
            gen, rate_pct, text = self._q.get()
            if not self._alive or gen < 0:
                return
            if not text:
                continue
            with self._lock:
                if gen != self._gen:
                    continue
            ok = False
            try:
                rate = ("+%d%%" % rate_pct) if rate_pct >= 0 else ("%d%%" % rate_pct)
                comm = _edge_tts.Communicate(text, self.VOICE, rate=rate)
                loop.run_until_complete(comm.save(tmp))
                ok = os.path.getsize(tmp) > 100
            except Exception:
                ok = False
            if not ok:
                self._on_fallback(text)
                continue
            with self._lock:
                if gen != self._gen:
                    continue
            self._mci('open "%s" type mpegvideo alias anatts' % tmp)
            self._mci("play anatts")
            # انتظار انتهاء التشغيل أو طلب إيقاف/نطق جديد
            buf = ctypes.create_unicode_buffer(64)
            while True:
                time.sleep(0.05)
                with self._lock:
                    if gen != self._gen:
                        break
                try:
                    ctypes.windll.winmm.mciSendStringW(
                        "status anatts mode", buf, 64, None)
                    if buf.value != "playing":
                        break
                except Exception:
                    break


class _SttSignals(QObject):
    """نقل نتيجة التفريغ من خيط العامل إلى خيط الواجهة بأمان."""
    done = pyqtSignal(dict)

RTL = Qt.LayoutDirection.RightToLeft
STRONG = Qt.FocusPolicy.StrongFocus
TABBING = Qt.FocusPolicy.TabFocus
NOFOCUS = Qt.FocusPolicy.NoFocus
READ_FLAGS = (Qt.TextInteractionFlag.TextSelectableByKeyboard
              | Qt.TextInteractionFlag.TextSelectableByMouse)
FOCUS_RING = "#ffd166"          # حلقة تركيز واضحة على كل العناصر التفاعلية


def shade(hex_color, amount):
    """يفتّح/يعتّم لون hex بنسبة amount (-1..1) لِhover حقيقي بدل CSS غير مدعوم."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    if amount >= 0:
        r, g, b = (int(c + (255 - c) * amount) for c in (r, g, b))
    else:
        r, g, b = (int(c * (1 + amount)) for c in (r, g, b))
    return "#%02x%02x%02x" % (r, g, b)


def relative_luminance(hex_color):
    """سطوع نسبي حسب تعريف WCAG 2.x."""

    def ch(v):
        v /= 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast_ratio(fg, bg):
    """نسبة التباين بين لونين (1..21)."""
    a, b = relative_luminance(fg), relative_luminance(bg)
    lo, hi = min(a, b), max(a, b)
    return (hi + 0.05) / (lo + 0.05)


def readable_on(bg):
    """أسود أم أبيض؟ أيّهما يقرأ أوضح على هذه الخلفية (تباين WCAG AA)."""
    return "#000000" if contrast_ratio("#000000", bg) >= contrast_ratio("#ffffff", bg) else "#ffffff"


# أحداث Windows التي تُعلم قارئ الشاشة بتغيّر نص المنطقة الحيّة
EVENT_OBJECT_ALERT = 0x0802
EVENT_OBJECT_NAMECHANGE = 0x080C
OBJID_CLIENT = -4
CHILDID_SELF = 0


def notify_screen_reader(hwnd):
    """يخبر قارئ الشاشة (عبر WinEvent) أن نص الإعلان تغيّر."""
    if not hwnd:
        return
    try:
        ctypes.windll.user32.NotifyWinEvent(
            ctypes.c_ulong(EVENT_OBJECT_ALERT), ctypes.c_void_p(hwnd),
            ctypes.c_long(OBJID_CLIENT), ctypes.c_long(CHILDID_SELF))
    except Exception:
        pass


def describe(w, name, help_text=""):
    """يمنح عنصر Qt اسماً مقروءاً + وصفاً لقارئ الشاشة."""
    w.setAccessibleName(name)
    if help_text:
        w.setAccessibleDescription(help_text)
    w.setFocusPolicy(STRONG)
    return w


# Qt يفعّل QPushButton بالمسافة فقط خارج نوافذ الحوار، فيختفي مفتاح Enter المتوقّع.
# هذه الفئة تُعيد Enter إلى كل زر حقيقي كما وعدنا في شاشة التعليمات.
ACTIVATE_KEYS = (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Select)


class AButton(QPushButton):
    """زر Qt حقيقي يفعّل بمفتاحي Enter والمسافة معاً."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._armed = False

    def keyPressEvent(self, e):
        if e.key() in ACTIVATE_KEYS:
            if not e.isAutoRepeat():
                self._armed = True
                self.setDown(True)
            e.accept()
            return
        super().keyPressEvent(e)
    def keyReleaseEvent(self, e):
        if e.key() in ACTIVATE_KEYS:
            if self._armed:
                self._armed = False
                self.setDown(False)
                self.click()
            e.accept()
            return
        super().keyReleaseEvent(e)


class SubmitLineEdit(QLineEdit):
    """حقل نصّي حقيقي: Enter يحفظ/يؤكّد بدل أن يبتلع المفتاح."""

    def keyPressEvent(self, e):
        if e.key() in ACTIVATE_KEYS:
            self.returnPressed.emit()
            e.accept()
            return
        super().keyPressEvent(e)


class AnaModhiQt(QMainWindow):
    def __init__(self):
        super().__init__()
        self.prog = load_progress()
        self.scale = SCALE_FACTORS[self.prog["scale_index"]]
        self.theme_key = self.prog["theme"]
        self.col = THEMES[self.theme_key]
        self.hc_bold = self.theme_key == "hc"
        self.prev = []
        self.current = None
        self.screens = {}
        self.recorder = None
        self.last_rec = {}                 # آخر تسجيل صالح لكل تحدي، لزر الاستماع
        self.tts_proc = self._start_tts()
        # الصوت العصبي (سلمى) أساسي عند توفر edge-tts، ومحرك ويندوز احتياطي.
        self.edge_worker = _EdgeTtsWorker(self._speak_fallback) if _HAS_EDGE_TTS else None
        self._build()

    # ------------------------------------------------------------------خطوط
    def F(self, size, bold=False):
        f = QFont(FONT_FAMILY)
        f.setPointSize(max(9, int(round(size * self.scale))))
        f.setBold(bool(bold) or self.hc_bold)
        return f

    def _pix(self, name):
        for folder in (IMG_DIR,):
            p = os.path.join(folder, name)
            if os.path.exists(p):
                return QPixmap(p)
        return QPixmap()

    def _icon(self, name):
        p = self._pix("icon-%s.png" % name)
        return QIcon(p) if not p.isNull() else QIcon()

    # ------------------------------------------------------------------TTS
    # نطق عربي: أصوات System.Speech العربية (Salma/Leila 22k) مسجّلة على
    # هذا الجهاز لكنها لا تُنتج أي صوت (0.00 ثانية). لذلك نستخدم محرك
    # Windows الأساسي عبر WinRT، ونُبقي System.Speech احتياطاً لو غاب النطق.
    TTS_PS = (
        "Add-Type -AssemblyName System.Speech\n"
        "[Console]::InputEncoding = [System.Text.Encoding]::UTF8\n"
        "$mode = 'sapi'\n"
        "$voice = $null\n"
        "$tmp = $null\n"
        "$asTaskGeneric = $null\n"
        "try {\n"
        "  Add-Type -AssemblyName System.Runtime.WindowsRuntime\n"
        "  [void][Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media.SpeechSynthesis, ContentType=WindowsRuntime]\n"
        "  [void][Windows.Storage.Streams.DataReader, Windows.Storage.Streams, ContentType=WindowsRuntime]\n"
        "  $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {\n"
        "    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and\n"
        "    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]\n"
        "  $voice = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices |\n"
        "    Where-Object { $_.Language -like 'ar*' } | Select-Object -First 1\n"
        "  if ($voice) { $mode = 'winrt'; $tmp = [System.IO.Path]::GetTempFileName() + '.wav' }\n"
        "} catch { $mode = 'sapi' }\n"
        "function Await($op, $type) {\n"
        "  $m = $asTaskGeneric.MakeGenericMethod($type)\n"
        "  $t = $m.Invoke($null, @($op))\n"
        "  $t.Wait(-1) | Out-Null\n"
        "  return $t.Result\n"
        "}\n"
        "$sapi = New-Object System.Speech.Synthesis.SpeechSynthesizer\n"
        "if ($mode -eq 'sapi') {\n"
        "  try { $sapi.SelectVoice('Salma22k_HQ') } catch { try { $sapi.SelectVoice('Leila22k_HQ') } catch {} }\n"
        "}\n"
        "$player = New-Object System.Media.SoundPlayer\n"
        "$sep = [string][char]0\n"
        "while ($true) {\n"
        "  $line = [Console]::In.ReadLine()\n"
        "  if ($line -eq $null -or $line -eq 'EXIT') { if ($tmp) { Remove-Item $tmp -ErrorAction SilentlyContinue }; break }\n"
        "  if ($line -eq 'STOP') {\n"
        "    try { if ($mode -eq 'winrt') { $player.Stop() } else { $sapi.SpeakAsyncCancelAll() } } catch {}\n"
        "    continue\n"
        "  }\n"
        "  if (-not $line) { continue }\n"
        "  $i = $line.IndexOf($sep)\n"
        "  $r = 0\n"
        "  $t = $line\n"
        "  if ($i -gt 0) { $r = [int]$line.Substring(0, $i); $t = $line.Substring($i + 1) }\n"
        "  if (-not $t) { continue }\n"
        "  try {\n"
        "    if ($mode -eq 'winrt') {\n"
        "      $player.Stop()\n"
        "      $s = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::new()\n"
        "      $s.Voice = $voice\n"
        "      try {\n"
        "        $sr = 1.0 * [Math]::Pow(2.0, $r / 10.0)\n"
        "        if ($sr -lt 0.5) { $sr = 0.5 }\n"
        "        if ($sr -gt 2.0) { $sr = 2.0 }\n"
        "        $s.SpeakingRate = $sr\n"
        "      } catch {}\n"
        "      $stream = Await ($s.SynthesizeTextToStreamAsync($t)) ([Windows.Media.SpeechSynthesis.SpeechSynthesisStream])\n"
        "      $size = [uint32]$stream.Size\n"
        "      if ($size -gt 44) {\n"
        "        $reader = [Windows.Storage.Streams.DataReader]::new($stream.GetInputStreamAt(0))\n"
        "        [void](Await ($reader.LoadAsync($size)) ([uint32]))\n"
        "        $bytes = New-Object byte[] $size\n"
        "        $reader.ReadBytes($bytes)\n"
        "        [System.IO.File]::WriteAllBytes($tmp, $bytes)\n"
        "        $player.SoundLocation = $tmp\n"
        "        $player.Play()\n"
        "      }\n"
        "      $s.Dispose()\n"
        "    } else {\n"
        "      $sapi.Rate = $r\n"
        "      $task = $sapi.SpeakAsync($t)\n"
        "      while (-not $task.IsCompleted) { Start-Sleep -Milliseconds 40 }\n"
        "    }\n"
        "  } catch {}\n"
        "}\n"
    )

    def _start_tts(self):
        if os.environ.get("ANOMODHI_NO_TTS"):
            return None
        try:
            return subprocess.Popen(
                ["powershell", "-NoProfile", "-Command", self.TTS_PS],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, creationflags=0x08000000)
        except Exception:
            return None

    def _speak_fallback(self, text):
        """نطق عبر محرك ويندوز (WinRT/SAPI): يُستخدم احتياطياً عند غياب
        الصوت العصبي أو فشل الاتصال به."""
        if not text or not self.tts_proc or not self.tts_proc.stdin:
            return
        rate = -6 + self.prog.get("rate", 6)
        try:
            self.tts_proc.stdin.write(("%d\x00%s\n" % (rate, text)).encode("utf-8"))
            self.tts_proc.stdin.flush()
        except Exception:
            pass

    def speak(self, text):
        log = os.environ.get("ANOMODHI_LOG")
        if log:
            try:
                with open(log, "a", encoding="utf-8") as fh:
                    fh.write((text or "") + "\n")
            except Exception:
                pass
        if not self.prog.get("tts") or not text:
            return
        if self.edge_worker is not None:
            # سرعة 1..10 تصبح ‎-50%..+40%‎ للصوت العصبي
            self.edge_worker.say((self.prog.get("rate", 6) - 6) * 10, text)
            return
        self._speak_fallback(text)

    def speak_stop(self):
        if self.edge_worker is not None:
            self.edge_worker.stop()
        if self.tts_proc and self.tts_proc.stdin:
            try:
                self.tts_proc.stdin.write(b"STOP\n")
                self.tts_proc.stdin.flush()
            except Exception:
                pass

    def play_sound(self, key):
        fname = SOUNDS.get(key)
        if not fname:
            return
        path = os.path.join(AUDIO_DIR, fname)
        if not os.path.exists(path):
            return
        try:
            mci = ctypes.windll.winmm.mciSendStringW
            mci("close sfx", None, 0, 0)
            mci('open "%s" alias sfx' % path.replace('"', ""), None, 0, 0)
            mci("play sfx", None, 0, 0)
        except Exception:
            pass

    # ------------------------------------------------------------------بناء
    def _build(self):
        self.setWindowTitle("أنا مذيع")
        self.resize(900, 900)
        self.setMinimumSize(640, 560)
        ico = self._pix("icon-star.png")
        if not ico.isNull():
            self.setWindowIcon(QIcon(ico))

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ترويسة + شريط حالة حيّ
        head = QWidget()
        head.setObjectName("header")
        hl = QVBoxLayout(head)
        hl.setContentsMargins(12, 8, 12, 8)
        title = QLabel("أنا مذيع")
        title.setObjectName("appTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(self.F(20, True))
        title.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        hl.addWidget(title)
        self.status = QLabel("")
        self.status.setObjectName("statusBar")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setWordWrap(True)
        self.status.setFont(self.F(12))
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        # منطقة حيّة: اسم ثابت + نص متغيّر + إمكانية الوصول إليها بـTab
        describe(self.status, "شريط الحالة",
                 "يعرض آخر رسالة أو حالة. اضغط F2 لإعادة وصف الشاشة الحالية")
        hl.addWidget(self.status)
        outer.addWidget(head)

        # منطقة المحتوى
        self.stack_host = QWidget()
        self.stack = QWidget(self.stack_host)
        self.stack.setObjectName("stack")
        self.stack_layout = QVBoxLayout(self.stack)
        self.stack_layout.setContentsMargins(0, 0, 0, 0)
        host_layout = QVBoxLayout(self.stack_host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.addWidget(self.stack)
        outer.addWidget(self.stack_host, 1)

        self.footer = QLabel(
            "Tab و Shift+Tab للتنقل  •  Enter أو المسافة للأزرار  •  "
            "المسافة لاختيار مربعات الاختيار  •  الأسهم داخل القوائم والمربعات الحقيقية  •  "
            "F1 التعليمات  •  F2 وصف الشاشة")
        self.footer.setObjectName("footer")
        self.footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.footer.setWordWrap(True)
        self.footer.setFont(self.F(11))
        self.footer.setFocusPolicy(NOFOCUS)
        outer.addWidget(self.footer)

        self.setCentralWidget(central)
        self._make_menus()
        self.apply_theme()
        self.show_screen("home")

    # --------------------------------------------------------------القوائم
    @staticmethod
    def _hook(signal, slot):
        """PyQt يحقن ``checked=False`` في أول معامل للدالة المستدعاة.

        إذا كانت الدالة لا تقبل وسائط نتجاهلها، فلا تصلها قيمة غلط أبداً.
        """
        try:
            params = inspect.signature(slot).parameters.values()
            takes = any(p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
                        for p in params)
        except (TypeError, ValueError):
            takes = False
        signal.connect(slot if takes else (lambda *a: slot()))

    def _act(self, menu, text, slot, shortcut="", tip=""):
        a = QAction(text, self)
        a.setToolTip(tip or text)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        self._hook(a.triggered, slot)
        menu.addAction(a)
        return a

    def _make_menus(self):
        bar = self.menuBar()
        describe(bar, "قائمة الأوامر", "استخدم Alt مع الحرف المميّز، أو Tab للوصول لكل قائمة")

        m_ch = bar.addMenu("&التحديات")
        m_ch.setAccessibleName("قائمة التحديات")
        for i, (cid, ctitle, _desc, _icon) in enumerate(CHALLENGES, 1):
            self._act(m_ch, "%d. %s" % (i, ctitle),
                      lambda _checked=False, cid=cid: self.show_screen(cid),
                      "Ctrl+%d" % i, "افتح %s" % ctitle)
        m_ch.addSeparator()
        self._act(m_ch, "دليل المذيع", lambda: self.show_screen("guide"), "Ctrl+G")
        self._act(m_ch, "الإعدادات", lambda: self.show_screen("settings"), "Ctrl+P")
        self._act(m_ch, "العودة للرئيسية", lambda: self.show_screen("home"), "Ctrl+H")

        m_view = bar.addMenu("&عرض")
        m_view.setAccessibleName("قائمة العرض")
        self._act(m_view, "تكبير الخط", lambda: self.zoom(1), "Ctrl++")
        self._act(m_view, "تصغير الخط", lambda: self.zoom(-1), "Ctrl+-")
        self._act(m_view, "حجم الخط الافتراضي", lambda: self.zoom(0), "Ctrl+0")
        self._act(m_view, "تبديل المظهر", self.cycle_theme, "Alt+T")
        self._act(m_view, "تشغيل/إيقاف القراءة الصوتية", self.toggle_tts, "Alt+S")
        self._act(m_view, "الخروج", self.quit_app, "Ctrl+Q")

        m_help = bar.addMenu("&مساعدة")
        m_help.setAccessibleName("قائمة المساعدة")
        self._act(m_help, "التعليمات واختصارات لوحة المفاتيح", lambda: self.show_screen("help"), "F1")
        self._act(m_help, "وصف الشاشة الحالية", self.describe_screen, "F2")
        self._act(m_help, "العودة للشاشة السابقة", self.go_back, "Esc")

    # --------------------------------------------------------------التنقل
    def _leave_recording(self):
        """يمنع بقاء الميكروفون مفتوحاً عند مغادرة شاشة التسجيل."""
        rec = getattr(self, "recorder", None)
        if rec is not None:
            try:
                rec.cancel()
            except Exception:
                pass
        self.recorder = None
        page = self.screens.get(self.current)
        if page is not None:                      # توقيت/تفريغ شاشة السرعة
            for name in ("_stt_cancel",):
                fn = getattr(page, name, None)
                if callable(fn):
                    try:
                        fn()
                    except Exception:
                        pass
            # مؤقّتات الصفحة (مثل الانتقال التلقائي في c4/c5) يجب أن تتوقف
            # فور مغادرتها، وإلا تحرّكت صفحة مخفية وعرضت نتيجة بعد سWAN.
            leave = getattr(page, "a11y_leave", None)
            if callable(leave):
                try:
                    leave()
                except Exception:
                    pass

    def show_screen(self, sid):
        if sid in self._challenge_ids():
            self.last_challenge = sid
        if self.current is not None and self.current != sid:
            self._leave_recording()
            self.prev.append(self.current)
            del self.prev[:-12]
        self.current = sid
        page = self.screens.get(sid)
        if page is None:
            page = self._build_page(sid)
            self.screens[sid] = page
            self.stack_layout.addWidget(page)
        else:
            # الصفحات مخزّنة مؤقتاً: بلا هذا.lines يصبح دخول المستخدم الثاني
            # إلى تحدٍ منتهٍ شاشة ميتة (كل الخيارات معطّلة ونصّ «أحسنت» عالق).
            hook = getattr(page, "a11y_reset", None)
            if callable(hook):
                hook()
        return self.activate(page, sid)

    def activate(self, page, sid):
        """يعرض صفحة، يضبط ترتيب Tab المنطقي، ثم ينقل التركيز والإعلان."""
        page.setVisible(True)
        for other in self.screens.values():
            if other is not page:
                other.setVisible(False)
        self.speak_stop()
        self.link_tab_order(page)
        first = getattr(page, "a11y_first", None)
        if first is not None and first.isEnabled():
            self.focus_first(first)
        self.announce(getattr(page, "a11y_head", "") or self.screen_title(sid))
        return page

    def focus_first(self, widget):
        """ينقل التركيز لأول عنصر في الشاشة (فوراً ومجدّداً بعد حدث الحلقة)."""
        def go():
            if widget.isVisible() and widget.isEnabled() and self.isVisible():
                widget.setFocus(Qt.FocusReason.OtherFocusReason)
        go()
        QTimer.singleShot(0, go)

    def focusables(self, root):
        """كل عناصر التركيز داخل صفحة، بترتيب ظهورها البصري."""
        out = []

        def walk(w):
            for c in w.children():
                if not isinstance(c, QWidget):
                    continue
                if c.focusPolicy() != NOFOCUS:
                    out.append(c)
                walk(c)
        walk(root)
        return out

    def link_tab_order(self, page):
        """حلقة Tab واحدة منطقية: شريط الحالة ← القوائم ← عناصر الصفحة."""
        chain = [self.status, self.menuBar()] + self.focusables(page)
        for a, b in zip(chain, chain[1:]):
            QWidget.setTabOrder(a, b)
        if len(chain) > 1:
            QWidget.setTabOrder(chain[-1], chain[0])

    def new_page(self, title, subtitle=""):
        outer_scroll = QScrollArea()
        outer_scroll.setWidgetResizable(True)
        outer_scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer_scroll.setFocusPolicy(NOFOCUS)
        inner = QWidget()
        inner.setObjectName("page")
        inner.setFocusPolicy(NOFOCUS)
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(18, 14, 18, 18)
        lay.setSpacing(8)

        head = QLabel(title)
        head.setObjectName("pageTitle")
        head.setFont(self.F(22, True))
        head.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        head.setWordWrap(True)
        head.setFocusPolicy(NOFOCUS)
        lay.addWidget(head)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("pageSub")
            sub.setFont(self.F(13))
            sub.setWordWrap(True)
            sub.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
            sub.setFocusPolicy(NOFOCUS)
            lay.addWidget(sub)
        outer_scroll.setWidget(inner)

        # الشريط التنقّل خارج منطقة التمرير: يبقى ظاهراً مهما طال المحتوى
        shell = QWidget()
        shell.setFocusPolicy(NOFOCUS)
        shell_lay = QVBoxLayout(shell)
        shell_lay.setContentsMargins(0, 0, 0, 0)
        shell_lay.setSpacing(0)
        shell_lay.addWidget(outer_scroll, 1)

        outer_scroll.setAccessibleName("محتوى: " + title)
        outer_scroll.a11y_head = title + (" — " + subtitle if subtitle else "")
        outer_scroll.a11y_first = None
        outer_scroll.a11y_shell = shell
        shell.a11y_head = outer_scroll.a11y_head
        shell.a11y_first = None
        shell.a11y_scroll = outer_scroll
        shell.a11y_shell_lay = shell_lay
        return shell, lay

    def _build_page(self, sid):
        builder = getattr(self, "_page_" + sid, None)
        if builder is None:
            builder = self._page_help
        page = builder()
        self._attach_nav(page, sid)
        return page

    # --------------------------------------------------------------شريط التنقل
    def _challenge_ids(self):
        return [c[0] for c in CHALLENGES]

    def nav_targets(self, sid):
        """(التالي، السابق)-from sid. الحلقتان تلتفّان: بعد c7 تأتي c1."""
        ids = self._challenge_ids()
        titles = {c[0]: c[1] for c in CHALLENGES}
        first, last = ids[0], ids[-1]
        if sid == "home":
            return first, last, titles
        base = None
        if sid in ids:
            base = ids.index(sid)
        elif sid == "result":
            cid = getattr(self, "result_for", None)
            if cid in ids:
                base = ids.index(cid)
        if base is None:
            cid = getattr(self, "last_challenge", None)
            if cid in ids:
                base = ids.index(cid)
        if base is None:
            return first, last, titles
        return ids[(base + 1) % len(ids)], ids[(base - 1) % len(ids)], titles

    def _attach_nav(self, page, sid):
        """يضع شريط التنقل أسفل الصفحة مرة واحدة فقط، خارج منطقة التمرير."""
        shell_lay = getattr(page, "a11y_shell_lay", None)
        if shell_lay is None or getattr(page, "a11y_nav", False):
            return
        page.a11y_nav = True
        shell_lay.addWidget(self.nav_bar(sid))

    def nav_bar(self, sid):
        """ثلاثة أزرار ثابتة أسفل كل شاشة: الرئيسية، التالي، السابق."""
        nxt, prv, titles = self.nav_targets(sid)
        row = QWidget()
        row.setObjectName("navBar")
        row.setFocusPolicy(NOFOCUS)
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 10, 0, 0)
        rl.setSpacing(8)

        b_home = self.button("القائمة الرئيسية", lambda: self.show_screen("home"),
                             "primary", 14, True, tip="العودة إلى القائمة الرئيسية")
        b_next = self.button("التحدي التالي", lambda: self.show_screen(nxt),
                             "gold", 14, True, tip="الانتقال إلى: %s" % titles[nxt])
        b_prev = self.button("التحدي السابق", lambda: self.show_screen(prv),
                             "neutral", 14, True, tip="الانتقال إلى: %s" % titles[prv])
        for b in (b_home, b_next, b_prev):
            rl.addWidget(b)
        # لا نعطّل أي زر هنا: زر معطّل يصبح «قفزة» في حلقة Tab، وهذا ما
        # يمنعه معيار قارئ الشاشة. 버튼 يبقى مفعّلاً حتى على الشاشة نفسها.
        if sid == "home":
            b_home.setAccessibleDescription("أنت في القائمة الرئيسية حالياً")
        row.a11y_first = b_home
        return row

    # --------------------------------------------------------------عناصر
    def label(self, text, size=14, bold=False, color=None, wrap=True, align_right=True,
              focusable=False, name=""):
        """نص ثابت. focusable=True يجعله محطة Tab يقرأه قارئ الشاشة."""
        lb = QLabel(text)
        lb.setWordWrap(wrap)
        lb.setFont(self.F(size, bold))
        lb.setAlignment((Qt.AlignmentFlag.AlignRight if align_right else Qt.AlignmentFlag.AlignCenter)
                        | Qt.AlignmentFlag.AlignVCenter)
        if color:
            lb.setStyleSheet("color:%s" % color)
        if focusable:
            describe(lb, name or text,
                     "نص للقراءة فقط: استخدم الأسهم و Page Up و Page Down للتنقل داخله")
        else:
            lb.setFocusPolicy(NOFOCUS)
        return lb

    def button(self, text, slot, kind="primary", size=15, big=False, tip="", icon=None):
        bg = {"primary": self.col["primary"], "gold": self.col["gold"],
              "neutral": self.col["card"], "accent": self.col["accent"]}[kind]
        b = AButton(text)
        b.setFont(self.F(size + (3 if big else 0), big or kind in ("primary", "accent")))
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setMinimumHeight(38 if big else 32)
        b.setStyleSheet(self._btn_css(bg, kind))
        self._hook(b.clicked, slot)
        if icon:
            b.setIcon(icon)
        b.setAccessibleName(text.split("\n")[0].strip())
        if tip:
            b.setAccessibleDescription(tip)
        b.setFocusPolicy(TABBING)
        b.a11y_answer = None
        return b

    def _btn_css(self, bg, kind):
        """Qt لا يدعم outline/filter في QSS: نستخدم حدوداً وألواناً حقيقية."""
        fg = readable_on(bg)          # أسود أو أبيض: الأوضح على لون الزر
        # حد شفاف بثلاثة بكسل دائماً حتى لا يتزحزح النص عند اكتساب التركيز
        return ("QPushButton{background:%s;color:%s;border:3px solid transparent;"
                "border-radius:10px;padding:10px 18px;font-weight:600;}"
                "QPushButton:hover{background:%s;}"
                "QPushButton:pressed{background:%s;}"
                "QPushButton:focus{border-color:%s;}"
                "QPushButton:disabled{background:%s;color:%s;}"
                % (bg, fg, shade(bg, 0.12), shade(bg, -0.15), FOCUS_RING,
                   self.col["line"], readable_on(self.col["line"])))

    def hint(self, text):
        lb = QLabel(text)
        lb.setWordWrap(True)
        lb.setFont(self.F(12))
        lb.setObjectName("hint")
        lb.setFocusPolicy(NOFOCUS)
        return lb

    def reader_box(self, text, name, min_h=170):
        box = QTextEdit()
        box.setReadOnly(True)
        box.setTextInteractionFlags(READ_FLAGS)
        box.setFont(self.F(14))
        box.setPlainText(text)
        box.setMinimumHeight(min_h)
        box.setObjectName("readerBox")
        describe(box, name, "نص للقراءة فقط: استخدم الأسهم و Page Up و Page Down للتنقل داخله")
        return box

    # --------------------------------------------------------------الشاشات
    def screen_title(self, sid):
        titles = {"home": "الرئيسية", "guide": "دليل المذيع", "settings": "الإعدادات",
                  "help": "التعليمات", "result": "نتيجة التحدي",
                  "c1": "تحدي سرعة النشرة", "c2": "تحدي مخارج الحروف",
                  "c3": "تحدي النبرة والتلوين", "c4": "تحدي علامات الوقف",
                  "c5": "تحدي الأذن المدربة", "c6": "تحدي الأداء أمام الكاميرا",
                  "c7": "تحدي المذيع الصغير"}
        return titles.get(sid, sid)

    def stars_total(self):
        return sum(self.prog["per_challenge"].values())

    def medal(self):
        t = self.stars_total()
        if t >= 15:
            return "وسام ذهبي"
        if t >= 9:
            return "وسام فضي"
        if t >= 4:
            return "وسام برونزي"
        return "مذيع مبتدئ"

    def _page_home(self):
        page, lay = self.new_page("الرئيسية")
        name = self.prog.get("name") or "المذيع الصغير"
        lay.addWidget(self.label("أهلاً بك يا %s!" % name, 20, True,
                                 focusable=True, name="ترحيب: أهلاً بك يا %s" % name))
        stars_txt = "نجومك: %d من %d  •  %s" % (self.stars_total(), MAX_TOTAL, self.medal())
        lay.addWidget(self.label(stars_txt, 14, True, self.col["gold"],
                                 focusable=True, name=stars_txt))
        ph = self._pix("newsroom-studio.png")
        if not ph.isNull():
            img = QLabel()
            img.setPixmap(ph.scaledToWidth(560, Qt.TransformationMode.SmoothTransformation))
            img.setAlignment(Qt.AlignmentFlag.AlignCenter)
            img.setFocusPolicy(NOFOCUS)
            img.setAccessibleName("صورة استوديو الأخبار")
            lay.addWidget(img)
        first = None
        for i, (cid, ctitle, desc, icon_name) in enumerate(CHALLENGES, 1):
            best = self.prog["per_challenge"].get(cid, 0)
            best_txt = ("نجوم هذا التحدي: %d" % best) if best else "لم يبدأ بعد"
            b = self.button("%d. %s — %s (%s)" % (i, ctitle, desc, best_txt),
                            lambda _checked=False, cid=cid: self.show_screen(cid),
                            "neutral", 13, True,
                            tip="افتح %s. %s" % (ctitle, desc), icon=self._icon(icon_name))
            b.setAccessibleName("%d. %s" % (i, ctitle))
            b.setAccessibleDescription("%s. %s" % (desc, best_txt))
            lay.addWidget(b)
            if first is None:
                first = b
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 6, 0, 6)
        b_g = self.button("دليل المذيع", lambda: self.show_screen("guide"), "primary")
        b_s = self.button("الإعدادات", lambda: self.show_screen("settings"), "gold")
        b_h = self.button("التعليمات", lambda: self.show_screen("help"), "accent")
        for b in (b_s, b_g, b_h):
            rl.addWidget(b)
        lay.addWidget(row)
        lay.addStretch(1)
        page.a11y_first = first or b_s
        return page

    def _page_c1(self):
        page, lay = self.new_page(
            "تحدي 1: سرعة النشرة",
            "اقرأ النشرة بصوت مرتفع ثم اضغط «انتهيت» ليحسب التطبيق سرعتك (كلمة في الدقيقة).")
        st = {"idx": 0, "start": None, "rec": None, "path": None,
              "token": 0, "transcribing": False, "dbg": None, "diag": {}}
        body = self.reader_box(BULLETINS[0][1], "نص النشرة — للقراءة فقط")
        lay.addWidget(body)
        meta = self.label("", 12, False, self.col["muted"])
        result = self.label("", 15, True, self.col["accent"], focusable=True, name="نتيجة القراءة")
        start_btn = self.button("ابدأ القراءة", lambda: toggle(), "primary", big=True)
        play_rec = self.button("استمع إلى تسجيلك",
                               lambda: self.play_recording(self.saved_recording("c1")),
                               "gold", tip="استمع إلى تسجيلك المحفوظ")
        play_rec.setVisible(False)

        def sync_play_rec():
            """يُبقي الزر مطابقاً للحقيقة: ظاهر ما دام هناك تسجيل صالح.

            كان الزر يُخفى عند بدء أي محاولة جديدة ويُستعاد فقط لو نجحت،
            فلمحاولة فاشلة (ميكروفون مرفوض مثلاً) كان الزر يختفي عن الطفل
            رغم وجود تسجيله السابق. الآن الزر يقرأ 항상 آخر تسجيل صالح.
            """
            have = self.saved_recording("c1") is not None
            play_rec.setVisible(have)
            return have
        dbg_box = QGroupBox("تشخيص تفريغ الكلام (تطوير فقط)")
        dbg_box.setVisible(False)
        dbg_lbl = self.label("", 12, False, self.col["muted"], align_right=False,
                             focusable=True, name="تشخيص التفريغ")
        dbg_lay = QVBoxLayout(dbg_box)
        dbg_lay.addWidget(dbg_lbl)
        dbg_box.setAccessibleName("تشخيص تفريغ الكلام — للتطوير فقط")

        def load(idx, talk=True):
            st["idx"] = idx
            st["token"] += 1
            title, text = BULLETINS[idx]
            body.setPlainText(text)
            body.setAccessibleName("نص النشرة: %s — للقراءة فقط" % title)
            # عدد كلمات *النص*، ليس ما قاله الطفل. لصياغة صريحة.
            meta.setText("نشرة: %s   (عدد كلمات النص: %d)" % (title, len(text.split())))
            meta.setAccessibleName(meta.text())
            st["start"] = None
            st["transcribing"] = False
            start_btn.setText("ابدأ القراءة")
            start_btn.setAccessibleName("ابدأ القراءة")
            result.setText("")
            result.setAccessibleName("نتيجة القراءة")
            sync_play_rec()          # نشرة جديدة: نُعيد الحالة إلى الحقيقة
            if talk:
                self.announce("النشرة: %s" % title)
                start_btn.setFocus(Qt.FocusReason.OtherFocusReason)

        def yesno(value):
            return "نعم" if value else "لا"

        def diag(**fields):
            """تشخيص المطوّر: كل خطوة في مسار التسجيل والتفريغ."""
            st["diag"].update(fields)
            d = st["diag"]
            if DEBUG_STT:
                ana_recorder.trace("diag", " ".join(
                    "%s=%s" % (k, v) for k, v in fields.items()))
            return d

        def show_debug(info, note=""):
            """لوحة التطوير: تُظهر ما رآه التطبيق بالضبط ومصدره."""
            if not DEBUG_STT:
                return
            d = st["diag"]
            text = ana_stt.describe(info)
            # خطوط الفحص المطلوبة: تسجيل/حفظ/تفريغ، مقروءةChildren فلا.
            text += "\n" + "\n".join((
                "— فحوص المسار (للتطوير فقط) —",
                "بدأ التسجيل: %s" % yesno(d.get("started")),
                "توقف التسجيل: %s" % yesno(d.get("stopped")),
                "مسار WAV: %s" % (d.get("path") or "(لا يوجد)"),
                "WAV موجود: %s" % yesno(d.get("exists")),
                "حجم WAV: %s بايت" % (d.get("size") if d.get("size") is not None
                                      else "(غير معروف)"),
                "مدة WAV: %s ثانية" % (d.get("seconds")
                                       if d.get("seconds") is not None
                                       else "(غير معروفة)"),
                "WAV قابل للقراءة: %s" % yesno(d.get("readable")),
                "بدأ التفريغ: %s" % yesno(d.get("stt_started")),
                "نتيجة التفريغ: %s" % (d.get("stt_result") or "(لم يبدأ)"),
                "خطأ التفريغ: %s" % (d.get("stt_error") or "(لا يوجد)"),
                "المسجّل: %s" % (d.get("recorder") or "(غير معروف)"),
                "سجل المطوّر: %s" % ana_recorder.trace_text().strip().replace(
                    "\n", " | ") or "(فارغ)",
            ))
            dbg_box.setVisible(True)
            dbg_lbl.setText(text)
            dbg_lbl.setAccessibleName(text)
            st["dbg"] = info

        def report(wpm_msg, stars, extra=""):
            self.finish("c1", stars, (wpm_msg + " " + extra).strip())

        def stars_for(wpm):
            if wpm <= 0:
                return 0
            return 3 if 45 <= wpm <= 160 else (2 if (25 <= wpm < 45 or 160 < wpm <= 200) else 1)

        def toggle():
            if st["start"] is None:
                if st["transcribing"]:
                    return                       # جارٍ التفريغ: لا تُعد قراءة جديدة
                rec = ana_recorder.make_recorder()
                st["path"] = ana_recorder.new_path("c1_")
                st["diag"] = {"path": st["path"], "recorder": rec.name,
                              "started": False, "stopped": False, "exists": False,
                              "readable": False, "size": None, "seconds": None,
                              "stt_started": False, "stt_result": None,
                              "stt_error": None}
                diag(started=False, recorder=rec.name, path=st["path"])
                mic_ok, mic_why = rec.start(st["path"])
                diag(started=bool(mic_ok), mic_reason=mic_why)
                st["rec"] = rec if mic_ok else None
                st["mic_why"] = mic_why
                self.recorder = rec if mic_ok else None
                st["start"] = time.perf_counter()
                sync_play_rec()     # محاولة جديدة: زر التسجيل السابق يبقى إن كان صالحاً
                self.play_sound("start")
                start_btn.setText("انتهيت من القراءة")
                start_btn.setAccessibleName("انتهيت من القراءة")
                if mic_ok:
                    result.setText("اقرأ الآن بصوت مرتفع وواضح…")
                    result.setAccessibleName("حالة التوقيت: بدأ القياس والتسجيل")
                    self.announce("بدأ التوقيت والتسجيل. اقرأ الآن بصوت مرتفع، "
                                  "ثم اضغط «انتهيت من القراءة».")
                else:
                    result.setText("الميكروفون غير متاح (%s)، فسيُحسب الوقت فقط "
                                   "دون تفريغ الكلام." % mic_why)
                    result.setAccessibleName("بدأ الوقت فقط: الميكروفون غير متاح")
                    self.announce("بدأ الوقت. الميكروفون غير متاح، فلن يُحسَب عدد الكلمات.")
            else:
                el = time.perf_counter() - st["start"]
                st["start"] = None
                rec, path = st["rec"], st["path"]
                st["rec"] = None
                self.recorder = None
                saved = False
                stop_err = ""
                if rec is not None:
                    saved, stop_err = rec.stop()
                start_btn.setText("ابدأ القراءة مرة أخرى")
                start_btn.setAccessibleName("ابدأ القراءة مرة أخرى")
                # فحوص فورية بعد الإيقاف: هل الملف موجود فعلاً وقابل للقراءة؟
                exists = bool(path) and os.path.exists(path)
                size = os.path.getsize(path) if exists else None
                wav_secs = ana_stt.wav_seconds(path) if exists else 0.0
                readable = exists and ana_recorder.wav_is_valid(path)
                diag(stopped=True, exists=exists, size=size, seconds=wav_secs,
                     readable=readable, stop_error=stop_err)
                if not saved or not path or not exists or not readable:
                    # بلا صوت حقيقي صالح: لا نحسب عدد كلمات إطلاقاً.
                    if rec is None:
                        # الميكروفون لم يبدأ أصلاً. سبب واحد واضح يُقال مرة
                        # واحدة: الطفل لم يخطئ، ولم نكرّر عليه «لم يُحفظ
                        # تسجيلك» وكأنه أخطأ في القراءة.
                        info = {"ok": False, "text": "", "words": 0,
                                "engine": "لا يوجد",
                                "language": ana_stt.LANGUAGE_TAG, "model": ana_stt.MODEL,
                                "path": path or "", "seconds": el, "elapsed": el,
                                "error": "الميكروفون لم يبدأ",
                                "source": "لا يوجد تسجيل صالح"}
                        show_debug(info)
                        why_mic = st.get("mic_why") or "الميكروفون غير متاح"
                        self.announce("سُجّل وقتك. الميكروفون لم يعمل، "
                                      "فلم يُسجَّل صوتك هذه المرة.")
                        report("سُجّل وقتك: %d ثانية." % int(el), 0,
                               "لم يعمل الميكروفون (%s)، فلم يُسجَّل صوتك. "
                               "تأكّد من توصيله ثم جرّب مرة أخرى." % why_mic)
                        return
                    why = stop_err or ("لم يُحفظ تسجيل (الميكروفون غير متاح؟)"
                                       if not exists else
                                       "ملف التسجيل غير صالح للقراءة.")
                    info = {"ok": False, "text": "", "words": 0, "engine": "لا يوجد",
                            "language": ana_stt.LANGUAGE_TAG, "model": ana_stt.MODEL,
                            "path": path or "", "seconds": wav_secs or el,
                            "elapsed": el,
                            "error": why, "source": "لا يوجد تسجيل صالح"}
                    show_debug(info)
                    self.announce("سُجّل وقتك. لم يُحفظ تسجيل صوتي واضح، "
                                  "فلا يمكن حساب عدد الكلمات.")
                    # نصّ الطفل: سبب واضح ودافئ فقط. المسارات ورموز
                    # الأخطاء للمطوّر في لوحة التشخيص لا هنا.
                    report("سُجّل وقتك: %d ثانية." % int(el), 0,
                           "لم يُحفظ تسجيلك، لذلك لم نحسب عدد الكلمات. "
                           "تأكّد من أن الميكروفون متصل ثم جرّب مرة أخرى.")
                    return
                ana_recorder.keep_recent(os.path.dirname(path), "c1_", 10)
                # التسجيل صالح: نُتيح إعادة تشغيله فوراً ونسجّل مساره لزر
                # الاستماع في شاشة النتيجة.
                self.last_rec["c1"] = path
                sync_play_rec()
                ok_engine, engine_name, detail = ana_stt.available()
                if not ok_engine:
                    st["token"] += 1
                    info = {"ok": False, "text": "", "words": 0, "engine": engine_name,
                            "language": ana_stt.LANGUAGE_TAG, "model": detail,
                            "path": path, "seconds": ana_stt.wav_seconds(path),
                            "elapsed": el,
                            "error": "لا يوجد محرّك تفريغ عربي مثبّت على هذا الجهاز.",
                            "source": "تسجيل صوت الطفل (بلا تفريغ)"}
                    show_debug(info)
                    self.announce("سُجّل وقتك. لا يوجد محرّك تفريغ عربي مثبّت، "
                                  "فلا نحسب عدد الكلمات.")
                    report("سُجّل وقتك: %d ثانية." % int(el), 0,
                           "تسجيلك محفوظ، لكن هذا الجهاز بلا محرّك تفريغ عربي، "
                           "لذلك لم نحسب عدد الكلمات ولا نذكر سرعة. "
                           "ثبّت faster-whisper لتفعيل العدّ.")
                    return
                # يوجد محرّك: نُفريغ دون تجميد الواجهة
                st["transcribing"] = True
                st["token"] += 1
                token = st["token"]
                result.setText("جارٍ تفريغ تسجيلك إلى نص…")
                result.setAccessibleName("جارٍ تفريغ تسجيلك إلى نص")
                self.announce("جارٍ تفريغ تسجيلك. انتظر قليلاً. "
                              "أول مرة قد يستغرق تحميل النموذج دقيقة.")

                def work():
                    # المدة تُقرأ من *ملف التسجيل* لا من المؤقّت، حتى لا يفترق
                    # العدد عن الصوت الذي فُرِّغ فعلاً.
                    info = ana_stt.transcribe(path)
                    info["elapsed"] = el
                    diag(stt_started=True,
                         stt_result="ok" if info.get("ok") else "فشل",
                         stt_error=info.get("error") or None,
                         stt_text=info.get("text") or "")
                    return info

                def done(info):
                    if token != st["token"] or self.current != "c1":
                        return                    # نتيجة قديمة: تُهمَل
                    st["transcribing"] = False
                    show_debug(info)
                    secs = float(info.get("seconds") or el)
                    if not info.get("ok"):
                        self.finish("c1", 0, (
                            "سُجّل وقتك: %d ثانية. %s" % (int(secs), info.get("error"))))
                        return
                    words = info.get("words", 0)
                    wpm = ana_stt.words_per_minute(words, secs)
                    if not words:
                        self.finish("c1", 0, (
                            "سُجّل وقتك: %d ثانية. لم نسمع كلاماً واضحاً في التسجيل، "
                            "فلا يمكن حساب عدد الكلمات. اقرأ بصوت أعلى من الميكروفون."
                            % int(secs)))
                        return
                    stars = stars_for(wpm)
                    self.finish("c1", stars, (
                        "قرأت %s في %d ثانية، أي نحو %d كلمة في الدقيقة. %s"
                        % (ana_stt.words_phrase(words), int(secs), wpm,
                           "أنت في سرعة المذيع الصغير الممتازة!" if stars == 3
                           else "استمر في التدريب فالسرعة تتحسن بالتكرار.")))

                signals = _SttSignals()
                page._stt_signals = signals          # يبقى حيّاً حتى تُحذف الصفحة
                signals.done.connect(done)

                def job():
                    try:
                        info = work()
                    except Exception as exc:
                        # أي خطأ غير متوقع يصل هنا صريحاً إلى لوحة التطوير
                        # بدل أن يختفي خلف "لم يُحفظ تسجيلك".
                        diag(stt_started=True, stt_result="استثناء",
                             stt_error="%s: %s" % (type(exc).__name__, exc))
                        info = {"ok": False, "text": "", "words": 0,
                                "engine": "خطأ في المحرّك",
                                "language": ana_stt.LANGUAGE_TAG,
                                "model": ana_stt.MODEL, "path": path,
                                "seconds": el, "elapsed": el, "error": str(exc),
                                "source": "تسجيل صوت الطفل"}
                    signals.done.emit(info)

                ana_stt.EXECUTOR.submit(job)

        lay.addWidget(meta)
        lay.addWidget(result)
        lay.addWidget(start_btn)
        lay.addWidget(play_rec)
        lay.addWidget(dbg_box)
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        listen = self.button("استمع إلى النص", lambda: self.speak(BULLETINS[st["idx"]][1]), "gold")
        nxt = self.button("نشرة أخرى", lambda: load((st["idx"] + 1) % len(BULLETINS)), "neutral")
        rl.addWidget(listen)
        rl.addWidget(nxt)
        lay.addWidget(row)
        lay.addWidget(self.hint(
            "نصيحة: اقرأ النشرة أولاً بخفوت مرة واحدة لتتعرف على الكلمات الصعبة، "
            "ثم ابدأ القراءة بصوت مرتفع."))
        lay.addStretch(1)
        page.a11y_first = start_btn

        def cancel_stt():
            """عند مغادرة الشاشة: أي نتيجة تفريغ قادمة تُهمَل."""
            st["token"] += 1
            st["transcribing"] = False

        page._stt_cancel = cancel_stt
        load(0, talk=False)
        return page

    def _page_c2(self):
        page, lay = self.new_page("تحدي 2: مخارج الحروف",
                                   "استمع للحرف والجملة، اقرأهما بوضوح وبصوت عالٍ، ثم قيّم أداءك.")
        st = {"i": 0, "acc": 0}
        big = self.label(LETTERS[0][0], 44, True, self.col["accent"], align_right=False,
                         focusable=True, name="الحرف: %s" % LETTERS[0][0])
        big.setStyleSheet("background:%s;border:1px solid %s;border-radius:12px;padding:14px;"
                          % (self.col["card"], self.col["line"]))
        sent = self.label(LETTERS[0][1], 17, align_right=False, focusable=True,
                          name="جملة التدريب: %s" % LETTERS[0][1])
        pos = self.label("الحرف 1 من %d" % len(LETTERS), 12, False, self.col["muted"], align_right=False)
        hear = self.button("استمع إلى الحرف والجملة", lambda: hear_now(), "gold", big=True)

        def hear_now():
            letter, word = LETTERS[st["i"]]
            self.speak("اقرأ معي. %s. ثم الجملة: %s" % (letter, word))
            self.announce("الحرف %s. الجملة: %s" % (letter, word))

        def choose(stars):
            st["acc"] += stars
            self.play_sound("correct" if stars >= 2 else "positive")
            if st["i"] + 1 < len(LETTERS):
                st["i"] += 1
                letter, word = LETTERS[st["i"]]
                big.setText(letter)
                big.setAccessibleName("الحرف: %s" % letter)
                sent.setText(word)
                sent.setAccessibleName("جملة التدريب: %s" % word)
                pos.setText("الحرف %d من %d" % (st["i"] + 1, len(LETTERS)))
                pos.setAccessibleName(pos.text())
                self.announce("الحرف %d من %d: %s" % (st["i"] + 1, len(LETTERS), letter))
                hear.setFocus(Qt.FocusReason.OtherFocusReason)
            else:
                total = min(3, max(1, round(st["acc"] / len(LETTERS))))
                self.finish("c2", total,
                            "أكملت تدريب مخارج الحروف الثمانية. أعد كل حرف كل يوم حتى يصبح نطقه تلقائياً.")

        lay.addWidget(big)
        lay.addWidget(sent)
        lay.addWidget(pos)
        lay.addWidget(hear)
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 6, 0, 6)
        for text_b, stars, kind in (("ممتاز", 3, "primary"), ("جيد", 2, "gold"),
                                    ("أحتاج تدريباً", 1, "accent")):
            b = self.button(text_b, lambda _checked=False, s=stars: choose(s), kind, big=True)
            b.setAccessibleDescription("قيّم أداءك بـ %s" % text_b)
            rl.addWidget(b)
        lay.addWidget(row)
        lay.addWidget(self.hint("نصيحة: ضع يدك على حلقك وتأكد أن الحروف النغمة مثل «ض» و«ق» تهتز بوضوح."))
        lay.addStretch(1)
        page.a11y_first = hear
        return page

    def _page_c3(self):
        page, lay = self.new_page("تحدي 3: النبرة والتلوين",
                                   "لكل جملة نبرة خاصة. استمع إلى النموذج، أعد القراءة بالإحساس نفسه، ثم قيّم نفسك.")
        st = {"i": 0, "acc": 0}
        big = self.label(EMOTIONS[0][0], 24, True, self.col["accent"], align_right=False,
                         focusable=True, name="المشهد: %s" % EMOTIONS[0][0])
        big.setStyleSheet("background:%s;border:1px solid %s;border-radius:12px;padding:12px;"
                          % (self.col["card"], self.col["line"]))
        sent = self.label(EMOTIONS[0][1], 17, align_right=False, focusable=True,
                          name="الجملة: %s" % EMOTIONS[0][1])
        pos = self.label("المشهد 1 من %d" % len(EMOTIONS), 12, False, self.col["muted"], align_right=False)
        hear = self.button("استمع إلى النموذج", lambda: hear_now(), "gold", big=True)

        def hear_now():
            nm, phrase = EMOTIONS[st["i"]]
            self.speak("أداء بالشعور: %s. %s" % (nm, phrase))
            self.announce("النبرة: %s. الجملة: %s" % (nm, phrase))

        def choose(stars):
            st["acc"] += stars
            self.play_sound("correct" if stars >= 2 else "positive")
            if st["i"] + 1 < len(EMOTIONS):
                st["i"] += 1
                nm, phrase = EMOTIONS[st["i"]]
                big.setText(nm)
                big.setAccessibleName("المشهد: %s" % nm)
                sent.setText(phrase)
                sent.setAccessibleName("الجملة: %s" % phrase)
                pos.setText("المشهد %d من %d" % (st["i"] + 1, len(EMOTIONS)))
                pos.setAccessibleName(pos.text())
                self.announce("المشهد %d من %d: %s" % (st["i"] + 1, len(EMOTIONS), nm))
                hear.setFocus(Qt.FocusReason.OtherFocusReason)
            else:
                total = min(3, max(1, round(st["acc"] / len(EMOTIONS))))
                self.finish("c3", total,
                            "أتقنت المشاهد الأربعة. المذيع الجيد يعرف متى يفرح ومتى يحزن بصوته فقط.")

        lay.addWidget(big)
        lay.addWidget(sent)
        lay.addWidget(pos)
        lay.addWidget(hear)
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 6, 0, 6)
        for text_b, stars, kind in (("ممتاز", 3, "primary"), ("جيد", 2, "gold"),
                                    ("أحتاج تدريباً", 1, "accent")):
            b = self.button(text_b, lambda _checked=False, s=stars: choose(s), kind, big=True)
            b.setAccessibleDescription("قيّم أداءك بـ %s" % text_b)
            rl.addWidget(b)
        lay.addWidget(row)
        lay.addWidget(self.hint("نصيحة: السؤال يرتفع صوته قليلاً في نهايته، والخبر الحزين يهدأ ويبطئ."))
        lay.addStretch(1)
        page.a11y_first = hear
        return page


    def _page_c4(self):
        page, lay = self.new_page("تحدي 4: علامات الوقف",
                                   "أين تقف وقفة تساعد السامع على فهم المعنى؟ اختر الموضع الصحيح.")
        st = {"q": 0, "correct": 0}
        adv = QTimer(self)          # قابل للإلغاء: يُوقف عند مغادرة الشاشة
        adv.setSingleShot(True)
        adv.timeout.connect(lambda: next_q())
        txt = self.label("", 18, align_right=False, focusable=True, name="جملة التدريب")
        txt.setStyleSheet("background:%s;border:1px solid %s;border-radius:12px;padding:14px;"
                          % (self.col["card"], self.col["line"]))
        qst = self.label("", 13, False, self.col["muted"], align_right=False,
                         focusable=True, name="السؤال")
        fb = self.label("", 15, True, self.col["accent"], align_right=False,
                        focusable=True, name="نتيجة الإجابة")
        pos = self.label("", 12, False, self.col["muted"], align_right=False)
        opt = [self.button("", lambda: None, "neutral") for _ in range(3)]

        def show_q(i):
            sentence, question, _c, _w1, _w2 = STOP_QUIZ[i]
            txt.setText(sentence)
            txt.setAccessibleName("جملة التدريب: %s" % sentence)
            qst.setText(question)
            qst.setAccessibleName("السؤال: %s" % question)
            fb.setText("")
            fb.setAccessibleName("نتيجة الإجابة")
            pos.setText("الجملة %d من %d" % (i + 1, len(STOP_QUIZ)))
            pos.setAccessibleName(pos.text())
            opts = rotated([STOP_QUIZ[i][2], STOP_QUIZ[i][3], STOP_QUIZ[i][4]], i)
            for k, b in enumerate(opt):
                b.setText(opts[k])
                b.setAccessibleName("الخيار %d: %s" % (k + 1, opts[k]))
                b.a11y_answer = opts[k]
                b.setEnabled(True)

        def answer(text):
            _s, _q, right, _w1, _w2 = STOP_QUIZ[st["q"]]
            if text == right:
                st["correct"] += 1
                self.play_sound("correct")
                fb.setText("أحسنت! وقعت وقفتك في المكان الصحيح.")
            else:
                self.play_sound("wrong")
                fb.setText("الموضع الصحيح هو: %s." % right)
            fb.setAccessibleName("نتيجة الإجابة: %s" % fb.text())
            for b in opt:
                b.setEnabled(False)
            # لا نُبقي التركيز على زر معطّل: ينتقل إلى نص النتيجة ليُعلَن فوراً
            fb.setFocus(Qt.FocusReason.OtherFocusReason)
            self.announce(fb.text())
            adv.start(2600)

        def next_q():
            adv.stop()
            if st["q"] + 1 < len(STOP_QUIZ):
                st["q"] += 1
                show_q(st["q"])
                opt[0].setFocus(Qt.FocusReason.OtherFocusReason)
            else:
                c = st["correct"]
                stars = 3 if c >= 5 else (2 if c >= 4 else (1 if c >= 3 else 0))
                self.finish("c4", stars, "أصبت %d من %d." % (c, len(STOP_QUIZ)))

        def reset():
            """عودة نظيفة: تُستدعى كلما دخل المستخدم التحدي من جديد."""
            adv.stop()
            st["q"] = 0
            st["correct"] = 0
            show_q(0)
            opt[0].setFocus(Qt.FocusReason.OtherFocusReason)

        for b in opt:
            b.clicked.connect(lambda _c=False, b=b: answer(b.a11y_answer))
        lay.addWidget(txt)
        lay.addWidget(qst)
        lay.addWidget(fb)
        lay.addWidget(pos)
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 6, 0, 6)
        for b in opt:
            rl.addWidget(b)
        lay.addWidget(row)
        lay.addWidget(self.hint("قاعدة: الوقفة تأتي عند اكتمال المعنى، لا في منتصف الجملة."))
        lay.addStretch(1)
        page.a11y_first = opt[0]
        page.a11y_reset = reset
        page.a11y_leave = adv.stop
        show_q(0)
        return page

    def _page_c5(self):
        page, lay = self.new_page("تحدي 5: الأذن المدربة",
                                   "اضغط «استمع» لتسمع الكلمة مرتين، ثم اختر من الخيارات ما سمعته بالضبط.")
        st = {"q": 0, "correct": 0}
        adv = QTimer(self)          # قابل للإلغاء: يُوقف عند مغادرة الشاشة
        adv.setSingleShot(True)
        adv.timeout.connect(lambda: next_q())
        txt = self.label("؟", 26, True, self.col["accent"], align_right=False,
                         focusable=True, name="الكلمة المخفية")
        txt.setStyleSheet("background:%s;border:1px solid %s;border-radius:12px;padding:14px;"
                          % (self.col["card"], self.col["line"]))
        fb = self.label("", 15, True, self.col["accent"], align_right=False,
                        focusable=True, name="نتيجة الإجابة")
        pos = self.label("", 12, False, self.col["muted"], align_right=False)
        opt = [self.button("", lambda: None, "neutral") for _ in range(3)]
        hear = self.button("استمع (مرتين)", lambda: hear_word(), "gold", big=True)

        def show_q(i):
            _word, options = LISTEN_QUIZ[i]
            txt.setText("؟")
            fb.setText("")
            fb.setAccessibleName("نتيجة الإجابة")
            pos.setText("السؤال %d من %d — اضغط «استمع» أولاً" % (i + 1, len(LISTEN_QUIZ)))
            pos.setAccessibleName(pos.text())
            for k, b in enumerate(opt):
                b.setText(options[k])
                b.setAccessibleName("الخيار %d: %s" % (k + 1, options[k]))
                b.a11y_answer = options[k]
                b.setEnabled(True)

        def hear_word():
            word, _ = LISTEN_QUIZ[st["q"]]
            # نداء واحد يحمل الكلمة مرتين: لو نُطقت بنداءين متتابعين لقُطع
            # الأول عند بدء الثاني، لأن مشغّل الصوت يُستبدل ولا ينتظر.
            self.speak("%s، %s" % (word, word))
            self.announce("استمع للكلمة ثم اختر ما سمعته")

        def answer(text):
            word, _o = LISTEN_QUIZ[st["q"]]
            if text == word:
                st["correct"] += 1
                self.play_sound("correct")
                fb.setText("أحسنت! سمعت كلمة «%s»." % word)
            else:
                self.play_sound("wrong")
                fb.setText("الكلمة كانت «%s»، اضغط «استمع» وحاول من جديد." % word)
            fb.setAccessibleName("نتيجة الإجابة: %s" % fb.text())
            for b in opt:
                b.setEnabled(False)
            fb.setFocus(Qt.FocusReason.OtherFocusReason)
            self.announce(fb.text())
            adv.start(2600)

        def next_q():
            adv.stop()
            if st["q"] + 1 < len(LISTEN_QUIZ):
                st["q"] += 1
                show_q(st["q"])
                hear.setFocus(Qt.FocusReason.OtherFocusReason)
            else:
                c = st["correct"]
                stars = 3 if c >= 5 else (2 if c >= 4 else (1 if c >= 3 else 0))
                self.finish("c5", stars, "أصبت %d من %d." % (c, len(LISTEN_QUIZ)))

        def reset():
            """عودة نظيفة: تُستدعى كلما دخل المستخدم التحدي من جديد."""
            adv.stop()
            st["q"] = 0
            st["correct"] = 0
            show_q(0)
            hear.setFocus(Qt.FocusReason.OtherFocusReason)

        for b in opt:
            b.clicked.connect(lambda _c=False, b=b: answer(b.a11y_answer))
        lay.addWidget(txt)
        lay.addWidget(fb)
        lay.addWidget(pos)
        lay.addWidget(hear)
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 6, 0, 6)
        for b in opt:
            rl.addWidget(b)
        lay.addWidget(row)
        lay.addWidget(self.hint("نصيحة: أغمض عينيك عند الاستماع لتتفرغ الأذن للتمييز."))
        lay.addStretch(1)
        page.a11y_first = hear
        page.a11y_reset = reset
        page.a11y_leave = adv.stop
        show_q(0)
        return page

    def _page_c6(self):
        page, lay = self.new_page("تحدي 6: الأداء أمام الكاميرا",
                                   "اختر نشرة، قف أمام المرآة، أَدِّ النشرة، ثم علّم على ما أنجزته.")
        st = {"sel": 0}
        sel_txt = self.label("", 15, align_right=False, focusable=True, name="النشرة المختارة")
        sel_txt.setStyleSheet("background:%s;border:1px solid %s;border-radius:12px;padding:12px;"
                              % (self.col["card"], self.col["line"]))

        def choose(i, talk=True):
            st["sel"] = i
            self.play_sound("positive")
            sel_txt.setText("النشرة المختارة: %s\n%s" % (BULLETINS[i][0], BULLETINS[i][1]))
            sel_txt.setAccessibleName("النشرة المختارة: %s" % BULLETINS[i][0])
            if talk:
                self.announce("النشرة المختارة: %s" % BULLETINS[i][0])

        brow = QWidget()
        bl = QHBoxLayout(brow)
        bl.setContentsMargins(0, 4, 0, 4)
        first = None
        for i, (t, _b) in enumerate(BULLETINS):
            b = self.button(t, lambda _checked=False, i=i: choose(i), "neutral")
            b.setAccessibleDescription("اختر نشرة %s للقراءة" % t)
            bl.addWidget(b)
            if first is None:
                first = b
        lay.addWidget(sel_txt)
        lay.addWidget(brow)
        group = QGroupBox("قائمة التقييم الذاتي")
        group.setFont(self.F(14, True))
        group.setAccessibleName("قائمة التقييم الذاتي")
        group.setAccessibleDescription("مربعات اختيار لما أنجزته")
        gl = QVBoxLayout(group)
        checks = []
        for item in SELFCHECK:
            cb = QCheckBox(item)
            cb.setFont(self.F(14))
            describe(cb, item, "ضع علامة إذا أنجزت هذا البند")
            gl.addWidget(cb)
            checks.append(cb)
        lay.addWidget(group)
        fin = self.button("أنهيت التمرين وأديت النشرة كاملة", lambda: finish(), "primary", big=True)

        def finish():
            n = sum(1 for c in checks if c.isChecked())
            stars = 3 if n >= 4 else (2 if n >= 2 else 1)
            self.speak("أنهيت الأداء أمام الكاميرا، رائع!")
            self.finish("c6", stars, "أكملت %d بنود من أصل %d من أداء المذيع المحترف."
                        % (n, len(SELFCHECK)))

        lay.addWidget(fin)
        ph = self._pix("anchor-simulator.png")
        if not ph.isNull():
            img = QLabel()
            img.setPixmap(ph.scaledToWidth(420, Qt.TransformationMode.SmoothTransformation))
            img.setAlignment(Qt.AlignmentFlag.AlignCenter)
            img.setFocusPolicy(NOFOCUS)
            img.setAccessibleName("صورة محاكي المرآة")
            lay.addWidget(img)
        lay.addWidget(self.hint("نصيحة: اقرأ مرة وأنت تنظر إلى النص، ومرة وترفع رأسك قليلاً."))
        lay.addStretch(1)
        page.a11y_first = first or fin
        choose(0, talk=False)
        return page

    def _page_c7(self):
        """تحدي المذيع الصغير: جملة قصيرة، تسجيل حقيقي، حفظ، نجوم، ومتابعة."""
        page, lay = self.new_page(
            "تحدي المذيع الصغير",
            "اقرأ جملة قصيرة بصوتك أنت، سجّلها، ثم استمع إليها. مشروعك الأول كمذيع!")
        st = {"sent": 0, "rec": None, "path": None, "phase": "idle", "timer": None,
              "panel": None}
        instruction = ("اقرأ الجملة بصوت واضح، ثم اضغط زر ابدأ التسجيل، وتكلّم في "
                       "الميكروفون، ثم اضغط زر إيقاف التسجيل لحفظ صوتك.")
        picks = CHILD_SENTENCES[:3]
        intro = self.label(
            "مرحباً يا مذيع صغير! اختر جملة، اقرأها بصوتك، ثم سجّلها. "
            "تُحسب لك نجوم على تسجيلك.", 16, True, self.col["primary"], focusable=True,
            name="مقدمة تحدي المذيع الصغير: اختر جملة واقرأها بصوتك ثم سجّلها")
        lay.addWidget(intro)
        listen = self.button("استمع إلى التعليمات", lambda: say_instructions(),
                             "neutral",
                             tip="استمع إلى شرح ما يجب أن تفعله في هذا التحدي")
        lay.addWidget(listen)
        lay.addWidget(self.label("اختر الجملة التي ستسجّلها:", 15, True))
        chosen = self.label("", 18, True, self.col["accent"],
                            focusable=True, name="الجملة المختارة")
        lay.addWidget(chosen)
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 4, 0, 4)
        first = None
        for idx, sent in enumerate(picks):
            b = self.button("جملة %d" % (idx + 1),
                            lambda _checked=False, i=idx: pick(i), "gold")
            b.setAccessibleName("اختر الجملة %d" % (idx + 1))
            b.setAccessibleDescription("ستسجّل هذه الجملة: %s" % sent)
            b.setMinimumWidth(120)
            rl.addWidget(b)
            if first is None:
                first = b
        lay.addWidget(row)
        def state_sheet(color):
            # العنصر محطة Tab أثناء التسجيل، فحلقة تركيزه ظاهرة لا مخفية
            return ("QLabel { color:%s; border:3px solid transparent;"
                    "border-radius:10px; padding:6px }"
                    "QLabel:focus { border-color:%s }" % (color, FOCUS_RING))

        state = self.label("لم يبدأ التسجيل بعد.", 15, True, self.col["muted"],
                           focusable=True, name="حالة التسجيل: لم يبدأ بعد")
        state.setStyleSheet(state_sheet(self.col["muted"]))
        lay.addWidget(state)
        clock = self.label("", 13, False, self.col["muted"], align_right=False)
        lay.addWidget(clock)
        start_btn = self.button("ابدأ التسجيل", lambda: toggle_record(), "primary",
                                big=True, tip="ابدأ تسجيل صوتك في الميكروفون")
        start_btn.setAccessibleDescription("ابدأ تسجيل صوتك، ثم اضغط إيقاف التسجيل لحفظه")
        stop_btn = self.button("إيقاف التسجيل", lambda: stop_record(), "accent",
                               big=True, tip="أوقف التسجيل واحفظ صوتك")
        stop_btn.setAccessibleDescription("أوقف التسجيل واحفظ ملف صوتك على الجهاز")
        stop_btn.setVisible(False)
        lay.addWidget(start_btn)
        lay.addWidget(stop_btn)
        lay.addWidget(self.hint(
            "نصيحة: اقرأ الجملة بصوت واضح وقريب من الميكروفون. "
            "أثناء التسجيل اضغط Esc لإيقافه وحفظه."))
        lay.addStretch(1)

        def say_instructions():
            self.announce(instruction)
            self.speak(instruction)

        def pick(i, talk=True):
            st["sent"] = i
            text = picks[i]
            chosen.setText("الجملة: %s" % text)
            chosen.setAccessibleName("الجملة المختارة: %s" % text)
            self.play_sound("positive")
            if talk:
                self.announce("اخترت الجملة: %s" % text)

        def set_state(text, color, name):
            state.setText(text)
            state.setStyleSheet(state_sheet(color))
            state.setAccessibleName("حالة التسجيل: " + name)
            self.announce(text)

        def stop_timer():
            if st["timer"] is not None:
                st["timer"].stop()
                st["timer"] = None

        def start_recording():
            self.speak_stop()                    # لا يُسجَّل صوت التطبيق نفسه
            rec = ana_recorder.make_recorder()
            st["rec"] = rec
            self.recorder = rec
            st["path"] = ana_recorder.new_path()
            ok, msg = rec.start(st["path"])
            if not ok:
                st["rec"] = None
                self.recorder = None
                set_state("تعذّر بدء التسجيل. %s" % msg, self.col["accent"],
                          "تعذّر البدء. %s" % msg)
                self.speak("تعذّر بدء التسجيل. %s" % msg)
                return
            st["phase"] = "recording"
            start_btn.setVisible(False)
            stop_btn.setVisible(True)
            clock.setText("0 ثانية")
            set_state("بدأ التسجيل الآن، تكلّم بصوت واضح ثم اضغط إيقاف التسجيل.",
                      self.col["accent"], "جاري التسجيل، تكلّم الآن")
            # لا نطق هنا إطلاقاً: صوت التطبيق يلتقطه الميكروفون فيفسد التسجيل،
            # وقارئ الشاشة يقرأ상태 التسجيل من شريط الحالة أصلاً.
            st["timer"] = QTimer(self)
            st["timer"].timeout.connect(tick)
            st["timer"].start(1000)
            self.link_tab_order(page)
            self.focus_first(stop_btn)

        def tick():
            rec = st["rec"]
            if rec is None or not rec.is_recording:
                return
            clock.setText("%d ثانية" % rec.seconds)
            if rec.seconds >= int(rec.max_seconds):
                stop_record()

        def toggle_record():
            if st["rec"] is not None and st["rec"].is_recording:
                stop_record()
            else:
                start_recording()

        def stop_record():
            rec = st["rec"]
            if rec is None or not rec.is_recording:
                return
            secs = rec.seconds
            ok, msg = rec.stop()
            stop_timer()
            st["phase"] = "done"
            self.recorder = None
            stop_btn.setVisible(False)
            start_btn.setVisible(False)
            if not ok:
                set_state("لم يُحفظ التسجيل. %s" % msg, self.col["accent"],
                          "لم يُحفظ. %s" % msg)
                self.speak("لم يحفظ التسجيل. %s" % msg)
                build_done_panel(0, None, secs)
                return
            clock.setText("%d ثانية" % secs)
            set_state("تم إيقاف التسجيل وحفظه بنجاح.", self.col["primary"], "تم الحفظ")
            self.speak("تم إيقاف التسجيل وحفظه بنجاح.")
            ana_recorder.keep_recent(os.path.dirname(st["path"]), "c7_", 10)
            if secs < 2:
                stars, praise = 1, "سجّلت قليلاً جداً، اقرأ الجملة كاملةً ثم أعد المحاولة."
            elif secs < 6:
                stars, praise = 2, "تسجيلك جيد، اقرأها مرة أخرى لتحصل على نجمة إضافية."
            else:
                stars, praise = 3, "رائع، تسجيلك كامل وواضح. أنت مذيع حقيقي."
            self.play_sound("applause" if stars == 3 else "positive")
            build_done_panel(stars, praise, secs)

        def build_done_panel(stars, praise, secs):
            if st["panel"] is not None:              # محاولة جديدة: لوحة نتيجة واحدة فقط
                lay.removeWidget(st["panel"])
                st["panel"].deleteLater()
                st["panel"] = None
            best = self.prog["per_challenge"].get("c7", 0)
            if stars > best:
                self.prog["per_challenge"]["c7"] = stars
                best = stars
                self.save()
            group = QGroupBox("نتيجة التسجيل")
            group.setFont(self.F(15, True))
            describe(group, "نتيجة تسجيلك", "نجومك في هذا التحدي، ثم زر المتابعة")
            gl = QVBoxLayout(group)
            if stars:
                where = "تم حفظ تسجيلك في الملف: %s" % st["path"]
                gl.addWidget(self.label(where, 13, False, self.col["muted"],
                                        focusable=True,
                                        name="موضع التسجيل: %s" % st["path"]))
                stars_txt = "%d من %d نجوم" % (stars, MAX_STARS)
                gl.addWidget(self.label("★" * stars, 30, True, self.col["gold"],
                                        align_right=False, focusable=True,
                                        name=stars_txt))
                gl.addWidget(self.label(praise, 16, True, self.col["primary"],
                                        focusable=True, name="مدح: %s" % praise))
                total = "نجومك في هذا التحدي %d من %d. مجموع نجومك %d من %d، والميدالية %s." % (
                    best, MAX_STARS, self.stars_total(), MAX_TOTAL, self.medal())
                gl.addWidget(self.label(total, 13, False, self.col["muted"],
                                        focusable=True, name=total))
                gl.addWidget(self.button("استمع إلى تسجيلك", lambda: play_back(),
                                         "neutral"))
            else:
                gl.addWidget(self.label("لم يكتمل التسجيل، جرّب مرة أخرى.", 15, True,
                                        focusable=True,
                                        name="لم يكتمل التسجيل، اختر إعادة المحاولة"))
            again = self.button("إعادة المحاولة", lambda: retry(), "primary", big=True)
            nxt = self.button("التالي", lambda: self.next_challenge("c7"), "gold", big=True)
            back = self.button("رجوع", lambda: self.show_screen("home"), "neutral", big=True)
            for b in (again, nxt, back):
                gl.addWidget(b)
            lay.addWidget(group)
            st["panel"] = group
            self.link_tab_order(page)
            if stars:
                head = ("نتيجة التسجيل. حصلت على %d من %d نجوم. %s استمع إلى تسجيلك. "
                        "المتابعة: إعادة المحاولة، أو التالي، أو رجوع."
                        % (stars, MAX_STARS, praise))
            else:
                head = "نتيجة التسجيل: لم يكتمل التسجيل. اختر إعادة المحاولة."
            page.a11y_head = head
            self.announce(head)
            self.focus_first(again)

        def play_back():
            ok = ana_recorder.play(st["path"])
            msg = "يجري الآن تشغيل تسجيلك." if ok else "تعذّر تشغيل التسجيل."
            self.announce(msg)
            self.speak(msg)

        def retry():
            stop_timer()
            st["rec"] = None
            st["phase"] = "idle"
            self.recorder = None
            if st["panel"] is not None:
                st["panel"].setVisible(False)
            start_btn.setVisible(True)
            stop_btn.setVisible(False)
            clock.clear()
            set_state("لم يبدأ التسجيل بعد. اضغط ابدأ التسجيل عندما تكون جاهزاً.",
                      self.col["muted"], "لم يبدأ بعد")
            page.a11y_head = (
                "الشاشة: تحدي المذيع الصغير. لم تبدأ محاولة جديدة بعد. "
                "الأزرار بالترتيب: %s، ابدأ التسجيل، إيقاف التسجيل بعد بدء التسجيل. %s"
                % (", ".join("جملة %d" % i for i in range(1, len(picks) + 1)), instruction))
            self.link_tab_order(page)
            self.focus_first(start_btn)

        def escape_action():
            if st["rec"] is not None and st["rec"].is_recording:
                stop_record()
                self.announce("أُوقف التسجيل بمفتاح Esc وحُفظ. "
                              "اضغط Esc مرة أخرى للرجوع.")
                return True
            return False

        page.escape_action = escape_action
        page.a11y_first = intro
        page.a11y_head = (
            "الشاشة: تحدي المذيع الصغير. اختر جملة، اقرأها بصوتك ثم سجّلها. "
            "الأزرار بالترتيب: %s، ابدأ التسجيل، إيقاف التسجيل بعد بدء التسجيل، "
            "وبعد الحفظ: إعادة المحاولة، التالي، رجوع. %s"
            % (", ".join("جملة %d" % i for i in range(1, len(picks) + 1)), instruction))
        pick(0, talk=False)
        return page

    def _page_guide(self):
        page, lay = self.new_page("دليل المذيع",
                                   "سبعة دروس قصيرة في التنفس، المخارج، النبرة، الوقف، السرعة، القواعد، وآداب المهنة.")
        lst = QListWidget()
        lst.setFont(self.F(13))
        lst.setMinimumHeight(150)
        describe(lst, "دروس دليل المذيع", "قائمة الدروس: استخدم الأسهم لاختيار الدرس")
        for t, _c in GUIDE_SECTIONS:
            item = QListWidgetItem(t)
            lst.addItem(item)
        viewer = self.reader_box("", "محتوى القسم — للقراءة فقط", 260)

        def render(*_a):
            row = lst.currentRow()
            if row < 0:
                return
            head_t, body = GUIDE_SECTIONS[row]
            viewer.setPlainText("%s\n\n%s" % (head_t, body))
            viewer.setAccessibleName("محتوى: %s — للقراءة فقط" % head_t)
            self.announce("دليل المذيع: %s" % head_t)

        lst.currentRowChanged.connect(render)
        lay.addWidget(lst)
        lay.addWidget(viewer)
        lay.addWidget(self.hint("استخدم الأسهم داخل قائمة الدروس، ثم Tab للانتقال إلى نص الدرس."))
        lay.addStretch(1)
        page.a11y_first = lst
        lst.setCurrentRow(0)
        return page

    def _page_settings(self):
        page, lay = self.new_page("الإعدادات",
                                   "تعديلات مريحة للعين والأذن: الاسم، حجم الخط، المظهر، والقراءة الصوتية.")
        name_edit = SubmitLineEdit(self.prog.get("name", ""))
        name_edit.setFont(self.F(15))
        name_edit.setPlaceholderText("اكتب اسمك هنا")
        describe(name_edit, "اسم المستخدم", "حقل نص لكتابة اسمك")
        lay.addWidget(self.label("اسم المستخدم", 13, True))
        lay.addWidget(name_edit)

        lay.addWidget(self.label("حجم الخط", 13, True))
        size_box = QComboBox()
        size_box.setFont(self.F(14))
        describe(size_box, "حجم الخط", "اختر حجم الخط: صغير، متوسط، كبير، كبير جداً")
        for lab in ("صغير", "متوسط", "كبير", "كبير جداً"):
            size_box.addItem(lab)
        size_box.setCurrentIndex(self.prog["scale_index"])
        lay.addWidget(size_box)

        theme_group = QGroupBox("المظهر والألوان")
        theme_group.setFont(self.F(13, True))
        describe(theme_group, "المظهر والألوان", "اختر المظهر: فاتح، داكن، تباين عالٍ")
        tg = QVBoxLayout(theme_group)
        self._theme_group = QButtonGroup(self)
        self._theme_buttons = {}
        for key, lab in (("light", "فاتح"), ("dark", "داكن"), ("hc", "تباين عالٍ")):
            rb = QRadioButton(lab)
            rb.setFont(self.F(13))
            describe(rb, "المظهر: %s" % lab)
            rb.setChecked(self.prog["theme"] == key)
            self._theme_group.addButton(rb)
            self._theme_buttons[key] = rb
            tg.addWidget(rb)
        lay.addWidget(theme_group)

        tts_cb = QCheckBox("القراءة الصوتية بالعربية (تنطق النصوص لك)")
        tts_cb.setFont(self.F(14))
        tts_cb.setChecked(bool(self.prog.get("tts")))
        describe(tts_cb, "القراءة الصوتية بالعربية", "فعّل أو عطّل نطق النصوص")
        lay.addWidget(tts_cb)

        lay.addWidget(self.label("سرعة القارئ الصوتي", 13, True))
        rate = QSlider(Qt.Orientation.Horizontal)
        rate.setRange(1, 10)
        rate.setValue(self.prog.get("rate", 6))
        rate.setSingleStep(1)
        rate.setPageStep(1)
        describe(rate, "سرعة القارئ الصوتي", "من 1 إلى 10")
        rate_lbl = self.label(str(rate.value()), 12, False, self.col["muted"], align_right=False)
        rate_lbl.setAccessibleName("قيمة سرعة القارئ الصوتي: %d من 10" % rate.value())
        rate.valueChanged.connect(lambda v: (rate_lbl.setText(str(v)),
                                             rate_lbl.setAccessibleName("قيمة سرعة القارئ الصوتي: %d من 10" % v),
                                             rate.setAccessibleDescription("القيمة الحالية %d من 10" % v),
                                             self.announce("سرعة القارئ الصوتي: %d من 10" % v)))
        lay.addWidget(rate)
        lay.addWidget(rate_lbl)

        def apply_save():
            self.prog["name"] = name_edit.text().strip()
            self.prog["scale_index"] = size_box.currentIndex()
            checked = [k for k, r in self._theme_buttons.items() if r.isChecked()]
            self.prog["theme"] = checked[0] if checked else self.prog["theme"]
            self.prog["tts"] = tts_cb.isChecked()
            self.prog["rate"] = rate.value()
            self.save()
            self.scale = SCALE_FACTORS[self.prog["scale_index"]]
            self.theme_key = self.prog["theme"]
            self.col = THEMES[self.theme_key]
            self.hc_bold = self.theme_key == "hc"
            self.apply_theme()
            self.rebuild()
            self.announce("تم حفظ الإعدادات")
            self.play_sound("positive")

        save_btn = self.button("حفظ الإعدادات", apply_save, "primary", big=True)
        name_edit.returnPressed.connect(apply_save)   # Enter داخل حقل الاسم يحفظ
        lay.addWidget(save_btn)

        def reset():
            self.prog["per_challenge"] = {}
            self.save()
            self.play_sound("end")
            self.rebuild()
            self.announce("تم تصفير نجوم التحديات")

        reset_btn = self.button("تصفير نجوم التحديات", reset, "accent")
        lay.addWidget(reset_btn)
        lay.addWidget(self.label("الإعدادات والنجوم تُحفظ على جهازك.", 12, False, self.col["muted"]))
        lay.addStretch(1)
        page.a11y_first = name_edit
        return page

    def _page_help(self):
        page, lay = self.new_page("التعليمات واختصارات لوحة المفاتيح",
                                   "كل مهام البرنامج ممكنة بلوحة المفاتيح وحدها.")
        viewer = self.reader_box(HELP_TEXT, "قائمة التعليمات والاختصارات — للقراءة فقط", 380)
        lay.addWidget(viewer)
        b = self.button("العودة إلى الرئيسية", lambda: self.show_screen("home"), "primary", big=True)
        lay.addWidget(b)
        lay.addStretch(1)
        page.a11y_first = viewer
        return page

    # --------------------------------------------------------------النتيجة
    def play_recording(self, path):
        """يعيد تشغيل تسجيل الطفل: نفس الملف الذي ذهب إلى التفريغ.

        لا نُنطق أي شيء قبل التشغيل ولا أثناءه. القارئ الصوتي هنا صوت
        مسجَّل (Hoda)، فكان يعلو على تسجيل الطفل فيسمع الطفل صوتاً ليس
        صوته، وهو ما هدم الثقة بزر «استمع». نُسكِت كل صوت آخر أولاً،
        وننتظر انتهاء تسجيل الطفل قبل أي كلام.
        """
        self.speak_stop()          # القارئ الصوتي يتوقف: لا يتداخل مع تسجيل الطفل
        ana_recorder.stop_all()   # ولا المؤثرات الصوتية
        ok = bool(path) and os.path.exists(path) and ana_recorder.play_blocking(path)
        if not ok:
            # الفشل وحده يستحق كلاماً، بعد أن تأكّدنا أن التشغيل انتهى.
            msg = "تعذّر تشغيل تسجيلك. جرّب مرة أخرى."
            self.announce(msg)
            self.speak(msg)
        return ok

    def saved_recording(self, challenge_id):
        """مسار آخر تسجيل صالح لهذا التحدي، أو None إن لم يوجد."""
        path = self.last_rec.get(challenge_id)
        if path and os.path.exists(path) and ana_recorder.wav_is_valid(path):
            return path
        return None

    def finish(self, challenge_id, stars, message):
        best = self.prog["per_challenge"].get(challenge_id, 0)
        if stars > best:
            self.prog["per_challenge"][challenge_id] = stars
            self.save()
        self.play_sound("applause" if stars else "end")
        self.show_result(challenge_id, stars, max(best, stars), message)

    def show_result(self, challenge_id, attempt, best, message):
        old = self.screens.pop("result", None)
        if old is not None:
            old.setParent(None)
            old.deleteLater()
        if challenge_id in self._challenge_ids():
            self.last_challenge = challenge_id
            self.result_for = challenge_id
        if self.current is not None and self.current != "result":
            self.prev.append(self.current)
            del self.prev[:-12]
        self.current = "result"
        has_rec = self.saved_recording(challenge_id) is not None
        rec_hint = " يمكنك الضغط على «استمع إلى تسجيلك» لإعادة سماع محاولتك. " if has_rec else ""
        head = ("نتيجة التحدي. %s حصلت على %d من %d نجوم. "
                "مجموع نجومك %d من %d، والميدالية: %s.%s"
                % (message, attempt, MAX_STARS, self.stars_total(), MAX_TOTAL,
                   self.medal(), rec_hint))
        page, lay = self.new_page("نتيجة التحدي", "أفضل نتيجة لك في هذا التحدي: %d نجوم" % best)
        msg_lb = self.label(message, 17, focusable=True, name="نتيجة: %s" % message)
        lay.addWidget(msg_lb)
        attempt_txt = "إنجاز هذا التحدي: %d نجوم" % attempt
        lay.addWidget(self.label(attempt_txt, 22, True, self.col["gold"],
                                 align_right=False, focusable=True, name=attempt_txt))
        stars_txt = "%d من %d نجوم" % (attempt, MAX_STARS)
        lay.addWidget(self.label("★" * attempt, 26, True, self.col["gold"], align_right=False,
                                 focusable=True, name=stars_txt))
        total_txt = "مجموع نجومك الآن: %d — %s" % (self.stars_total(), self.medal())
        lay.addWidget(self.label(total_txt, 14, focusable=True, name=total_txt))
        # بعد التسجيل صارت هناك نسخة مسموعة من المحاولة نفسها: نفس الملف
        # الذي ذهب إلى التفريغ، بلا إعادة ترميز ولا نسخة أخرى.
        rec_path = self.saved_recording(challenge_id)
        if rec_path:
            again_rec = self.button("استمع إلى تسجيلك",
                                    lambda: self.play_recording(rec_path), "gold",
                                    tip="استمع إلى تسجيلك المحفوظ في هذا التحدي")
            where = self.label("موضع التسجيل: %s" % rec_path, 12, False,
                               self.col["muted"], focusable=True,
                               name="موضع التسجيل: %s" % rec_path)
            lay.addWidget(again_rec)
            lay.addWidget(where)
        again = self.button("أعد التحدي", lambda: self.show_screen(challenge_id), "primary", big=True)
        nxt = self.button("التحدي التالي", lambda: self.next_challenge(challenge_id), "gold", big=True)
        home = self.button("العودة للرئيسية", lambda: self.show_screen("home"), "neutral")
        for b in (again, nxt, home):
            lay.addWidget(b)
        lay.addStretch(1)
        page.a11y_first = msg_lb
        page.a11y_head = head
        self.screens["result"] = page
        self.stack_layout.addWidget(page)
        self._attach_nav(page, "result")
        return self.activate(page, "result")

    def next_challenge(self, cid):
        ids = [c[0] for c in CHALLENGES]
        self.show_screen(ids[(ids.index(cid) + 1) % len(ids)])

    # --------------------------------------------------------------أوامر
    def announce(self, text, focus_it=False):
        """يعلن رسالة في المنطقة الحيّة (يراها قارئ الشاشة عند Tab وعند Event)."""
        text = text or ""
        if self.status.text() == text:
            # النص نفسه: نُعيد 설정ه كي يُرسَل حدث تغيّر الاسم لقارئ الشاشة
            self.status.clear()
        self.status.setText(text)
        try:
            hwnd = int(self.winId())
        except Exception:
            hwnd = 0
        notify_screen_reader(hwnd)
        if focus_it and text:
            self.status.setFocus(Qt.FocusReason.OtherFocusReason)

    def _is_recording(self):
        rec = getattr(self, "recorder", None)
        return rec is not None and rec.is_recording

    def describe_screen(self):
        msg = self.screen_title(self.current)
        if self.current == "home":
            msg += ". اختر تحدياً من الأزرار."
        elif self.current == "guide":
            msg += ". اختر درساً من قائمة الدروس ثم انتقل بمفتاح Tab لقراءة المادة."
        elif self.current == "settings":
            msg += ". عدّل الاسم وحجم الخط والمظهر والقراءة الصوتية."
        elif self.current == "result":
            msg += ". النتيجة معروضة أعلاه. اختر أعد التحدي أو التحدي التالي أو العودة للرئيسية."
        elif self.current == "c1":
            msg += (". اضغط ابدأ القراءة فيُفتح الميكروفون ويبدأ الوقت، اقرأ النشرة "
                    "بصوت مرتفع، ثم اضغط انتهيت من القراءة ليُحفظ صوتك ويُفرَّغ إلى نص. "
                    "عدد الكلمات يُحسب من تسجيلك أنت، ولا يُحسب من النص المكتوب. "
                    "إن لم يتوفّر محرّك تفريغ عربي على الجهاز فسيُذكر ذلك بوضوح "
                    "وستُحفظ مدّة قراءتك فقط.")
        elif self.current == "c7":
            msg += (". اختر جملة، اقرأها بصوت واضح، ثم اضغط Enter على زر ابدأ التسجيل،"
                    " وتكلّم في الميكروفون، ثم اضغط إيقاف التسجيل لحفظ صوتك."
                    " عند الانتهاء اختر إعادة المحاولة أو التالي أو رجوع.")
        elif self.current and self.current.startswith("c"):
            msg += ". اتبع التعليمات واضغط Enter أو مسافة على الأزرار."
        self.announce(msg, focus_it=True)
        if not self._is_recording():      # أثناء التسجيل لا يُتلى صوت التطبيق
            self.speak(msg)

    def go_back(self):
        # Esc يصل هنا من مفتاح القائمة «Esc» ومن مفتاح الهروب في النافذة،
        # فنسأل الصفحة أولاً: قد تكون لها مهمة قبل الرجوع (إيقاف التسجيل مثلاً).
        page = self.screens.get(self.current)
        hook = getattr(page, "escape_action", None) if page is not None else None
        if hook is not None and hook():
            return
        self.speak_stop()
        dest = self.prev.pop() if self.prev else "home"
        if dest == self.current:
            dest = "home"
        self.show_screen(dest)

    def save(self):
        if os.environ.get("ANOMODHI_NO_SAVE"):
            return
        try:
            os.makedirs(os.path.dirname(
                os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "ana_modhi")),
                exist_ok=True)
            from ana_data import PROGRESS_FILE
            with open(PROGRESS_FILE, "w", encoding="utf-8") as fh:
                json.dump(self.prog, fh, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def zoom(self, direction):
        idx = self.prog["scale_index"]
        idx = 1 if direction == 0 else max(0, min(len(SCALE_FACTORS) - 1, idx + direction))
        self.prog["scale_index"] = idx
        self.save()
        self.scale = SCALE_FACTORS[idx]
        self.rebuild()
        self.announce("حجم الخط: %s" % ("صغير", "متوسط", "كبير", "كبير جداً")[idx])

    def cycle_theme(self):
        order = ["light", "dark", "hc"]
        i = order.index(self.theme_key)
        self.prog["theme"] = order[(i + 1) % 3]
        self.theme_key = self.prog["theme"]
        self.col = THEMES[self.theme_key]
        self.hc_bold = self.theme_key == "hc"
        self.save()
        self.apply_theme()
        self.rebuild()
        self.announce("المظهر: %s" % {"light": "فاتح", "dark": "داكن", "hc": "تباين عالٍ"}[self.theme_key])

    def toggle_tts(self):
        self.prog["tts"] = not self.prog.get("tts")
        self.save()
        self.announce("القراءة الصوتية %s" % ("مُفعّلة" if self.prog["tts"] else "متوقفة"))
        if self.prog["tts"]:
            self.speak("تم تشغيل القراءة الصوتية")
            self.play_sound("positive")

    def apply_theme(self):
        c = self.col
        ring = FOCUS_RING
        on_primary = readable_on(c["primary"])
        self.setStyleSheet("""
            QWidget { background:%(bg)s; color:%(fg)s; font-family:'%(font)s'; }
            QLabel#appTitle { color:%(on_primary)s; font-size:%(t1)spx; }
            QWidget#header { background:%(primary)s; }
            QLabel#statusBar { color:%(on_primary)s; }
            QLabel#footer { color:%(muted)s; }
            QLabel#pageTitle { color:%(primary)s; }
            QLabel#pageSub { color:%(muted)s; }
            QLabel#hint { background:%(chips)s; color:%(fg)s; border-radius:10px; padding:10px; }
            QGroupBox { border:1px solid %(line)s; border-radius:10px; margin-top:14px; padding:10px; }
            QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top right;
                               left:12px; color:%(primary)s; }
            QListWidget, QTextEdit, QLineEdit, QComboBox, QSlider {
                background:%(card)s; color:%(fg)s; border:3px solid %(line)s;
                border-radius:10px; padding:6px; }
            QListWidget::item:selected { background:%(sel)s; color:%(fg)s; }
            QMenuBar { background:%(primary)s; color:%(on_primary)s; }
            QMenuBar::item { padding:6px 12px; border-radius:6px; }
            QMenuBar::item:selected, QMenuBar::item:focus { background:%(gold)s; color:%(on_gold)s; }
            QMenu { background:%(card)s; color:%(fg)s; }
            QMenu::item { padding:6px 22px; }
            QMenu::item:selected, QMenu::item:focus { background:%(sel)s; }
            QScrollBar:vertical { background:%(bg)s; width:14px; }
            QScrollBar::handle:vertical { background:%(line)s; border-radius:7px; }
            QSlider::groove:horizontal { height:8px; background:%(line)s; border-radius:4px; }
            QSlider::handle:horizontal { width:20px; margin:-6px 0; background:%(primary)s;
                                         border-radius:10px; }
            QSlider:focus::handle:horizontal { background:%(ring)s; }
            QCheckBox, QRadioButton { border:3px solid transparent; border-radius:6px; padding:4px; }
            QCheckBox:focus, QRadioButton:focus { border-color:%(ring)s; }
            QLineEdit:focus, QComboBox:focus, QSlider:focus, QListWidget:focus,
            QTextEdit:focus { border-color:%(ring)s; }
            QGroupBox:focus { border:3px solid %(ring)s; }
            QLabel:focus { border:3px solid %(ring)s; border-radius:10px; padding:2px; }
        """ % {
            "bg": c["bg"], "fg": c["fg"], "card": c["card"], "primary": c["primary"],
            "accent": c["accent"], "gold": c["gold"], "line": c["line"],
            "sel": c["sel"], "chips": c["chips"], "muted": c["muted"],
            "font": FONT_FAMILY, "t1": int(20 * self.scale), "ring": ring,
            "on_primary": on_primary, "on_gold": readable_on(c["gold"]),
        })

    def rebuild(self):
        """يعيد بناء الشاشات بعد تغيير الخط/المظهر مع الحفاظ على الشاشة الحالية."""
        current = self.current
        self._leave_recording()
        for w in self.screens.values():
            w.setParent(None)
            w.deleteLater()
        self.screens.clear()
        self.show_screen(current or "home")

    # --------------------------------------------------------------أحداث
    def keyPressEvent(self, e):
        key = e.key()
        if key == Qt.Key.Key_Escape:
            self.go_back()
            return
        if key == Qt.Key.Key_F2:
            self.describe_screen()
            return
        if key == Qt.Key.Key_F1:
            self.show_screen("help")
            return
        n = len(CHALLENGES)
        if (self.current == "home" and n <= 9
                and Qt.Key.Key_1 <= key <= Qt.Key.Key_0 + n):
            self.show_screen("c%d" % (key - Qt.Key.Key_0))
            return
        if key in (Qt.Key.Key_PageDown, Qt.Key.Key_PageUp, Qt.Key.Key_Home, Qt.Key.Key_End):
            focus = self.focusWidget()
            # لا نسرق المفاتيح من الحقول النصية الحقيقية
            if isinstance(focus, (QLineEdit, QTextEdit, QListWidget, QComboBox, QSlider)):
                return super().keyPressEvent(e)
            page = self.screens.get(self.current)
            if page is None:
                return super().keyPressEvent(e)
            bar = page.verticalScrollBar()
            if key == Qt.Key.Key_PageDown:
                bar.setValue(bar.value() + bar.pageStep())
            elif key == Qt.Key.Key_PageUp:
                bar.setValue(bar.value() - bar.pageStep())
            elif key == Qt.Key.Key_Home:
                bar.setValue(0)
            else:
                bar.setValue(bar.maximum())
            return
        super().keyPressEvent(e)

    def quit_app(self):
        self.speak_stop()
        self._leave_recording()
        if self.edge_worker is not None:
            self.edge_worker.shutdown()
        if self.tts_proc and self.tts_proc.stdin:
            try:
                self.tts_proc.stdin.write(b"EXIT\n")
                self.tts_proc.stdin.flush()
            except Exception:
                pass
        self.close()


# ------------------------------------------------------------------وضع الفحص
INTERACTIVE = (QPushButton, QLineEdit, QCheckBox, QRadioButton, QComboBox,
               QSlider, QListWidget, QTextEdit)


def tab_chain(win, start):
    """ترتيب Tab الفعلي: حلقة واحدة عبر العناصر المرئية القابلة للتركيز."""
    out, w = [], start
    for _ in range(400):
        w = w.nextInFocusChain()
        if w is start or w is None:
            break
        if w.focusPolicy() == NOFOCUS or not w.isVisible() or w.isWindow():
            continue
        out.append(w)
    return out


def a11y_role(w):
    """دور العنصر كما يقرؤه قارئ الشاشة (الفئات الفرعية تُحسب كأنها أصلها)."""
    if isinstance(w, QCheckBox):
        return "checkbox"
    if isinstance(w, QRadioButton):
        return "radio"
    if isinstance(w, QPushButton):
        return "button"
    if isinstance(w, QComboBox):
        return "combobox"
    if isinstance(w, QSlider):
        return "slider"
    if isinstance(w, QListWidget):
        return "list"
    if isinstance(w, QGroupBox):
        return "group"
    if isinstance(w, (QLineEdit, QTextEdit)):
        return "textbox"
    if isinstance(w, QLabel):
        return "text"
    return "other"


def describe_widget(w):
    cls = type(w).__name__
    text = ""
    if isinstance(w, (QLineEdit, QTextEdit)):
        text = w.toPlainText() if isinstance(w, QTextEdit) else w.text()
    elif isinstance(w, QComboBox):
        text = w.currentText()
    elif isinstance(w, (QPushButton, QLabel, QCheckBox, QRadioButton, QGroupBox)):
        text = w.text() if hasattr(w, "text") else w.title()
    return {
        "class": cls,
        "id": w.objectName(),
        "role": a11y_role(w),
        "name": w.accessibleName(),
        "description": w.accessibleDescription(),
        "text": text,
        "enabled": w.isEnabled(),
        "visible": w.isVisible(),
        "tabbable": w.focusPolicy() != NOFOCUS,
    }


def dump_accessibility(win, path, screens=None):
    """يكتب شجرة عناصر Qt مع أسماءها ودورها (ما يراه قارئ الشاشة)."""
    data = {"binding": BINDING, "window": win.windowTitle(), "screens": {}}
    for sid in (screens or [win.current]):
        win.show_screen(sid)
        QApplication.processEvents()   # ننفّذ نقل التركيز المؤجَّل قبل الفحص
        page = win.screens.get(sid)
        controls = [describe_widget(w) for w in win.focusables(page)] if page else []
        focus = win.focusWidget()
        data["screens"][sid] = {
            "status": win.status.text(),
            "head": getattr(page, "a11y_head", ""),
            "focus": describe_widget(focus) if isinstance(focus, QWidget) else None,
            "tabOrder": [describe_widget(w)["name"] or describe_widget(w)["text"]
                         for w in tab_chain(win, win.status)],
            "controls": controls,
        }
    menus = []
    for a in win.menuBar().actions():
        sub = []
        for sa in a.menu().actions() if a.menu() else []:
            if sa.isSeparator():
                continue
            sub.append({"text": sa.text().replace("&", ""),
                        "shortcut": sa.shortcut().toString()})
        menus.append({"text": a.text().replace("&", ""), "items": sub})
    data["menus"] = menus
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    return data


def main():
    if PROBE:
        probe_report()
        return
    if CHECK_STT:
        check_stt_report()
        return

    app = QApplication(sys.argv)
    app.setLayoutDirection(RTL)
    app.setApplicationName("أنا مذيع")
    win = AnaModhiQt()
    win.show()

    if DUMP:
        out = sys.argv[sys.argv.index("--dump-a11y") + 1]
        seq = ["home"] + [c[0] for c in CHALLENGES] + ["guide", "settings", "help"]

        def do_dump():
            dump_accessibility(win, out, screens=seq)
            app.quit()
        QTimer.singleShot(700, do_dump)
    elif SELFTEST:
        seq = ["home"] + [c[0] for c in CHALLENGES] + ["guide", "settings", "help"]
        state = {"i": 0}

        def step():
            if state["i"] < len(seq):
                win.show_screen(seq[state["i"]])
                state["i"] += 1
                QTimer.singleShot(300, step)
            else:
                app.quit()
        QTimer.singleShot(300, step)
    else:
        QTimer.singleShot(800, lambda: win.announce(
            "مرحباً بك في برنامج أنا مذيع. تنقّل بمفتاح Tab بين الخيارات، "
            "ونفّذ بمفتاح Enter أو المسافة، والعودة للخلف بمفتاح Esc."))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
