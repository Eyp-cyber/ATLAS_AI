# -*- coding: utf-8 -*-
"""
ATLAS AI - Yerel Uzay Bilgi Sistemi
GÖK ATLAS için terminal tabanlı astronomi bilgi asistanı.

Gerekli dosya:
    Python çalıştırmasında server.json bu dosyayla aynı klasörde;
    EXE çalıştırmasında ise server.json ATLAS_AI.exe ile aynı klasörde bulunmalıdır.

Beklenen temel JSON yapısı:
{
    "gezegenler": {
        "mars": {
            "isim": "Mars",
            "tur": "Karasal gezegen",
            "uydu_sayisi": 2,
            "gunes_uzakligi_km": 227940000,
            "aciklama": "..."
        }
    },
    "uzay_terimleri": {
        "olay ufku": {"tanım": "..."}
    },
    "uzay_bilgileri": ["...", "..."],
    "cucce_gezegenler": {},
    "yildizlar": {},
    "dogal_uydular": {},
    "uzay_misyonlari": {},
    "kullanici_profili": {
        "kullanici_adi": "Kullanıcı",
        "olusturulma_tarihi": null,
        "guncellenme_tarihi": null
    }
}

Not: Veritabanındaki mevcut kayıtlar korunur; bu program yalnızca okur.
"""

from __future__ import annotations

import json
import os
import queue
import random
import re
import shutil
import sys
import textwrap
import threading
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


# ============================================================
# KONSOL ÇIKTISI VE SOHBET GEÇMİŞİ KAYDI
# ============================================================


# PyInstaller one-file paketinde salt-okunur kaynaklar sys._MEIPASS içindedir.
# Kullanıcıya ait değişebilir veriler ise Windows AppData altında saklanır.
if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR)).resolve()
    USER_DATA_DIR = Path(
        os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
    ) / "GOK_ATLAS" / "ATLAS_AI"
else:
    APP_DIR = Path(__file__).resolve().parent
    RESOURCE_DIR = APP_DIR
    USER_DATA_DIR = APP_DIR

SOHBET_KAYDI: Any = None

# Tkinter arayüzü: üst paneller sabit kalır, yalnızca sohbet alanı kayar.
GUI_MODE = False
GUI_INPUT_QUEUE: queue.Queue[str | None] = queue.Queue()
GUI_UI_QUEUE: queue.Queue[tuple[str, str]] = queue.Queue()


class KonsolVeDosya:
    """Çıktıyı hem terminale hem de kalıcı metin günlüğüne yazar."""

    def __init__(self, konsol: Any, dosya: Any) -> None:
        self.konsol = konsol
        self.dosya = dosya

    def write(self, veri: str) -> int:
        sonuc = self.konsol.write(veri) if self.konsol is not None else None
        # Günlük dosyasında ANSI renk ve satır başına dönme kodlarını tutma.
        temiz = re.sub(r"\x1b\[[0-9;]*m", "", veri).replace("\r", "")
        if temiz:
            self.dosya.write(temiz)
            if "\n" in temiz:
                self.dosya.flush()
        return len(veri) if sonuc is None else sonuc

    def flush(self) -> None:
        if self.konsol is not None:
            self.konsol.flush()
        self.dosya.flush()

    def isatty(self) -> bool:
        return bool(getattr(self.konsol, "isatty", lambda: False)()) if self.konsol is not None else False

    @property
    def encoding(self) -> str:
        return getattr(self.konsol, "encoding", None) or "utf-8"

    def fileno(self) -> int:
        if self.konsol is None:
            raise OSError("Konsol çıktısı bu uygulama modunda kullanılamıyor.")
        return self.konsol.fileno()


def kullanici_mesajini_kaydet(metin: str) -> None:
    """Kullanıcı mesajını kalıcı sohbet günlüğüne yazar."""
    if SOHBET_KAYDI is None or not metin:
        return
    SOHBET_KAYDI.write(f">{kullanici_adi_getir()}\n{metin}\n\n")
    SOHBET_KAYDI.flush()


def sohbet_mesajini_kaydet(konusmaci: str, metin: str) -> None:
    """GUI'de stdout'a uğramadan gösterilen asistan mesajlarını da günlüğe ekler."""
    if SOHBET_KAYDI is None or not metin:
        return
    SOHBET_KAYDI.write(f">{konusmaci}\n{str(metin).strip()}\n\n")
    SOHBET_KAYDI.flush()


# ============================================================
# ATLAS AYARLARI
# ============================================================

# EXE sürümünde server.json EXE'nin içine gömülür ve ilk açılışta
# kalıcı kullanıcı veri klasörüne kopyalanır. Böylece kullanıcıdan ayrı
# server.json istemeyiz ve Program Files gibi yazma korumalı klasörlere yazmayız.
VERITABANI_DOSYASI = USER_DATA_DIR / "server.json"
SOHBET_GECMISI_DOSYASI = USER_DATA_DIR / "sohbet_gecmisi.txt"
VERITABANI_HAZIRLAMA_HATASI: str | None = None

if getattr(sys, "frozen", False):
    try:
        USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not VERITABANI_DOSYASI.is_file():
            # Önce eski sürümde EXE'nin yanına bırakılmış veritabanını taşı.
            eski_veritabani = APP_DIR / "server.json"
            gomulu_veritabani = RESOURCE_DIR / "server.json"
            kaynak_veritabani = (
                eski_veritabani if eski_veritabani.is_file() else gomulu_veritabani
            )
            if not kaynak_veritabani.is_file():
                raise FileNotFoundError(
                    f"Paketin içinde server.json bulunamadı: {gomulu_veritabani}"
                )
            shutil.copy2(kaynak_veritabani, VERITABANI_DOSYASI)

        # Eski sürümün sohbet günlüğünü de ilk çalıştırmada koru.
        eski_sohbet = APP_DIR / "sohbet_gecmisi.txt"
        if not SOHBET_GECMISI_DOSYASI.exists() and eski_sohbet.is_file():
            shutil.copy2(eski_sohbet, SOHBET_GECMISI_DOSYASI)
    except OSError as hata:
        VERITABANI_HAZIRLAMA_HATASI = str(hata)

BASE_DIR = USER_DATA_DIR

# Bir ışık yılının kilometre cinsinden yaklaşık değeri.
ISIK_YILI_KM = Decimal("9460730472581")
GENISLIK = 66


def stdout_tty_mi() -> bool:
    """stdout None olsa bile terminal kontrolünü güvenli yapar."""
    stdout = sys.stdout
    isatty = getattr(stdout, "isatty", None) if stdout is not None else None
    return bool(isatty()) if callable(isatty) else False

# ATLAS_NO_ANIM=1 ortam değişkeni animasyonları kapatır.
ANIMASYON_AKTIF = (
    stdout_tty_mi()
    and os.environ.get("ATLAS_NO_ANIM", "0") != "1"
)


class Renk:
    """ANSI terminal renkleri. TTY olmayan çıktılarda renk kullanma."""

    AKTIF = stdout_tty_mi() and os.environ.get("NO_COLOR") is None

    RESET = "\033[0m" if AKTIF else ""
    BEYAZ = "\033[97m" if AKTIF else ""
    GRI = "\033[90m" if AKTIF else ""
    MAVI = "\033[94m" if AKTIF else ""
    ACIK_MAVI = "\033[96m" if AKTIF else ""
    YESIL = "\033[92m" if AKTIF else ""
    SARI = "\033[93m" if AKTIF else ""
    KIRMIZI = "\033[91m" if AKTIF else ""
    MOR = "\033[95m" if AKTIF else ""


VERITABANI: dict[str, Any] | None = None

# Sohbet oturumu belleği yalnızca mevcut çalıştırma boyunca tutulur.
# "yeni sohbet" komutu bu belleği sıfırlar; terminal çıktısını silmez.
SOHBET_BAGLAMI: dict[str, Any] = {
    "kullanici_adi": None,
    "son_konu": None,
    "son_sohbet_konusu": None,
    "son_kullanici_mesaji": None,
    "dogal_yanit_gecmisi": {},
    "sohbet_tonu": "dogal",
    "yanit_uzunlugu": "normal",
}


# ============================================================
# GENEL YARDIMCI FONKSİYONLAR
# ============================================================


def clear() -> None:
    """GUI'de hiçbir alanı temizleme; terminal modunda geçmişi koru."""
    if GUI_MODE:
        return
    if os.environ.get("ATLAS_CLEAR_SCREEN", "0") == "1" and stdout_tty_mi():
        os.system("cls" if os.name == "nt" else "clear")
        return

    if stdout_tty_mi():
        print(f"\n{Renk.GRI}{'─' * GENISLIK}{Renk.RESET}")
    else:
        print()


def bekle(saniye: float = 0.8, temizle: bool = False) -> None:
    if ANIMASYON_AKTIF and saniye > 0:
        time.sleep(saniye)
    if temizle:
        clear()


def input_al(istem: str = "") -> str:
    """Terminalden veya GUI giriş kutusundan kullanıcı girdisi alır."""
    if GUI_MODE:
        GUI_UI_QUEUE.put(("prompt", str(istem)))
        cevap = GUI_INPUT_QUEUE.get()
        if cevap is None:
            raise EOFError
        return cevap.strip()
    return input(istem).strip()


def yaz(metin: Any, hiz: float = 0.018, renk: str = Renk.BEYAZ) -> None:
    metin = str(metin)
    if not ANIMASYON_AKTIF or hiz <= 0:
        print(f"{renk}{metin}{Renk.RESET}")
        return

    for karakter in metin:
        print(renk + karakter + Renk.RESET, end="", flush=True)
        time.sleep(hiz)
    print()


def atlas_yaz(metin: Any, hiz: float = 0.018) -> None:
    """Asistan mesajını diyalog akışına gönderir; GUI'de kutu/tablo oluşturmaz."""
    if GUI_MODE:
        sohbet_mesajini_kaydet("ATLAS AI", str(metin))
        GUI_UI_QUEUE.put(("chat", str(metin)))
        return
    yaz(f">ATLAS AI\n{metin}", hiz, Renk.BEYAZ)


def bilgi_yaz(metin: Any, hiz: float = 0.012) -> None:
    if GUI_MODE:
        sohbet_mesajini_kaydet("ATLAS AI", str(metin))
        GUI_UI_QUEUE.put(("chat", str(metin)))
        return
    yaz(f">ATLAS AI\n{metin}", hiz, Renk.ACIK_MAVI)


def hata_yaz(metin: Any, hiz: float = 0.012) -> None:
    if GUI_MODE:
        sohbet_mesajini_kaydet("ATLAS AI", f"Hata: {metin}")
        GUI_UI_QUEUE.put(("chat_error", str(metin)))
        return
    yaz(f">ATLAS AI\nHata: {metin}", hiz, Renk.KIRMIZI)


def yukleniyor(mesaj: str = "Veriler inceleniyor", tekrar: int = 3) -> None:
    """Kısa ve isteğe bağlı yükleniyor animasyonu."""
    if GUI_MODE:
        return
    if not ANIMASYON_AKTIF:
        print(f"{Renk.ACIK_MAVI}[ {mesaj} ]{Renk.RESET}")
        return

    for i in range(max(1, tekrar)):
        noktalar = "." * ((i % 3) + 1)
        print(
            f"\r{Renk.ACIK_MAVI}[ ATLAS ]{Renk.RESET} {mesaj}{noktalar}   ",
            end="",
            flush=True,
        )
        time.sleep(0.18)
    print()


def baslik() -> None:
    print(Renk.ACIK_MAVI)
    print("╔" + "═" * (GENISLIK - 2) + "╗")
    print("║" + "ATLAS AI".center(GENISLIK - 2) + "║")
    print(
        "║"
        + "ASTRONOMY & SPACE INTELLIGENCE SYSTEM".center(GENISLIK - 2)
        + "║"
    )
    print("╚" + "═" * (GENISLIK - 2) + "╝")
    print(Renk.RESET)


def durum_satiri() -> None:
    print(
        f"{Renk.YESIL}● ONLINE{Renk.RESET}"
        f"   {Renk.GRI}|{Renk.RESET}   "
        f"{Renk.ACIK_MAVI}LOCAL DATABASE{Renk.RESET}"
        f"   {Renk.GRI}|{Renk.RESET}   "
        f"{Renk.MAVI}powered by Gök Atlas{Renk.RESET}"
    )
    print()


def panel(
    baslik_metni: str,
    icerik: str | list[Any] | tuple[Any, ...],
    baslik_rengi: str = Renk.ACIK_MAVI,
) -> None:
    """Terminalde kutu çizer; grafik arayüzde sade sohbet mesajı üretir."""
    baslik_metni = str(baslik_metni)
    if GUI_MODE:
        satirlar = icerik.splitlines() if isinstance(icerik, str) else list(icerik)
        temiz_satirlar = []
        for satir in satirlar:
            satir = re.sub(r"\x1b\[[0-9;]*m", "", str(satir)).strip()
            if satir:
                temiz_satirlar.append(satir)
        govde = "\n".join(temiz_satirlar)
        mesaj = f"{baslik_metni}\n{govde}" if govde else baslik_metni
        sohbet_mesajini_kaydet("ATLAS AI", mesaj)
        GUI_UI_QUEUE.put(("chat", mesaj))
        return

    ic_genislik = GENISLIK - 4
    cizgi_uzunlugu = max(1, GENISLIK - len(baslik_metni) - 6)

    print()
    print(
        f"{baslik_rengi}╭── {baslik_metni} "
        f"{'─' * cizgi_uzunlugu}╮{Renk.RESET}"
    )

    satirlar = icerik.splitlines() if isinstance(icerik, str) else list(icerik)
    for satir in satirlar:
        satir = str(satir)
        if not satir:
            print(f"{baslik_rengi}│{Renk.RESET}")
            continue

        # Renk kodları uzunluk hesabını etkilemesin.
        ansi_temiz = re.sub(r"\x1b\[[0-9;]*m", "", satir)
        if len(ansi_temiz) > ic_genislik and "\033[" not in satir:
            parcalar = textwrap.wrap(
                satir,
                width=ic_genislik,
                break_long_words=True,
                break_on_hyphens=False,
            )
        else:
            parcalar = [satir]

        for parca in parcalar:
            print(f"{baslik_rengi}│{Renk.RESET} {parca}")

    print(f"{baslik_rengi}╰{'─' * (GENISLIK - 1)}╯{Renk.RESET}")


def devam_icin_enter() -> None:
    """Eski menü çağrılarıyla uyumluluk; scrollback varken duraklatma gerekmez."""
    return


def metin_normalize(metin: Any) -> str:
    """Türkçe karakterleri sadeleştirir ve noktalama işaretlerini temizler."""
    metin = str(metin or "").strip().casefold()
    karakterler = str.maketrans(
        {
            "ç": "c",
            "ğ": "g",
            "ı": "i",
            "ö": "o",
            "ş": "s",
            "ü": "u",
        }
    )
    metin = metin.translate(karakterler)
    metin = re.sub(r"[^a-z0-9\s]", " ", metin)
    return " ".join(metin.split())


def turkce_sayi_bicimle(deger: Decimal, basamak: int = 8) -> str:
    """Sayıyı Türkçe ayırıcılarla gösterir: 1.234,56"""
    metin = f"{deger:,.{max(0, basamak)}f}"
    if "." in metin:
        tam_kisim, ondalik_kisim = metin.split(".", 1)
        ondalik_kisim = ondalik_kisim.rstrip("0")
        metin = tam_kisim if not ondalik_kisim else f"{tam_kisim}.{ondalik_kisim}"
    return metin.replace(",", "X").replace(".", ",").replace("X", ".")


