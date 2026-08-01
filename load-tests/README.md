# آزمون فشار و پایداری

`run_load.py` یک harness بدون وابستگی خارجی برای سناریوهای health، خواندن داشبورد، آپلود فایل، درخواست پردازش مجدد و endpoint سفارشی است. گزارش هر اجرا JSON و HTML است و token در آن ذخیره نمی‌شود.

## تست سبک و غیرمخرب

```powershell
python load-tests/run_load.py --scenario health --requests 100 --concurrency 10
```

## خواندن هم‌زمان داشبورد

توکن آزمایشی را در محیط قرار دهید، نه در command history یا فایل گزارش:

```powershell
$env:MOKALEMEBAN_TEST_TOKEN="توکن-کوتاه‌عمر-آزمایش"
python load-tests/run_load.py --scenario dashboard --duration-seconds 600 --concurrency 20 --rate-per-second 40
Remove-Item Env:MOKALEMEBAN_TEST_TOKEN
```

## آپلود ۱۰۰ فایل

این سناریو داده ایجاد می‌کند و فقط باید روی tenant آزمایشی اجرا شود:

```powershell
$env:MOKALEMEBAN_TEST_TOKEN="توکن-کوتاه‌عمر-آزمایش"
python load-tests/run_load.py --scenario upload --requests 100 --concurrency 5 --audio-file C:\qa-data\short-consented-call.wav
```

هر درخواست `Idempotency-Key` یکتا دارد. خود فایل صوتی و token داخل گزارش قرار نمی‌گیرند.

## Retry storm کنترل‌شده

پرچم ایمنی و شناسه تماس الزامی است:

```powershell
python load-tests/run_load.py --scenario retry-storm --requests 50 --concurrency 5 --allow-mutations --call-id UUID-OF-QA-CALL
```

این کار را روی تماس تولیدی انجام ندهید. برای ۵۰۰ آیتم queue، ابتدا در tenant آزمایشی ۵۰۰ فایل وارد کنید و رشد queue، نرخ شکست و زمان تخلیه را از endpoint مانیتورینگ یا ابزار زیرساخت ثبت کنید.

فایل نمونه موجود `DRY_RUN` است و هیچ ادعای کارایی ندارد. exit code برابر `3` یعنی درخواست‌ها اجرا شده‌اند ولی gate پیش‌فرض (خطا حداکثر ۱٪ و p95 حداکثر ۲ ثانیه) پاس نشده است.

برای ثبت CPU/RAM کانتینرها، اتصال/حجم PostgreSQL، عمق صف Redis، فضای دیسک و health در آزمون طولانی، collector را در PowerShell دوم اجرا کنید:

```powershell
$env:MOKALEMEBAN_TEST_TOKEN="توکن-کوتاه‌عمر-آزمایش"
powershell -ExecutionPolicy Bypass -File load-tests/collect_compose_metrics.ps1 -DurationSeconds 86400 -IntervalSeconds 30
```

خروجی NDJSON در `load-tests/results` قرار می‌گیرد. مقدار token ذخیره نمی‌شود. بدون token، endpoint محافظت‌شده API خطا ثبت می‌کند ولی سایر نمونه‌ها ادامه می‌یابند.
