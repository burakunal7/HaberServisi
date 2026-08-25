@echo off
REM Haber Toplama Servisi'ni NSSM ile Windows servisi olarak kurar.
REM Yönetici olarak çalıştır. NSSM yolunu ve klasörü ortamına göre ayarla.
set NSSM=C:\nssm-2.24\win64\nssm.exe
set APPDIR=C:\HaberServisi

"%NSSM%" stop HaberServisi
"%NSSM%" remove HaberServisi confirm
"%NSSM%" install HaberServisi "%APPDIR%\HaberServisi.exe"
"%NSSM%" set HaberServisi AppDirectory "%APPDIR%"
"%NSSM%" set HaberServisi Start SERVICE_AUTO_START
"%NSSM%" set HaberServisi AppExit Default Restart
"%NSSM%" set HaberServisi AppRestartDelay 3000
"%NSSM%" set HaberServisi AppStdout "%APPDIR%\logs\svc-out.log"
"%NSSM%" set HaberServisi AppStderr "%APPDIR%\logs\svc-err.log"
"%NSSM%" set HaberServisi DisplayName "Haber Toplama Servisi"
"%NSSM%" start HaberServisi
echo Kuruldu. Panel: http://localhost:8770