# ============================================================
# SAYI AYRIŞTIRMA VE IŞIK YILI HESAPLAMA
# ============================================================


BUYUK_SAYI_CARPANLARI = {
    "bin": Decimal("1000"),
    "milyon": Decimal("1000000"),
    "milyar": Decimal("1000000000"),
    "trilyon": Decimal("1000000000000"),
    "katrilyon": Decimal("1000000000000000"),
}


def sayi_ayristir(giris: str | int | float | Decimal) -> Decimal:
    """Türkçe/uluslararası ondalık gösterimleri Decimal olarak ayrıştırır.

    Örnekler:
        1,5       -> 1.5
        1.5       -> 1.5
        1.234.567 -> 1234567
        1.234,56  -> 1234.56
        2,5 milyon -> 2500000
    Tek ayraçlı sayılarda ayraç ondalık kabul edilir. Böylece 1.524,
    astronomi bağlamındaki 1,524 değerini yanlışlıkla 1524 yapmaz.
    """
    if isinstance(giris, Decimal):
        deger = giris
    else:
        metin = str(giris).strip().casefold().replace("\u00a0", " ")
        if not metin:
            raise ValueError("Bir sayı girmelisiniz.")

        carpan = Decimal("1")
        for birim, katsayi in BUYUK_SAYI_CARPANLARI.items():
            eslesme = re.search(rf"\s+{birim}\s*$", metin)
            if eslesme:
                carpan = katsayi
                metin = metin[: eslesme.start()].strip()
                break

        metin = metin.replace(" ", "")
        if not re.fullmatch(r"[+-]?(?:\d+(?:[.,]\d+)*|[.,]\d+)", metin):
            raise ValueError("Geçersiz sayı girdiniz. Örnek: 1,5 veya 1250000.")

        if "." in metin and "," in metin:
            # Son görülen ayraç ondalık; diğeri binlik ayırıcıdır.
            ondalik_ayrac = "." if metin.rfind(".") > metin.rfind(",") else ","
            binlik_ayrac = "," if ondalik_ayrac == "." else "."
            metin = metin.replace(binlik_ayrac, "")
            metin = metin.replace(ondalik_ayrac, ".")
        elif "." in metin or "," in metin:
            ayirac = "." if "." in metin else ","
            if metin.count(ayirac) > 1:
                parcalar = metin.split(ayirac)
                if all(len(parca) == 3 for parca in parcalar[1:]):
                    metin = "".join(parcalar)
                else:
                    metin = "".join(parcalar[:-1]) + "." + parcalar[-1]
            else:
                metin = metin.replace(ayirac, ".")

        try:
            deger = Decimal(metin) * carpan
        except InvalidOperation as hata:
            raise ValueError("Girilen sayı çözümlenemedi.") from hata

    if not deger.is_finite():
        raise ValueError("Sonsuz veya geçersiz bir sayı kullanılamaz.")
    if deger < 0:
        raise ValueError("Mesafe negatif olamaz.")
    return deger


def komuttan_sayi_bul(komut: str) -> Decimal | None:
    """Doğal dil komutundaki ilk sayıyı ve varsa büyüklük ekini bulur.

    Sayı yakalanmadan önce noktalama temizlenmez; aksi hâlde 2,5 değeri
    2 ve 5 şeklinde bölünebilirdi.
    """
    temiz = str(komut).casefold().replace("\u00a0", " ")
    desen = (
        r"(?<!\d)([+-]?\d+(?:[.,]\d+)*(?:\s+"
        r"(?:bin|milyon|milyar|trilyon|katrilyon))?)(?!\d)"
    )
    eslesme = re.search(desen, temiz)
    if not eslesme:
        return None
    try:
        return sayi_ayristir(eslesme.group(1))
    except ValueError:
        return None


def isik_yili_yonu_belirle(komut: str) -> str | None:
    """Doğal dil komutunda kaynak ve hedef birimi tespit eder."""
    temiz = metin_normalize(komut)
    if not ("isik yil" in temiz and (" km" in f" {temiz}" or "kilometre" in temiz)):
        return None

    km_hedef_ipuclari = (
        "kmye",
        "km ye",
        "kilometreye",
        "kilometre ye",
        "kac km",
        "km cinsinden",
        "kilometre cinsinden",
        "km olarak",
        "kilometre olarak",
    )
    isik_yili_hedef_ipuclari = (
        "kac isik yil",
        "isik yilina",
        "isik yili cinsinden",
        "kmden",
        "kilometreden",
    )

    if any(ipucu in temiz for ipucu in km_hedef_ipuclari):
        return "isik_yili_to_km"
    if any(ipucu in temiz for ipucu in isik_yili_hedef_ipuclari):
        return "km_to_isik_yili"

    # Açık hedef ifadesi yoksa önce yazılan birimi kaynak kabul et.
    if temiz.find("isik yil") < min(
        [konum for konum in (temiz.find(" km"), temiz.find("kilometre")) if konum >= 0]
    ):
        return "isik_yili_to_km"
    return "km_to_isik_yili"


def isik_yili_sonuc_goster(yon: str, deger: Decimal) -> None:
    if deger < 0:
        hata_yaz("Mesafe negatif olamaz.")
        return

    if yon == "isik_yili_to_km":
        sonuc = deger * ISIK_YILI_KM
        satirlar = [
            f"Girdi   : {turkce_sayi_bicimle(deger)} ışık yılı",
            f"Sonuç   : {turkce_sayi_bicimle(sonuc, 3)} km",
        ]
    else:
        sonuc = deger / ISIK_YILI_KM
        satirlar = [
            f"Girdi   : {turkce_sayi_bicimle(deger)} km",
            f"Sonuç   : {turkce_sayi_bicimle(sonuc, 18)} ışık yılı",
        ]

    panel("IŞIK YILI DÖNÜŞÜMÜ", satirlar, Renk.YESIL)


def isik_yili_hesaplayici(komut: str | None = None) -> None:
    """Işık yılı-kilometre dönüşümü: doğal dil veya sayısal menü."""
    if komut:
        yon = isik_yili_yonu_belirle(komut)
        if yon:
            deger = komuttan_sayi_bul(komut)
            if deger is None:
                birim = "Işık yılı" if yon == "isik_yili_to_km" else "Kilometre"
                try:
                    deger = sayi_ayristir(input_al(f"\n{Renk.GRI}{birim} miktarı > {Renk.RESET}"))
                except ValueError as hata:
                    hata_yaz(hata)
                    return
            isik_yili_sonuc_goster(yon, deger)
            return

    clear()
    panel(
        "MESAFE HESAPLAMA MERKEZİ",
        [
            f"{Renk.ACIK_MAVI}01{Renk.RESET}  Işık yılı → Kilometre",
            f"{Renk.ACIK_MAVI}02{Renk.RESET}  Kilometre → Işık yılı",
            "",
            f"{Renk.GRI}0   Geri dön{Renk.RESET}",
        ],
    )

    secim = input_al(f"\n{Renk.MAVI}ATLAS CALC > {Renk.RESET}")
    if secim == "0":
        return
    if secim not in {"1", "2"}:
        hata_yaz("Geçersiz seçim.")
        return

    birim = "Işık yılı" if secim == "1" else "Kilometre"
    try:
        deger = sayi_ayristir(input_al(f"{Renk.GRI}{birim} miktarı > {Renk.RESET}"))
    except ValueError as hata:
        hata_yaz(hata)
        return

    yon = "isik_yili_to_km" if secim == "1" else "km_to_isik_yili"
    isik_yili_sonuc_goster(yon, deger)


# ============================================================
# VERİTABANI YÖNETİMİ
# ============================================================



def veritabani_yukle() -> dict[str, Any] | None:
    """server.json dosyasını kalıcı kullanıcı veri klasöründen yükler."""
    if VERITABANI_HAZIRLAMA_HATASI:
        hata_yaz(f"ATLAS AI veri klasörü hazırlanamadı: {VERITABANI_HAZIRLAMA_HATASI}")
        return None
    if not VERITABANI_DOSYASI.is_file():
        hata_yaz("server.json dosyası bulunamadı.")
        bilgi_yaz(f"Dosyayı şu klasöre yerleştir: {BASE_DIR}")
        return None

    try:
        with VERITABANI_DOSYASI.open("r", encoding="utf-8-sig") as dosya:
            veritabani = json.load(dosya)
    except json.JSONDecodeError as hata:
        hata_yaz("server.json dosyasında geçersiz JSON biçimi var.")
        bilgi_yaz(f"Satır: {hata.lineno}, sütun: {hata.colno}")
        return None
    except OSError as hata:
        hata_yaz(f"Veritabanı okunamadı: {hata}")
        return None

    if not isinstance(veritabani, dict):
        hata_yaz("server.json ana yapısı bir JSON nesnesi olmalıdır.")
        return None

    dict_kategorileri = (
        "gezegenler", "cucce_gezegenler", "yildizlar",
        "dogal_uydular", "uzay_terimleri", "uzay_misyonlari",
    )
    for kategori in dict_kategorileri:
        if kategori in veritabani and not isinstance(veritabani[kategori], dict):
            hata_yaz(f'"{kategori}" alanı bir JSON nesnesi olmalıdır.')
            return None

    if "uzay_bilgileri" in veritabani and not isinstance(veritabani["uzay_bilgileri"], list):
        hata_yaz('"uzay_bilgileri" alanı bir JSON listesi olmalıdır.')
        return None

    if not any(
        kategori in veritabani
        for kategori in ("gezegenler", "uzay_terimleri", "uzay_bilgileri")
    ):
        hata_yaz("Veritabanında ATLAS'ın beklediği temel veri alanları bulunamadı.")
        return None

    for kategori in dict_kategorileri:
        kayitlar = veritabani.get(kategori)
        if isinstance(kayitlar, dict):
            bozuk = [
                anahtar for anahtar, kayit in kayitlar.items()
                if not isinstance(kayit, dict)
            ]
            if bozuk:
                hata_yaz(
                    f'"{kategori}" içinde nesne olmayan kayıtlar var: '
                    f'{", ".join(map(str, bozuk[:4]))}'
                )
                return None

    bilgiler = veritabani.get("uzay_bilgileri", [])
    if any(not isinstance(bilgi, str) for bilgi in bilgiler):
        hata_yaz('"uzay_bilgileri" içindeki her kayıt metin olmalıdır.')
        return None

    bilgi_kategorileri = veritabani.get("bilgi_kategorileri", {})
    if not isinstance(bilgi_kategorileri, dict):
        hata_yaz('"bilgi_kategorileri" alanı bir JSON nesnesi olmalıdır.')
        return None

    for kategori, kayitlar in bilgi_kategorileri.items():
        if not isinstance(kayitlar, list) or any(
            not isinstance(kayit, str) for kayit in kayitlar
        ):
            hata_yaz(f'"bilgi_kategorileri.{kategori}" bir metin listesi olmalıdır.')
            return None

    meta = veritabani.get("_meta", {})
    if meta is not None and not isinstance(meta, dict):
        hata_yaz('"_meta" alanı bir JSON nesnesi olmalıdır.')
        return None

    return veritabani





    return veritabani



def veritabani_kaydet() -> bool:
    """server.json dosyasını atomik biçimde kaydeder; mevcut astronomi verilerini korur."""
    if not isinstance(VERITABANI, dict):
        return False
    gecici_dosya = VERITABANI_DOSYASI.with_suffix(VERITABANI_DOSYASI.suffix + ".tmp")
    try:
        with gecici_dosya.open("w", encoding="utf-8", newline="\n") as dosya:
            json.dump(VERITABANI, dosya, ensure_ascii=False, indent=2)
            dosya.write("\n")
            dosya.flush()
            os.fsync(dosya.fileno())
        os.replace(gecici_dosya, VERITABANI_DOSYASI)
        return True
    except OSError as hata:
        try:
            gecici_dosya.unlink(missing_ok=True)
        except OSError:
            pass
        hata_yaz(f"Kullanıcı profili server.json dosyasına kaydedilemedi: {hata}")
        return False


def kullanici_adi_getir() -> str:
    """Kalıcı kullanıcı profilindeki görünen adı döndürür."""
    if isinstance(VERITABANI, dict):
        profil = VERITABANI.get("kullanici_profili", {})
        if isinstance(profil, dict):
            ad = str(profil.get("kullanici_adi", "")).strip()
            if ad:
                return ad
    return str(SOHBET_BAGLAMI.get("kullanici_adi") or "Kullanıcı")


def kullanici_profili_yukle() -> None:
    """server.json içindeki kullanıcı profilini yükler veya varsayılan profil ekler."""
    if not isinstance(VERITABANI, dict):
        return

    profil = VERITABANI.get("kullanici_profili")
    degisti = False
    if not isinstance(profil, dict):
        profil = {}
        degisti = True

    ad = str(profil.get("kullanici_adi", "")).strip()
    if not ad:
        ad = "Kullanıcı"
        profil["kullanici_adi"] = ad
        degisti = True

    if not profil.get("olusturulma_tarihi"):
        profil["olusturulma_tarihi"] = datetime.now().isoformat(timespec="seconds")
        degisti = True
    VERITABANI["kullanici_profili"] = profil
    SOHBET_BAGLAMI["kullanici_adi"] = ad
    if GUI_MODE:
        GUI_UI_QUEUE.put(("username", ad))

    if degisti:
        veritabani_kaydet()


def kullanici_adi_degistir(yeni_ad: str) -> bool:
    """Kullanıcı adını doğrular ve kalıcı olarak server.json dosyasına yazar."""
    if not isinstance(VERITABANI, dict):
        hata_yaz("Veritabanı yüklenmeden kullanıcı adı değiştirilemez.")
        return False

    ad = " ".join(str(yeni_ad or "").strip().split())
    if not 2 <= len(ad) <= 24:
        hata_yaz("Kullanıcı adı 2 ile 24 karakter arasında olmalı.")
        return False
    if not re.fullmatch(r"[\w][\w .'-]{0,23}", ad, flags=re.UNICODE):
        hata_yaz("Kullanıcı adı harf, rakam, boşluk, nokta, kısa çizgi veya alt çizgi içerebilir.")
        return False

    eski_profil = VERITABANI.get("kullanici_profili")
    eski_profil = dict(eski_profil) if isinstance(eski_profil, dict) else {}
    yeni_profil = dict(eski_profil)
    yeni_profil["kullanici_adi"] = ad
    yeni_profil.setdefault("olusturulma_tarihi", datetime.now().isoformat(timespec="seconds"))
    yeni_profil["guncellenme_tarihi"] = datetime.now().isoformat(timespec="seconds")

    VERITABANI["kullanici_profili"] = yeni_profil
    if not veritabani_kaydet():
        VERITABANI["kullanici_profili"] = eski_profil
        return False

    SOHBET_BAGLAMI["kullanici_adi"] = ad
    if GUI_MODE:
        GUI_UI_QUEUE.put(("username", ad))
    atlas_yaz(f"Kullanıcı adın artık {ad}. Bu değişiklik server.json dosyasına kaydedildi.")
    return True



def veri_al(kategori: str) -> Any:
    if not isinstance(VERITABANI, dict):
        return None
    return VERITABANI.get(kategori)



