# -*- coding: utf-8 -*-
"""
تفريغ تسجيل الطفل إلى نص عربي — محرّك حقيقي واحد فقط، بلا أي نص وهمي.

لماذا هذا الملف؟ لأن النسخة السابقة كانت تحسب عدد الكلمات من *نص النشرة
المكتوب على الشاشة*، لا من كلام الطفل، فكان الرقم المُعرض خطأً تماماً.

قاعدة هذا الملف: لا يُختلق نص أبداً.
  - إن توفّر محرّك حقيقي، يُرجع نصّاً مُفرَّغاً من ملف تسجيل الطفل.
  - إن لم يتوفّر محرّك (أو فشل، أو لم يسمع كلاماً)، تُرجع ok=False ونصاً
    فارغاً ورسالة عربية تشرح السبب، ولا يُحسب أي عدد كلمات من مصدر آخر.

المحرّكات المدعومة بالترتيب:
  1) faster-whisper داخل بيئة افتراضية منفصلة (worker، والموصى به)
  2) faster-whisper مثبّت في بايثون النظام نفسه
  3) openai-whisper   (نفس النموذج لكن أبطأ)
  4) vosk             (خفيف وسريع، ويحتاج نموذج عربي صريح عبر مسار النموذج)

اللغة مثبّتة على العربية دائماً: LANGUAGE = "ar".
لا نستخدم System.Speech ولا SAPI لأن دعم العربية فيهما غير موثوق.
"""

import atexit
import os
import re
import subprocess
import sys
import threading
import time
import wave
from concurrent.futures import ThreadPoolExecutor

LANGUAGE = "ar"                                   # لا تُغيَّر: التطبيق عربي
LANGUAGE_TAG = "ar"                               # Whisper
AZURE_TAG = "ar-SA"                               # مرجع لـ Azure/Google إن استُعملا لاحقاً
# النموذج الافتراضي "small": اختبرناه على تسجيل حقيقي من ميكروفون طفل، فكان
# "base" يعطي صفر كلمات و"small" تعرّف على الكلام. صوت الطفل قريب من
# الميكروفون وبيئته أعلى ضوضاء من صوت استوديو، فيحتاج نموذجاً أدقّ.
# يمكن التغيير عبر ANOMODHI_STT_MODEL.
MODEL = os.environ.get("ANOMODHI_STT_MODEL", "small")   # tiny/small/base/medium
MIN_SECONDS = 0.4                                 # أقصر تسجيل مقبول
TIMEOUT_NOTE = "قد يستغرق التفريرغ أول مرة بضع ثوانٍ لتحميل النموذج."
# المهلة سخوة عمداً: أول تشغيل قد ينزّل النموذج (~150 ميغابايت) على اتصال بطيء،
# والواجهة تعرض «جارٍ تفريغ تسجيلك» طوال الوقت فلا يبدو التطبيق معلّقاً.
WORKER_TIMEOUT = float(os.environ.get("ANOMODHI_STT_TIMEOUT", "900"))

_PUNCT = re.compile(r"[^0-9A-Za-z\u0600-\u06FF\u0750-\u077F]+")
_ARABIC_LETTER = re.compile(r"[ء-يa-zA-Z]")
_TASHKEEL = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u0640\u200c\u200f\u0643]")

_CACHE = {}
_LOCK = threading.Lock()
EXECUTOR = ThreadPoolExecutor(max_workers=1,
                              thread_name_prefix="ana-stt")
_WORKER_LOCK = threading.Lock()
_WORKER = None


# --------------------------------------------------------- عامل venv منفصل
WORKER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "stt_worker.py")


def _default_venv_python():
    """مسار بايثون بيئة افتراضية افتراضية بجانب بيانات التطبيق."""
    local = os.environ.get("LOCALAPPDATA", "")
    if not local:
        return ""
    return os.path.join(local, "ana_modhi", "stt-venv", "Scripts", "python.exe")


def worker_python():
    """بايثون بيئة العامل، أو نص فارغ إن لم يوجد (ولا نبحث على الإنترنت)."""
    if os.environ.get("ANOMODHI_STT_NO_WORKER"):
        return ""
    for candidate in (os.environ.get("ANOMODHI_STT_PYTHON", "").strip(),
                      _default_venv_python()):
        if candidate and os.path.isfile(candidate):
            return candidate
    return ""


