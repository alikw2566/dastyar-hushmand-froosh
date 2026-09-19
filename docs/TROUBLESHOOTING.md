# عیب‌یابی عملیاتی

## ترتیب بررسی

```powershell
docker compose ps
Invoke-RestMethod http://localhost:8000/health/details
Invoke-RestMethod http://localhost:8010/health/ready
docker compose logs --since 15m api
docker compose logs --since 15m worker
docker compose logs --since 15m watcher
```

قبل از restart، زمان، call id، status، error code و آخرین log مرتبط را ثبت کنید. رمز، token یا متن کامل مشتری را داخل ticket عمومی نگذارید.

## Docker یا سرویس بالا نمی‌آید

- `docker` پیدا نمی‌شود: Docker Desktop/Engine نصب و shell دوباره باز شود.
- port اشغال است: `Get-NetTCPConnection -LocalPort 3000,8000,8010,8081,9001` را بررسی کنید.
- config نامعتبر: `docker compose config` اجرا و `.env` را با `.env.example` مقایسه کنید.
- API در migration متوقف است: `docker compose logs api` را ببینید؛ قبل از هر تغییر schema backup بگیرید.
- MinIO/PostgreSQL unhealthy: فضای دیسک، volume و password یکسان بین سرویس‌ها را بررسی کنید.

## Watcher live است ولی ready نیست

- `watcher_disabled`: `ISSABEL_IMPORT_MODE` باید `local`، `shared_folder` یا `sftp` باشد.
- خطای SFTP host key: فایل `known_hosts`، اثر انگشت تأییدشده و bind mount آن را بررسی کنید؛ بررسی host key را غیرفعال نکنید.
- خطای MariaDB: دسترسی شبکه به پورت 3306 و مجوز `SELECT` حساب CDR را بررسی کنید.
- `watcher_degraded`: مسیر `/recordings` داخل کانتینر را بررسی کنید:

```powershell
docker compose exec watcher python -c "from pathlib import Path; p=Path('/recordings'); print(p.exists(), p.is_dir())"
docker compose logs --since 15m watcher
docker compose run --rm watcher python -m app.check_issabel
```

- فایل کشف نمی‌شود: پسوند مجاز، پسوند موقت، stability window، permission و زیرپوشه quarantine را بررسی کنید.
- فایل duplicate است: hash یا source identifier قبلاً در `source_imports` ثبت شده؛ تغییر نام bytes یکسان را جدید نمی‌کند.
- فایل quarantined است: ffprobe، مدت حداقل، codec و حجم را بررسی کنید؛ فایل را کورکورانه به پوشه ورودی برنگردانید.

## تماس در queue مانده است

```powershell
docker compose ps worker redis
docker compose logs --since 15m worker
docker compose exec worker celery -A app.tasks.celery_app inspect ping
```

اگر Worker سالم نیست ابتدا علت را رفع و سپس آن را restart کنید. ثبت دوباره همان تماس بدون idempotency ممکن است داده اضافه بسازد؛ از Retry/Reprocess همان call id استفاده کنید.

## `retry_scheduled` یا `failed`

- `storage_unavailable`: MinIO و bucket را بررسی کنید.
- `transcription_timeout/unavailable`: شبکه، quota، base URL و کلید ارائه‌دهنده را بررسی کنید.
- `empty_transcript`: صوت خالی/کم‌صدا یا مدل بدون segment؛ نیازمند بازبینی فایل است.
- `analysis_invalid/unavailable`: پاسخ مدل/JSON schema یا provider را بررسی کنید.
- `unsupported_evidence`: داده تحلیل شاهد معتبر ندارد و نباید قطعی نمایش داده شود.
- `audio_corrupt/audio_too_short/unsupported_audio`: خطای دائمی ورودی؛ Retry خودکار مفید نیست.

پس از رفع علت، `reanalyze` برای تحلیل مجدد متن موجود یا `full` برای پردازش دوباره صوت انتخاب شود.

## ورود و 401/403

- 401: token منقضی، issuer/audience اشتباه یا Keycloak unavailable؛ logout/login کنید.
- 403: نقش membership مجاز نیست. نقش را در پنل بررسی و token را refresh کنید.
- loop ورود: `APP_URL`، `OIDC_ISSUER` و clock سیستم را بررسی کنید.
- `AUTH_DISABLED=true` فقط در `ENVIRONMENT=development` کار می‌کند و راه‌حل production نیست.

## صوت باز نمی‌شود

لینک presigned حدود ۱۵ دقیقه اعتبار دارد؛ صفحه را refresh کنید. اگر `audio_download_enabled=false` است، API عمداً URL نمی‌دهد. ساعت MinIO/API و permission bucket را هم بررسی کنید.

## PDF فارسی خراب است

`PDF_FONT_PATH` را به یک TTF فارسی داخل image/mount تنظیم و کانتینر API را recreate کنید. PDF را در viewer دیگر و چاپ تست کنید. نبود فونت یا reshape مناسب نباید با تغییر encoding متن حل شود.

## backup/restore

- sidecar گم شده یا hash mismatch: restore را متوقف کنید؛ `--ignore-sidecar` فقط برای بازیابی کارشناسی و پس از تأیید منبع است.
- target وجود دارد: ابتدا dry-run؛ سپس مقصد خالی یا `--overwrite` آگاهانه.
- Docker restore شکست می‌خورد: سرویس نام، compose file و خالی‌بودن مقصد PostgreSQL/MinIO را بررسی کنید.

## جمع‌آوری بسته عیب‌یابی امن

فقط خروجی health، نسخه commit، وضعیت کانتینر، error code و log redacted را جمع کنید. `.env`، dump دیتابیس، token، لینک presigned و فایل صوتی را ضمیمه نکنید.