def uzay_bilgileri(kategori: str | None = None) -> None:
    """Genel veya seçilmiş bir konu kategorisinden rastgele bilgi gösterir."""
    if kategori:
        kategoriler = veri_al("bilgi_kategorileri")
        bilgiler = kategoriler.get(kategori) if isinstance(kategoriler, dict) else None
        panel_basligi = f"RANDOM DATA / {kategori.replace('_', ' ').upper()}"
    else:
        bilgiler = veri_al("uzay_bilgileri")
        panel_basligi = "RANDOM SPACE DATA"

    if not isinstance(bilgiler, list) or not bilgiler:
        hata_yaz("Bu kategoride gösterilecek bilgi kaydı bulunamadı.")
        return

    bilgi = random.choice(bilgiler)
    if GUI_MODE:
        # RANDOM SPACE DATA kartının içeriğini güncelle; kartın kendisi sabittir.
        GUI_UI_QUEUE.put(("random", bilgi))
        atlas_yaz("Rastgele uzay bilgisi üstteki RANDOM SPACE DATA panelinde güncellendi.")
        return
    panel(
        panel_basligi,
        [f"{Renk.SARI}◆{Renk.RESET} {bilgi}"],
        Renk.SARI,
    )




def sistem_durumu() -> None:
    gezegenler = veri_al("gezegenler") or {}
    cucce_gezegenler = veri_al("cucce_gezegenler") or {}
    yildizlar = veri_al("yildizlar") or {}
    uydular = veri_al("dogal_uydular") or {}
    terimler = veri_al("uzay_terimleri") or {}
    bilgiler = veri_al("uzay_bilgileri") or []
    misyonlar = veri_al("uzay_misyonlari") or []
    meta = veri_al("_meta") or {}

    panel(
        "SYSTEM STATUS",
        [
            "Durum                         : ONLINE",
            f"Veritabanı                    : {VERITABANI_DOSYASI.name}",
            f"Veritabanı sürümü             : {meta.get('surum', 'Belirtilmemiş')}",
            f"Güneş Sistemi/ötegezegen      : {len(gezegenler)}",
            f"Cüce gezegen                  : {len(cucce_gezegenler)}",
            f"Yıldız                        : {len(yildizlar)}",
            f"Seçili doğal uydu             : {len(uydular)}",
            f"Uzay terimi                   : {len(terimler)}",
            f"Uzay görevi                   : {len(misyonlar)}",
            f"Rastgele bilgi                : {len(bilgiler)}",
            f"Işık yılı sabiti              : {turkce_sayi_bicimle(ISIK_YILI_KM, 0)} km",
            f"Son veritabanı güncellemesi   : {meta.get('guncelleme_tarihi', 'Belirtilmemiş')}",
        ],
        Renk.ACIK_MAVI,
    )



# ============================================================
# GEZEGEN VE UZAY TERİMİ ARAMA
# ============================================================



VARLIK_KOLEKSIYONLARI = (
    "gezegenler",
    "cucce_gezegenler",
    "yildizlar",
    "dogal_uydular",
)


def _alternatif_adlar(kayit: dict[str, Any], anahtar: str) -> list[str]:
    adlar = [str(anahtar), str(kayit.get("isim", anahtar))]
    alternatifler = kayit.get("alternatif_isimler", [])
    if isinstance(alternatifler, list):
        adlar.extend(str(ad) for ad in alternatifler if ad)
    return adlar


def gezegen_bul(gezegen_ismi: str) -> dict[str, Any] | None:
    """Gezegenler, cüce gezegenler, yıldızlar ve seçili uydularda arama yapar."""
    aranan = metin_normalize(gezegen_ismi)
    if not aranan:
        return None

    for kategori in VARLIK_KOLEKSIYONLARI:
        kayitlar = veri_al(kategori)
        if not isinstance(kayitlar, dict):
            continue

        for anahtar, bilgi in kayitlar.items():
            if not isinstance(bilgi, dict):
                continue
            for ad in _alternatif_adlar(bilgi, str(anahtar)):
                if aranan == metin_normalize(ad):
                    return bilgi
    return None




def gezegen_ismi_cikar(metin: str) -> str | None:
    """Doğal dil girdisinden gök cismi adını ve alternatif adlarını bulur."""
    temiz = metin_normalize(metin)
    if not temiz:
        return None

    # "Mars'ın Güneş'e uzaklığı" gibi sorularda Güneş hedef değil, referans cismidir.
    if "gunes sistemi" in temiz or ("gunes" in temiz.split() and any("uzak" in kelime or "mesafe" in kelime for kelime in temiz.split())):
        temiz_hedef = temiz.replace("gunes sistemi", " ").split()
        if "gunes" in temiz_hedef:
            temiz_hedef.remove("gunes")
        temiz = " ".join(temiz_hedef)

    adaylar: list[tuple[str, str]] = []
    for kategori in VARLIK_KOLEKSIYONLARI:
        kayitlar = veri_al(kategori)
        if not isinstance(kayitlar, dict):
            continue
        for anahtar, bilgi in kayitlar.items():
            if not isinstance(bilgi, dict):
                continue
            for ad in _alternatif_adlar(bilgi, str(anahtar)):
                normal_ad = metin_normalize(ad)
                if normal_ad:
                    adaylar.append((str(anahtar), normal_ad))

    adaylar.sort(key=lambda item: len(item[1]), reverse=True)
    padded = f" {temiz} "

    for anahtar, ad in adaylar:
        if len(ad) <= 2:
            if temiz == ad or (
                f" {ad} " in padded
                and any(kelime in temiz.split() for kelime in ("nedir", "kimdir", "uydusu", "hakkinda"))
            ):
                return anahtar
            continue

        if f" {ad} " in padded:
            return anahtar

        for kelime in temiz.split():
            if kelime.startswith(ad) and len(kelime) - len(ad) <= 6:
                return anahtar

    return None








def uzay_terimi_bul(terim_ismi: str) -> dict[str, Any] | None:
    aranan = metin_normalize(terim_ismi)
    terimler = veri_al("uzay_terimleri")
    if not aranan or not isinstance(terimler, dict):
        return None

    for anahtar, bilgi in terimler.items():
        if not isinstance(bilgi, dict):
            continue
        adlar = [str(anahtar)]
        alternatifler = bilgi.get("alternatif_isimler", [])
        if isinstance(alternatifler, list):
            adlar.extend(str(ad) for ad in alternatifler if ad)
        if any(aranan == metin_normalize(ad) for ad in adlar):
            return bilgi
    return None




def uzay_terimi_ismi_cikar(metin: str) -> str | None:
    temiz = metin_normalize(metin)
    terimler = veri_al("uzay_terimleri")
    if not isinstance(terimler, dict):
        return None

    adaylar: list[tuple[str, str]] = []
    for anahtar, bilgi in terimler.items():
        if not isinstance(bilgi, dict):
            continue
        adlar = [str(anahtar)]
        alternatifler = bilgi.get("alternatif_isimler", [])
        if isinstance(alternatifler, list):
            adlar.extend(str(ad) for ad in alternatifler if ad)
        adaylar.extend((str(anahtar), metin_normalize(ad)) for ad in adlar)

    padded = f" {temiz} "
    for anahtar, ad in sorted(adaylar, key=lambda item: len(item[1]), reverse=True):
        if ad and f" {ad} " in padded:
            return anahtar
    return None




def uzay_terimi_sorgula(metin: str) -> None:
    terim_ismi = uzay_terimi_ismi_cikar(metin)
    if terim_ismi is None:
        terim_ismi = metin.strip()

    terim = uzay_terimi_bul(terim_ismi)
    if terim is None:
        hata_yaz("Bu terimi veritabanımda bulamadım.")
        bilgi_yaz('Örnek: "Olay ufku nedir?" veya "Radyal hız yöntemi nedir?"')
        return

    yukleniyor("Uzay terimi analiz ediliyor")
    tanim = terim.get("tanım", terim.get("tanim", terim.get("aciklama", "Tanım kaydı bulunamadı.")))
    satirlar = [
        f"{Renk.ACIK_MAVI}TERİM{Renk.RESET} : {terim_ismi}",
    ]
    if terim.get("kategori"):
        satirlar.append(f"KATEGORİ : {terim['kategori']}")
    satirlar.extend(["", f"{Renk.YESIL}TANIM{Renk.RESET} : {tanim}"])

    alternatifler = terim.get("alternatif_isimler", [])
    if isinstance(alternatifler, list) and alternatifler:
        satirlar.extend(["", f"Alternatif adlar: {', '.join(map(str, alternatifler))}"])

    panel("SPACE TERMINOLOGY", satirlar, Renk.ACIK_MAVI)




def gezegenleri_listele() -> None:
    satirlar = []
    kategoriler = (
        ("gezegenler", "GEZEGENLER VE ÖTEGEZEGENLER"),
        ("cucce_gezegenler", "CÜCE GEZEGENLER"),
    )
    for kategori, etiket in kategoriler:
        kayitlar = veri_al(kategori)
        if isinstance(kayitlar, dict) and kayitlar:
            satirlar.append(etiket)
            for kayit in kayitlar.values():
                if isinstance(kayit, dict):
                    satirlar.append(f" • {kayit.get('isim', 'İsimsiz kayıt')}")
            satirlar.append("")

    if not satirlar:
        hata_yaz('Veritabanında gezegen kaydı bulunamadı.')
        return
    panel("CELESTIAL BODY CATALOG", satirlar, Renk.ACIK_MAVI)



def _gezegen_degeri(gezegen: dict[str, Any], alan: str, varsayilan: str = "Bilgi yok") -> Any:
    return gezegen.get(alan, varsayilan)



def gezegen_detay_paneli(gezegen: dict[str, Any]) -> None:
    isim = str(gezegen.get("isim", "Gök cismi"))
    satirlar: list[str] = []

    alanlar = (
        ("kategori", "Sınıf"),
        ("tur", "Tür"),
        ("yoresindeki_cisim", "Yörüngesinde bulunduğu cisim"),
        ("yildiz", "Ev sahibi yıldız"),
        ("uydu_sayisi", "Doğal uydu sayısı"),
        ("gunes_uzakligi_km", "Güneş'e ortalama uzaklık"),
        ("ortalama_gunes_uzakligi_au", "Güneş'e uzaklık (AU)"),
        ("yildizina_uzakligi_au", "Yıldızına uzaklık (AU)"),
        ("dunyaya_uzakligi_km", "Dünya'ya uzaklık"),
        ("uzaklik_dunya_isik_yili", "Dünya'ya uzaklık (ışık yılı)"),
        ("yaricap_ekvator_km", "Ekvator yarıçapı (km)"),
        ("cap_km", "Çap (km)"),
        ("kutle_kg", "Kütle (kg)"),
        ("yogunluk_g_cm3", "Yoğunluk (g/cm³)"),
        ("yaricap_dunya", "Yarıçap (Dünya yarıçapı)"),
        ("kutle_dunya", "Kütle (Dünya kütlesi)"),
        ("kutle_jupiter", "Kütle (Jüpiter kütlesi)"),
        ("arsiv_durumu", "Arşiv durumu"),
        ("yil_suresi_dunya_gunu", "Yörünge süresi (Dünya günü)"),
        ("fırlatma_yılı", "Fırlatma yılı"),
        ("hedef", "Görev hedefi"),
    )

    for alan, etiket in alanlar:
        deger = gezegen.get(alan)
        if deger is None or deger == "":
            continue
        if isinstance(deger, (int, float)) and alan in {"ortalama_gunes_uzakligi_km", "yaricap_ekvator_km", "cap_km", "kutle_kg"}:
            try:
                deger = turkce_sayi_bicimle(Decimal(str(deger)), 2 if isinstance(deger, float) else 0)
            except (InvalidOperation, ValueError):
                deger = str(deger)
        satirlar.append(f"{etiket:<27}: {deger}")

    uydu_bilgisi = gezegen.get("uydu_bilgisi")
    if uydu_bilgisi:
        satirlar.append(f"Uydu notu                 : {uydu_bilgisi}")

    ozellikler = gezegen.get("ozellikler", [])
    if isinstance(ozellikler, list) and ozellikler:
        satirlar.extend(["", "ÖNE ÇIKAN ÖZELLİKLER"])
        satirlar.extend(f" • {ozellik}" for ozellik in ozellikler)

    aciklama = gezegen.get("aciklama")
    if aciklama:
        satirlar.extend(["", f"AÇIKLAMA: {aciklama}"])

    kaynak = gezegen.get("kaynak")
    if kaynak:
        satirlar.extend(["", f"Kaynak: {kaynak}"])

    panel(f"{isim.upper()} - DATA PROFILE", satirlar or ["Bu kayıt için ek ayrıntı bulunmuyor."], Renk.ACIK_MAVI)




def gezegen_menusu(gezegen: dict[str, Any]) -> None:
    isim = str(gezegen.get("isim", "Gök cismi"))
    kategori = str(gezegen.get("kategori", "Gök cismi"))

    while True:
        clear()
        panel(
            f"{isim.upper()} - DATA MODULE",
            [
                f"Kategori: {kategori}",
                "01  Genel açıklama",
                "02  Uzaklık / yörünge bilgisi",
                "03  Fiziksel özellikler",
                "04  Doğal uydu / ev sahibi bilgisi",
                "05  Tüm kayıt ayrıntıları",
                "",
                "00  Geri dön",
            ],
            Renk.ACIK_MAVI,
        )

        secim = input_al(f"\n{Renk.ACIK_MAVI}ATLAS / {isim.upper()} > {Renk.RESET}")
        if secim in {"1", "01"}:
            atlas_yaz(gezegen.get("aciklama", "Bu kayıt için açıklama bulunmuyor."))
        elif secim in {"2", "02"}:
            uzaklik_satirlari = []
            for alan, etiket in (
                ("gunes_uzakligi_km", "Güneş'e ortalama uzaklık"),
                ("ortalama_gunes_uzakligi_km", "Güneş'e ortalama uzaklık (km)"),
                ("ortalama_gunes_uzakligi_au", "Güneş'e uzaklık (AU)"),
                ("yildizina_uzakligi_au", "Ev sahibi yıldızına uzaklık (AU)"),
                ("yildiz", "Ev sahibi yıldız"),
                ("yoresindeki_cisim", "Yörüngesinde bulunduğu cisim"),
                ("yil_suresi_dunya_gunu", "Yörünge süresi (Dünya günü)"),
            ):
                deger = gezegen.get(alan)
                if deger is not None:
                    uzaklik_satirlari.append(f"{etiket}: {deger}")
            panel("ORBITAL DATA", uzaklik_satirlari or ["Bu kayıt için uzaklık/yörünge verisi bulunmuyor."], Renk.ACIK_MAVI)
        elif secim in {"3", "03"}:
            fizik_satirlari = []
            for alan, etiket in (
                ("yaricap_ekvator_km", "Ekvator yarıçapı (km)"),
                ("cap_km", "Çap (km)"),
                ("kutle_kg", "Kütle (kg)"),
                ("yogunluk_g_cm3", "Yoğunluk (g/cm³)"),
                ("yaricap_dunya", "Yarıçap (Dünya yarıçapı)"),
                ("kutle_dunya", "Kütle (Dünya kütlesi)"),
                ("kutle_jupiter", "Kütle (Jüpiter kütlesi)"),
            ):
                deger = gezegen.get(alan)
                if deger is not None:
                    fizik_satirlari.append(f"{etiket}: {deger}")
            panel("PHYSICAL DATA", fizik_satirlari or ["Bu kayıt için fiziksel ölçüm verisi bulunmuyor."], Renk.ACIK_MAVI)
        elif secim in {"4", "04"}:
            uydu = gezegen.get("uydu_sayisi")
            if uydu is not None:
                atlas_yaz(f"Kayıtlı doğal uydu sayısı: {uydu}")
            elif gezegen.get("uydu_bilgisi"):
                atlas_yaz(gezegen["uydu_bilgisi"])
            elif gezegen.get("yoresindeki_cisim"):
                atlas_yaz(f"{isim}, {gezegen['yoresindeki_cisim']} çevresinde dolanır.")
            elif gezegen.get("yildiz"):
                atlas_yaz(f"Ev sahibi yıldız: {gezegen['yildiz']}")
            else:
                bilgi_yaz("Bu kayıt için uydu/ev sahibi bilgisi bulunmuyor.")
        elif secim in {"5", "05"}:
            gezegen_detay_paneli(gezegen)
        elif secim in {"0", "00", "geri"}:
            atlas_yaz("Ana menüye dönülüyor...")
            return
        else:
            hata_yaz("Bu seçeneği tanıyamadım.")

        devam_icin_enter()