def worker_available():
    return bool(worker_python()) and os.path.isfile(WORKER_SCRIPT)


def _worker_stop():
    global _WORKER
    proc = _WORKER
    _WORKER = None
    if proc is None:
        return
    try:
        proc.stdin.write('{"cmd": "quit"}\n')
        proc.stdin.flush()
        proc.wait(timeout=3)
    except Exception:
        pass
    try:
        if proc.poll() is None:
            proc.kill()
    except Exception:
        pass


atexit.register(_worker_stop)


def _worker_start():
    """يشغّل العامل مرة واحدة ويحافظ عليه محمّلاً في الذاكرة."""
    global _WORKER
    if _WORKER is not None and _WORKER.poll() is None:
        return _WORKER
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"       # العربية لا تتلف في الأنبوب
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONWARNINGS"] = "ignore"
    env["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    env["TOKENIZERS_PARALLELISM"] = "false"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    _WORKER = subprocess.Popen(
        [worker_python(), "-u", WORKER_SCRIPT],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,          # تحذيرات المكتبة لا تلمس stdout
        text=True, encoding="utf-8", env=env, bufsize=1, creationflags=flags)
    return _WORKER


def _worker_request(payload, timeout=None):
    """يرسل طلباً للعامل وينتظر جوابه، ويقتل العملية إن تعطّلت."""
    timeout = float(timeout or WORKER_TIMEOUT)
    with _WORKER_LOCK:
        proc = _worker_start()
        box = {}

        def reader():
            try:
                box["line"] = proc.stdout.readline()
            except Exception as exc:
                box["error"] = str(exc)

        thread = threading.Thread(target=reader, name="ana-stt-read")
        thread.daemon = True
        thread.start()
        proc.stdin.write(json_dumps(payload) + "\n")
        proc.stdin.flush()
        thread.join(timeout)
        if thread.is_alive():
            _worker_stop()
            raise TimeoutError("تجاوز التفريغ %.0f ثانية" % timeout)
        if "line" not in box:
            _worker_stop()
            raise RuntimeError(box.get("error") or "انقطع جواب عامل التفريغ.")
        line = (box.get("line") or "").strip()
        if not line:
            _worker_stop()
            raise RuntimeError("توقّف عامل التفريغ دون جواب.")
        import json
        return json.loads(line)


def json_dumps(payload):
    import json
    return json.dumps(payload, ensure_ascii=False)


# ------------------------------------------------------------------ عدّاد الكلمات
def normalize(text):
    """ينظّف النص قبل العدّ: يحذف التشكيل والتطويل وعلامات الوقف."""
    if not text:
        return ""
    out = []
    for token in str(text).replace("\n", " ").split():
        token = _TASHKEEL.sub("", token)
        token = _PUNCT.sub(" ", token)
        out.extend(t for t in token.split() if _ARABIC_LETTER.search(t))
    return " ".join(out)


def word_count(text):
    """عدد الكلمات من نص مُفرَّغ فعلياً فقط، ولا يُحسب من أي مصدر آخر."""
    return len(normalize(text).split())


