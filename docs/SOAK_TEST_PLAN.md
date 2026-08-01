# برنامه آزمون فشار و پایداری

وجود این برنامه اثبات پایداری نیست. وضعیت «هفت روز بدون دخالت» فقط پس از اجرای واقعی هفت‌روزه، حفظ log و امضای نتیجه قابل اعلام است.

## ابزار

`load-tests/run_load.py` سناریوهای `health`، `dashboard`، `upload`، `retry-storm` و endpoint سفارشی را با Python استاندارد اجرا می‌کند. خروجی JSON/HTML، latency p50/p95/p99، throughput، error rate، statusها، حافظه harness و snapshotهای metrics را ثبت می‌کند. token در گزارش ذخیره نمی‌شود.

`load-tests/collect_compose_metrics.ps1` نیز در یک shell جدا، آمار CPU/RAM کانتینر، connection/size دیتابیس، عمق صف Redis، health و فضای دیسک را به NDJSON append می‌کند.

نمونه موجود `DRY_RUN` است و نتیجه performance نیست.

## پیش‌شرط

- tenant و داده آزمایشی جدا؛
- فایل‌های صوتی consented و غیرمحرمانه/ناشناس؛
- backup موفق و امکان reset محیط؛
- dashboard مانیتورینگ CPU، RAM، disk، PostgreSQL connections، Redis queue، MinIO و provider quota؛
- token کوتاه‌عمر در متغیر محیط؛
- ثبت commit، image digest، worker count و منابع ماشین.

## مراحل

### ۱. Baseline پنج‌دقیقه‌ای

```powershell
& ".\.venv\Scripts\python.exe" load-tests/run_load.py --scenario health --requests 100 --concurrency 5
```

### ۲. کاربران هم‌زمان داشبورد

```powershell
$env:MOKALEMEBAN_TEST_TOKEN="short-lived-token"
& ".\.venv\Scripts\python.exe" load-tests/run_load.py `
  --scenario dashboard --duration-seconds 600 --concurrency 20 --rate-per-second 40 `
  --metrics-url http://localhost:8000/health/details
```

### ۳. Burst صد فایل

```powershell
& ".\.venv\Scripts\python.exe" load-tests/run_load.py `
  --scenario upload --requests 100 --concurrency 5 `
  --audio-file "D:\qa-data\short-consented-call.wav" `
  --metrics-url http://localhost:8000/health/details
```

برای سناریوی ۵۰۰ تماس در queue، ۵۰۰ idempotency key یکتا وارد و زمان رسیدن queue به صفر، تعداد completed/review/failed و هزینه provider ثبت شود. concurrency Worker را وسط تست تغییر ندهید مگر سناریوی جداگانه scaling باشد.

### ۴. Failure injection کنترل‌شده

- توقف موقت Worker و رشد queue؛ سپس restart و drain؛
- توقف کوتاه Redis/MinIO/PostgreSQL در محیط QA؛
- provider timeout/429؛ بررسی backoff و سقف retry؛
- restart Watcher هنگام copy فایل؛
- retry storm فقط با `--allow-mutations` و call idهای QA؛
- export Excel بزرگ و PDF هم‌زمان با dashboard.

هیچ failure injection روی محیط مشتری بدون change window انجام نشود.

### ۵. Soak ۲۴ ساعته توسعه

الگوی پیشنهادی: میانگین بار واقعی تخمینی، burst ساعتی، upload پیوسته، dashboard read و export دوره‌ای. هر ۳۰ ثانیه snapshot زیر ثبت شود:

- process/container CPU و memory؛
- disk free، اندازه PostgreSQL/MinIO/Redis؛
- queue depth و سن قدیمی‌ترین job؛
- DB pool/connections؛
- تعداد status و error code؛
- p95/p99 و نرخ خطا؛
- Watcher heartbeat و زمان آخرین scan؛
- هزینه/429/latency ارائه‌دهنده مدل.

### ۶. آزمون هفت‌روزه پایلوت

پس از پاس ۲۴ ساعت، روی محیط کنترل‌شده هفت روز اجرا شود. عملیات مجاز روزانه فقط مشاهده است؛ هر restart، پاک‌سازی queue، correction دستی زیرساخت یا تغییر config به‌عنوان intervention ثبت و شرط «بدون دخالت» را fail می‌کند.

## Gateهای اولیه پیشنهادی

این‌ها baseline پذیرش‌اند و SLA قراردادی نیستند:

- zero data loss و zero duplicate برای فایل‌های واردشده؛
- cross-tenant incident برابر صفر؛
- error rate درخواست read کمتر از ۱٪ و p95 کمتر از ۲ ثانیه در سخت‌افزار ثبت‌شده؛
- job دائماً queued/retry بدون visibility برابر صفر؛
- رشد memory/queue بدون بازگشت به baseline وجود نداشته باشد؛
- failed دائمی علت و runbook داشته باشد؛
- backup زمان‌بندی‌شده و حداقل یک restore در طول دوره موفق؛
- تمام فایل‌های stable حداکثر در polling + stability window کشف شوند.

Threshold پردازش صوت به quota و طول تماس وابسته است و باید بعد از baseline واقعی تعیین شود.

## توقف اضطراری

در نشت tenant، data corruption، مصرف کنترل‌نشده هزینه، disk کمتر از ۱۵٪، queue رو به رشد بدون drain یا error rate بالاتر از ۱۰٪ برای پنج دقیقه تست را متوقف، artifactها را حفظ و incident باز کنید.

## گزارش نهایی

گزارش باید شامل command redacted، زمان UTC، commit، config غیرمحرمانه، topology، workload، نمودار منابع، شمارش outcome، failure/intervention، gateهای pass/fail و لینک artifact باشد. نتیجه فقط یکی از این‌هاست: `PASS`، `FAIL` یا `INCONCLUSIVE`؛ توقف زودهنگام `PASS` نیست.
