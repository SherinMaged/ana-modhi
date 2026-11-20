# -*- coding: utf-8 -*-
"""
تسجيل صوت الطفل — مسجّل ويندوز خفيف بلا أي مكتبة خارجية.

سبب عدم استخدام PyQt6.QtMultimedia: ربط PyQt 6.11 لا يعرض QtAudioInput.start
ولا QtAudioInput.open، فلا يمكن بدء الالتقاط من بايثون. لذلك نستخدم
واجهة ويندوز نفسها (winmm) عبر ctypes، بِمسارَين متكاملين:

  1) waveIn  (المسار الأساسي، واجهة قياسية على كل أجهزة ويندوز)
  2) waveaudio عبر MCI (احتياطي حين لا تصدّر نسخة ويندوز دالّتَي
     Preparer/Unprepare من winmm)

وكلاهما يفشل برسالة عربية واضحة بدل أن يتعطّل التطبيق، وواجهة
VoiceRecorder الموحّدة تُرجع دائماً (True, '') أو (False, سبب).

وضع الفحص الآلي: المتغيّر ANOMODHI_FAKE_RECORDER=1 يستبدل المسجّل بواحد
وهمي يكتب ملف WAV صالحاً بلا ميكروفون، ليجري الفحص على أي جهاز.
"""

import ctypes
import math
import os
import struct
import sys
import tempfile
import threading
import time
import wave
from ctypes import wintypes

SAMPLE_RATE = 16000        # هرتز: يكفي للكلام ويصغّر الملف
CHANNELS = 1
BITS = 16
BYTES_PER_SEC = SAMPLE_RATE * CHANNELS * BITS // 8
BLOCK_MS = 500             # حجم مخزن واحد في مسار waveIn
MAX_SECONDS = 30           # سقف أمان: تتوقف الواجهة عند بلوغه

# بعض تعريفات التسجيل (مثل Intel Smart Sound) ترفض إعادة إضافة مخزن بعد
# اكتماله (ترجع WAVERR_STILLPLAYING=34) فلا يتجاوز الالتقاط عدد المخازن
# الأولى. لذلك نخطّط المخازن مسبقاً لتغطية *كامل* المدة المسموح بها:
# 30 ثانية ÷ 0.5 = 60 مخزناً. بهذه الطريقة لا نحتاج إعادة إضافة إطلاقاً،
# ونحتفظ بمحاولة الإعادة لو كان التعريف يسمح بها.
BLOCKS = int(MAX_SECONDS * 1000 / BLOCK_MS) + 2      # 62

# تشخيص المطوّر: يكتب كل خطوة في ملف ولا يظهر أبداً في واجهة الأطفال.
DEBUG_RECORD = bool(os.environ.get("ANOMODHI_DEBUG_RECORD"))
TRACE_PATH = os.path.join(tempfile.gettempdir(), "ana_modhi_record.log")


def trace(step, detail=""):
    """يسجّل خطوة في سجل المطوّر فقط (لا يظهر في الواجهة أبداً)."""
    if not DEBUG_RECORD:
        return
    try:
        with open(TRACE_PATH, "a", encoding="utf-8") as fh:
            fh.write("%s  %-22s %s\n" % (time.strftime("%H:%M:%S"), step, detail))
    except OSError:
        pass