def gezegen_ara():
    clear()
    panel(
        "CELESTIAL BODY SEARCH",
        [
            "Veritabanında bulunan bir gök cismini arayın.",
            "Örnek: Mars, Plüton, Güneş, Proxima Centauri, Europa",
            "Ayrıca ötegezegen ve seçili doğal uydu kayıtlarını arayabilirsiniz.",
        ],
        Renk.ACIK_MAVI,
    )
    aranan_isim = input_al(f"\n{Renk.ACIK_MAVI}Gök cismi adı > {Renk.RESET}")
    if not aranan_isim:
        hata_yaz("Bir gök cismi adı girmediniz.")
        return

    yukleniyor("Astronomi kataloğu taranıyor")
    kayit = gezegen_bul(aranan_isim)
    if kayit is None:
        hata_yaz(f'"{aranan_isim}" adlı gök cismini bulamadım.')
        bilgi_yaz("Gezegen, cüce gezegen, yıldız veya seçili doğal uydu adı deneyin.")
        return

    atlas_yaz(f"{kayit.get('isim', aranan_isim)} veritabanımda bulundu.")
    gezegen_menusu(kayit)






def gezegen_sorgula(metin: str) -> None:
    temiz = metin_normalize(metin)
    varlik_anahtari = gezegen_ismi_cikar(metin)
    if varlik_anahtari is None:
        hata_yaz("Hangi gök cismi hakkında bilgi istediğinizi anlayamadım.")
        return

    kayit = gezegen_bul(varlik_anahtari)
    if kayit is None:
        hata_yaz("Bu gök cismi veritabanımda bulunamadı.")
        return

    isim = str(kayit.get("isim", varlik_anahtari))
    kategori = str(kayit.get("kategori", "Gök cismi"))
    yukleniyor("Gök cismi verileri analiz ediliyor")

    if any(ifade in temiz for ifade in ("tum bilgiler", "butun bilgiler", "hepsi", "detay", "ayrintili")):
        gezegen_detay_paneli(kayit)
        return

    # Uydu kaydının hangi gezegene bağlı olduğu, genel uydu sayısı kontrolünden önce ele alınır.
    if kategori == "Doğal uydu" and any(
        ifade in temiz for ifade in ("hangi gezegen", "neyin uydusu", "hangi cisim", "hangi gezegenin")
    ):
        atlas_yaz(f"{isim}, {kayit.get('yoresindeki_cisim', 'bilinmeyen bir gök cismi')} çevresinde dolanır.")
        return

    if "uydu" in temiz:
        uydu = kayit.get("uydu_sayisi")
        if uydu is None:
            atlas_yaz(kayit.get("uydu_bilgisi", f"{isim} için doğrulanmış uydu sayısı bu veritabanında bulunmuyor."))
        else:
            atlas_yaz(f"{isim} için kayıtlı doğal uydu sayısı: {uydu}.")
            if kayit.get("uydu_sayisi_notu"):
                bilgi_yaz(str(kayit["uydu_sayisi_notu"]))
            if kayit.get("uydu_sayisi_veri_tarihi"):
                bilgi_yaz(f"Veri tarihi: {kayit['uydu_sayisi_veri_tarihi']}")
        return

    if "hangi yildiz" in temiz or "ev sahibi yildiz" in temiz or "yildizinin adi" in temiz:
        yildiz = kayit.get("yildiz")
        if yildiz:
            atlas_yaz(f"{isim}, {yildiz} yıldızının çevresinde dolanır.")
        else:
            atlas_yaz(f"{isim} için ev sahibi yıldız bilgisi kayıtlı değil.")
        return

    if "yildiz" in temiz and any(kelime in temiz for kelime in ("uzak", "mesafe")):
        au = kayit.get("yildizina_uzakligi_au")
        if au is not None:
            atlas_yaz(f"{isim}, ev sahibi yıldızına ortalama {au} AU uzaklıktadır.")
        else:
            atlas_yaz(f"{isim} için yıldızına uzaklık bilgisi kayıtlı değil.")
        return

    if "dunya" in temiz and any(kelime in temiz for kelime in ("uzak", "mesafe")):
        uzaklik = kayit.get("dunyaya_uzakligi_km")
        isik_yili = kayit.get("uzaklik_dunya_isik_yili")
        if uzaklik is not None:
            uzaklik_metni = str(uzaklik)
            on_ek = "" if uzaklik_metni.casefold().startswith("yaklaşık") else "yaklaşık "
            ek = f" (yaklaşık {isik_yili} ışık yılı)" if isik_yili is not None else ""
            atlas_yaz(f"{isim}'in Dünya'ya uzaklığı {on_ek}{uzaklik_metni} km{ek}.")
        else:
            atlas_yaz(f"{isim} için Dünya'ya uzaklık bilgisi kayıtlı değil.")
        return

    if "gunes" in temiz and any(kelime in temiz for kelime in ("uzak", "mesafe", "kac")):
        uzaklik = kayit.get("gunes_uzakligi_km")
        au = kayit.get("ortalama_gunes_uzakligi_au")
        if uzaklik is None and kayit.get("ortalama_gunes_uzakligi_km") is not None:
            uzaklik = turkce_sayi_bicimle(Decimal(str(kayit["ortalama_gunes_uzakligi_km"])), 0)
        if uzaklik is not None:
            ek = f" (yaklaşık {au} AU)" if au is not None else ""
            atlas_yaz(f"{isim} adlı gök cisminin Güneş'e ortalama uzaklığı {uzaklik} km{ek}.")
        else:
            atlas_yaz(f"{isim} için Güneş'e uzaklık verisi bu kayıtta bulunmuyor.")
        return

    if "cap" in temiz and kayit.get("cap_km") is not None:
        atlas_yaz(f"{isim}'in çapı yaklaşık {kayit['cap_km']} km.")
        return

    if "yaricap" in temiz:
        yaricap = kayit.get("yaricap_ekvator_km", kayit.get("yaricap_dunya"))
        if yaricap is not None:
            birim = "Dünya yarıçapı" if kayit.get("yaricap_dunya") is not None else "km"
            atlas_yaz(f"{isim}'in yarıçapı yaklaşık {yaricap} {birim}.")
            return

    if "kutle" in temiz:
        kutle = kayit.get("kutle_kg", kayit.get("kutle_dunya", kayit.get("kutle_jupiter")))
        if kutle is not None:
            if kayit.get("kutle_dunya") is not None:
                birim = "Dünya kütlesi"
            elif kayit.get("kutle_jupiter") is not None:
                birim = "Jüpiter kütlesi"
            else:
                birim = "kg"
            atlas_yaz(f"{isim}'in kütlesi yaklaşık {kutle} {birim}.")
            return

    if "yogunluk" in temiz and kayit.get("yogunluk_g_cm3") is not None:
        atlas_yaz(f"{isim}'in ortalama yoğunluğu yaklaşık {kayit['yogunluk_g_cm3']} g/cm³.")
        return

    if any(kelime in temiz for kelime in ("yil", "yorunge", "periyot")):
        sure = kayit.get("yil_suresi_dunya_gunu")
        if sure is not None:
            atlas_yaz(f"{isim}'in yörünge süresi yaklaşık {sure} Dünya günüdür.")
            return

    atlas_yaz(f"{isim}, {kategori.lower()} kategorisinde kayıtlıdır.")
    if kayit.get("tur"):
        atlas_yaz(f"Türü: {kayit['tur']}.")
    if kayit.get("arsiv_durumu"):
        bilgi_yaz(f"NASA Exoplanet Archive durumu: {kayit['arsiv_durumu']}")
    atlas_yaz(kayit.get("aciklama", "Bu kayıt için ayrıntılı açıklama bulunmuyor."))




# ============================================================
# SOHBET OTURUMU VE TEMEL SOHBET YETENEĞİ
# ============================================================


def yeni_sohbet_baslat() -> None:
    """Yeni bir konuşma bağlamı başlatır; terminal geçmişini silmez."""
    # Kullanıcı adı profilden gelir; yeni sohbetlerde de korunur.
    SOHBET_BAGLAMI["kullanici_adi"] = kullanici_adi_getir()
    SOHBET_BAGLAMI["son_konu"] = None
    SOHBET_BAGLAMI["son_sohbet_konusu"] = None
    SOHBET_BAGLAMI["son_kullanici_mesaji"] = None
    SOHBET_BAGLAMI["dogal_yanit_gecmisi"] = {}
    SOHBET_BAGLAMI["sohbet_tonu"] = "dogal"
    SOHBET_BAGLAMI["yanit_uzunlugu"] = "normal"
    clear()
    panel(
        "YENİ SOHBET",
        [
            f"Yeni oturum: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}",
            "Önceki konuşma ekrandan silinmedi; terminal geçmişinde duruyor.",
            "Tam metin ayrıca sohbet_gecmisi.txt dosyasına kaydediliyor.",
            "Fare tekerleğiyle yukarı/aşağı kaydırarak geçmişe dönebilirsin.",
            "Nasıl yardımcı olabilirim?",
        ],
        Renk.YESIL,
    )


def _dogal_yanit_sec(kategori: str, secenekler: list[str] | tuple[str, ...]) -> str:
    """Aynı sohbet içinde aynı hazır cümlenin art arda gelmesini azaltır."""
    if not secenekler:
        return "Buradayım. Nasıl devam edelim?"

    gecmis = SOHBET_BAGLAMI.setdefault("dogal_yanit_gecmisi", {})
    oncekiler = gecmis.setdefault(kategori, [])
    uygunlar = [secenek for secenek in secenekler if secenek not in oncekiler]
    secilen = random.choice(uygunlar or list(secenekler))
    oncekiler.append(secilen)
    del oncekiler[:-3]

    # Kullanıcı kısa yanıt istediğinde sonraki sohbet yanıtlarını da kısalt.
    if SOHBET_BAGLAMI.get("yanit_uzunlugu") == "kisa":
        cumleler = re.split(r"(?<=[.!?])\s+", secilen.strip())
        if cumleler:
            secilen = cumleler[0]
        if len(secilen) > 190:
            secilen = secilen[:187].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"
    return secilen


def _dogal_sohbet_yaniti(kategori: str, secenekler: list[str] | tuple[str, ...], konu: str | None = None) -> str:
    """Yanıtı seçer ve kısa süreli konuşma bağlamını günceller."""
    SOHBET_BAGLAMI["son_sohbet_konusu"] = konu or kategori
    return _dogal_yanit_sec(kategori, secenekler)


