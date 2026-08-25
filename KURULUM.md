# Haber Toplama Servisi — Sunucu Kurulum Kılavuzu

Hedef sunucu: **<SUNUCU_IP>** (Windows). Sistem Python GEREKTİRMEZ (tek `.exe`).

> ⚠️ Kuruluma kadar canlı klasörlere (`D:\ANKA` vb.) dokunulmaz. Geçiş adım adım,
> geri alınabilir şekilde yapılır (bkz. **6. Cutover**).

---

## 1. Dosyaları sunucuya kopyala
Sunucuda `C:\HaberServisi\` klasörü aç, içine koy:
- `dist\HaberServisi.exe`
- `config.yaml`

## 2. config.yaml'ı sunucuya göre ayarla
ANKA/AA çıktısını **gerçek** yollara çevir, DHA/Reuters'ı aç:
```yaml
# ANKA
  output_dir: 'D:\ANKA'          # test_cikti/ANKA -> D:\ANKA
# AA
  output_dir: 'D:\AA'            # test_cikti/AA   -> D:\AA
# DHA   -> enabled: true
# Reuters -> enabled: true
```
> `path_prefix` alanları zaten `D:\ANKA` / `D:\AA` — dokunma. ANKA `verify_ssl:false`
> kalabilir; sunucuda sertifika geçerliyse `true` yapıp test et.

## 3. Ön-tohumlama (ÇOK ÖNEMLİ — eskileri yeniden yazmasın)
Servisi kurmadan ÖNCE bir kez çalıştır:
```
cd C:\HaberServisi
HaberServisi.exe --seed
```
Bu, `D:\ANKA` ve `D:\AA`'daki mevcut binlerce dosyayı "görüldü" işaretler; servis
sadece BUNDAN SONRAKİ yeni haberleri yazar.

## 4. NSSM ile Windows servisi kur (boot'ta başlar, çökünce kalkar)
`nssm.exe`'yi `C:\HaberServisi\`'ye koy (https://nssm.cc). Yönetici CMD'de:
```
nssm install HaberServisi "C:\HaberServisi\HaberServisi.exe"
nssm set HaberServisi AppDirectory "C:\HaberServisi"
nssm set HaberServisi Start SERVICE_AUTO_START
nssm set HaberServisi AppExit Default Restart
nssm set HaberServisi AppStdout "C:\HaberServisi\logs\service-out.log"
nssm set HaberServisi AppStderr "C:\HaberServisi\logs\service-err.log"
nssm start HaberServisi
```
Kaldırmak için: `nssm stop HaberServisi` + `nssm remove HaberServisi confirm`

## 5. Paneli aç
Tarayıcıdan: **http://<SUNUCU_IP>:8770**
Her ajans için ışık, sayaç, son hata, Durdur/Başlat/Şimdi çek + canlı log.

## 6. Cutover (ajans-ajans, geri alınabilir)
Eski exe ile ÇİFT yazımı önlemek için her ajansı tek tek devral:

**ANKA:**
1. Panelde ANKA'yı bir süre izle (yeni haber yazıyor mu, D:\ANKA'ya doğru düşüyor mu).
2. Emin olunca eski controller'ı durdur:
   `taskkill /IM MarsisANKAAPIController.exe /F` (ve başlangıçtan kaldır).
3. Artık D:\ANKA'yı sadece yeni servis besliyor.

**AA:** Aynı adımlar (AA controller zaten pasif görünüyor; teyit et).

**DHA:** API yok — vendor `DHAAboneWatchdog.exe` ayakta tutar+login yapar; yeni servis
`D:\DHA_YENI`'yi izler, durursa vendor watchdog'u yeniden başlatır. Vendor watchdog'un
boot'ta çalıştığından emin ol.

**Reuters:** `Reuters Content Downloader Service` çalışır; yeni servis `D:\Reuters`'ı
izler, durursa `net stop/start` ile kaldırır.

## 7. DHA login testi (kurulumda yapılacak)
DHA'da exe her açılışta login ister. Vendor watchdog login'i de yapıyor mu kontrol et:
DHA'yı kapat → watchdog açsın → **login tıklamadan haber düşüyor mu?**
- Düşüyorsa: tamam.
- Düşmüyorsa: bize haber ver, otomatik login tıklama (pywinauto) ekleyeceğiz.

## 8. Geri alma (rollback)
Sorun olursa: `nssm stop HaberServisi` + ilgili eski exe'yi tekrar başlat. Yeni servis
hiçbir dosyayı SİLMEZ, sadece yeni ekler — riski düşüktür.
