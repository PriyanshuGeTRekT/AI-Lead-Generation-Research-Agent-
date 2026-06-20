# Human Maximizer Website

Next.js App Router project for Human Maximizer marketing pages and product module pages.

## Architecture documentation

- [Product page conventions](docs/product-page-conventions.md) — section order, SEO keys, FAQ placement, shared components
- [Deferred architecture decisions](docs/future-architecture.md) — CMS, i18n, email queue tradeoffs (tracked for later)

## Setup

1. Install dependencies:

```bash
npm install
```

2. Create local env file:

```bash
cp .env.example .env.local
```

3. Set environment variables:

- `MONGODB_URI`: MongoDB connection string
- `MONGODB_DB`: database name (optional, defaults to URI database)
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM`: SMTP config for sending mail
- `SMTP_TO`: inbox that receives **contact** and **book-demo** notification emails (submitter details). Example: `hidrodox8989@gmail.com`. If omitted, notifications go to `SMTP_USER`.

**Amazon SES (recommended for production):** The app uses **SES SMTP** with Nodemailer (`src/lib/email/smtpTransporter.ts`). Example variable set: `docs/ses-smtp.env.example`.

1. In **AWS SES** (choose a region), verify a **domain** or **email** used as the **From** address.
2. **SES → SMTP settings → Create SMTP credentials** — copy **SMTP username** (often `AKIA…`) and **SMTP password** (not your AWS login).
3. Set `SMTP_HOST` to `email-smtp.<region>.amazonaws.com` for that region ([SMTP endpoints](https://docs.aws.amazon.com/ses/latest/dg/smtp-connect.html)), e.g. `email-smtp.us-east-1.amazonaws.com`.
4. `SMTP_PORT=587` (STARTTLS) or `465` (TLS). Set **`SMTP_FROM`** to a verified sender (required: SES SMTP `SMTP_USER` is not an email).
5. **`SMTP_TO`** = inbox for contact + demo notifications (verify that email in SES while in **sandbox**, or exit sandbox).

**Gmail / Google Workspace SMTP (alternative):** Google does not accept your normal account password for SMTP. Use a [Google App Password](https://support.google.com/accounts/answer/185833) (requires 2-Step Verification on the account). Set `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587` (or `465`), `SMTP_USER` to the **full email address** that owns the App Password, and `SMTP_PASS` to the 16-character App Password (no spaces). If `SMTP_FROM` is set, it should be the same address or an alias allowed for that account.

- `CRON_SECRET` (optional): long random string; required for `GET /api/cron/email-queue` to drain the mail queue on a schedule.

- `NEXT_PUBLIC_SITE_URL`: canonical site URL for metadata and Open Graph (optional; defaults to production URL in `src/constants/seo.ts`). In production this must match the public URL (https, apex vs www) so canonicals and social previews stay correct.
- `NEXT_PUBLIC_IMAGE_REMOTE_HOSTS` (optional): comma-separated hostnames allowed for `next/image` when blog thumbnails or avatars use absolute `https://` URLs (e.g. a CDN). You can provide bare hosts or full URLs; config normalizes them to hostnames. Defaults include `humanmaximizer.com`, `www.humanmaximizer.com`, `localhost`, and `127.0.0.1`. Example: `cdn.example.com,https://images.ctfassets.net`.

## Run Locally

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Contact and demo APIs

- Contact: `POST /api/contact` — `src/app/api/contact/route.ts`
- Book demo: `POST /api/book-demo` — `src/app/api/book-demo/route.ts`

Both routes apply **per-IP rate limiting** (in-memory sliding window; 10 requests per minute per route). For multiple server instances or stricter abuse protection, replace with Redis (e.g. Upstash) or edge middleware.

## Contact Form Storage

The contact form stores submissions in MongoDB.

- DB connector: `src/lib/mongodb.ts`
- Model: `src/models/ContactSubmission.ts`
- Outbound mail: `src/lib/email/queue/emailQueue.ts` (MongoDB-backed jobs) and senders in `src/lib/jobs/contactEmailJob.ts` / `demoBookingEmailJob.ts`

Demo bookings use `src/models/DemoBooking.ts` and the same mail pipeline.

### Email event queue

After a successful form save, the API **enqueues** a document in the `EmailQueueJob` collection (`src/models/EmailQueueJob.ts`), then returns a success response. Delivery runs **after** the response via Next.js `after()` by draining the queue (SMTP send + retries with exponential backoff). Jobs survive process restarts because they live in MongoDB.

Optional **`CRON_SECRET`**: set in production and call `GET /api/cron/email-queue` with header `Authorization: Bearer <CRON_SECRET>` on a schedule (e.g. Vercel Cron every minute) to drain stuck or backlog jobs if `after()` did not run or a worker died mid-send. Without `CRON_SECRET`, the cron route returns 503.

## Production Commands

```bash
npm run lint
npm test
npm run build
npm run start
```

## Bundle analysis

To inspect client/server chunks after a production build:

```bash
npm run analyze
```

This sets `ANALYZE=true` and runs `next build` with `@next/bundle-analyzer`.