def sohbet_yanitla(metin: str) -> str:
    """Yerel, kural tabanlı ama daha doğal ve bağlama duyarlı sohbet motoru.

    Bu motor bir büyük dil modeli değildir. Hazır yanıtları çeşitlendirir,
    temel duygu/niyet işaretlerini tanır ve konuşmanın son konusunu hatırlar.
    """
    ham = str(metin or "").strip()
    temiz = metin_normalize(ham)
    SOHBET_BAGLAMI["son_kullanici_mesaji"] = ham

    if not temiz:
        return _dogal_sohbet_yaniti("bos", [
            "Buradayım. Aklında ne varsa yazabilirsin.",
            "Bir şey sormak mı istedin? Yaz, birlikte bakalım.",
        ])

    # Kullanıcı adı sorusu, isim değiştirme yönlendiricisinden bağımsız çalışır.
    if any(ifade in temiz for ifade in ("adim ne", "benim adim ne", "ismim ne", "kullanici adim ne")):
        return f"Şu anda kullanıcı adın {kullanici_adi_getir()}. Bu bilgi server.json dosyasında kayıtlı."

    # Kullanıcı konuşma biçimini doğrudan ayarlayabilir.
    if any(ifade in temiz for ifade in ("daha samimi konus", "daha dogal konus", "resmi konusma", "robot gibi konusma", "daha insansi konus")):
        SOHBET_BAGLAMI["sohbet_tonu"] = "dogal"
        return _dogal_sohbet_yaniti("stil_dogal", [
            "Tamam, daha doğal ve rahat bir dil kullanacağım. Gereksiz resmiyetten kaçınırım; ama emin olmadığım bir şeyi de kesinmiş gibi anlatmam.",
            "Anlaştık. Bundan sonra daha akıcı, gündelik ve doğrudan konuşacağım. Bir şey belirsizse bunu açıkça söylerim.",
        ])

    if any(ifade in temiz for ifade in ("daha resmi konus", "resmi bir dil kullan", "daha ciddi yaz")):
        SOHBET_BAGLAMI["sohbet_tonu"] = "resmi"
        return _dogal_sohbet_yaniti("stil_resmi", [
            "Elbette. Bundan sonra daha resmî ve ölçülü bir dil kullanacağım.",
            "Anlaşıldı. Yanıtlarımı daha resmî, açık ve düzenli biçimde yazacağım.",
        ])

    if any(ifade in temiz for ifade in ("kisa cevap ver", "daha kisa yaz", "uzatma")):
        SOHBET_BAGLAMI["yanit_uzunlugu"] = "kisa"
        return "Tamam, bundan sonra daha kısa ve doğrudan yanıtlayacağım."

    if any(ifade in temiz for ifade in ("detayli cevap ver", "daha detayli yaz", "uzun anlat")):
        SOHBET_BAGLAMI["yanit_uzunlugu"] = "detayli"
        return "Peki, bundan sonra konuları daha ayrıntılı açıklayacağım. Gerektiğinde örnek de eklerim."

    # Selamlaşma: aynı selamı her seferinde aynı cümleyle karşılamaz.
    if temiz in {"merhaba", "selam", "hey", "sa", "gunaydin", "iyi gunler", "iyi aksamlar", "iyi geceler"} or temiz.startswith(("merhaba atlas", "selam atlas", "gunaydin atlas")):
        ad = kullanici_adi_getir()
        hitap = f" {ad}" if ad and ad != "Kullanıcı" and random.random() < 0.45 else ""
        secenekler = [
            f"Selam{hitap}! Neler oluyor? Bugün ne konuşalım?",
            f"Merhaba{hitap}. Buradayım; aklındaki konudan başlayabiliriz.",
            f"Hey{hitap}! Bugün nasıl gidiyor? Bir şey mi danışacaksın, yoksa biraz sohbet mi edelim?",
            f"Merhaba{hitap}! İstersen uzaydan konuşuruz, istersen günün nasıl geçtiğini anlatırsın.",
        ]
        return _dogal_sohbet_yaniti("selam", secenekler, "günün nasıl geçtiği")

    # Asistanın insan olmadığını saklamadan gündelik karşılık ver.
    if any(ifade in temiz for ifade in ("nasilsin", "naber", "ne haber", "iyi misin", "keyifler nasil")):
        return _dogal_sohbet_yaniti("nasilsin", [
            "Buradayım ve konuşmaya hazırım. Asıl sen nasılsın, günün nasıl geçiyor?",
            "İyiyim demek benim için tam olarak doğru olmaz; ama sistem olarak çalışıyorum ve sana yardımcı olmaya hazırım. Senin taraf nasıl?",
            "Her şey yolunda; sorularını bekliyorum. Sen nasılsın, bugün nasıl geçti?",
        ], "günün nasıl geçtiği")

    # Duygu ve günlük yaşam ifadeleri: öğüt vermek yerine önce karşılık ver, sonra alan aç.
    if any(ifade in temiz for ifade in ("cok kotuyum", "iyi degilim", "moralim bozuk", "uzgunum", "canim sikkin", "keyfim yok", "mutsuzum")):
        return _dogal_sohbet_yaniti("uzgun", [
            "Bunu yaşaman üzücü. İstersen ne olduğunu anlat; hemen çözüm önermek yerine önce ne yaşadığını anlamaya çalışayım.",
            "Zor bir gün geçiriyor gibisin. Seni en çok neyin yorduğunu anlatmak ister misin? Burada yargılamadan dinleyip düşüncelerini toparlamana yardımcı olabilirim.",
            "Üzgün hissettiğini anladım. Tek cümleyle geçiştirmek istemem. Ne oldu?",
        ], "kullanıcının moralinin bozuk olması")

    if any(ifade in temiz for ifade in ("yorgunum", "cok yoruldum", "bitkinim", "uykum var", "bugun cok yogundu")):
        return _dogal_sohbet_yaniti("yorgun", [
            "Yoğun geçmiş gibi. İstersen bugün neler yaptığını anlat; istersen de biraz daha hafif bir konudan konuşalım.",
            "Anladım, biraz nefes alma zamanı olabilir. Günün en yorucu kısmı neydi?",
            "O zaman seni uzun uzun sorularla yormayayım. İstersen kısa bir sohbet edelim ya da kafanı dağıtacak bir konu bulalım.",
        ], "yoğun geçen gün")

    if any(ifade in temiz for ifade in ("cok mutluyum", "mutluyum", "harika hissediyorum", "heyecanliyim", "cok guzel bir sey oldu", "basardim", "basardik")):
        return _dogal_sohbet_yaniti("mutlu", [
            "Güzel haber! Ne oldu, anlat bakalım.",
            "Bunu duymak güzel. Seni bu kadar sevindiren şey ne?",
            "Harika, paylaşmak ister misin? Nasıl gelişti?",
        ], "kullanıcının güzel bir gelişme yaşaması")

    if any(ifade in temiz for ifade in ("sikildim", "canim sikiliyor", "yapacak bir sey yok", "cok sikici")):
        return _dogal_sohbet_yaniti("sikinti", [
            "Biraz konu değiştirelim o zaman. Uzayla ilgili ilginç bir şey mi konuşalım, yoksa tamamen farklı bir konu mu seçelim?",
            "Olur, bazen insanın aklına yapacak bir şey gelmiyor. Sana kısa bir uzay bilmecesi sorayım mı, yoksa sohbet konusu mu bulalım?",
            "Kafanı dağıtalım. Teknoloji, filmler, oyunlar veya evren hakkında konuşabiliriz. Hangisi daha cazip geliyor?",
        ], "boş vakitte sohbet konusu aramak")

    if any(ifade in temiz for ifade in ("stresliyim", "gerginim", "sinavim var", "sinavdan korkuyorum", "yetistiremiyorum", "cok fazla is var")):
        return _dogal_sohbet_yaniti("stres", [
            "Üst üste binmiş gibi duruyor. İstersen işleri tek tek ayıralım; önce seni en çok zorlayan kısmı bulalım.",
            "Bu kadar şey aynı anda akıldayken bunalmış hissetmek anlaşılır. Şu an çözmemiz gereken ilk şey ne?",
            "Birlikte biraz düzenleyebiliriz. Önce yapılacakları yaz, sonra hangisinden başlamanın mantıklı olduğuna bakalım.",
        ], "kullanıcının yapmak istedikleri")

    # Basit olumlu/olumsuz cevaplar, önceki konuşma sorusunu dikkate alır.
    if temiz in {"iyiyim", "ben de iyiyim", "fena degil", "kotu degilim", "gayet iyiyim"}:
        return _dogal_sohbet_yaniti("iyi", [
            "Sevindim. Bugün güzel geçen bir şey oldu mu?",
            "Güzel, umarım günün böyle devam eder. Bugün neler yaptın?",
            "İyi olmana sevindim. Şu sıralar aklını en çok meşgul eden şey ne?",
        ], "günün nasıl geçtiği")

    if temiz in {"evet", "aynen", "dogru", "kesinlikle", "olabilir", "tamam"}:
        onceki = SOHBET_BAGLAMI.get("son_sohbet_konusu")
        if onceki:
            return _dogal_sohbet_yaniti("onay", [
                f"Tamam, o zaman {onceki} üzerinden devam edelim. Hangi kısmını biraz daha açmamı istersin?",
                f"Anlaştık. {onceki} konusunu biraz daha derinleştirebiliriz.",
            ], str(onceki))
        return _dogal_sohbet_yaniti("onay_genel", [
            "Peki. Buradan nasıl devam edelim?",
            "Tamamdır. Aklındaki diğer şeyi de sorabilirsin.",
        ])

    # Sohbete giriş ve paylaşım isteği.
    if any(ifade in temiz for ifade in ("sana bir sey anlatacagim", "bir sey anlatacagim", "sana bir sey soyleyecegim", "bir sey soracagim")):
        return _dogal_sohbet_yaniti("anlatma", [
            "Tabii, anlat. Önce seni dinleyeyim; sonra birlikte değerlendiririz.",
            "Buyur, buradayım. Aklındakini olduğu gibi yazabilirsin.",
            "Anlat bakalım. Ne olduğunu merak ettim.",
        ], "kullanıcının paylaşacağı konu")

    if any(ifade in temiz for ifade in ("sence", "ne dusunuyorsun", "fikrin ne", "sen olsan")):
        return _dogal_sohbet_yaniti("fikir", [
            "Birlikte tartabiliriz. Önce hangi seçenekler arasında kaldığını anlatır mısın?",
            "Fikrimi söyleyebilmem için biraz bağlam iyi olur. Durumu nasıl değerlendiriyorsun?",
            "Bunu birkaç açıdan ele alabiliriz. Senin için en önemli nokta hangisi?",
        ], "kullanıcının görüş istediği konu")

    if any(ifade in temiz for ifade in ("neden", "neden ki", "nasil yani", "peki neden", "biraz ac", "devam et")):
        onceki = SOHBET_BAGLAMI.get("son_sohbet_konusu")
        if onceki:
            return _dogal_sohbet_yaniti("takip", [
                f"Tabii. En son {onceki} konusundaydık. Hangi noktayı kastettiğini söylersen oradan açayım.",
                f"Biraz daha açalım. {onceki} ile ilgili hangi kısmı merak ettin?",
            ], str(onceki))
        return "Hangi kısmı kastettiğini bir cümleyle belirtir misin? Ona göre daha net açıklayayım."

    if any(ifade in temiz for ifade in ("tesekkur", "sag ol", "cok yardimci oldun", "eyvallah")):
        return _dogal_sohbet_yaniti("tesekkur", [
            "Rica ederim! Başka bir şeye takılırsan birlikte bakarız.",
            "Ne demek, yardımcı olabildiysem güzel. Devam etmek istediğin bir şey var mı?",
            "Her zaman. Bir sonraki sorunu da gönderebilirsin.",
        ])

    if any(ifade in temiz for ifade in ("sen kimsin", "adin ne", "kendini tanit", "kimsin")):
        return "Ben ATLAS AI. GÖK ATLAS projesi için geliştirilen yerel bir astronomi ve sohbet asistanıyım. Bu sürümde yanıtlarımı Python kuralları ve bilgisayarındaki server.json verilerinden oluşturuyorum; insan değilim ve her konuyu bir insan kadar serbestçe yorumlayamam. Yine de konuşmayı daha doğal sürdürmek ve bildiğim konularda yardımcı olmak için tasarlandım."

    if any(ifade in temiz for ifade in ("ne yapabilirsin", "neler yapabilirsin", "ne ise yariyorsun", "yardimci olabilir misin")):
        return "Gezegenleri, yıldızları, cüce gezegenleri, doğal uyduları ve uzay görevlerini sorgulayabilirim. Astronomi terimlerini açıklayabilir, ışık yılı-kilometre dönüşümü yapabilir ve gündelik konularda temel sohbet edebilirim. Daha samimi konuşmamı, kısa yanıt vermemi veya ayrıntılı anlatmamı da söyleyebilirsin."

    if any(ifade in temiz for ifade in ("kac yasindasin", "yas kac", "insan misin", "gercek misin")):
        return "Ben bir yapay zekâ yazılımıyım; insan değilim, bu yüzden gerçek bir yaşım veya kişisel hayatım yok. Ama sana daha doğal ve anlaşılır bir dille yanıt verebilirim."

    if any(ifade in temiz for ifade in ("internete bagli misin", "internete erisebiliyor musun", "canli verin var mi")):
        return "Bu sürüm yanıtlarını ağırlıklı olarak bilgisayarındaki server.json dosyasından üretir. Şu anda canlı internet bağlantısıyla bilgi aramıyorum; bu yüzden güncel veri gerektiren konularda bunu belirtirim."

    if any(ifade in temiz for ifade in ("saka yap", "bir saka anlat", "beni guldur")):
        return _dogal_sohbet_yaniti("saka", [
            "Astronom neden bilgisayarını uzaya gönderdi? Sabit diskinin kapasitesini galaksiler arası yapmak istiyordu!",
            "Bir kara delik neden sır saklayamaz? Çünkü her şeyi içine atar ama olay ufkunun ötesinde tutar!",
            "Astronomun en sevmediği şey ne? Işık yılı beklemek… Çünkü adı üstünde, biraz uzun sürüyor!",
        ])

    if any(ifade in temiz for ifade in ("motivasyon ver", "beni motive et", "moral ver")):
        return _dogal_sohbet_yaniti("motivasyon", [
            "Her şeyi aynı anda çözmen gerekmiyor. Bir sonraki küçük adımı seçmen yeterli; gerisi onun üzerine kurulur.",
            "İlerleme bazen yavaş görünür. Ama bugün öğrendiğin bir kavram veya düzelttiğin tek bir hata bile seni ileri taşır.",
            "Büyük projeler parça parça tamamlanır. Şu an yapabileceğin en küçük işe odaklan; başlamak çoğu zaman en zor kısımdır.",
        ])

    if any(ifade in temiz for ifade in ("ne konusalim", "konu oner", "sohbet edelim", "biraz sohbet")):
        return _dogal_sohbet_yaniti("konu_oner", [
            "Şöyle yapalım: uzayda yaşam arayışını, yapay zekânın geleceğini ya da izlediğin bir filmi konuşabiliriz. Hangisi daha çok ilgini çekiyor?",
            "Aklıma üç konu geldi: kara delikler, yeni uzay görevleri veya teknoloji. İstersen bambaşka bir konu da seçebiliriz.",
            "Bir konu seçmek zorunda değiliz. Gününün nasıl geçtiğinden başlayabiliriz; oradan sohbet kendiliğinden ilerler.",
        ])

    if any(ifade in temiz for ifade in ("anlamadim", "anlamiyorum", "daha basit anlat")):
        return _dogal_sohbet_yaniti("anlamama", [
            "Sorun değil, başka türlü anlatalım. Hangi kısmında koptun? Daha basit bir örnekle açıklayayım.",
            "Tabii. Açıklamayı sadeleştireyim; takıldığın cümleyi söylersen doğrudan oradan başlayayım.",
        ])

    if any(ifade in temiz for ifade in ("gorusuruz", "hosca kal", "kendine iyi bak")):
        return _dogal_sohbet_yaniti("veda", [
            "Görüşürüz! Sonra devam etmek istersen buradayım.",
            "Kendine iyi bak. Bir sonraki sohbette görüşürüz!",
            "Hoşça kal! ATLAS AI hazır olduğunda kaldığımız konuya yeniden dönebiliriz.",
        ])

    if any(ifade in temiz for ifade in ("bugun hangi gun", "bugunun tarihi", "tarih ne")):
        return f"Bilgisayarının yerel tarihine göre bugün {datetime.now().strftime('%d.%m.%Y')}."

    # Kişinin gündelik paylaşımında konuşmanın konusunu yakalamaya çalış.
    konu_eslesmeleri = [
        (("okul", "ders", "sinav", "ogretmen"), "okul ve dersler"),
        (("python", "kod", "program", "yazilim", "hata"), "yazılım ve kodlama"),
        (("gok atlas", "proje", "web sitesi", "site"), "GÖK ATLAS projesi"),
        (("uzay", "gezegen", "yildiz", "teleskop", "astronomi"), "astronomi ve uzay"),
        (("oyun", "playstation", "ps5"), "oyunlar"),
        (("film", "dizi", "izledim", "sinema"), "film ve diziler"),
        (("basketbol", "mac", "antrenman", "takim"), "basketbol"),
    ]
    for anahtarlar, konu in konu_eslesmeleri:
        if any(anahtar in temiz for anahtar in anahtarlar):
            return _dogal_sohbet_yaniti(f"paylasim_{konu}", [
                f"{konu.capitalize()} tarafında bir şeyler olmuş gibi. En çok hangi kısmı anlatmak istersin?",
                f"İlginç, {konu} hakkında konuşabiliriz. Bugün bununla ilgili ne yaşadın?",
                f"Anladım. {konu} konusunda aklında belirli bir şey mi var, yoksa gününden mi bahsediyorsun?",
            ], konu)

    # Son çare: konuşmayı kapatmayan, doğal bir açıklama isteği.
    return _dogal_sohbet_yaniti("anlasilamadi", [
        "Ne demek istediğini tam yakalayamadım. Biraz daha açar mısın? Nereden başlayacağımızı birlikte bulalım.",
        "Bunu biraz daha anlatırsan daha iyi karşılık verebilirim. Özellikle hangi kısmı konuşmak istiyorsun?",
        "Seni yanlış anlamak istemem. Biraz bağlam verir misin; ona göre daha net yanıtlayayım.",
    ], "açıklığa kavuşturulacak konu")


def onceki_konuyu_acikla() -> None:
    """Önceki katalog sorusunun daha ayrıntılı görünümünü açar."""
    onceki = SOHBET_BAGLAMI.get("son_konu")
    if not onceki:
        atlas_yaz("Henüz ayrıntılandırabileceğim bir konu yok. Önce bir gök cismi veya uzay terimi sorabilirsin.")
        return

    tur, anahtar = onceki
    if tur == "gok_cismi":
        kayit = gezegen_bul(str(anahtar))
        if kayit:
            gezegen_detay_paneli(kayit)
            return
    elif tur == "terim":
        uzay_terimi_sorgula(str(anahtar))
        return
    elif tur == "misyon":
        misyon_sorgula(str(anahtar))
        return

    atlas_yaz("Önceki konu kaydına şu anda erişemiyorum. Sorunu yeniden yazabilir misin?")


# ============================================================
# DOĞAL DİL KOMUT ANALİZİ
# ============================================================



