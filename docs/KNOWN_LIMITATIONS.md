# محدودیت‌های شناخته‌شده

این فهرست بخشی از تحویل است و نباید در ارائه پایلوت حذف شود.

## مانع‌های اثبات عملیاتی

- دقت رونویسی فارسی روی دیتاست تماس واقعی اندازه‌گیری نشده است. گزارش فعلی فقط دو نمونه ساختگی و `NOT_MEASURED_ON_REAL_CALLS` است.
- دقت جداسازی نقش فروشنده/مشتری روی تماس تک‌کاناله واقعی اندازه‌گیری نشده است.
- آزمون soak واقعی ۲۴ ساعته و هفت‌روزه اجرا نشده؛ کارکرد مستقل هفت روز اثبات نشده است.
- backup/restore fixture پاس شده، ولی restore کامل PostgreSQL+MinIO و RTO/RPO روی deployment مقصد باید اجرا شود.

## Issabel و Pipeline

- فقط Local/Shared Folder watcher عملیاتی است؛ SFTP با وجود متغیرهای config پیاده نشده و readiness آن 503 است.
- هر Watcher یک tenant ثابت دارد؛ routing چندشرکت از یک پوشه مشترک وجود ندارد.
- watcher polling است، نه event-driven؛ latency کشف به interval و stability window وابسته است.
- فایل corrupt از drop-folder به quarantine منتقل می‌شود؛ اتصال مستقیم به spool read-only یا حیاتی Issabel مناسب نیست.
- stage واژگانی `diarizing` وجود دارد، ولی سرویس رونویسی ممکن است diarization را داخل همان call انجام دهد و رخداد مستقل تولید نشود.

## امنیت و نگهداری

- سیاست RLS جدول‌های عملیاتی جدید اضافه شده، اما اجرای integration test واقعی PostgreSQL برای cross-tenant هنوز باید در Release Gate ثبت شود.
- Compose فعلی reverse proxy/TLS ندارد و Keycloak را با `start-dev` و بدون persistence production اجرا می‌کند.
- rate limit اجرایی backend، WAF و abuse protection کامل نشده‌اند.
- retention days در تنظیمات ذخیره می‌شود، ولی purge زمان‌بندی‌شده PostgreSQL/MinIO و حذف سرتاسری مشتری کامل نیست.
- backup داخلی رمزنگاری‌شده نیست و secret scanner همه قالب‌های سفارشی را تضمین نمی‌کند.
- metrics فعلی حداقلی است؛ مانیتورینگ/alert خارجی و ارسال `ALERT_*` آماده نیست.

## محصول و اتصال‌ها

- تعریف Integration و ذخیره config وجود دارد، اما registry اجرایی CRM/تلفن/پیام خالی است؛ تست اتصال، sync، delivery، webhook signature و retry واقعی وجود ندارد.
- تأیید message draft الزاماً پیام را به SMS/WhatsApp/Email خارجی ارسال نمی‌کند.
- جست‌وجوی معنایی pgvector و پاسخ دارای citation کامل نشده است؛ جست‌وجوی فعلی عمدتاً فیلتر/متن است.
- مقایسه پیشرفته فروشندگان و برنامه مربیگری خودکار هنوز نیازمند اعتبارسنجی KPI واقعی است.
- پرداخت آنلاین و اپ موبایل مستقل خارج از نسخه پایلوت هستند.

## تحلیل و گزارش

- evidence validator ریسک hallucination را کم می‌کند، نه اینکه صفر بودن آن را تضمین کند؛ مقدار کم‌اطمینان نیازمند بازبینی انسانی است.
- تاریخ/مبلغ مبهم عمداً ممکن است `null` بماند؛ سیستم نباید برای پرکردن گزارش داده جعل کند.
- PDF فارسی به فونت نصب‌شده/`PDF_FONT_PATH` و viewer مقصد وابسته است و باید چاپ تست شود.
- Export بزرگ در همان API process ساخته می‌شود و background export/job storage جدا ندارد.
- حالت سبک `web npm run dev` از D1/R2 محلی استفاده می‌کند و معادل backend کامل Docker نیست.

## Release Gate فعلی

تا وقتی RLS جدید، E2E واقعی Issabel، restore کامل و حداقل soak ۲۴ساعته پاس نشده‌اند، وضعیت محافظه‌کارانه `READY_FOR_INTERNAL_TESTING` است؛ نه `READY_FOR_CONTROLLED_PILOT` و نه محصول عمومی.
