"""İlk yönetici hesabını oluşturur (sistemde hiç kullanıcı yokken giriş yapılabilsin diye).

Kullanım:
    python -m services.auth.bootstrap --email ad@firma.com --name "Ad Soyad" --username kullanici
    (şifre verilmezse güvenli bir GEÇİCİ şifre üretilir ve yalnızca bir kez ekrana yazılır; ilk girişte değiştirmek zorunludur)

Mevcut bir kullanıcının üzerine YAZMAZ; e-posta/kullanıcı adı varsa hiçbir şey değiştirmeden çıkar.
"""

import argparse
import sys

from packages.db.base import SessionLocal
from services.auth.security import generate_temp_password
from services.auth.service import AuthError, create_user, find_by_identifier


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--role", default="yonetici", choices=("yonetici", "calisan", "stajyer"))
    parser.add_argument("--password", help="verilmezse güvenli geçici şifre üretilir")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if find_by_identifier(db, args.email) or find_by_identifier(db, args.username):
            print(f"Kullanıcı zaten var ({args.email} / {args.username}); hiçbir değişiklik yapılmadı.")
            return 0
        password = args.password or generate_temp_password()
        try:
            user = create_user(db, None, name=args.name, email=args.email, username=args.username, role=args.role, password=password, must_change_password=True)
        except AuthError as exc:
            print(f"Hata: {exc.detail}", file=sys.stderr)
            return 1
        print(f"Kullanıcı oluşturuldu: {user.name} <{user.email}> — rol: {user.role}")
        print(f"Kullanıcı adı: {user.username}")
        print(f"GEÇİCİ ŞİFRE (yalnızca şimdi gösterilir): {password}")
        print("İlk girişte şifreyi değiştirmeniz istenecek.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
