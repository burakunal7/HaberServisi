# Haber Toplama Servisi

Haber ajanslarından (ANKA, AA, DHA, Reuters) haberleri **sürekli, kesintisiz** toplayan;
çöken kaynakları **kendi kendine kaldıran**; web panelinden yönetilen dayanıklı bir Windows
servisi. Kararsız üçüncü-parti "abone" exe'lerinin yerine geçmek için yazıldı.

## Neden?

Ajans haberleri, sürekli çöken ve elle yeniden başlatılması gereken exe'lerle çekiliyordu.
Bu servis:

- **Sürekli/canlı çeker** — 60 sn'lik tur beklemesi yok, ne geliyorsa anında.
- **Kendi kendine kalkar** — çökse Windows (NSSM) kaldırır; worker hatası servisi düşürmez.
- **Kaldığı yerden devam eder** — makine kapansa bile aradaki haberleri toplar (dedup + checkpoint).
- **Hiçbir şey kaçmaz** — medya inmezse tekrar dener, olmazsa metni yine de yazar + "arıza" işaretler.
- **Panelden yönetilir** — durum, canlı log, aç/kapat, ayar (şifre dahil), hepsi tarayıcıdan.
- **Diski yönetir** — her gün eski dosyaları (retention) temizler.

## Mimari

İki tür ajans, tek dayanıklılık iskeleti:

| Tür | Ajans | Ne yapar |
|-----|-------|----------|
| **Çekici** (API) | ANKA, AA | Ajans API'sine bağlanır, haberi kendi çeker ve ajansın formatında yazar |
| **Bekçi** (watchdog) | DHA, Reuters | API'si olmayan exe/servisi izler; akış durursa yeniden başlatır |

- Her ajans kendi thread'inde **paralel** çalışır (biri diğerini bekletmez).
- Çekiciler ajansın çıktı formatını **birebir** üretir (ANKA: JSON-in-xml, AA: NewsML, ...).
- Durum `StatusRegistry`'de; web paneli (Flask + waitress) buradan besleniyor.

```
newshub/
├── agencies/         # ajans adaptörleri
│   ├── base.py       # ortak sözleşme (çek/kaydet, retry, atomik indirme, throttle)
│   ├── anka.py       # ANKA API çekici + yazıcı
│   ├── aa.py         # AA (Anadolu Ajansı) NewsML çekici + yazıcı
│   └── watchdog.py   # DHA/Reuters klasör bekçisi + süreç izleme
├── service.py        # paralel worker'lar + reload + retention + web başlatma
├── web.py            # kumanda paneli (durum, log, aç/kapat, ⚙ ayarlar)
├── state.py          # SQLite: dedup + checkpoint + arıza + bakım
├── config_io.py      # panelden config düzenleme (yorumları korur, şifre maskeler)
├── status.py         # durum kayıt merkezi + log tamponu
└── runner.py         # config yükleme, loglama, tek-tur (bakım)
run.py                # giriş: (servis) | --seed | --cleanup | --once
```

## Kurulum & Çalıştırma

```bash
pip install -r requirements.txt
cp config.example.yaml config.yaml   # <...> alanlarını doldur (API şifreleri vb.)
python run.py                        # servis + panel: http://localhost:8770
```

Komutlar:

- `python run.py` — servis (paralel ajanslar + web panel)
- `python run.py --seed` — mevcut dosyaları "görüldü" say (ilk kurulum; baştan indirmesin)
- `python run.py --cleanup` — eski dosyaları (retention) şimdi temizle
- `python run.py --once` — tek tur (bakım/test)

## Üretim (Windows) dağıtımı

Tek parça exe (Python gerektirmez) ve NSSM ile Windows servisi olarak çalışır — ayrıntılar
[KURULUM.md](KURULUM.md)'de.

```bash
pyinstaller --onefile --name HaberServisi --collect-all ruamel.yaml run.py
```

## Güvenlik

- Gerçek şifreler `config.yaml`'da tutulur ve **repoya girmez** (`.gitignore`).
- Panel girişi opsiyonel (`web_user`/`web_password`) — üretimde doldurulmalı.
- Retention silme işlemi güvenli: sürücü kökünü reddeder, taze dosyayı silmez.

## Lisans

[Apache License 2.0](LICENSE) — Copyright © 2026 Burak Ünal.
