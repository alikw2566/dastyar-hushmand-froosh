# اتصال Issabel/Asterisk

## روش‌های عملیاتی پشتیبانی‌شده

نسخه فعلی **Local/Shared Folder** و **SFTP فقط‌خواندنی** را اجرا می‌کند. برای حسابی که فقط SFTP دارد و shell/upload/delete آن بسته است، روش SFTP انتخاب مناسب‌تری است. Watcher فایل را موقت دریافت، اعتبارسنجی، با CDR تطبیق و سپس در MinIO داخلی ثبت می‌کند؛ فایل روی Issabel تغییر یا حذف نمی‌شود.

### تنظیم SFTP و MariaDB CDR

رمزها فقط در `.env` سرور یا فایل secret قرار می‌گیرند و نباید commit شوند. اگر رمز شامل `@`، `#` یا `:` است از فیلدهای جداگانه زیر استفاده کنید؛ برنامه URL امن SQLAlchemy را خودش می‌سازد.

```dotenv
ISSABEL_IMPORT_MODE=sftp
ISSABEL_SFTP_HOST=IP-ISSABEL
ISSABEL_SFTP_PORT=22
ISSABEL_SFTP_USERNAME=readonly_audio
ISSABEL_SFTP_PASSWORD="PASSWORD"
ISSABEL_SFTP_REMOTE_PATH=/recordings
ISSABEL_SFTP_KNOWN_HOSTS=/run/secrets/issabel_known_hosts
ISSABEL_SFTP_ALLOW_INSECURE_HOST_KEY=false

ISSABEL_CDR_HOST=IP-ISSABEL
ISSABEL_CDR_PORT=3306
ISSABEL_CDR_USERNAME=cdr_reader
ISSABEL_CDR_PASSWORD="PASSWORD"
ISSABEL_CDR_DATABASE=asteriskcdrdb
ISSABEL_CDR_TABLE=cdr
ISSABEL_CDR_RECORDING_COLUMN=recordingfile
ISSABEL_CDR_MATCH_WINDOW_SECONDS=180

DEFAULT_TENANT_ID=UUID-شرکت-پایلوت
ISSABEL_DEFAULT_TENANT_ID=UUID-شرکت-پایلوت
```

کلید میزبان را از یک دستگاه مطمئن داخل شبکه شرکت بگیرید و مسیر فایل را در `ISSABEL_SFTP_KNOWN_HOSTS_HOST_PATH` بگذارید:

```bash
ssh-keyscan -p 22 IP-ISSABEL > deploy/issabel/known_hosts
```

اثر انگشت خروجی را با مدیر سرور تطبیق دهید. در production هرگز `ISSABEL_SFTP_ALLOW_INSECURE_HOST_KEY=true` نگذارید.

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

### تطبیق read-only با CDR

برای پایلوت، کاربر MariaDB فقط باید `SELECT` روی جدول CDR داشته باشد. روش متغیرهای جداگانه بالا ترجیح دارد؛ URL قدیمی هم برای سازگاری پشتیبانی می‌شود:

```dotenv
ISSABEL_CDR_DATABASE_URL=mysql+asyncmy://cdr_reader:PASSWORD@ISSABEL_IP:3306/asteriskcdrdb
ISSABEL_CDR_TABLE=cdr
ISSABEL_CDR_RECORDING_COLUMN=recordingfile
ISSABEL_CDR_MATCH_WINDOW_SECONDS=180
```

سیستم ابتدا نام فایل را با ستون `recordingfile` تطبیق می‌دهد، سپس `uniqueid` و در نبود آن زمان/مبدأ/مقصد را امتحان می‌کند. نتیجه برای هر تماس با یکی از وضعیت‌های `matched`، `ambiguous` یا `unmatched` ذخیره می‌شود. خطای موقت CDR باعث حذف فایل صوتی نمی‌شود؛ تماس با fallback نام فایل وارد می‌شود و خطای تطبیق برای بازبینی باقی می‌ماند.

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
docker compose run --rm watcher python -m app.check_issabel
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
