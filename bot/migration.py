"""Explicit, authenticated setup jobs. No periodic Upstash access."""
import copy
import os
import threading


class MigrationJob:
    def __init__(self, store, settings):
        self.store, self.settings = store, settings
        self.lock = threading.Lock()
        self.result = {"state": "idle", "mode": "", "counts": {}, "error": ""}
        self.inspected = False
        self.thread = None

    @staticmethod
    def configured():
        return bool(os.getenv("UPSTASH_REDIS_REST_URL") and os.getenv("UPSTASH_REDIS_REST_TOKEN"))

    def status(self):
        with self.lock:
            return copy.deepcopy(self.result)

    def start(self, mode, confirmed=False):
        if mode not in {"inspect", "import"}:
            raise ValueError("Geçiş işlemi tanınmadı.")
        if not self.configured():
            raise ValueError("Eski Upstash bağlantıları Render Environment içinde korunmalı.")
        if mode == "import":
            if not confirmed:
                raise ValueError("Eski sürümün artık çalışmadığını doğrulayın.")
            if not self.store.setting("paused", True):
                raise ValueError("Önce yeni gönderimleri duraklatın.")
            if self.store.orders(states={"processing", "sending", "queued"}, limit=1):
                raise ValueError("Devam eden işleme bitince aktarımı tekrar başlatın.")
        with self.lock:
            if self.result["state"] == "running":
                raise ValueError("Bir geçiş işlemi zaten çalışıyor.")
            if mode == "import" and not self.inspected:
                raise ValueError("Önce eski kayıtları kontrol edin.")
            self.result = {"state": "running", "mode": mode, "counts": {}, "error": ""}
            self.thread = threading.Thread(target=self._run, args=(mode,), daemon=True, name="migration")
            self.thread.start()

    def _run(self, mode):
        try:
            # Credentials stay in Render's environment. No panel/Telegram requests.
            from scripts.migrate_upstash import import_snapshot, read_snapshot
            snapshot = read_snapshot()
            if mode == "import":
                # Recheck immediately before writes; never trust a stale preview.
                if not self.store.setting("paused", True):
                    raise ValueError()
                counts = import_snapshot(self.store, self.settings, snapshot)
            else:
                counts = {key: len(value) for key, value in snapshot.items()}
            with self.lock:
                self.inspected = True
                self.result.update(state="done", counts=counts)
        except Exception:
            # DB/API exception strings may contain credentials: never return them.
            with self.lock:
                self.inspected = False
                self.result.update(state="error", error=(
                    "Aktarım tamamlanamadı. Upstash kota/bağlantı durumunu ve Render Environment "
                    "ayarlarını kontrol edin. Kaynak kayıtlar silinmedi; gönderimler açılmadı."
                    if mode == "import" else
                    "Eski kayıtlar okunamadı. Upstash kota/bağlantı durumunu ve Render Environment "
                    "ayarlarını kontrol edin. Hiçbir kaynak kayıt değiştirilmedi."))