def misyon_ismi_cikar(metin: str) -> str | None:
    temiz = metin_normalize(metin)
    misyonlar = veri_al("uzay_misyonlari")
    if not isinstance(misyonlar, dict):
        return None

    adaylar: list[tuple[str, str]] = []
    for anahtar, kayit in misyonlar.items():
        if not isinstance(kayit, dict):
            continue
        adlar = [str(anahtar), str(kayit.get("isim", anahtar))]
        alternatifler = kayit.get("alternatif_isimler", [])
        if isinstance(alternatifler, list):
            adlar.extend(str(ad) for ad in alternatifler if ad)
        adaylar.extend((str(anahtar), metin_normalize(ad)) for ad in adlar)

    padded = f" {temiz} "
    for anahtar, ad in sorted(adaylar, key=lambda item: len(item[1]), reverse=True):
        if ad and f" {ad} " in padded:
            return anahtar
    return None


def misyon_sorgula(metin: str) -> None:
    anahtar = misyon_ismi_cikar(metin)
    misyonlar = veri_al("uzay_misyonlari")
    if not anahtar or not isinstance(misyonlar, dict):
        hata_yaz("Hangi uzay görevini sorduğunuzu anlayamadım.")
        bilgi_yaz('Örnek: "Voyager 1 ne yaptı?" veya "Apollo 11 nedir?"')
        return

    kayit = misyonlar.get(anahtar)
    if not isinstance(kayit, dict):
        hata_yaz("Bu görev kaydı bulunamadı.")
        return

    isim = kayit.get("isim", anahtar)
    temiz = metin_normalize(metin)

    if any(kelime in temiz for kelime in ("ne zaman", "hangi yil", "firlatti", "fırlatıldı")):
        yil = kayit.get("fırlatma_yılı")
        if yil:
            atlas_yaz(f"{isim}, {yil} yılında fırlatıldı.")
            return

    panel(
        "SPACE MISSION DATABASE",
        [
            f"GÖREV       : {isim}",
            f"KATEGORİ    : {kayit.get('kategori', 'Belirtilmemiş')}",
            f"HEDEF       : {kayit.get('hedef', 'Belirtilmemiş')}",
            f"FIRLATMA    : {kayit.get('fırlatma_yılı', 'Bilgi yok')}",
            "",
            f"AÇIKLAMA    : {kayit.get('aciklama', 'Açıklama kaydı bulunmuyor.')}",
            "",
            f"KAYNAK      : {kayit.get('kaynak', 'Belirtilmemiş')}",
        ],
        Renk.MOR,
    )


def misyonlari_listele() -> None:
    misyonlar = veri_al("uzay_misyonlari")
    if not isinstance(misyonlar, dict) or not misyonlar:
        hata_yaz('Veritabanında "uzay_misyonlari" kaydı bulunamadı.')
        return

    satirlar = []
    for index, kayit in enumerate(misyonlar.values(), start=1):
        if isinstance(kayit, dict):
            satirlar.append(f"{index:02d}  {kayit.get('isim', 'İsimsiz görev')}")
    panel("SPACE MISSIONS", satirlar, Renk.MOR)


def katalog_listele(kategori: str) -> None:
    basliklar = {
        "gezegenler": ("PLANET DATABASE", "gezegenler"),
        "cucce_gezegenler": ("DWARF PLANET DATABASE", "cucce_gezegenler"),
        "yildizlar": ("STAR DATABASE", "yildizlar"),
        "dogal_uydular": ("NATURAL SATELLITE DATABASE", "dogal_uydular"),
    }
    if kategori not in basliklar:
        hata_yaz("Bilinmeyen katalog kategorisi.")
        return

    panel_basligi, veri_kategorisi = basliklar[kategori]
    kayitlar = veri_al(veri_kategorisi)
    if not isinstance(kayitlar, dict) or not kayitlar:
        hata_yaz(f'"{veri_kategorisi}" kategorisinde kayıt bulunamadı.')
        return

    satirlar = []
    for index, kayit in enumerate(kayitlar.values(), start=1):
        if isinstance(kayit, dict):
            isim = kayit.get("isim", "İsimsiz kayıt")
            tur = kayit.get("tur", "")
            satirlar.append(f"{index:02d}  {isim}" + (f" — {tur}" if tur else ""))
    panel(panel_basligi, satirlar, Renk.ACIK_MAVI)


def nlp_komut_analiz(metin: str) -> tuple[str, Any]:
    temiz = metin_normalize(metin)

    if not temiz:
        return "bos", None

    # Kullanıcı adı sorgusu / değiştirme komutları. Adın kendisini ham metinden
    # alıyoruz ki Türkçe karakterler ve büyük-küçük harfler korunsun.
    if temiz in {
        "adim ne", "benim adim ne", "ismim ne", "kullanici adim ne",
        "kullanici ismim ne", "ben kimim",
    }:
        return "kullanici_adi_sorgula", None

    ham_kelimeler = str(metin or "").strip().split()
    norm_kelimeler = [metin_normalize(kelime) for kelime in ham_kelimeler]
    isim_on_ekleri = [
        ["kullanici", "adimi", "degistir"],
        ["kullanici", "adini", "degistir"],
        ["adimi", "degistir"],
        ["isim", "degistir"],
        ["benim", "adim"],
        ["isim"],  # /isim komutu, aşağıda yalnızca tek başına veya argümanlı kullanım
    ]
    for on_ek in isim_on_ekleri:
        if norm_kelimeler[:len(on_ek)] == on_ek:
            kalan = " ".join(ham_kelimeler[len(on_ek):]).strip()
            if on_ek == ["isim"] and ham_kelimeler and not ham_kelimeler[0].startswith("/"):
                continue
            if kalan.casefold() in {"degistir", "değiştir"} and on_ek == ["isim"]:
                kalan = ""
            return "kullanici_adi_degistir", kalan or None

    if ham_kelimeler and ham_kelimeler[0].casefold() in {"/isim", "/ad"}:
        kalan = " ".join(ham_kelimeler[1:]).strip()
        return "kullanici_adi_degistir", kalan or None

    yeni_sohbet_komutlari = {
        "yeni sohbet", "yeni sohbet baslat", "sohbeti yenile", "sohbeti sifirla",
        "yeni konusma", "yeni oturum", "yeni", "/yeni", "/new", "new chat",
    }
    if temiz in yeni_sohbet_komutlari:
        return "yeni_sohbet", None

    devam_komutlari = (
        "bunu daha detayli anlat", "biraz daha detay", "daha fazla bilgi ver",
        "bunun hakkinda daha fazla bilgi", "biraz daha acikla", "devam et",
        "tum ayrintilari anlat", "detaylandir",
    )
    if any(ifade in temiz for ifade in devam_komutlari):
        return "onceki_konu", None

    kapatma = {
        "0", "kapat", "sistemi kapat", "programi kapat", "cikis",
        "cik", "cikis yap", "programdan cik",
    }
    if temiz in kapatma:
        return "kapat", None

    if temiz in {"1", "gezegen ara", "gezegen arastir", "gezegen arastirma", "gezegenleri arastir", "bir gezegen arastir"}:
        return "gezegen_ara", None

    if temiz in {"2", "isik yili hesapla", "isik yili hesaplayici", "mesafe hesapla", "mesafe hesaplayici"}:
        return "isik_yili_menu", None

    if temiz in {"3", "terim ara", "uzay terimi ara"}:
        return "terim_ara", None

    if temiz in {"4", "gezegen listesi", "gezegenleri listele", "gezegenler", "kayitli gezegenler"}:
        return "gezegen_listesi", None

    if temiz in {"5", "uzay gorevleri", "uzay gorevlerini listele", "uzay gorevleri listesi", "misyonlar", "uzay misyonlari", "gorevleri listele", "misyonlari listele"}:
        return "misyon_listesi", None

    liste_komutlari = {
        "cucce_gezegenler": {"cuce gezegenler", "cuce gezegenleri listele", "cuce gezegen listesi", "cuce gezegenlerini listele"},
        "yildizlar": {"yildizlar", "yildizlari listele", "yildiz listesi"},
        "dogal_uydular": {"dogal uydular", "dogal uydulari listele", "dogal uydulari goster", "uydulari listele", "uydu listesi"},
    }
    for kategori, komutlar in liste_komutlari.items():
        if temiz in komutlar:
            return "katalog_listesi", kategori

    has_light_year = "isik yil" in temiz
    has_km = " km" in f" {temiz}" or "kilometre" in temiz
    conversion_words = any(
        word in temiz.split()
        for word in ("kac", "cevir", "cevirin", "donustur", "hesapla", "hesaplayalim")
    )
    direction_phrase = any(
        phrase in temiz
        for phrase in (
            "kmye", "km ye", "kilometreye", "kilometre ye",
            "kmden", "kilometreden", "isik yilindan", "isik yilina",
            "kac km", "kac isik yil", "cinsinden",
        )
    )
    if has_light_year and has_km and (conversion_words or direction_phrase):
        return "isik_yili", temiz


    bilgi_kategori_komutlari = {
        "gunes_sistemi": (
            "rastgele gunes sistemi bilgisi", "gunes sistemi hakkinda rastgele bilgi",
            "gezegenler hakkinda rastgele bilgi", "rastgele gezegen bilgisi",
        ),
        "yildizlar": (
            "rastgele yildiz bilgisi", "yildizlar hakkinda rastgele bilgi",
        ),
        "galaksiler_kozmoloji": (
            "rastgele galaksi bilgisi", "evren hakkinda rastgele bilgi",
            "kozmoloji hakkinda bilgi ver",
        ),
        "kara_delikler_gorecelilik": (
            "rastgele kara delik bilgisi", "kara delikler hakkinda rastgele bilgi",
            "gorecelilik hakkinda rastgele bilgi",
        ),
        "otegezegenler_yasam": (
            "rastgele otegezegen bilgisi", "otegezegenler hakkinda rastgele bilgi",
            "yasam arastirmalari hakkinda bilgi",
        ),
        "uzay_araclari_gorevler": (
            "rastgele uzay gorevi bilgisi", "uzay araclari hakkinda rastgele bilgi",
            "uzay gorevleri hakkinda bilgi ver",
        ),
        "astronomi_fizik": (
            "rastgele astronomi bilgisi", "rastgele astrofizik bilgisi",
            "astronomi fizigi hakkinda bilgi",
        ),
    }
    for kategori, komutlar in bilgi_kategori_komutlari.items():
        if any(komut in temiz for komut in komutlar):
            return "rastgele_bilgi_kategori", kategori

    bilgi_komutlari = (
        "rastgele bilgi", "rastgele uzay bilgisi", "uzay bilgisi ver",
        "bana uzay bilgisi ver", "uzay hakkinda bilgi ver",
        "bir uzay bilgisi soyle", "uzaydan bir bilgi ver",
    )
    if any(komut in temiz for komut in bilgi_komutlari):
        return "rastgele_bilgi", None

    rastgele_terim_komutlari = {"rastgele uzay terimi", "rastgele terim", "bir terim soyle"}
    if temiz in rastgele_terim_komutlari:
        return "rastgele_terim", None

    terim_menu_komutlari = (
        "uzay terimleri", "uzay terimleri sozlugu", "terimler",
        "astronomi terimleri", "terim sozlugu", "uzay terimi soyle",
    )
    if any(komut == temiz for komut in terim_menu_komutlari):
        return "terim_ara", None

    yardim_komutlari = {"yardim", "ne yapabilirsin", "komutlar", "ana menu", "menu", "yardim et"}
    if temiz in yardim_komutlari:
        return "yardim", None

    if temiz in {"sistem durumu", "durum", "sistem bilgisi"}:
        return "sistem_durumu", None

    # Önce kayıtlı gök cisimlerini ve görevleri kontrol et.
    varlik = gezegen_ismi_cikar(metin)
    if varlik is not None:
        return "gezegen", varlik

    misyon = misyon_ismi_cikar(metin)
    if misyon is not None:
        return "uzay_misyonu", misyon

    terim = uzay_terimi_ismi_cikar(metin)
    if terim is not None:
        return "uzay_terimi", terim

    return "bilinmiyor", None



# ============================================================
# YARDIM VE MENÜLER
# ============================================================



def yardim_goster() -> None:
    clear()
    panel(
        "ATLAS COMMAND INTERFACE",
        [
            f"{Renk.MAVI}GÖK CİSİMLERİ{Renk.RESET}",
            '  • "Mars hakkında bilgi ver"',
            '  • "Jüpiterin kaç uydusu var"',
            '  • "Proxima Centauri b hangi yıldızın çevresinde?"',
            '  • "Plüton nedir?"',
            '  • "Europa hangi gezegenin uydusu?"',
            '  • "Güneş nedir?"',
            "",
            f"{Renk.MAVI}ASTRONOMİ VE FİZİK{Renk.RESET}",
            '  • "Radyal hız yöntemi nedir?"',
            '  • "Olay ufku nedir?"',
            '  • "Bortle ölçeği nedir?"',
            '  • "5 ışık yılını kmye çevir"',
            "",
            f"{Renk.MAVI}UZAY GÖREVLERİ{Renk.RESET}",
            '  • "Voyager 1 ne yaptı?"',
            '  • "Apollo 11 ne zaman fırlatıldı?"',
            '  • "Uzay görevlerini listele"',
            "",
            f"{Renk.MAVI}KATALOGLAR{Renk.RESET}",
            '  • "Gezegenleri listele"',
            '  • "Cüce gezegenleri listele"',
            '  • "Yıldızları listele"',
            '  • "Doğal uyduları listele"',
            '  • "Rastgele yıldız bilgisi"',
            '  • "Rastgele kara delik bilgisi"',
            "",
            f"{Renk.MAVI}SİSTEM{Renk.RESET}",
            '  • "Rastgele uzay bilgisi ver"',
            '  • "Rastgele uzay terimi"',
            '  • "Sistem durumu" / "Yardım" / "Sistemi kapat"',
            "",
            f"{Renk.MAVI}SOHBET{Renk.RESET}",
            '  • "Merhaba" / "Nasılsın?" / "Sen kimsin?"',
            '  • "Benim adım ..." (bu sohbet içinde hatırlanır)',
            '  • "Bunu daha detaylı anlat" (son katalog konusu)',
            '  • "Yeni sohbet" veya "/yeni" (ekranı silmeden bağlamı sıfırlar)',
            "",
            "SAYISAL KISAYOLLAR",
            "  1  Gök cismi ara",
            "  2  Işık yılı hesaplayıcı",
            "  3  Uzay terimi ara",
            "  4  Gezegenleri listele",
            "  5  Uzay görevleri",
            "  0  Sistemi kapat",
            "",
            "GEÇMİŞ: Terminalde fare tekerleğiyle yukarı/aşağı kaydır.",
        ],
        Renk.ACIK_MAVI,
    )
    devam_icin_enter()



def terim_menusu() -> None:
    clear()
    panel(
        "SPACE TERMINOLOGY DATABASE",
        [
            "ATLAS uzay terimleri veritabanına erişildi.",
            "",
            'Örnek: "Olay ufku nedir?"',
            'Örnek: "Parsek nedir?"',
            'Örnek: "Astronomi ne demek?"',
        ],
        Renk.ACIK_MAVI,
    )
    terim = input_al(f"\n{Renk.ACIK_MAVI}Terim > {Renk.RESET}")
    if terim:
        uzay_terimi_sorgula(terim)
        devam_icin_enter()


def rastgele_terim_goster() -> None:
    terimler = veri_al("uzay_terimleri")
    if not isinstance(terimler, dict) or not terimler:
        hata_yaz('Veritabanında "uzay_terimleri" kaydı bulunamadı.')
        return

    isim = random.choice(list(terimler.keys()))
    uzay_terimi_sorgula(isim)


