# پشتیبان‌گیری و بازیابی

اسکریپت‌های `scripts/backup.py` و `scripts/restore.py` یک archive زمان‌دار، manifest نسخه‌دار، SHA-256 برای هر فایل و checksum sidecar برای کل archive می‌سازند. dry-run پیش‌فرض restore و کنترل path traversal از بازگردانی ناامن جلوگیری می‌کند.

## دامنه backup

برای پشته Docker، backup کامل پایلوت باید شامل این موارد باشد:

- dump سفارشی PostgreSQL: تمام metadata، تحلیل، glossary، correction، task و audit؛
- داده MinIO: صوت اصلی و objectهای وابسته؛
- فایل‌های deployment غیرمحرمانه مانند realm template؛
- secretها **خارج از archive** در secret manager/فرآیند امن سازمان؛
- سند نسخه commit، Docker image digest و سیاست retention.

فایل‌های `.env`، private key، certificate key، credential و فایل دارای assignment شبیه secret به‌صورت دفاعی حذف و دلیل آن در manifest ثبت می‌شود. scanner تضمین ریاضی کشف همه قالب‌های اختصاصی secret نیست؛ archive را قبل از انتقال بازبینی کنید.

Keycloak روی PostgreSQL پایدار جداگانه اجرا می‌شود. برای حفظ کاربران، نقش‌ها، MFA و نشست‌های مدیریتی، گزینه `--include-keycloak` باید همراه backup کامل و گزینه `--restore-keycloak` همراه بازیابی آزمایشی استفاده شود.

## Dry-run

مقصد نباید داخل هیچ source باشد:

```powershell
& ".\.venv\Scripts\python.exe" scripts/backup.py `
  --output-dir "D:\MokalemebanBackups" `
  --source "deployment=deploy" `
  --dry-run
```

خروجی dry-run تعداد فایل انتخابی و لیست exclusion را می‌دهد و archive نمی‌سازد.

## Backup کامل Docker

```powershell
& ".\.venv\Scripts\python.exe" scripts/backup.py `
  --output-dir "D:\MokalemebanBackups" `
  --source "deployment=deploy" `
  --compose-file docker-compose.yml `
  --include-postgres `
  --include-minio `
  --include-keycloak `
  --retention-days 14
```

اسکریپت داخل کانتینر PostgreSQL، `pg_dump --format=custom --no-owner --no-acl` اجرا می‌کند. برای MinIO از tar داخل کانتینر استفاده می‌کند؛ availability فرمان `sh`/`tar` در image نهایی باید در تست بازیابی همان release اثبات شود. خروجی موفق فقط بعد از بازخوانی archive و تطبیق تمام hashها `integrity_verified=true` می‌دهد.

برای snapshot سازگار بین دیتابیس و object storage، ورود فایل جدید را متوقف و اجازه دهید queue تخلیه شود؛ سپس Watcher/Worker را در maintenance window متوقف و backup را بگیرید. اجرای هم‌زمان ingestion می‌تواند snapshot هر جزء را سالم ولی از نظر زمانی ناهماهنگ کند.

دو فایل تولید می‌شود:

- `mokalemeban-backup-YYYYMMDDTHHMMSSZ.tar.gz`
- همان نام با پسوند `.sha256`

برای حذف archiveهای منقضی فقط بعد از backup موفق و با پرچم صریح اجرا کنید:

```powershell
& ".\.venv\Scripts\python.exe" scripts/backup.py ... --retention-days 14 --prune-expired
```

این retention فقط فایل‌های مطابق prefix ابزار را در همان output directory حذف می‌کند. حداقل یک نسخه immutable/off-site مستقل نگه دارید.

## بررسی و Dry-run بازیابی

```powershell
& ".\.venv\Scripts\python.exe" scripts/restore.py `
  --archive "D:\MokalemebanBackups\mokalemeban-backup-20260801T120000Z.tar.gz" `
  --target "D:\MokalemebanRestorePreview"
```

بدون `--apply` هیچ فایل یا دیتابیسی restore نمی‌شود؛ checksum sidecar، manifest و hash تمام entryها بررسی می‌شوند. target preview شامل پوشه‌ای با نام label هر source خواهد بود.

## بازیابی فایل‌های غیرمحرمانه

```powershell
& ".\.venv\Scripts\python.exe" scripts/restore.py `
  --archive "D:\MokalemebanBackups\mokalemeban-backup-20260801T120000Z.tar.gz" `
  --target "D:\MokalemebanRestoreStaging" `
  --apply
```

به‌صورت پیش‌فرض فایل موجود overwrite نمی‌شود. ابتدا staging را بازبینی و سپس تنظیمات لازم را دستی deploy کنید. secretها باید جداگانه از secret manager بازیابی شوند.

## Disaster recovery دیتابیس و صوت

این عملیات مخرب است و باید روی stack تازه/خالی آزمایش شود:

1. stack مقصد تازه با همان release بسازید و tenant traffic را قطع کنید.
2. checksum/dry-run را اجرا کنید.
3. API، Worker، Watcher و Web را متوقف و فقط PostgreSQL/MinIO را روشن نگه دارید.
4. فرمان restore را با تأییدهای دقیق اجرا کنید:

```powershell
docker compose stop api worker watcher web
& ".\.venv\Scripts\python.exe" scripts/restore.py `
  --archive "D:\MokalemebanBackups\mokalemeban-backup-20260801T120000Z.tar.gz" `
  --target "D:\MokalemebanRestoreStaging" `
  --apply `
  --compose-file docker-compose.yml `
  --restore-postgres `
  --restore-minio `
  --restore-keycloak `
  --confirm-database mokalemeban `
  --confirm-object-storage RESTORE `
  --confirm-keycloak-database keycloak
docker compose up -d api worker watcher web
```

`pg_restore --clean --if-exists` داده مقصد را تغییر می‌دهد و tar MinIO می‌تواند objectهای هم‌نام را overwrite کند. روی volume تولیدی موجود بدون change approval اجرا نکنید.

## آزمون و زمان‌بندی

Unit test همراه ابزار یک fixture امن می‌سازد، secretها را حذف می‌کند، archive را restore می‌کند و tamper checksum را رد می‌کند:

```powershell
& ".\.venv\Scripts\python.exe" -m unittest discover -s scripts/tests -v
```

Task Scheduler/cron باید backup روزانه، کپی off-site و هشدار شکست را اجرا کند. ماهانه restore کامل روی stack جدا و RPO/RTO واقعی ثبت شود. تا اجرای چنین restoreای، صرف وجود archive اثبات بازیابی‌پذیری نیست.
