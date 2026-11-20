# -*- coding: utf-8 -*-
"""
عامل تفريغ عربي منفصل، يعمل داخل *بيئة بايثون خاصة* (venv).

لماذا ملف منفصل؟ لأن تطبيق الواجهة (PyQt6) يعمل ببايثون النظام، بينما
faster-whisper قد يكون مثبّتاً في بيئة افتراضية منفصلة حتى لا نخلط المكتبات.
بدل استيراد المكتبة في نفس العملية (وهي C امتدادية ثقيلة تُبطئ الإقلاع وتربك
الواجهة)، نُشغّل هذا العامل كعملية مستقلة تُحمّل النموذج مرة واحدة وتبقى جاهزة،
وتتحدث معها بسطر JSON واحد لكل طلب.

البروتوكول بسيط ومتّفق عليه:
    stdin : {"cmd": "transcribe", "path": "...", "model": "base", "language": "ar"}
    stdout: سطر واحد {"ok": true,  "text": "..."} أو {"ok": false, "error": "..."}

قاعدة لا تُكسر: أي فشل يُعاد كرسالة خطأ صريحة، ولا يُختلق نص أبداً.
"""

import json
import sys


def _emit(payload):
    """يكتب سطر JSON واحداً ويطرّده فوراً (stdout نظيف لا تحكم فيه)."""
    try:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    except Exception:
        pass


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    except Exception:
        pass

    engine = None
    loaded = None

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except Exception:
            _emit({"ok": False, "error": "طلب غير مفهوم."})
            continue

        if request.get("cmd") == "quit":
            break

        path = request.get("path") or ""
        model_name = request.get("model") or "base"
        language = request.get("language") or "ar"

        if engine is None or loaded != model_name:
            try:
                from faster_whisper import WhisperModel
            except Exception as exc:
                _emit({"ok": False,
                       "error": "faster-whisper غير مثبّت في بيئة العامل: %s" % exc})
                continue
            try:
                # int8 على المعالج = استهلاك ذاكرة منخفض وسرعة مقبولة للأطفال.
                engine = WhisperModel(model_name, device="cpu", compute_type="int8")
                loaded = model_name
            except Exception as exc:
                engine = None
                _emit({"ok": False, "error": "تعذّر تحميل النموذج '%s': %s"
                                         % (model_name, exc)})
                continue

        try:
            segments, info = engine.transcribe(
                path,
                language=language,
                task="transcribe",
                beam_size=5,
                vad_filter=True,
                condition_on_previous_text=False,
            )
            text = " ".join(seg.text for seg in segments).strip()
            _emit({"ok": True, "text": text,
                   "language": getattr(info, "language", language) or language})
        except Exception as exc:
            _emit({"ok": False, "error": "فشل التفريغ: %s" % exc})


if __name__ == "__main__":
    main()