def acilis_ekrani() -> bool:
    clear()
    if not GUI_MODE:
        yukleniyor("Yerel uzay veritabanına bağlanılıyor", tekrar=4)
    if VERITABANI is None:
        hata_yaz("Veritabanı yüklenemedi. Sistem başlatılamıyor.")
        bilgi_yaz("server.json dosyasını ATLAS_AI.py ile aynı klasöre koy.")
        return False

    atlas_yaz("Veritabanı bağlantısı başarılı.")
    return True


def ana_menu() -> None:
    if not acilis_ekrani():
        return

    atlas_yaz(
        f"Merhaba {kullanici_adi_getir()}. Kullanıcı adını değiştirmek için '/isim YeniAd' "
        "veya 'kullanıcı adımı değiştir' komutunu kullanabilirsin."
    )

    if GUI_MODE:
        # Dört üst kart GUI tarafından oluşturulur ve sabit tutulur.
        bilgiler = veri_al("uzay_bilgileri")
        if isinstance(bilgiler, list) and bilgiler:
            GUI_UI_QUEUE.put(("random", random.choice(bilgiler)))
    else:
        baslik()
        durum_satiri()
        panel(
            "ATLAS CHAT CONSOLE",
            [
                "Komutlarını aşağıdaki isteme yaz; önceki mesajlar silinmez.",
                "Fare tekerleği ile önceki mesajlara yukarı/aşağı kaydırarak dönebilirsin.",
                "Yeni sohbet başlatmak için: yeni sohbet  |  /yeni",
                "Çıkış için: sistemi kapat",
                "Sohbet günlüğü: sohbet_gecmisi.txt (kalıcı metin kaydı)",
            ],
            Renk.ACIK_MAVI,
        )
        uzay_bilgileri()

    while True:
        try:
            komut = input_al(f"\n{Renk.ACIK_MAVI}>{kullanici_adi_getir()} {Renk.RESET}")
        except EOFError:
            atlas_yaz("Girdi akışı kapandı. Sistem sonlandırılıyor.")
            return

        kullanici_mesajini_kaydet(komut)
        niyet, veri = nlp_komut_analiz(komut)

        try:
            if niyet == "bos":
                continue
            if niyet == "kapat":
                atlas_yaz("Sistem sonlandırılıyor...")
                bekle(0.35)
                atlas_yaz("Yerel bağlantılar kapatıldı. Görüşmek üzere.")
                return
            if niyet == "yeni_sohbet":
                yeni_sohbet_baslat()
                continue
            if niyet == "kullanici_adi_sorgula":
                atlas_yaz(f"Kullanıcı adın {kullanici_adi_getir()}. Bu isim server.json dosyasında kayıtlı.")
                continue
            if niyet == "kullanici_adi_degistir":
                yeni_ad = veri
                if not yeni_ad:
                    yeni_ad = input_al(f"\n{Renk.ACIK_MAVI}Yeni kullanıcı adı > {Renk.RESET}")
                kullanici_adi_degistir(str(yeni_ad))
                continue
            if niyet == "onceki_konu":
                onceki_konuyu_acikla()
                continue
            if niyet == "gezegen_ara":
                gezegen_ara()
            elif niyet == "gezegen":
                SOHBET_BAGLAMI["son_konu"] = ("gok_cismi", str(veri))
                gezegen_sorgula(komut)
            elif niyet == "gezegen_listesi":
                gezegenleri_listele()
            elif niyet == "misyon_listesi":
                misyonlari_listele()
            elif niyet == "katalog_listesi":
                katalog_listele(str(veri))
            elif niyet == "uzay_misyonu":
                SOHBET_BAGLAMI["son_konu"] = ("misyon", str(veri))
                misyon_sorgula(komut)
            elif niyet == "isik_yili_menu":
                isik_yili_hesaplayici()
            elif niyet == "isik_yili":
                isik_yili_hesaplayici(str(veri))
            elif niyet == "uzay_terimi":
                SOHBET_BAGLAMI["son_konu"] = ("terim", str(veri))
                uzay_terimi_sorgula(komut)
            elif niyet == "terim_ara":
                terim_menusu()
            elif niyet == "rastgele_terim":
                rastgele_terim_goster()
            elif niyet == "rastgele_bilgi":
                uzay_bilgileri()
            elif niyet == "rastgele_bilgi_kategori":
                uzay_bilgileri(str(veri))
            elif niyet == "yardim":
                yardim_goster()
            elif niyet == "sistem_durumu":
                sistem_durumu()
            else:
                yanit = sohbet_yanitla(komut)
                atlas_yaz(yanit)
        except EOFError:
            atlas_yaz("Girdi akışı kapandı. Sistem sonlandırılıyor.")
            return
        except KeyboardInterrupt:
            print()
            atlas_yaz("Klavye kesintisi algılandı. Sistem güvenli şekilde kapatılıyor.")
            return
        except Exception as hata:
            hata_yaz(f"Bu komut işlenirken beklenmeyen bir hata oluştu: {hata}")
            bilgi_yaz("Diğer komutlarla devam edebilirsin; sohbet geçmişi korunuyor.")


def main() -> None:
    global VERITABANI, SOHBET_KAYDI

    orijinal_stdout = sys.stdout
    kayit_dosyasi = None
    try:
        if os.environ.get("ATLAS_SAVE_HISTORY", "1") != "0":
            kayit_dosyasi = SOHBET_GECMISI_DOSYASI.open("a", encoding="utf-8")
            SOHBET_KAYDI = kayit_dosyasi
            sys.stdout = KonsolVeDosya(orijinal_stdout, kayit_dosyasi)
            oturum_satiri = f"ATLAS AI OTURUMU | {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
            kayit_dosyasi.write("\n" + "=" * GENISLIK + "\n" + oturum_satiri + "\n" + "=" * GENISLIK + "\n")
            kayit_dosyasi.flush()
            if not GUI_MODE:
                print("\n" + "=" * GENISLIK)
                print(oturum_satiri)
                print("=" * GENISLIK)

        VERITABANI = veritabani_yukle()
        if VERITABANI is not None:
            kullanici_profili_yukle()
        ana_menu()
    except KeyboardInterrupt:
        print()
        atlas_yaz("Sistem kullanıcı tarafından durduruldu.")
    except Exception as hata:
        hata_yaz(f"Beklenmeyen bir hata oluştu: {hata}")
        bilgi_yaz("Hata devam ederse terminal çıktısını ve server.json yapısını kontrol et.")
    finally:
        try:
            sys.stdout.flush()
        except Exception:
            pass
        sys.stdout = orijinal_stdout
        SOHBET_KAYDI = None
        if kayit_dosyasi is not None:
            kayit_dosyasi.close()


# ============================================================
# SABİT ÜST PANELLİ TKINTER ARAYÜZÜ
# ============================================================


class TkQueueWriter:
    """Arka plan iş parçacığından gelen çıktıyı GUI kuyruğuna aktarır."""

    def __init__(self, hedef_kuyruk: queue.Queue[tuple[str, str]]) -> None:
        self.hedef_kuyruk = hedef_kuyruk

    def write(self, veri: str) -> int:
        if veri:
            self.hedef_kuyruk.put(("output", veri))
        return len(veri)

    def flush(self) -> None:
        return

    def isatty(self) -> bool:
        return False

    @property
    def encoding(self) -> str:
        return "utf-8"