def trace_text():
    try:
        with open(TRACE_PATH, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""

WAVE_FORMAT_PCM = 1
CALLBACK_EVENT = 0x500000
# WIM_DATA هو المُرسِل القياسي لـ waveIn، لكن بعض تعريفات Windows
# (ومنها تعريفات Intel Smart Sound على ويندوز 11) تكتب في dwFlags القيمة
# 0x3 (WHDR_DONE | WHDR_RETURNED) بدل ذلك. سابقاً كنا نطلب 0x3D000000
# حصرياً، فتُهدر كل المخازن المكتملة ويخرج الملف صامتاً. لذلك نعتمد الآن
# بت WHDR_DONE (القيمة الدنيا المشتركة بين التعريفين) لا القيمة الكاملة.
WHDR_DONE = 0x00000001
WIM_DATA = 0x3D000000
# أي بت "انتهى" صالح:Mask يغطي كل الأشكال التي تعيدها تعريفات التعريفات
DONE_MASK = WIM_DATA | WHDR_DONE

MCI_ALIAS = "anarec"       # اسم جهاز MCI الحصري بالتسجيل

_WAVEIN_ERRORS = {
    0: "تم التسجيل.",
    1: "خطأ غير معروف من جهاز الصوت.",
    2: "لا يوجد ميكروفون متصل بالجهاز.",
    3: "الميكروفون مشغول الآن، أغلق البرامج الأخرى ثم أعد المحاولة.",
    4: "الميكروفون مشغول من تطبيق آخر، أغلقه ثم أعد المحاولة.",
    5: "تعذّر تشغيل محوّل الصوت في ويندوز.",
    6: "لا يوجد برنامج تشغيل للتسجيل الصوتي على هذا الجهاز.",
    7: "نفدت الذاكرة أثناء فتح الميكروفون.",
    8: "خطأ في جهاز الصوت، جرّب إعادة تشغيل الجهاز.",
    11: "الجهاز لا يدعم صيغة التسجيل المطلوبة.",
    32: "الجهاز لا يستجيب، أعد تشغيله ثم جرّب مجدداً.",
    64: "الميكروفون غير موجود أو غير موصول.",
    999: "خطأ غير معروف في التسجيل الصوتي.",
}

_MCI_HINTS = {
    259: "جهاز waveaudio مشغول الآن، أغلق البرامج الأخرى ثم أعد المحاولة.",
    261: "اسم ملف التسجيل غير صالح.",
    263: "تسجيل الصوت غير متاح في هذه النسخة من ويندوز.",
    270: "ويندوز رفض أمر التسجيل الصوتي.",
    273: "تعذّر فتح ملف التسجيل.",
    275: "لا يوجد جهاز تسجيل صوتي جاهز.",
    293: "الميكروفون مشغول من تطبيق آخر.",
    352: "لا يوجد ميكروفون متصل بالجهاز.",
}


# ------------------------------------------------------------------ أدوات
def _winmm():
    """winmm مع تعريفات أنواع صريحة.

    ctypes يمرّر الأعداد الصحيحة 32-bit افتراضياً، وقد يُفسِّر معرّف
    المقبض (HANDLE = مؤشر) كعدد صحيح فيقتطع أعلاه 32 بتة، بينما
    MMSYSERR_*fit-في-32-بت. تحديد الأنواع يمنع سلوكاً غير محدَّد.
    """
    win = ctypes.WinDLL("winmm")
    try:
        win.waveInOpen.restype = ctypes.c_uint
        win.waveInOpen.argtypes = [ctypes.POINTER(wintypes.HANDLE), wintypes.WORD,
                                   ctypes.POINTER(_WAVEFORMATEX), wintypes.DWORD,
                                   wintypes.DWORD, wintypes.DWORD]
        win.waveInClose.restype = ctypes.c_uint
        win.waveInClose.argtypes = [wintypes.HANDLE]
        win.waveInStart.restype = ctypes.c_uint
        win.waveInStart.argtypes = [wintypes.HANDLE]
        win.waveInStop.restype = ctypes.c_uint
        win.waveInStop.argtypes = [wintypes.HANDLE]
        win.waveInReset.restype = ctypes.c_uint
        win.waveInReset.argtypes = [wintypes.HANDLE]
        # الأسماء المصدَّرة فعلاً (انظر تعليق WaveInRecorder)
        win.waveInPrepareHeader.restype = ctypes.c_uint
        win.waveInPrepareHeader.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                            wintypes.DWORD]
        win.waveInUnprepareHeader.restype = ctypes.c_uint
        win.waveInUnprepareHeader.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                              wintypes.DWORD]
        win.waveInAddBuffer.restype = ctypes.c_uint
        win.waveInAddBuffer.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                        wintypes.DWORD]
        win.waveInGetNumDevs.restype = ctypes.c_uint
    except AttributeError:
        return None            # نسخة ويندوز ناقصة: نُبلغ عن ذلك بوضوح
    return win


def wave_error(code):
    return _WAVEIN_ERRORS.get(int(code), _WAVEIN_ERRORS[999])


def mci_error(code):
    return _MCI_HINTS.get(int(code), "تعذّر التسجيل الصوتي (رمز %d)." % int(code))


def _wav_header(pcm_len, rate=SAMPLE_RATE, channels=CHANNELS, bits=BITS):
    block = channels * bits // 8
    head = b"RIFF" + struct.pack("<I", 36 + pcm_len) + b"WAVE"
    head += b"fmt " + struct.pack("<IHHIIHH", 16, 1, channels, rate,
                                  rate * block, block, bits)
    return head + b"data" + struct.pack("<I", pcm_len)


def write_wav(path, pcm, rate=SAMPLE_RATE, channels=CHANNELS, bits=BITS):
    """يكتب ملف WAV قياسياً من بيانات PCM خام."""
    with open(path, "wb") as fh:
        fh.write(_wav_header(len(pcm), rate, channels, bits))
        fh.write(pcm)
    return path


