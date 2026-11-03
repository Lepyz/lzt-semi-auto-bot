"""Binding CSV export/import and bulk service changes. Validation only; the caller writes."""
import csv
import hashlib
import io
import json

from .config import panel_key
from .engine import normalize_binding

HEADER = ["İlan", "Ad", "Durum", "Panel", "Servis", "Adet", "Platform", "Servis adı", "Hedef türü"]


def snapshot_hash(bindings):
    """Changes between a preview and its apply are detected with this."""
    return hashlib.sha256(json.dumps(bindings, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def export_csv(bindings, panels):
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";")
    writer.writerow(HEADER)
    for advert, binding in bindings.items():
        for part in binding.get("components", []):
            writer.writerow([advert, binding.get("name", ""), "aktif" if binding.get("active", True) else "pasif",
                             panels.get(part["panel"], {}).get("name", part["panel"]), part["service_id"],
                             part["quantity"], part["platform"], part.get("name", ""), part.get("target_type", "auto")])
    return "﻿" + out.getvalue()


def decode(raw):
    for encoding in ("utf-8-sig", "cp1254"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Dosya okunamadı; CSV (UTF-8) olarak kaydedin.")


def resolve_panel(value, panels):
    key = panel_key(value)
    if key in panels:
        return key
    return next((k for k, p in panels.items() if str(p["name"]).casefold() == str(value).strip().casefold()), "")


def parse_import(text, current, panels):
    """Return (changes, errors). Adverts missing from the file are left untouched."""
    lines = text.lstrip("\ufeff").splitlines()
    if not lines:
        raise ValueError("Dosya boş.")
    delimiter = ";" if lines[0].count(";") >= lines[0].count(",") else ","
    reader = csv.reader(lines, delimiter=delimiter)
    header = [h.strip() for h in next(reader)]
    if header[:7] != HEADER[:7]:
        raise ValueError("Başlık satırı beklenen biçimde değil. Önce mevcut eşleştirmeleri indirip o dosyayı düzenleyin.")
    grouped, errors = {}, []
    for number, row in enumerate(reader, start=2):
        if not any(cell.strip() for cell in row):
            continue
        row = (row + [""] * 9)[:9]
        advert, name, status, panel, service, quantity, platform, part_name, target_type = (cell.strip() for cell in row)
        if len(header) < 9:
            existing = next((p for p in current.get(advert, {}).get("components", []) if
                             p.get("service_id") == service and p.get("panel") == resolve_panel(panel, panels)), {})
            target_type = existing.get("target_type", "auto")
        if not advert.isdigit():
            errors.append(f"Satır {number}: ilan numarası geçersiz.")
            continue
        if status.casefold() not in {"aktif", "pasif"}:
            errors.append(f"Satır {number}: durum 'aktif' veya 'pasif' olmalı.")
            continue
        key = resolve_panel(panel, panels)
        if not key:
            errors.append(f"Satır {number}: panel tanınmadı ({panel[:40]}).")
            continue
        entry = grouped.setdefault(advert, {"name": name, "active": status.casefold() == "aktif", "components": []})
        entry["components"].append({"panel": key, "service_id": service, "quantity": quantity,
                                    "platform": platform or "instagram", "name": part_name, "target_type": target_type or "auto"})
    changes = []
    for advert, data in grouped.items():
        try:
            binding = normalize_binding(data, panels)
        except ValueError as exc:
            errors.append(f"İlan {advert}: {exc}")
            continue
        before = current.get(advert)
        if before != binding:
            changes.append({"advert": advert, "kind": "Değişecek" if before else "Eklenecek",
                            "before": before, "after": binding})
    return changes, errors


def service_swap(current, panel, old_service, new_service, panels):
    """Every binding component using panel/old_service moved to new_service."""
    if panel not in panels or not old_service.isdigit() or not new_service.isdigit() or old_service == new_service:
        raise ValueError("Panel ve iki farklı servis numarası gerekli.")
    changes = []
    for advert, binding in current.items():
        if not any(p["panel"] == panel and p["service_id"] == old_service for p in binding.get("components", [])):
            continue
        after = json.loads(json.dumps(binding))
        for part in after["components"]:
            if part["panel"] == panel and part["service_id"] == old_service:
                part["service_id"] = new_service
        changes.append({"advert": advert, "kind": "Değişecek", "before": binding, "after": after})
    return changes