def gui_baslat() -> None:
    """Koyu uzay temalı arayüz: üst paneller sabit, yalnızca sohbet alanı kayar."""
    global GUI_MODE, ANIMASYON_AKTIF

    try:
        import tkinter as tk
        import tkinter.font as tkfont
        import math
    except Exception as hata:
        print(f"Grafik arayüzü yüklenemedi: {hata}")
        print("Terminal sürümünü başlatmak için ATLAS_INTERFACE=terminal kullan.")
        return

    GUI_MODE = True
    ANIMASYON_AKTIF = False

    # Tüm arayüz renkleri altı haneli HEX (#RRGGBB) biçimindedir.
    THEME = {
        "background": "#03050B",
        "panel": "#080E1B",
        "panel_alt": "#0B1424",
        "panel_deep": "#050A13",
        "border": "#1D2C45",
        "border_hover": "#2B496B",
        "text": "#EAF2FF",
        "muted": "#8FA2BA",
        "accent": "#57C7FF",
        "accent_soft": "#8B83FF",
        "success": "#5CE0A0",
        "warning": "#F4C96B",
        "danger": "#FF718A",
        "button": "#123B5B",
        "button_hover": "#1A567F",
        "input": "#060C17",
        "selection": "#21496B",
        "assistant": "#D8E5F7",
        "user": "#71D7FF",
    }

    try:
        root = tk.Tk()
    except tk.TclError as hata:
        GUI_MODE = False
        print(f"Grafik arayüzü başlatılamadı: {hata}")
        print("Terminal moduna geçiliyor.")
        main()
        return

    # Font seçimi: modern fontlar varsa onları kullan, yoksa Windows varsayılanlarına dön.
    try:
        mevcut_fontlar = set(tkfont.families(root))
    except tk.TclError:
        mevcut_fontlar = set()

    def font_sec(*adaylar: str) -> str:
        for aday in adaylar:
            if not mevcut_fontlar or aday in mevcut_fontlar:
                return aday
        return "TkDefaultFont"

    FONT_HEADING = font_sec("Bahnschrift", "Aptos Display", "Segoe UI")
    FONT_BODY = font_sec("Aptos", "Segoe UI Variable", "Segoe UI")
    FONT_MONO = font_sec("Cascadia Code", "JetBrains Mono", "Consolas")

    root.title("ATLAS AI | Astronomy & Space Intelligence System")

    # GÖK ATLAS uygulama simgesi. ICO dosyası PyInstaller paketi içine eklenir.
    icon_candidates = (
        RESOURCE_DIR / "gokatlasico.ico",
        APP_DIR / "gokatlasico.ico",
    )
    app_icon = next((path for path in icon_candidates if path.is_file()), None)
    if app_icon is not None:
        try:
            root.iconbitmap(default=str(app_icon))
        except tk.TclError:
            # Simge yüklenemezse uygulama çalışmaya devam etsin.
            pass
    root.geometry("1280x920")
    root.minsize(940, 700)
    root.configure(bg=THEME["background"])

    # Arka plan görseli: EXE içine paketlenen salt-okunur kaynak klasöründen yüklenir.
    background_canvas = tk.Canvas(
        root, bg=THEME["background"], bd=0, highlightthickness=0,
        relief="flat", takefocus=0,
    )
    background_canvas.place(x=0, y=0, relwidth=1, relheight=1)
    background_image = None
    background_image_id = None
    # Görsel ve varsayılan server.json PyInstaller kaynaklarında; kullanıcı
    # veritabanı ve sohbet günlüğü ise USER_DATA_DIR altında tutulur.
    background_candidates = (
        RESOURCE_DIR / "assets" / "atlas_nebula_background.png",
        APP_DIR / "assets" / "atlas_nebula_background.png",
    )
    background_path = next(
        (aday for aday in background_candidates if aday.is_file()),
        background_candidates[0],
    )
    if background_path.is_file():
        try:
            background_image = tk.PhotoImage(file=str(background_path))
            background_image_id = background_canvas.create_image(
                0, 0, image=background_image, anchor="center", tags=("wallpaper",)
            )
            # PhotoImage referansını Python çöp toplayıcısından koru.
            root._atlas_background_image = background_image
        except tk.TclError:
            background_image = None
            background_image_id = None

    def arka_plani_hizala(event: Any) -> None:
        if background_image_id is not None:
            background_canvas.coords(
                background_image_id, event.width // 2, event.height // 2
            )

    background_canvas.bind("<Configure>", arka_plani_hizala)

    # Rounded-card yüzeyi. Tkinter'de yerleşik rounded Frame olmadığı için
    # Canvas üzerinde çokgen tabanlı, yumuşak köşeli kart çizilir.
    def yuvarlak_kart(
        parent: Any,
        height: int | None = None,
        fill: str | None = None,
        outline: str | None = None,
        radius: int = 18,
    ) -> tuple[Any, Any]:
        fill_color = fill or THEME["panel"]
        outline_color = outline or THEME["border"]
        canvas = tk.Canvas(
            parent,
            bg=THEME["background"],
            bd=0,
            highlightthickness=0,
            relief="flat",
            height=height or 180,
        )
        content = tk.Frame(canvas, bg=fill_color, bd=0, highlightthickness=0)
        window_id = canvas.create_window(
            14, 14, window=content, anchor="nw", tags=("content",)
        )

        def rounded_points(x1: float, y1: float, x2: float, y2: float, r: float):
            points = []
            # Dört köşe için 9 noktalı yay; düzgün ve hafif yuvarlak bir görünüm.
            corners = [
                (x2 - r, y1 + r, -90, 0),
                (x2 - r, y2 - r, 0, 90),
                (x1 + r, y2 - r, 90, 180),
                (x1 + r, y1 + r, 180, 270),
            ]
            for cx, cy, angle_start, angle_end in corners:
                for index in range(9):
                    angle = math.radians(
                        angle_start + (angle_end - angle_start) * index / 8
                    )
                    points.extend((cx + r * math.cos(angle), cy + r * math.sin(angle)))
            return points

        def redraw(event: Any) -> None:
            width = max(40, event.width)
            height_now = max(40, event.height)
            canvas.delete("card-surface")
            inset = 2
            r = min(radius, max(8, min(width, height_now) / 5))
            canvas.create_polygon(
                *rounded_points(inset, inset, width - inset, height_now - inset, r),
                fill=fill_color,
                outline=outline_color,
                width=1,
                smooth=False,
                tags=("card-surface",),
            )
            canvas.coords(window_id, 14, 12)
            canvas.itemconfigure(
                window_id,
                width=max(1, width - 28),
                height=max(1, height_now - 24),
            )
            canvas.tag_lower("card-surface")

        canvas.bind("<Configure>", redraw)
        return canvas, content

    def kart_basligi(parent: Any, text: str, accent: str = "accent") -> Any:
        label = tk.Label(
            parent,
            text=text,
            bg=THEME["panel"],
            fg=THEME[accent],
            font=(FONT_HEADING, 9, "bold"),
            anchor="w",
        )
        label.pack(fill="x", padx=3, pady=(1, 7))
        return label

    # Ana ızgara: üstteki dört panel ve alt giriş alanı sabit; yalnızca sohbet metni kayar.
    root.columnconfigure(0, weight=1)
    root.rowconfigure(4, weight=1)

    # 1) ATLAS AI OTURUMU
    session_card, session_body = yuvarlak_kart(root, height=76)
    session_card.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 6))
    kart_basligi(session_body, "ATLAS AI OTURUMU", "success")
    session_text = tk.Label(
        session_body,
        text=(
            f"● ONLINE     |     LOCAL DATABASE     |     USER: {kullanici_adi_getir()}"
            f"     •     {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
        ),
        bg=THEME["panel"],
        fg=THEME["muted"],
        font=(FONT_BODY, 9),
        anchor="w",
    )
    session_text.pack(fill="x", padx=3, pady=(0, 2))

    # 2) ATLAS AI başlık bandı
    title_card, title_body = yuvarlak_kart(
        root, height=122, fill=THEME["panel_alt"], outline=THEME["border_hover"], radius=22
    )
    title_card.grid(row=1, column=0, sticky="ew", padx=16, pady=6)
    tk.Label(
        title_body,
        text="ATLAS AI",
        bg=THEME["panel_alt"],
        fg=THEME["accent"],
        font=(FONT_HEADING, 27, "bold"),
    ).pack(pady=(7, 0))
    tk.Label(
        title_body,
        text="ASTRONOMY & SPACE INTELLIGENCE SYSTEM",
        bg=THEME["panel_alt"],
        fg=THEME["text"],
        font=(FONT_HEADING, 10, "bold"),
    ).pack(pady=(1, 8))

    # 3) ATLAS CHAT CONSOLE ve 4) RANDOM SPACE DATA
    cards_row = tk.Frame(root, bg=THEME["background"], bd=0, highlightthickness=0)
    cards_row.grid(row=2, column=0, sticky="ew", padx=16, pady=6)
    cards_row.columnconfigure(0, weight=1, uniform="headercards")
    cards_row.columnconfigure(1, weight=1, uniform="headercards")

    console_card, console_body = yuvarlak_kart(cards_row, height=146)
    console_card.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
    kart_basligi(console_body, "ATLAS CHAT CONSOLE")
    tk.Label(
        console_body,
        text=(
            "Komutlarını aşağıdaki sohbet alanına yaz.\n"
            "Yeni sohbet:  yeni sohbet  veya  /yeni\n"
            "Kullanıcı adı:  /isim YeniAd     •     Yardım:  yardım\n"
            "Çıkış:  sistemi kapat"
        ),
        bg=THEME["panel"],
        fg=THEME["muted"],
        font=(FONT_BODY, 9),
        justify="left",
        anchor="w",
    ).pack(fill="both", expand=True, padx=3, pady=(0, 3))

    random_card, random_body = yuvarlak_kart(cards_row, height=146)
    random_card.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
    kart_basligi(random_body, "RANDOM SPACE DATA", "warning")
    random_label = tk.Label(
        random_body,
        text="Yerel veritabanından astronomi bilgisi yükleniyor...",
        bg=THEME["panel"],
        fg=THEME["text"],
        font=(FONT_BODY, 9),
        justify="left",
        anchor="nw",
        wraplength=500,
    )
    random_label.pack(fill="both", expand=True, padx=3, pady=(0, 3))
    random_card.bind(
        "<Configure>",
        lambda event: random_label.configure(wraplength=max(250, event.width - 55)),
        add="+",
    )

    # SOHBET GEÇMİŞİ kartı: sabit başlık, kaydırılan tek bileşen Text alanıdır.
    chat_card, chat_body = yuvarlak_kart(root, fill=THEME["panel"])
    chat_card.grid(row=4, column=0, sticky="nsew", padx=16, pady=(6, 8))
    chat_body.rowconfigure(1, weight=1)
    chat_body.columnconfigure(0, weight=1)
    tk.Label(
        chat_body,
        text="SOHBET GEÇMİŞİ",
        bg=THEME["panel"],
        fg=THEME["accent"],
        font=(FONT_HEADING, 9, "bold"),
        anchor="w",
    ).grid(row=0, column=0, sticky="ew", padx=3, pady=(1, 8))

    transcript_wrap = tk.Frame(chat_body, bg=THEME["panel"], bd=0, highlightthickness=0)
    transcript_wrap.grid(row=1, column=0, sticky="nsew", padx=2, pady=(0, 2))
    transcript_wrap.rowconfigure(0, weight=1)
    transcript_wrap.columnconfigure(0, weight=1)

    transcript = tk.Text(
        transcript_wrap,
        wrap="word",
        state="disabled",
        undo=False,
        bg=THEME["panel_deep"],
        fg=THEME["assistant"],
        insertbackground=THEME["accent"],
        selectbackground=THEME["selection"],
        selectforeground=THEME["text"],
        relief="flat",
        bd=0,
        highlightthickness=1,
        highlightbackground=THEME["border"],
        highlightcolor=THEME["accent"],
        font=(FONT_BODY, 10),
        padx=16,
        pady=14,
        spacing1=3,
        spacing3=5,
    )
    # Yazma animasyonu sırasında otomatik kaydırma yalnızca kullanıcı en alttaysa
    # çalışır. Kullanıcı geçmişi incelerken metin onu zorla aşağı çekmez.
    otomatik_asagi = {"aktif": True}

    def sohbet_kaydir(*args: Any) -> None:
        transcript.yview(*args)
        otomatik_asagi["aktif"] = transcript.yview()[1] >= 0.985

    scrollbar = tk.Scrollbar(
        transcript_wrap,
        orient="vertical",
        command=sohbet_kaydir,
        bg=THEME["panel_alt"],
        troughcolor=THEME["panel_deep"],
        activebackground=THEME["accent"],
        highlightthickness=0,
        bd=0,
        relief="flat",
        width=11,
    )
    transcript.configure(yscrollcommand=scrollbar.set)
    transcript.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
    scrollbar.grid(row=0, column=1, sticky="ns")

    transcript.tag_configure(
        "user", foreground=THEME["user"], font=(FONT_BODY, 10, "bold")
    )
    transcript.tag_configure(
        "notice", foreground=THEME["muted"], font=(FONT_BODY, 9, "italic")
    )
    transcript.tag_configure("error", foreground=THEME["danger"])
    transcript.tag_configure(
        "atlas", foreground=THEME["accent"], font=(FONT_BODY, 10, "bold")
    )
    transcript.tag_configure("user_body", foreground=THEME["text"], font=(FONT_BODY, 10))
    transcript.tag_configure("atlas_body", foreground=THEME["assistant"], font=(FONT_BODY, 10))
    transcript.tag_configure("error_body", foreground=THEME["danger"], font=(FONT_BODY, 10))

    def sohbet_yaz(metin: str, etiket: str | None = None) -> None:
        """Yeni metni ekler; geçmişte geziniliyorsa kullanıcıyı zorla alta çekmez."""
        takip_et = otomatik_asagi["aktif"]
        transcript.configure(state="normal")
        if etiket:
            transcript.insert("end", metin, etiket)
        else:
            transcript.insert("end", metin)
        transcript.configure(state="disabled")
        if takip_et:
            transcript.see("end")

    def sohbet_mesaji_yaz(konusmaci: str, metin: str, tur: str = "atlas") -> None:
        """Kullanıcı mesajlarını anında ekler; asistan mesajları animasyon kuyruğuna alınır."""
        govde = str(metin).strip()
        if tur != "user":
            asistan_mesaji_kuyruga_ekle(konusmaci, govde, tur)
            return

        # Kullanıcı yeni mesaj gönderdiğinde görünüm yeni konuşmaya odaklanır.
        otomatik_asagi["aktif"] = True
        transcript.configure(state="normal")
        transcript.insert("end", f">{konusmaci}\n", tur)
        if govde:
            transcript.insert("end", govde + "\n\n", "user_body")
        else:
            transcript.insert("end", "\n")
        transcript.configure(state="disabled")
        transcript.see("end")

    # ATLAS AI yanıtlarını harf harf yazdıran, Tk ana döngüsünü bloklamayan animasyon.
    # Ortam değişkeniyle ayarlanabilir: ATLAS_TYPING_DELAY_MS=5 (hızlı), 14 (yavaş).
    try:
        yazma_araligi_ms = int(os.environ.get("ATLAS_TYPING_DELAY_MS", "9"))
    except ValueError:
        yazma_araligi_ms = 9
    yazma_araligi_ms = max(0, min(80, yazma_araligi_ms))

    asistan_mesaj_kuyrugu: list[tuple[str, str, str]] = []
    animasyon_durumu = {"aktif": False}
    bekleyen_istem: str | None = None

    def istemi_etkinlestir() -> None:
        nonlocal bekleyen_istem
        if bekleyen_istem is None or animasyon_durumu["aktif"] or asistan_mesaj_kuyrugu:
            return
        temiz_istem = re.sub(r"\x1b\[[0-9;]*m", "", bekleyen_istem).strip()
        bekleyen_istem = None
        prompt_label.configure(text=temiz_istem or f">{kullanici_adi_getir()}")
        entry.configure(state="normal")
        send_button.configure(state="normal")
        entry.focus_set()

    def asistan_animasyonunu_baslat() -> None:
        if animasyon_durumu["aktif"] or not asistan_mesaj_kuyrugu:
            istemi_etkinlestir()
            return

        konusmaci, govde, tur = asistan_mesaj_kuyrugu.pop(0)
        animasyon_durumu["aktif"] = True
        body_tag = "error_body" if tur == "error" else "atlas_body"

        transcript.configure(state="normal")
        transcript.insert("end", f">{konusmaci}\n", "error" if tur == "error" else "atlas")
        karakter_indeksi = 0

        def sonraki_karakter() -> None:
            nonlocal karakter_indeksi
            try:
                if not root.winfo_exists():
                    return
            except tk.TclError:
                return

            if karakter_indeksi < len(govde):
                karakter = govde[karakter_indeksi]
                transcript.insert("end", karakter, body_tag)
                karakter_indeksi += 1
                if otomatik_asagi["aktif"]:
                    transcript.see("end")
                root.after(yazma_araligi_ms, sonraki_karakter)
                return

            transcript.insert("end", "\n\n")
            transcript.configure(state="disabled")
            if otomatik_asagi["aktif"]:
                transcript.see("end")
            animasyon_durumu["aktif"] = False
            if asistan_mesaj_kuyrugu:
                asistan_animasyonunu_baslat()
            else:
                istemi_etkinlestir()

        if not govde:
            transcript.insert("end", "\n")
            transcript.configure(state="disabled")
            animasyon_durumu["aktif"] = False
            asistan_animasyonunu_baslat()
            return
        root.after(yazma_araligi_ms, sonraki_karakter)

    def asistan_mesaji_kuyruga_ekle(konusmaci: str, metin: str, tur: str = "atlas") -> None:
        asistan_mesaj_kuyrugu.append((konusmaci, str(metin), tur))
        asistan_animasyonunu_baslat()

    def fare_tekerlegi(event: Any) -> str:
        if getattr(event, "num", None) == 4:
            transcript.yview_scroll(-3, "units")
        elif getattr(event, "num", None) == 5:
            transcript.yview_scroll(3, "units")
        else:
            delta = getattr(event, "delta", 0)
            adim = -1 if delta > 0 else 1
            transcript.yview_scroll(adim * max(1, abs(delta) // 120), "units")
        otomatik_asagi["aktif"] = transcript.yview()[1] >= 0.985
        return "break"

    transcript.bind("<MouseWheel>", fare_tekerlegi)
    transcript.bind("<Button-4>", fare_tekerlegi)
    transcript.bind("<Button-5>", fare_tekerlegi)

    # Alt giriş paneli sabittir; giriş alanı da koyu ve yuvarlak kart içinde durur.
    input_card, input_body = yuvarlak_kart(
        root, height=78, fill=THEME["panel_alt"], outline=THEME["border_hover"], radius=17
    )
    input_card.grid(row=5, column=0, sticky="ew", padx=16, pady=(0, 14))
    input_body.columnconfigure(1, weight=1)

    prompt_label = tk.Label(
        input_body,
        text=f">{kullanici_adi_getir()}",
        bg=THEME["panel_alt"],
        fg=THEME["accent"],
        font=(FONT_MONO, 10, "bold"),
    )
    prompt_label.grid(row=0, column=0, padx=(3, 12), pady=5)

    entry = tk.Entry(
        input_body,
        bg=THEME["input"],
        fg=THEME["text"],
        insertbackground=THEME["accent"],
        selectbackground=THEME["selection"],
        selectforeground=THEME["text"],
        relief="flat",
        bd=0,
        highlightthickness=1,
        highlightbackground=THEME["border"],
        highlightcolor=THEME["accent"],
        font=(FONT_BODY, 11),
        disabledbackground=THEME["panel"],
        disabledforeground=THEME["muted"],
    )
    entry.grid(row=0, column=1, sticky="ew", ipady=10, padx=(0, 10), pady=5)
    entry.configure(state="disabled")

    send_button = tk.Button(
        input_body,
        text="GÖNDER  ➤",
        command=lambda: komut_gonder(),
        bg=THEME["button"],
        fg=THEME["text"],
        activebackground=THEME["button_hover"],
        activeforeground=THEME["text"],
        disabledforeground=THEME["muted"],
        relief="flat",
        bd=0,
        highlightthickness=0,
        font=(FONT_HEADING, 9, "bold"),
        padx=18,
        pady=10,
        cursor="hand2",
        state="disabled",
    )
    send_button.grid(row=0, column=2, padx=(0, 3), pady=5)

    def komut_gonder(event: Any = None) -> str | None:
        metin = entry.get().strip()
        if not metin or str(entry.cget("state")) == "disabled":
            return "break"
        entry.delete(0, "end")
        entry.configure(state="disabled")
        send_button.configure(state="disabled")
        sohbet_mesaji_yaz(kullanici_adi_getir(), metin, "user")
        GUI_INPUT_QUEUE.put(metin)
        return "break"

    entry.bind("<Return>", komut_gonder)
    send_button.configure(command=komut_gonder)

    def kuyruklari_isle() -> None:
        nonlocal bekleyen_istem
        ciktilar: list[str] = []
        while True:
            try:
                tur, deger = GUI_UI_QUEUE.get_nowait()
            except queue.Empty:
                break
            if tur == "output":
                temiz = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", deger)
                temiz = temiz.replace("\r", "").strip()
                if temiz:
                    ciktilar.append(temiz)
            elif tur == "chat":
                asistan_mesaji_kuyruga_ekle("ATLAS AI", deger, "atlas")
            elif tur == "chat_error":
                asistan_mesaji_kuyruga_ekle("ATLAS AI", deger, "error")
            elif tur == "username":
                prompt_label.configure(text=f">{deger}")
                session_text.configure(
                    text=(
                        f"● ONLINE     |     LOCAL DATABASE     |     USER: {deger}"
                        f"     •     {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
                    )
                )
            elif tur == "prompt":
                # Asistan yanıtını yazmayı bitirmeden yeni giriş etkinleştirilmez.
                bekleyen_istem = deger
            elif tur == "random":
                random_label.configure(text=deger)

        if ciktilar:
            asistan_mesaji_kuyruga_ekle("ATLAS AI", "\n".join(ciktilar), "atlas")

        istemi_etkinlestir()
        if root.winfo_exists():
            root.after(35, kuyruklari_isle)

    def kapat() -> None:
        try:
            GUI_INPUT_QUEUE.put_nowait(None)
        except Exception:
            pass
        try:
            root.destroy()
        except tk.TclError:
            pass

    root.protocol("WM_DELETE_WINDOW", kapat)

    # Worker: eski Python komut/NLP motoru aynen kullanılır.
    stdout_onceki = sys.stdout
    sys.stdout = TkQueueWriter(GUI_UI_QUEUE)

    def atlas_worker() -> None:
        try:
            main()
            GUI_UI_QUEUE.put(("chat", "ATLAS AI oturumu sona erdi. Pencereyi kapatabilirsin."))
        except Exception as hata:
            GUI_UI_QUEUE.put(("chat_error", f"Beklenmeyen arayüz hatası: {hata}"))

    worker = threading.Thread(target=atlas_worker, name="ATLAS-AI-Worker", daemon=True)
    worker.start()
    root.after(35, kuyruklari_isle)
    entry.focus_set()
    root.mainloop()

    sys.stdout = stdout_onceki
    GUI_MODE = False



if __name__ == "__main__":
    if os.environ.get("ATLAS_INTERFACE", "gui").casefold() == "terminal":
        main()
    else:
        gui_baslat()