def wav_seconds(path):
    """مدة ملف WAV بالثواني (0 إن تعذّرت قراءته)."""
    try:
        with wave.open(path, "rb") as w:
            return w.getnframes() / float(w.getframerate() or SAMPLE_RATE)
    except Exception:
        return 0.0


def play(path):
    """تشغيل ملف WAV مسجَّل بلا حواجز عبر MCI. يُرجع True عند قبول الطلب."""
    if not path or not os.path.exists(path):
        return False
    try:
        mci = ctypes.windll.winmm.mciSendStringW
        buf = ctypes.create_unicode_buffer(1024)
        mci("close play_rec", None, 0, 0)
        rc = mci('open "%s" alias play_rec type waveaudio' % path.replace('"', ""),
                 buf, 1024, 0)
        if rc != 0:                      # لا ندّعي التشغيل إن رفض الجهاز الملف
            return False
        return mci("play play_rec", None, 0, 0) == 0
    except Exception:
        return False


def play_blocking(path, timeout=None):
    """يشغّل تسجيل الطفل وينتظر انتهاءه فعلاً، ثم يُغلق الجهاز.

    play() غير حاجز: يعود فوراً بينما الملف ما زال مفتوحاً في MCI. لذلك
    كان أي صوت آخر (القارئ الصوتي) يبدأ فوق تسجيل الطفل، ويُمسَك الملف
    فلا يُحذف. هنا ننتظر وضع device became "not playing" قبل الإغلاق.
    """
    if not path or not os.path.exists(path):
        return False
    limit = timeout if timeout is not None else max(5.0, wav_seconds(path) + 4.0)
    try:
        mci = ctypes.windll.winmm.mciSendStringW
        buf = ctypes.create_unicode_buffer(1024)
        mci("close playblk", None, 0, 0)
        if mci('open "%s" alias playblk type waveaudio' % path.replace('"', ""),
               buf, 1024, 0) != 0:
            return False
        if mci("play playblk", None, 0, 0) != 0:
            mci("close playblk", None, 0, 0)
            return False
        deadline = time.time() + limit
        while time.time() < deadline:
            time.sleep(0.05)
            buf2 = ctypes.create_unicode_buffer(64)
            if mci("status playblk mode", buf2, 64, 0) != 0:
                break                     # الجهاز أُغلق: انتهى
            if "playing" not in buf2.value.lower():
                break
        mci("close playblk", None, 0, 0)
        return True
    except Exception:
        try:
            ctypes.windll.winmm.mciSendStringW("close playblk", None, 0, 0)
        except Exception:
            pass
        return False


def stop_all():
    """يوقف أي تشغيل صوتي جارٍ: مؤثرات، تسجيل، أو إعادة سماع."""
    try:
        mci = ctypes.windll.winmm.mciSendStringW
        for alias in ("sfx", "play_rec", "playblk"):
            mci("stop %s" % alias, None, 0, 0)
            mci("close %s" % alias, None, 0, 0)
    except Exception:
        pass


def recording_dir():
    """مجلد حفظ التسجيلات: داخل المشروع، أو في بيانات المستخدم إن تعذّر.

    في نسخة مجمَّدة (PyInstaller) يكون مجلد التطبيق هو مجلد فكّ مؤقّت
    يُمحى عند الإغلاق، فالتسجيلات فيه تضيع. لذلك نكتب مباشرةً في
    %APPDATA%\\ana_modhi\\recordings بدون أي مجلد بديل.
    """
    if getattr(sys, "frozen", False):
        alt = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                           "ana_modhi", "recordings")
        os.makedirs(alt, exist_ok=True)
        return alt
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "assets", "recordings")
    try:
        os.makedirs(base, exist_ok=True)
        probe = os.path.join(base, ".w")
        with open(probe, "wb") as fh:
            fh.write(b"0")
        os.remove(probe)
        return base
    except OSError:
        alt = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                           "ana_modhi", "recordings")
        os.makedirs(alt, exist_ok=True)
        return alt


def new_path(prefix="c7_"):
    """اسم ملف جديد للتسجيل الحالي، مسبق يحمل اسم التحدي."""
    stamp = time.strftime("%Y%m%d_%H%M%S")
    safe = "".join(ch for ch in str(prefix) if ch.isalnum() or ch in "_-") or "rec_"
    return os.path.join(recording_dir(), "%s%s.wav" % (safe, stamp))


def keep_recent(folder, prefix="c7_", keep=10):
    """يحتفظ بأحدث keep تسجيلاً فقط حتى لا تتراكم الملفات."""
    try:
        files = sorted((os.path.join(folder, f) for f in os.listdir(folder)
                        if f.startswith(prefix) and f.lower().endswith(".wav")),
                       key=os.path.getmtime, reverse=True)
        for old in files[keep:]:
            try:
                os.remove(old)
            except OSError:
                pass
    except OSError:
        pass


