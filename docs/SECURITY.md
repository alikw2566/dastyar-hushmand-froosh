# امنیت و حریم خصوصی

## مرز اعتماد

فایل صوتی، نام فایل Issabel، transcript و تمام متن مشتری ورودی غیرقابل اعتماد هستند. مدل نباید دستور داخل مکالمه را اجرا کند. خروجی مدل پیشنهاد است و فقط داده validate‌شده همراه شاهد باید به‌عنوان اطلاعات ساختاریافته استفاده شود.

## کنترل‌های پیاده‌سازی‌شده

- OIDC/JWT با بررسی signature، issuer و audience؛
- نقش‌های `admin/manager/supervisor/seller/agent/viewer` در endpointها؛
- tenant از claim و session setting دیتابیس، نه از پارامتر دلخواه کاربر؛
- RLS اجباری و policy مبتنی بر `app.tenant_id` برای جدول‌های اصلی و عملیاتی جدید؛
- محدودیت اندازه upload، الزام consent و کنترل MIME اولیه؛
- ffprobe/ffmpeg روی ورودی Watcher/Worker و عدم overwrite صوت اصلی؛
- نام object پاک‌سازی‌شده و namespace دارای tenant/call؛
- URL امضاشده MinIO با عمر پیش‌فرض ۱۵ دقیقه؛
- audit برای عملیات مدیریتی و correction history برای ویرایش transcript؛
- prompt صریح برای نادیده‌گرفتن دستور داخل مکالمه و evidence validation؛
- CORS قابل تنظیم و نه wildcard پیش‌فرض؛
- log rotation کانتینر.

## Release blockers و مسئولیت استقرار

1. migration و SQL bootstrap برای جدول‌های عملیاتی جدید RLS می‌سازند، اما Release Gate فقط پس از اجرای تست cross-tenant روی همه آن‌ها پاس می‌شود.
2. Keycloak پایدار شده، اما Compose توسعه‌ای TLS reverse proxy ندارد و با `start-dev` اجرا می‌شود. پیش از دسترسی شبکه‌ای، TLS و hostname نهایی را روی محیط مقصد فعال کنید.
3. `API_RATE_LIMIT_PER_MINUTE` در config وجود دارد، ولی middleware اجرایی rate limit در API دیده نمی‌شود. WAF/proxy limit و سپس تست لازم است.
4. تنظیم `retention_days` ذخیره می‌شود، اما job حذف زمان‌بندی‌شده صوت/داده کامل اثبات نشده است.
5. `ALERT_*` در نمونه env به معنی ارسال alert نیست؛ backend alert sender عملیاتی ندارد.

## Secretها

- `.env`، API key، password، Fernet key، private key و token وارد Git، log یا backup عمومی نشوند.
- مقادیر پیش‌فرض `change-me` قبل از اجرا عوض شوند.
- token آزمون کوتاه‌عمر باشد و در `MOKALEMEBAN_TEST_TOKEN` محیط قرار گیرد.
- کلیدها حداقل فصلی و بلافاصله پس از نشت rotate شوند.
- فایل backup فعلی رمزنگاری داخلی ندارد؛ روی volume رمزنگاری‌شده و سپس با ابزار سازمانی encrypt شود.

## Upload و Issabel

- پسوند/MIME به‌تنهایی قابل اعتماد نیست؛ ffprobe باید قبل از پردازش موفق باشد.
- service account share کم‌اختیار و drop-folder جدا استفاده شود.
- symlink و مسیر خارج از root نباید وارد شود؛ Watcher مسیرهای واقعی زیر root را می‌خواند و quarantine جداست.
- فایل خراب را بدون بررسی به ورودی برنگردانید.
- رضایت ضبط و مبنای قانونی پردازش باید قبل از ingestion ثبت شده باشد.

## داده شخصی

صوت، متن، شماره، مبلغ و رفتار فروشنده داده حساس‌اند. دسترسی بر پایه کمترین اختیار، download صوت قابل توقف و خروجی PDF/Excel دارای کنترل انتقال باشد. درخواست حذف/نگهداری باید در سطح PostgreSQL، MinIO، backup و export اجرا و audit شود؛ پاک‌کردن فقط یک ردیف کافی نیست.

## آزمون امنیتی الزامی

- توکن بدون `tenant_id`، issuer/audience غلط و token منقضی → 401؛
- نقش پایین روی endpoint مدیریت/reprocess → 403؛
- UUID شرکت دیگر → 404/عدم افشای وجود؛
- query مستقیم تحت RLS برای هر جدول tenantدار → صفر ردیف شرکت دیگر؛
- filename traversal، MIME جعلی، فایل حجیم/خراب و zip-bomb مشابه → رد امن؛
- prompt injection داخل transcript → بدون اجرای دستور و بدون خروج secret؛
- XSS در نام مشتری/متن → render متنی و نه HTML آزاد؛
- presigned URL پس از انقضا/غیرفعال‌کردن download → غیرقابل استفاده؛
- backup حاوی `.env`/private key → تست باید fail کند.

## رخداد امنیتی

دسترسی را محدود، token/secret مربوط را revoke، ingestion را در صورت نیاز متوقف، logهای immutable را حفظ و scope tenant/فایل/زمان را تعیین کنید. قبل از پاک‌سازی شواهد، مسئول امنیت/حقوقی سازمان را درگیر کنید.
