"""Giriş noktası.

  python run.py                 # servis: paralel ajanslar + web panel
  python run.py --seed          # mevcut dosyaları 'görüldü' say (ilk kurulum)
  python run.py --cleanup       # eski dosyaları temizle (retention) ve çık
  python run.py --once          # tek tur çalış ve çık (bakım/test)
"""
import argparse
import os
import sys
from pathlib import Path

from newshub.runner import build_enabled_agencies, load_config, run_once, setup_logging
from newshub.service import run_service, seed_seen
from newshub.state import SeenStore


def _locate_config_and_chdir(config_arg: str) -> str:
    """config.yaml'ı bul ve çalışma dizinini onun yanına al; böylece exe nereden
    çalışırsa çalışsın (çift tık, NSSM) göreli yollar doğru çözülür."""
    cfg = Path(config_arg)
    if not cfg.exists() and not cfg.is_absolute():
        base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
        alt = base / cfg.name
        if alt.exists():
            cfg = alt
    cfg = cfg.resolve()
    if cfg.exists():
        os.chdir(cfg.parent)
        return cfg.name
    return config_arg


def main() -> None:
    ap = argparse.ArgumentParser(description="Ajans haber toplama servisi")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--seed", action="store_true", help="Mevcut dosyaları 'görüldü' işaretle (ilk kurulum)")
    ap.add_argument("--cleanup", action="store_true", help="Eski dosyaları şimdi temizle (retention) ve çık")
    ap.add_argument("--once", action="store_true", help="Tek tur çalış ve çık (bakım/test)")
    ap.add_argument("--agency", default="", help="Sadece bu ajans (örn. AA)")
    ap.add_argument("--limit", type=int, default=0, help="Ajans başına en fazla N haber")
    ap.add_argument("--no-media", action="store_true", help="Medya indirmeyi atla")
    args = ap.parse_args()
    args.config = _locate_config_and_chdir(args.config)

    if args.seed:
        cfg = load_config(args.config)
        g = cfg.get("global", {})
        setup_logging(g.get("log_dir", "logs"))
        seen = SeenStore(g.get("state_db", "state.sqlite3"))
        # Kapalı ajanslar dahil hepsini işaretle -> ileride açılınca baştan indirmesin
        from newshub.agencies import build_agency
        agencies = []
        for a in cfg.get("agencies", []):
            if args.agency and a.get("name", "").lower() != args.agency.lower():
                continue
            try:
                agencies.append(build_agency(a))
            except Exception as e:
                print(f"  {a.get('name')}: kurulamadı ({e})")
        counts = seed_seen(agencies, seen)
        print("Ön-tohumlama tamamlandı (görüldü işaretlenen):")
        for name, n in counts.items():
            print(f"  {name}: {n}")
        return

    if args.cleanup:
        import logging
        from newshub.service import cleanup_once
        cfg = load_config(args.config)
        setup_logging(cfg.get("global", {}).get("log_dir", "logs"))
        res = cleanup_once(cfg, logging.getLogger("cleanup"))
        print("Temizlik tamamlandı (silinen dosya):")
        for name, n in res.items():
            print(f"  {name}: {n}")
        return

    if args.once:
        run_once(args.config, args.agency, args.limit, args.no_media)
        return

    run_service(args.config)


if __name__ == "__main__":
    main()