def _peak(pcm):
    """أعلى قيمة مطلقة في PCM 16-bit little-endian (0 إن كان الملف فارغاً)."""
    if not pcm:
        return 0
    import array
    data = array.array("h")
    usable = len(pcm) - (len(pcm) % 2)
    data.frombytes(pcm[:usable])
    return max((abs(v) for v in data), default=0)


# مستوى التسجيل الطبيعي: صوت الطفل قد يكون هادئاً أو بعيداً عن الميكروفون،
# ف انخفاض الذروة لا يعني "لا يوجد كلام" بل "يحتاج إلى رفع مستوى".
#
# الأرقام مقيسة: الكلام المفحوص كلام مسموع يقارب -20 إلى -14 dBFS عند
# RMS. الاختيار 3200 يقارب -20 dBFS: أعلى من الضجيج في الغرفة، ومع ذلك
# أقل من القصّ. القيمة القديمة 900 كانت تعني -31 dBFS، أي أن التسجيل كان
# يُحفظ هادئاً لدرجة لا تُسمع عند إعادة التشغيل.
TARGET_RMS = 3200          # مستوى RMS مستهدف لصوت مسموع (-20 dBFS)
MAX_GAIN = 60.0            # سقف الرفع: تكبير الضجيج الرقمي يولّد تشويشاً
# حد أدنى صغير جداً: ما دونه ضجيج رقمي خالص لا كلام. الحكم على وجود
# كلام منصوص يتكفّل به محرّك التفريغ، لا عتبة من عندنا قد ترفض طفلاً هادئاً.
MIN_RMS_FOR_GAIN = 3


