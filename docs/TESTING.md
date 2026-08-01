# راهنمای تست و Release Gate

## پیش‌نیاز محلی

Python 3.12 و Node 22 لازم‌اند. محیط فعلی پروژه در `.venv` قابل استفاده است. برای نصب تازه:

```powershell
py -3.12 -m venv .venv
& ".\.venv\Scripts\python.exe" -m pip install -e ".\backend[dev]"
cd web
npm.cmd ci
cd ..
```

## فرمان جامع Windows

```powershell
powershell -ExecutionPolicy Bypass -File scripts/test_all.ps1
```

اسکریپت به‌ترتیب Ruff، تست backend، تست و گزارش evaluation، تست backup/restore، تست load harness، dry-run بار، lint/typecheck/build/test وب را اجرا و JSON شامل `PASS/FAIL` چاپ می‌کند. برای Python سفارشی:

```powershell
powershell -File scripts/test_all.ps1 -PythonExecutable "C:\Python312\python.exe"
```

گزینه `-SkipWeb` فقط برای عیب‌یابی است و Release Gate کامل محسوب نمی‌شود.

## فرمان‌های مستقل

```powershell
& ".\.venv\Scripts\python.exe" -m ruff check backend
& ".\.venv\Scripts\python.exe" -m pytest backend/tests -ra
& ".\.venv\Scripts\python.exe" -m pytest evaluation/tests scripts/tests load-tests/tests -q
& ".\.venv\Scripts\python.exe" evaluation/run_evaluation.py

cd web
npm.cmd run lint
npm.cmd exec tsc -- --noEmit
npm.cmd test
```

تست ابزارهای QA در آخرین اجرای محلی ۱۰ مورد را پاس کرده است. گزارش نمونه evaluation دو متن ساختگی را سنجیده و با `measured=false` و `NOT_MEASURED_ON_REAL_CALLS` علامت خورده؛ WER/CER آن صرفاً خروجی fixture است، نه کیفیت تماس فارسی واقعی.

## ارزیابی دقت فارسی

راهنمای کامل در `evaluation/README.md` است. حداقل dataset پایلوت باید تنوع گوینده، لهجه، نویز، تماس تک‌کاناله، کلمات تخصصی، عدد/مبلغ، code-switching و طول تماس را پوشش دهد. reference باید با بازبینی انسانی مستقل تهیه شود.

```powershell
& ".\.venv\Scripts\python.exe" evaluation/run_evaluation.py --dataset "D:\secure-qa\dataset.json"
```

تا وقتی dataset واقعی کافی اجرا نشده، هیچ threshold مانند «۸۵٪» پاس‌شده اعلام نشود. WER پایین‌تر بهتر است؛ عبارت «۸۵٪ متن قابل استفاده» معادل مستقیم WER نیست و باید rubric انسانی جدا داشته باشد.

## تست یکپارچه دستی Issabel

1. فایل consented با پسوند `.part` وارد drop-folder شود؛ نباید ingest شود.
2. rename به `.wav`؛ بعد از stability window دقیقاً یک تماس ساخته شود.
3. همان bytes با نام دیگر؛ duplicate شود.
4. فایل corrupt؛ quarantine و error ثبت شود، Watcher ready باقی بماند.
5. Worker در میانه کار restart؛ job ack-late بازیابی و داده تکراری ساخته نشود.
6. provider موقتاً قطع؛ `retry_scheduled` و backoff ثبت شود.
7. متن/نقش اصلاح؛ correction audit و re-analysis بدون overwrite اجرا شود.
8. follow-up؛ یک task و نه duplicate ایجاد شود.
9. PDF و Excel فارسی روی Windows/چاپ باز شوند.
10. مدیر شرکت دیگر نتواند call id، صوت، error، extraction یا export را ببیند.

## CI

Workflow `.github/workflows/ci.yml` backend و web را روی push/PR شاخه main اجرا می‌کند و ابزارهای عملیاتی را compile می‌کند. نتیجه CI جای تست Docker/E2E، مدل خارجی، فایل واقعی و restore کامل را نمی‌گیرد.

## معیار Release Gate

Release فقط وقتی جلو می‌رود که:

- lint/typecheck/unit/integration/E2E بحرانی pass؛
- cross-tenant/RLS همه جدول‌های جدید pass؛
- Docker health و migration روی دیتابیس تازه و ارتقا از نسخه قبلی pass؛
- backup و restore PostgreSQL+MinIO روی stack جدا pass؛
- یک چرخه واقعی Issabel تا dashboard/export pass؛
- گزارش load موجود و soak موردنیاز اجرا شده؛
- محدودیت‌ها و خطاهای failشده پنهان نشده باشند.
