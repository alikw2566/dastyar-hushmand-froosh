# اتصال Issabel/Asterisk

## روش عملیاتی پشتیبانی‌شده

نسخه فعلی روش **Local/Shared Folder** را اجرا می‌کند. پوشه ضبط Issabel باید روی میزبان Docker به‌صورت مسیر محلی، SMB یا NFS mount شده باشد و سپس با `ISSABEL_HOST_RECORDINGS_PATH` داخل کانتینر Watcher روی `/recordings` bind شود.

متغیرهای SFTP در config پیش‌بینی شده‌اند، اما SFTP Puller هنوز پیاده‌سازی نشده و `/health/ready` در حالت `sftp` پاسخ 503 با `sftp_mode_not_implemented` می‌دهد. برای پایلوت از SFTP استفاده نکنید.

## آماده‌سازی Issabel

1. ضبط تماس‌های صف/داخلی موردنظر را در Issabel فعال کنید و رضایت قانونی ضبط را برقرار کنید.
2. دسترسی سرویس را فقط به پوشه ضبط لازم محدود کنید. پیشنهاد امن‌تر این است که Issabel فایل‌های کامل‌شده را به یک drop-folder اختصاصی کپی کند؛ Watcher را مستقیماً با دسترسی گسترده به کل spool اجرا نکنید.
3. ساعت Issabel و سرور برنامه را با NTP هماهنگ و timezone را ثبت کنید. timestamp دیتابیس UTC است.
4. فرمت‌های مجاز پیش‌فرض `.wav,.mp3,.gsm` هستند. ffprobe/ffmpeg داخل تصویر backend نصب‌اند.

### Windows و SMB

Share را با یک حساب سرویس کم‌اختیار روی میزبان mount کنید و Docker Desktop را مجاز به خواندن آن مسیر کنید. نمونه `.env`:

```dotenv
ISSABEL_IMPORT_MODE=shared_folder
ISSABEL_HOST_RECORDINGS_PATH=Z:\Issabel\recordings-drop
ISSABEL_RECORDINGS_PATH=/recordings
ISSABEL_QUARANTINE_PATH=/quarantine
ISSABEL_POLL_INTERVAL=10
ISSABEL_FILE_STABILITY_SECONDS=15
DEFAULT_TENANT_ID=UUID-شرکت-پایلوت
ISSABEL_DEFAULT_TENANT_ID=UUID-شرکت-پایلوت
```

این دو UUID باید برابر باشند و پیش از ورود اولین فایل، فرمان `python -m app.bootstrap_admin` با موفقیت سازمان و مدیر اولیه را ساخته باشد.

در Compose مسیر میزبان فقط از `ISSABEL_HOST_RECORDINGS_PATH` گرفته می‌شود و مسیر داخل کانتینر باید `/recordings` بماند. اگر Docker به drive map‌شده دسترسی ندارد، از UNC قابل‌دسترسی برای سرویس Docker یا یک پوشه محلی sync‌شده استفاده کنید.

### Linux و NFS/SMB

ابتدا mount پایدار سیستم‌عامل را بسازید و سپس همان مسیر را در `.env` قرار دهید:

```dotenv
ISSABEL_IMPORT_MODE=shared_folder
ISSABEL_HOST_RECORDINGS_PATH=/mnt/issabel/recordings-drop
ISSABEL_RECORDINGS_PATH=/recordings
```

مجوز خواندن فایل‌ها و نوشتن/انتقال فایل خراب به quarantine را تست کنید. فایل سالم اصلی حذف یا overwrite نمی‌شود؛ فایل خراب ممکن است به volume قرنطینه منتقل شود. اگر منبع باید read-only باشد، ابتدا فایل‌ها را به drop-folder قابل‌نوشتن کپی کنید.

## الگوی نام فایل و metadata

Parser روی الگوهای رایج Asterisk fallback دارد و در صورت ناشناخته‌بودن نام، فایل را از دست نمی‌دهد. برای قالب اختصاصی، regex دارای named group تعریف کنید:

```dotenv
ISSABEL_FILENAME_PATTERN=^(?P<direction>in|out)-(?P<caller>\d+)-(?P<destination>\d+)-(?P<date>\d{8})-(?P<time>\d{6})-(?P<uniqueid>[^.]+)
```

نام گروه‌های قابل استفاده را با یک مجموعه فایل واقعی غیرحساس در محیط QA آزمایش کنید: `caller`، `destination`، `extension`، `direction`، `date`، `time`، `uniqueid`، `queue` و `agent`. الگوی نامناسب نباید مانع import شود، ولی metadata ناشناخته `null` می‌ماند.

## رفتار Watcher

- پسوندهای `.tmp,.part,.partial,.download` نادیده گرفته می‌شوند.
- تغییر size/mtime، شمارش زمان پایداری را از نو شروع می‌کند.
- SHA-256 و شناسه مسیر در `source_imports` ثبت می‌شوند.
- فایل سالم به MinIO وارد، Call ساخته و job در Celery صف می‌شود.
- فایل خراب با error code امن ثبت و قرنطینه می‌شود.
- restart سرویس به علت unique constraint باعث پردازش دوباره فایل قبلی نمی‌شود.

## راه‌اندازی و بررسی

```powershell
docker compose up -d --build postgres redis minio api worker watcher
docker compose ps
Invoke-RestMethod http://localhost:8010/health/live
Invoke-RestMethod http://localhost:8010/health/ready
Invoke-WebRequest http://localhost:8010/metrics
docker compose logs --since 10m watcher
```

یک WAV کوتاه، غیرحساس و دارای رضایت را ابتدا با پسوند `.part` در drop-folder کپی کنید؛ سپس rename اتمیک به `.wav` انجام دهید. انتظار:

1. در زمان `.part` کشف نشود؛
2. تا پایان stability window در وضعیت انتظار بماند؛
3. یک `source_import` و یک تماس بسازد؛
4. کپی مجدد همان bytes با نام دیگر duplicate شناخته شود؛
5. فایل خراب به quarantine برود و Watcher زنده بماند.

## توقف امن و تغییر مسیر

قبل از تغییر mount یا tenant:

```powershell
docker compose stop watcher
docker compose config
docker compose up -d watcher
```

هر instance Watcher فعلی یک `ISSABEL_DEFAULT_TENANT_ID` دارد. برای چند شرکت، instance و drop-folder جدا برای هر tenant لازم است؛ routing چند tenant از یک پوشه هنوز پیاده نشده است.
