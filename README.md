# VEXARO CLIPS

A creator-focused video-to-shorts workspace. This repository contains the responsive web app foundation and an initial Supabase data model.

## Included
- Responsive React + TypeScript dashboard for mobile and desktop.
- Video file picker with a 2 GB client-side size guard.
- YouTube URL input with an ownership/permission reminder.
- Category, clip-count, aspect-ratio, and caption-language settings.
- Supabase client setup using environment variables.
- Initial database tables and row-level security policies.

## Honest project status
AI highlight detection, transcription, clip rendering, caption timing, licensed audio, YouTube ingestion, previews, MP4 downloads, and ZIP exports are **not connected yet**. The interface clearly labels this as a preview. A separate authenticated processing API and worker service is required before actual clipping can run.

## Requirements
Node.js 20.19+ or 22.12+, and npm.

## Local development
```bash
npm install
cp .env.example .env.local
npm run dev
```

Set `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY` in `.env.local` when the dedicated Supabase project is ready. Never expose service-role or secret keys in browser code.

## Supabase setup
1. Create a separate Supabase project for VEXARO CLIPS. Do not reuse unrelated projects.
2. Review and apply `supabase/schema.sql`.
3. Confirm Data API exposure and grants for the required tables; keep RLS enabled.
4. Create private Storage buckets `source-videos` and `generated-clips`.
5. Configure a 2 GB source object limit and use TUS resumable uploads for large files.
6. Add and test storage object policies before allowing uploads.

## Cloudflare Pages
Build command: `npm run build`  
Output directory: `dist`  
Framework: Vite  
Environment variables: the two public Supabase values above.

## Processing architecture still required
An authenticated job API and worker must handle resumable uploads, media probing, speech transcription, highlight scoring, vertical reframing, caption rendering, licensed audio, encoding, and secure delivery. Keep all processing credentials server-side. Only process video sources that the user owns or is authorized to use, through permitted ingestion methods.

## Roadmap
1. Authentication and saved projects.
2. Private resumable uploads with progress.
3. Processing queue and worker orchestration.
4. AI transcript and highlight selection.
5. Rendering, preview, and caption styling.
6. Individual MP4 and ZIP exports.
7. Usage limits, cost controls, and monitoring.


## Connected Supabase project

The VEXARO CLIPS project uses its dedicated Supabase project for authentication and job metadata. Cloudflare Pages production and preview builds receive the public Supabase URL and publishable key through environment variables. Never put a Supabase secret key in browser code.