def normalize_pcm(pcm):
    """
    يرفع مستوى التسجيل الهادئ تلقائياً قبل الحفظ.
    يحسب الذروة و RMS، ثم يضرب الإsamples حسب الحاجة. لا يعمل إن كان الصوت
    أصلاً بمستوى طبيعي، ولا إن كان صمتاً بلا أي إشارة فعلية.
    """
    if not pcm or len(pcm) % 2:
        return pcm, 1.0
    import array
    samples = array.array("h")
    samples.frombytes(pcm)
    if not samples:
        return pcm, 1.0
    peak = max((abs(v) for v in samples), default=0)
    if peak == 0:
        return pcm, 1.0
    total = 0
    for v in samples:
        total += v * v
    rms = (total / float(len(samples))) ** 0.5
    if rms < MIN_RMS_FOR_GAIN:
        # صمت حقيقي بلا كلام: لا نضخّمه.
        return pcm, 1.0
    # نحسب مقدار الرفع من مستوى RMS (متوسط الإشارة الكلي، لا أعلى عيّنة).
    # الاعتماد على الذروة وحدها خطأ: نقرة واحدة عالية تُقصّ الصوت وتُفقد
    # 나머ه، بينما الكلام الهادئ يحتاج رفعاً كبيراً.
    gain = 1.0
    if rms < TARGET_RMS:
        gain = max(gain, TARGET_RMS / max(1.0, rms))
    gain = min(gain, MAX_GAIN)
    if gain <= 1.05:
        return pcm, 1.0
    # نفترض أن عيّنة تعلو الحد دفعة واحدة (طرقعة بداية/نهاية)، ونضغط
    # الذروة بلطف (soft knee) قبل الرفع حتى لا تسقط الإشارة كلها.
    # نقيس "ذروة كلام" من مئين الـ99.5 بدل أعلى عيّنة على الإطلاق: طرقعة
    # واحدة عند بداية التسجيل (نقرة زر) كانت تُفسد حساب الرفع فتبقى
    # النتيجة بلا رفع، فتصبح صامتة عند التشغيل.
    step = max(1, len(samples) // 20000)
    mags = sorted(abs(v) for v in samples[::step])
    speech_peak = mags[int(len(mags) * 0.995)] if mags else 0
    if speech_peak > 0:
        # نترك مساحة فوق لذروة الكلام بعد الرفع؛ ما يتجاوز ذلك يُحدّ بلطف.
        gain = min(gain, 30000.0 / float(speech_peak))
    if gain <= 1.05:
        return pcm, 1.0
    out = array.array("h")
    for v in samples:
        x = v * gain
        if x > 32767.0:
            # حدّ ناعم أحادي الجانب: يقترب من الحد ولا يتجاوزه أبداً.
            x = 32767.0 - (32768.0 - (x - 32767.0)) % 32768.0
        elif x < -32768.0:
            x = -32768.0 + (32768.0 - (-32768.0 - x)) % 32768.0
        if x > 32767.0:
            x = 32767.0
        elif x < -32768.0:
            x = -32768.0
        out.append(int(x))
    import sys
    if sys.byteorder != "little":
        out.byteswap()
    return out.tobytes(), gain


def wav_is_valid(path):
    """هل الملف موجود ويحوي إطار WAV سليم المدة؟ (فحص تطويري)"""
    try:
        with wave.open(path, "rb") as w:
            frames, rate = w.getnframes(), w.getframerate()
            return bool(rate and frames > 0)
    except Exception:
        return False


def _silence(seconds, rate=SAMPLE_RATE):
    """PCM صامت بموجة خفيفة جداً: ملف صالح بلا تشويش مسموع."""
    n = int(rate * seconds)
    return b"".join(struct.pack("<h", int(600 * math.sin(2 * math.pi * 180 * i / rate)))
                    for i in range(n))


# ------------------------------------------------------- المسجّل: waveIn
class _WAVEFORMATEX(ctypes.Structure):
    _fields_ = [
        ("wFormatTag", wintypes.WORD), ("nChannels", wintypes.WORD),
        ("nSamplesPerSec", wintypes.DWORD), ("nAvgBytesPerSec", wintypes.DWORD),
        ("nBlockAlign", wintypes.WORD), ("wBitsPerSample", wintypes.WORD),
        ("cbSize", wintypes.WORD),
    ]


class _WAVEINBUFFER(ctypes.Structure):
    _fields_ = [
        ("lpData", ctypes.c_void_p), ("dwBufferLength", wintypes.DWORD),
        ("dwBytesReturned", wintypes.DWORD), ("dwUser", ctypes.c_size_t),
        ("dwFlags", wintypes.DWORD), ("dwLoops", ctypes.c_size_t),
    ]


class WaveInRecorder:
    """مسجّل عبر واجهة waveIn القياسية (المسار الأساسي).

    تصحيحان جوهريان في هذا المسار، مكتشفان على ويندوز 11 (بناء 26200):

      1) الدالتان waveInPrepareBuffer و waveInUnprepareBuffer *ليستا مصدَّرتين*
         أصلاً من winmm.dll — إنهما ماكرو في ترويسة mmioapi يسمّيان
         waveInPrepareHeader و waveInUnprepareHeader. لذلك كان الفحص
         (hasattr) يعطي False دائماً، فيسقط التطبيق إلى "غير متاح" وترا
         الميكروفون موجوداً. نستخدم الآن التسمّيتين المصدَّرتين فعلاً.
      2) يجب تمرير حجم المخزن (dwSize) إلى waveInPrepareHeader. تمرير 0
         يعيد MMSYSERR_NODRIVER(11) ويفشل التحضير بصمت.
    """

    name = "waveIn"

    def __init__(self, max_seconds=MAX_SECONDS):
        self.max_seconds = float(max_seconds)
        self._win = None
        self._handle = None
        self._fmt = _WAVEFORMATEX(WAVE_FORMAT_PCM, CHANNELS, SAMPLE_RATE,
                                  BYTES_PER_SEC, CHANNELS * BITS // 8, BITS, 0)
        self._blocks = []
        self._pcm = bytearray()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._t0 = 0.0
        self._path = None
        self._duration = 0.0
        self._error = None
        self._block_size = 0
        self._readd_refused = False   # تعريف يرفض إعادة الإضافة
        self._trace = []              # تشخيص مطوّر فقط (DEBUG_RECORD)

    def probe(self):
        """هل|winmm| يصدّر دالّتَي تحضير المخازن بالاسم الصحيح؟

        نفحص الأسماء المصدَّرة (Header لا Buffer) ونتحقق أن الجهاز نفسه
        يقبل صيغتنا بفتحه وإغلاقه، حتى لا نُعلن "متاح" ثم نفشل لاحقاً.
        """
        try:
            win = _winmm()
            if win is None:
                return False
            if not (hasattr(win, "waveInPrepareHeader")
                    and hasattr(win, "waveInUnprepareHeader")):
                return False
            if win.waveInGetNumDevs() < 1:
                return False
            fmt = _WAVEFORMATEX(WAVE_FORMAT_PCM, CHANNELS, SAMPLE_RATE,
                                BYTES_PER_SEC, CHANNELS * BITS // 8, BITS, 0)
            handle = wintypes.HANDLE()
            rc = win.waveInOpen(ctypes.byref(handle), 0, ctypes.byref(fmt),
                                0, CALLBACK_EVENT, 0)
            if rc != 0:
                return False
            win.waveInClose(handle)
            return True
        except Exception:
            return False

    @property
    def is_recording(self):
        return self._thread is not None and self._thread.is_alive()

    def elapsed(self):
        if self._t0:
            if self.is_recording:
                return min(time.monotonic() - self._t0, self.max_seconds)
            return self._duration
        return 0.0

    @property
    def seconds(self):
        return int(round(self.elapsed()))

    def start(self, path):
        if self.is_recording:
            return False, "التسجيل جارٍ بالفعل."
        self._pcm = bytearray()
        self._error = None
        self._duration = 0.0
        self._path = path
        self._stop.clear()
        self._blocks = []
        self._readd_refused = False
        trace("start.begin", "path=%s" % path)
        try:
            win = _winmm()
            if win is None:
                return self._fail("start", "winmm unavailable")
            self._win = win
            handle = wintypes.HANDLE()
            rc = win.waveInOpen(ctypes.byref(handle), 0, ctypes.byref(self._fmt),
                                0, CALLBACK_EVENT, 0)
            trace("start.waveInOpen", "rc=%d" % rc)
            if rc != 0:
                self._win = None
                return False, wave_error(rc)
            self._handle = handle
            self._block_size = int(BYTES_PER_SEC * BLOCK_MS / 1000) or 2
            for i in range(BLOCKS):
                buf = ctypes.create_string_buffer(self._block_size)
                wib = _WAVEINBUFFER(ctypes.cast(buf, ctypes.c_void_p).value,
                                    self._block_size, 0, i, 0, 0)
                self._blocks.append((wib, buf))
                # dwSize إلزامي: تمرير 0 يعيد MMSYSERR_NODRIVER(11).
                rc = win.waveInPrepareHeader(
                    handle, ctypes.cast(ctypes.byref(wib), ctypes.c_void_p),
                    self._block_size)
                if rc != 0:
                    trace("start.prepare[%d]" % i, "rc=%d" % rc)
                    self._close()
                    return False, wave_error(rc)
                rc = win.waveInAddBuffer(
                    handle, ctypes.cast(ctypes.byref(wib), ctypes.c_void_p),
                    self._block_size)
                if rc != 0:
                    trace("start.addBuffer[%d]" % i, "rc=%d" % rc)
                    self._close()
                    return False, wave_error(rc)
            rc = win.waveInStart(handle)
            if rc != 0:
                trace("start.waveInStart", "rc=%d" % rc)
                self._close()
                return False, wave_error(rc)
            self._t0 = time.monotonic()
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
            trace("start.ok", "blocks=%d block_size=%d cover=%.1fs"
                  % (len(self._blocks), self._block_size,
                     len(self._blocks) * self._block_size / float(BYTES_PER_SEC)))
            return True, ""
        except Exception as exc:
            self._close()
            return self._fail("start.exception", "%s (%s)" % (wave_error(999), exc))

    def _fail(self, step, detail):
        trace(step, detail)
        self._trace.append("%s: %s" % (step, detail))
        return False, detail

    def _loop(self):
        win, handle = self._win, self._handle
        collected = 0
        try:
            # السقف الزمني تفرضه الواجهة عند التدقيق كل ثانية، لا هذا الخيط:
            # لو توقّف الخيط هنا وحده لبقي الميكروفون مفتوحاً بلا حفظ.
            while not self._stop.is_set():
                for wib, _buf in self._blocks:
                    if wib.dwFlags & DONE_MASK:
                        got = int(wib.dwBytesReturned)
                        if got > 0:
                            collected += got
                            with self._lock:
                                self._pcm += ctypes.string_at(wib.lpData, got)
                        wib.dwFlags = 0
                        wib.dwBytesReturned = 0
                        # إعادة الإضافة اختيارية: نجرّبها، وإن رفضها التعريف
                        # فنكتفي بما خطّطنا له مسبقاً.
                        rc = win.waveInAddBuffer(
                            handle, ctypes.cast(ctypes.byref(wib), ctypes.c_void_p),
                            self._block_size)
                        if rc != 0 and not self._readd_refused:
                            self._readd_refused = True
                            trace("loop.readd_refused", "rc=%d" % rc)
                self._stop.wait(0.02)
        except Exception as exc:
            self._error = "%s (%s)" % (wave_error(999), exc)
            trace("loop.exception", self._error)
        finally:
            trace("loop.end", "collected=%d bytes" % collected)
            self._close()

    def stop(self):
        """يوقف التسجيل ويحفظ WAV. يُرجع (نجاح, سبب) ويشخّص كل خطوة."""
        if self._thread is None:
            trace("stop.none", "no active thread")
            return False, "لا يوجد تسجيل جارٍ."
        self._stop.set()
        thread = self._thread
        thread.join(timeout=6.0)
        self._thread = None
        if thread.is_alive():
            # لم ينتهِ الالتقاط: لا نكتب WAV ناقصاً ولا نُبلغ نجاحاً كاذباً.
            trace("stop.timeout", "capture thread still running")
            return False, "توقّف خيط الالتقاط قبل انتهاء القراءة. حاول مجدداً."
        if self._error:
            trace("stop.error", self._error)
            return False, self._error
        with self._lock:
            pcm = bytes(self._pcm)
        trace("stop.pcm", "%d bytes" % len(pcm))
        if not pcm:
            # لا بايت واحد: هذه حالة فشل حقيقية، لا "صوت هادئ".
            return self._fail("stop.no_pcm", "لم يصل أي صوت من الميكروفون.")
        # ملاحظة مقصودة: لا نرفض التسجيل لأن صوته "هادئ". رفع مستوى هادئ
        # (طفل بعيد عن الميكروفون، أو ميكروفون ضعيف الكسب) أمر طبيعي، والحكم
        # على وجود كلام منصوص يتكفّل به محرّك التفريغ نفسه — لا عتبة من عندنا.
        peak_before = _peak(pcm)
        pcm, gain = normalize_pcm(pcm)
        trace("stop.peak", "%d -> %d (gain x%.1f)" % (peak_before, _peak(pcm), gain))
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            write_wav(self._path, pcm)
        except Exception as exc:
            return self._fail("stop.write", "تعذّر حفظ التسجيل: %s" % exc)
        self._duration = len(pcm) / float(BYTES_PER_SEC)
        if not os.path.exists(self._path):
            return self._fail("stop.missing", "لم يُنشأ ملف التسجيل.")
        size = os.path.getsize(self._path)
        if size <= 44:
            return self._fail("stop.empty", "ملف التسجيل فارغ.")
        trace("stop.saved", "%s (%d bytes, %.2fs)"
              % (self._path, size, self._duration))
        return True, ""

    def cancel(self):
        if self._thread is not None:
            self._stop.set()
            self._thread.join(timeout=6.0)
            self._thread = None
        else:
            self._close()
        self._pcm = bytearray()
        return True

    def _close(self):
        win, handle = self._win, self._handle
        if win is None or handle is None:
            self._blocks = []
            return
        for call in ("waveInReset", "waveInStop"):
            try:
                getattr(win, call)(handle)
            except Exception:
                pass
        for wib, _buf in self._blocks:
            try:
                win.waveInUnprepareHeader(
                    handle, ctypes.cast(ctypes.byref(wib), ctypes.c_void_p),
                    self._block_size)
            except Exception:
                pass
        try:
            win.waveInClose(handle)
        except Exception:
            pass
        self._blocks = []
        self._handle = None
        self._win = None


# ------------------------------------------------------ المسجّل: MCI
class MciRecorder:
    """مسجّل عبر جهاز waveaudio في MCI (احتياطي)."""

    name = "MCI"

    def __init__(self, max_seconds=MAX_SECONDS):
        self.max_seconds = float(max_seconds)
        self._busy = False
        self._path = None
        self._t0 = 0.0
        self._duration = 0.0

    def _mci(self, cmd):
        buf = ctypes.create_unicode_buffer(1024)
        rc = ctypes.windll.winmm.mciSendStringW(cmd, buf, 1024, 0)
        return rc, buf.value

    def probe(self):
        path = os.path.join(tempfile.gettempdir(), "ana_modhi_probe.wav")
        try:
            self._mci("close %s" % MCI_ALIAS)
            rc, _ = self._mci('open "%s" alias %s new type waveaudio'
                              % (path, MCI_ALIAS))
            self._mci("close %s" % MCI_ALIAS)
            if os.path.exists(path):
                os.remove(path)
            return rc == 0
        except Exception:
            return False

    @property
    def is_recording(self):
        return self._busy

    def elapsed(self):
        if not self._t0:
            return 0.0
        if self._busy:
            return min(time.monotonic() - self._t0, self.max_seconds)
        return self._duration

    @property
    def seconds(self):
        return int(round(self.elapsed()))

    def start(self, path):
        if self._busy:
            return False, "التسجيل جارٍ بالفعل."
        self._path = path
        self._duration = 0.0
        self._mci("close %s" % MCI_ALIAS)
        rc, _ = self._mci('open "%s" alias %s new type waveaudio'
                          % (path.replace('"', ""), MCI_ALIAS))
        if rc != 0:
            return False, mci_error(rc)
        for cmd, val in (("format tag", WAVE_FORMAT_PCM), ("samplespersec", SAMPLE_RATE),
                         ("bitspersample", BITS), ("channels", CHANNELS),
                         ("time limit", int(self.max_seconds * 1000))):
            rc, _ = self._mci("set %s %s %d" % (MCI_ALIAS, cmd, val))
            if rc != 0:
                self._mci("close %s" % MCI_ALIAS)
                return False, mci_error(rc)
        rc, _ = self._mci("record %s" % MCI_ALIAS)
        if rc != 0:
            self._mci("close %s" % MCI_ALIAS)
            return False, mci_error(rc)
        self._busy = True
        self._t0 = time.monotonic()
        return True, ""

    def stop(self):
        if not self._busy:
            return False, "لا يوجد تسجيل جارٍ."
        self._busy = False
        self._mci("stop %s" % MCI_ALIAS)
        self._mci("close %s" % MCI_ALIAS)
        secs = wav_seconds(self._path)
        if secs <= 0:
            return False, ("لم يصل أي صوت. تأكد من توصيل الميكروفون "
                           "ثم حاول مجدداً.")
        self._duration = secs
        if not (os.path.exists(self._path) and os.path.getsize(self._path) > 44):
            return False, "تعذّر تأكيد حفظ التسجيل على القرص."
        return True, ""

    def cancel(self):
        if self._busy:
            self._busy = False
            self._mci("stop %s" % MCI_ALIAS)
        self._mci("close %s" % MCI_ALIAS)
        if self._path and os.path.exists(self._path):
            try:
                os.remove(self._path)
            except OSError:
                pass
        return True


# ------------------------------------------------ المسجّل الوهمي للاختبار
class FakeRecorder:
    """مسجّل بلا ميكروفون: يكتب ملف WAV صالحاً. للاختبار الآلي فقط."""

    name = "اختبار"

    def __init__(self, max_seconds=MAX_SECONDS):
        self.max_seconds = float(max_seconds)
        try:
            self.fake_seconds = float(os.environ.get("ANOMODHI_FAKE_SECONDS", "7"))
        except ValueError:
            self.fake_seconds = 7.0
        self._path = None
        self._duration = 0.0
        self._busy = False

    def probe(self):
        return True

    @property
    def is_recording(self):
        return self._busy

    def elapsed(self):
        return self._duration if self._duration else self.fake_seconds

    @property
    def seconds(self):
        return int(round(self.elapsed()))

    def start(self, path):
        if self._busy:
            return False, "التسجيل جارٍ بالفعل."
        self._path = path
        self._duration = 0.0
        self._busy = True
        return True, ""

    def stop(self):
        if not self._busy:
            return False, "لا يوجد تسجيل جارٍ."
        self._busy = False
        self._duration = self.fake_seconds
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            write_wav(self._path, _silence(self.fake_seconds))
        except Exception as exc:
            return False, "تعذّر حفظ التسجيل: %s" % exc
        if not (os.path.exists(self._path) and os.path.getsize(self._path) > 44):
            return False, "تعذّر تأكيد حفظ التسجيل على القرص."
        return True, ""

    def cancel(self):
        self._busy = False
        self._duration = 0.0
        return True


# ------------------------------------------ المسجّل غير المتاح (رسالة فقط)
class UnavailableRecorder:
    """لا ميكروفون/لا واجهة تسجيل: يشرح السبب بأمان بدل أن يفشل صامتاً."""

    name = "غير متاح"

    def __init__(self, reason="التسجيل الصوتي غير متاح على هذا الجهاز.",
                 max_seconds=MAX_SECONDS):
        self.reason = reason
        self.max_seconds = float(max_seconds)
        self._duration = 0.0

    def probe(self):
        return False

    @property
    def is_recording(self):
        return False

    def elapsed(self):
        return 0.0

    @property
    def seconds(self):
        return 0

    def start(self, path):
        return False, self.reason

    def stop(self):
        return False, self.reason

    def cancel(self):
        return True


def make_recorder(max_seconds=MAX_SECONDS):
    """أفضل مسجّل متاح على هذا الجهاز."""
    if os.environ.get("ANOMODHI_FAKE_RECORDER"):
        return FakeRecorder(max_seconds)
    if os.name != "nt":
        return UnavailableRecorder("تسجيل الصوت متاح على ويندوز فقط.", max_seconds)
    for cls, reason in ((WaveInRecorder, "واجهة التسجيل الصوتي غير متاحة في هذه النسخة من ويندوز."),
                        (MciRecorder, "لا يوجد جهاز تسجيل صوتي (ميكروفون) في هذا الجهاز.")):
        try:
            rec = cls(max_seconds)
            if rec.probe():
                return rec
        except Exception:
            pass
    return UnavailableRecorder(reason, max_seconds)