def words_phrase(n):
    """صياغة عربية سليمة للعدد: 1 كلمة، 2 كلمتان، 3-10 كلمات، 11+ كلمة."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        return "لم تُفرَّغ أي كلمة"
    if n == 1:
        return "كلمة واحدة"
    if n == 2:
        return "كلمتان"
    if 3 <= n <= 10:
        return "%d كلمات" % n
    return "%d كلمة" % n


def words_per_minute(words, seconds):
    """كلمة/دقيقة مع حماية من القسمة على وقت شبه معدوم."""
    try:
        secs = float(seconds)
    except (TypeError, ValueError):
        return 0
    if words <= 0 or secs < MIN_SECONDS:
        return 0
    return int(round(float(words) / max(secs / 60.0, MIN_SECONDS / 60.0)))


# ------------------------------------------------------------- محرّكات التفريغ
def _load_faster_whisper(model):
    key = ("faster_whisper", model)
    with _LOCK:
        if key not in _CACHE:
            from faster_whisper import WhisperModel
            _CACHE[key] = WhisperModel(model, device="cpu", compute_type="int8")
    return _CACHE[key]


def _run_faster_whisper(path, model, language):
    engine = _load_faster_whisper(model)
    segments, _info = engine.transcribe(
        path, language=language, task="transcribe", beam_size=5,
        vad_filter=True, condition_on_previous_text=False)
    return " ".join(s.text for s in segments).strip()


def _run_faster_whisper_worker(path, model, language):
    """يفرّغ عبر العملية المنفصلة داخل بيئة venv، بلا تجميد الواجهة."""
    answer = _worker_request({"cmd": "transcribe", "path": path,
                              "model": model, "language": language})
    if not answer.get("ok"):
        raise RuntimeError(answer.get("error") or "فشل التفريغ في بيئة منفصلة.")
    return (answer.get("text") or "").strip()


def _load_openai_whisper(model):
    key = ("openai_whisper", model)
    with _LOCK:
        if key not in _CACHE:
            import whisper
            _CACHE[key] = whisper.load_model(model)
    return _CACHE[key]


def _run_openai_whisper(path, model, language):
    engine = _load_openai_whisper(model)
    out = engine.transcribe(path, language=language, fp16=False,
                            task="transcribe")
    return (out or {}).get("text", "").strip()


VOSK_MODEL_NAME = "vosk-model-ar-mgb2-0.4"


def _vosk_model_dir():
    """مسار نموذج vosk العربي، أو نص فارغ إن لم يُوجد.

    بالترتيب: المتغيّر البيئي، ثم مجلد beside التطبيق (حزمة مثبّتة أو محمولة)،
    ثم نسبةً لجذر الحزمة عند التجميد، ثم %APPDATA% للنسخة المجمَّدة.
    """
    path = os.environ.get("ANOMODHI_VOSK_MODEL", "").strip()
    if path and os.path.isdir(path):
        return path
    roots = []
    if getattr(sys, "frozen", False):
        roots.append(os.path.dirname(os.path.abspath(sys.executable)))
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            roots.append(meipass)
    else:
        roots.append(os.path.dirname(os.path.abspath(__file__)))
    roots.append(os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                              "ana_modhi"))
    for root in roots:
        for rel in (os.path.join("vosk", VOSK_MODEL_NAME), VOSK_MODEL_NAME):
            cand = os.path.join(root, rel)
            if os.path.isdir(cand):
                return cand
    return ""


def _run_vosk(path, _model, language):
    """vosk يعمل بنماذج لغوية: نرفض أي نموذج ليس عربياً صراحةً."""
    folder = _vosk_model_dir()
    if not folder:
        raise RuntimeError("لم يُحدَّد نموذج vosk العربي. ضع ANOMODHI_VOSK_MODEL.")
    if "ar" not in os.path.basename(folder).lower().replace("-", ""):
        raise RuntimeError("نموذج vosk المختار ليس عربياً (%s). "
                           "استخدم نموذجاً عربياً مثل vosk-model-small-ar-0.15."
                           % os.path.basename(folder))
    from vosk import KaldiRecognizer, Model, SetLogLevel
    SetLogLevel(-1)
    key = ("vosk", folder)
    with _LOCK:
        if key not in _CACHE:
            _CACHE[key] = Model(folder)
    rec = KaldiRecognizer(_CACHE[key], 16000)
    rec.SetWords(False)
    with wave.open(path, "rb") as w:
        while True:
            data = w.readframes(4000)
            if not data:
                break
            rec.AcceptWaveform(data)
    import json
    return (json.loads(rec.FinalResult()) or {}).get("text", "").strip()


def _has_module(name):
    """هل الوحدة متاحة فعلاً؟ find_spec وحده يكذب داخل الحزم المجمَّدة."""
    try:
        import importlib
        importlib.import_module(name)
        return True
    except Exception:
        return False


def engines():
    """قائمة المحرّكات المتاحة فعلياً، مرتّبة بالأفضل. تُبنى كل مرة."""
    if os.environ.get("ANOMODHI_STT_NO_ENGINES"):
        return ()
    found = []
    if worker_available():
        found.append(("faster-whisper (بيئة منفصلة)", _run_faster_whisper_worker))
    if _has_module("faster_whisper"):
        found.append(("faster-whisper", _run_faster_whisper))
    if _has_module("whisper"):
        found.append(("openai-whisper", _run_openai_whisper))
    if _has_module("vosk") and _vosk_model_dir():
        found.append(("vosk-ar", _run_vosk))
    return tuple(found)


# يُبقي الاسم القديم ENGINES متاحاً لأن الاختبارات تستبدله ببديل وهمي.
ENGINES = ()


def available():
    """(متاح؟, اسم المحرّك, سبب عدم التوفّر) — يفحص التثبيت لا التشغيل."""
    found = engines()
    if found:
        return True, found[0][0], MODEL
    return False, "لا يوجد", ("محرّك التفريغ العربي غير مثبّت. "
                               "ثبّت: pip install faster-whisper")


def install_hint():
    if worker_available():
        return ("التفريغ يعمل عبر: %s" % worker_python())
    return ("لتفعيل عدّ الكلمات من تسجيل الطفل: pip install faster-whisper"
            " (يعمل دون إنترنت، ويدعم العربية)")


# --------------------------------------------------------------- التفريغ نفسه
def wav_seconds(path):
    try:
        with wave.open(path, "rb") as w:
            return w.getnframes() / float(w.getframerate() or 16000)
    except Exception:
        return 0.0


def _result(ok, text, engine, path, seconds, error="", model=MODEL, elapsed=None,
            language=LANGUAGE_TAG):
    text = (text or "").strip()
    return {
        "ok": bool(ok),
        "text": text,
        "words": word_count(text) if ok else 0,
        "engine": engine,
        "language": language,
        "model": model,
        "path": path or "",
        "seconds": float(seconds or 0.0),        # مدة *ملف التسجيل* الحقيقية
        "elapsed": float(elapsed if elapsed is not None else seconds or 0.0),
        "error": error,
        "source": "تسجيل صوت الطفل",   # ليس نص النشرة ولا نصاً وهمياً
    }


def transcribe(path, engine_name=None, model=None, seconds=None, language=LANGUAGE):
    """يفرّغ ملف WAV عربي ويعيد قاموساً واضحاً. لا يخترع نصاً أبداً."""
    model = model or MODEL
    lang = language or LANGUAGE
    secs = float(seconds if seconds is not None else wav_seconds(path))
    if not path or not os.path.exists(path):
        return _result(False, "", "لا يوجد", path, secs,
                       "لم يُعثر على ملف التسجيل.", model=model, language=lang)
    if secs < MIN_SECONDS:
        return _result(False, "", "لا يوجد", path, secs,
                       "التسجيل قصير جداً (%d ثانية) فلا يمكن تفريغه." % int(secs),
                       model=model, language=lang)
    order = engines() or ENGINES
    if engine_name:
        wanted = tuple(e for e in order if e[0] == engine_name)
        order = wanted or order or ENGINES
    last = "لم يُعثر على محرّك تفريغ عربي مثبّت."
    for name, run in order:
        try:
            text = run(path, model, lang)
        except ImportError:
            last = "%s غير مثبّت." % name
            continue
        except Exception as exc:
            last = "%s: %s" % (name, exc)
            continue
        if text:
            return _result(True, text, name, path, secs, model=model, language=lang)
        return _result(True, "", name, path, secs,
                       "انتهى التفريغ دون نص (لم يُتعرَّف على كلام).",
                       model=model, language=lang)
    return _result(False, "", "لا يوجد", path, secs, last,
                   model=model, language=lang)


def describe(info):
    """نص تشخيصي متعدّد الأسطر للوحة التطوير (ليس للأطفال)."""
    info = info or {}
    secs = float(info.get("seconds") or 0.0)
    wpm = words_per_minute(info.get("words", 0), secs)
    return "\n".join((
        "— تشخيص تفريغ الكلام (للتطوير فقط) —",
        "النص الذي تم التعرف عليه: %s" % ('"%s"' % (info.get("text") or "(فارغ)")),
        "عدد الكلمات: %d" % info.get("words", 0),
        "مدة التسجيل: %.1f ثانية" % secs,
        "مدة القراءة بالمؤقّت: %.1f ثانية" % float(info.get("elapsed") or 0.0),
        "سرعة الكلام: %d كلمة/دقيقة" % wpm,
        "مصدر العدد: %s" % info.get("source", "غير معروف"),
        "المحرّك: %s (اللغة %s / %s)" % (info.get("engine", "?"),
                                         info.get("language", "?"),
                                         info.get("model", "?")),
        "ملف التسجيل: %s" % (info.get("path") or "(لا يوجد)"),
        "ملاحظة: %s" % (info.get("error") or install_hint()),
    ))
