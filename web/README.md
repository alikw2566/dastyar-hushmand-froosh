# داشبورد مکالمه‌بان

رابط فارسی و راست‌چین سامانه هوش مکالمه فروش. این برنامه بدون داده نمونه شروع
می‌شود و کاربر ناشناس را به ورود یا ساخت حساب هدایت می‌کند.

## پیش‌نیاز

- Node.js `>=22.13.0`

## اجرای محلی

```powershell
npm.cmd install
npm.cmd run dev
```

آدرس برنامه: `http://localhost:3000`

در Development و وقتی `API_BASE_URL` و `OIDC_ISSUER` تنظیم نشده‌اند، یک فضای
Preview محلی D1/R2 برای ساخت حساب، ورود و آزمایش رابط فعال می‌شود. برای اجرای
واقعی پردازش صوت و پایلوت، این متغیرها باید به FastAPI و Keycloak اشاره کنند.

## فرمان‌های بررسی

```powershell
npm.cmd run lint
npx.cmd tsc --noEmit
npm.cmd test
```
