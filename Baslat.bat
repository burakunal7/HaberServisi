@echo off
REM Haber Toplama Servisi - cift tikla baslat
REM Bu .bat proje klasorunde olmali; exe'yi dogru calisma diziniyle acar.
cd /d "%~dp0"
echo Haber Toplama Servisi baslatiliyor...
echo Panel: http://localhost:8770
echo (Kapatmak icin bu pencereyi kapatin)
dist\HaberServisi.exe
pause
