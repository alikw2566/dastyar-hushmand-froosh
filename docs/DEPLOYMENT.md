# استقرار نسخه پایلوت

## پیش‌نیاز

- Docker Desktop با Compose v2 روی Windows، یا Docker Engine/Compose روی Linux
- دسترسی خروجی HTTPS به ارائه‌دهنده OpenAI-compatible
- فضای پایدار برای PostgreSQL، MinIO، Redis و backup خارج از همان دیسک
- mount قابل اتکای پوشه Issabel
- دامنه، TLS reverse proxy و SMTP/هشدار برای محیطی فراتر از شبکه آزمایشی

اجرای `npm run dev` به‌تنهایی استقرار پایلوت کامل نیست.

## تنظیم اولیه

```powershell
cd "C:\Users\LOQ\OneDrive\Documents\voice agent farazma"
Copy-Item .env.example .env
```

در `.env` حداقل این مقادیر را با مقادیر واقعی و یکتا جایگزین کنید:

- `POSTGRES_PASSWORD`
- `S3_ACCESS_KEY` و `S3_SECRET_KEY`
- `KEYCLOAK_ADMIN` و `KEYCLOAK_ADMIN_PASSWORD`
- `OPENAI_API_KEY` و در صورت نیاز `OPENAI_BASE_URL`
- `SECRET_ENCRYPTION_KEY` از نوع Fernet
- سه مقدار `FIRST_ADMIN_*`، نام شرکت و یک UUID ثابت در `DEFAULT_TENANT_ID`
- همان UUID در `ISSABEL_DEFAULT_TENANT_ID` و مسیر اتصال Issabel

ساخت کلید Fernet با محیط Python پروژه:

```powershell
& ".\.venv\Scripts\python.exe" -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

فایل `.env` را commit نکنید. مقدارهای پیش‌فرض `change-me` برای محیط عملیاتی مردود هستند.

## اعتبارسنجی و اجرا

```powershell
docker compose config
docker compose up -d --build
docker compose ps
```

API هنگام بالا آمدن `alembic upgrade head` را اجرا می‌کند. بعد از آماده‌شدن Keycloak و API، اولین مدیر را idempotent بسازید:

```powershell
docker compose run --rm api python -m app.bootstrap_admin
```

فرمان باید همان `tenant_id` تنظیم‌شده را چاپ کند. تا قبل از موفقیت این فرمان، فایل واقعی داخل drop-folder Issabel قرار ندهید. مقدارهای `DEFAULT_TENANT_ID` و `ISSABEL_DEFAULT_TENANT_ID` باید دقیقاً یکسان باشند؛ در غیر این صورت تماس وارد سازمان اشتباه می‌شود یا به‌علت نبود سازمان ثبت نمی‌شود.

پس از موفقیت، `FIRST_ADMIN_PASSWORD` را از `.env` و secret distribution حذف و کانتینرها را recreate کنید. فرمان bootstrap در اجرای بعدی همان membership را فعال/به‌روزرسانی می‌کند و حساب تکراری نمی‌سازد.

## آدرس‌ها و health gate

- داشبورد: `http://localhost:3000`
- API docs: `http://localhost:8000/api/v1/docs`
- API health: `http://localhost:8000/health/live` و `/health/ready`
- جزئیات dependencyها: `http://localhost:8000/health/details`
- Watcher: `http://localhost:8010/health/live` و `/health/ready`
- Keycloak: `http://localhost:8081`
- MinIO Console: `http://localhost:9001`

```powershell
Invoke-RestMethod http://localhost:8000/health/live
Invoke-RestMethod http://localhost:8000/health/ready
Invoke-RestMethod http://localhost:8000/health/details
Invoke-RestMethod http://localhost:8010/health/ready
```

`live=200` فقط زنده‌بودن process را نشان می‌دهد؛ ورود ترافیک فقط وقتی مجاز است که `ready=200` باشد.

## نکات Windows

- Docker Desktop باید روشن و WSL2 سالم باشد.
- برای drive شبکه، دسترسی Docker به مسیر را جداگانه تست کنید.
- پروژه روی OneDrive است؛ دیتای PostgreSQL/MinIO داخل named volume است، نه sync مستقیم OneDrive. backup را روی مقصد مستقل و رمزنگاری‌شده نگه دارید.
- فرمان جامع تست: `powershell -ExecutionPolicy Bypass -File scripts/test_all.ps1`.

## نکات Linux/سرور

- سرویس‌ها را با کاربر غیرroot عملیات مدیریت کنید.
- firewall فقط 443 را عمومی کند؛ 5432، 6379، 9000/9001، 8000، 8010 و 8081 نباید عمومی باشند.
- Compose فعلی Keycloak را با `start-dev` اجرا می‌کند و reverse proxy TLS ندارد. برای محیط عمومی، Keycloak production mode، پایگاه داده پایدار آن و proxy استاندارد الزامی است.
- logهای Docker rotate می‌شوند، اما باید به سامانه مرکزی ارسال و alert تعریف شوند.

## ارتقا

1. backup و dry-run restore بگیرید.
2. release/commit مشخص را دریافت کنید؛ از `latest` نامشخص استفاده نکنید.
3. `docker compose build --pull` و سپس `docker compose up -d` اجرا کنید.
4. log migration و `/health/ready` را بررسی کنید.
5. یک تماس consented تست و یک Export بسازید.
6. در شکست migration، سرویس را متوقف و طبق سند Backup/Recovery روی محیط تازه restore کنید؛ migration مخرب یا downgrade کورکورانه اجرا نکنید.

## توقف

`docker compose stop` داده volumeها را حفظ می‌کند. از `docker compose down -v` استفاده نکنید؛ `-v` پایگاه داده، Redis و فایل‌های MinIO را حذف می‌کند.
