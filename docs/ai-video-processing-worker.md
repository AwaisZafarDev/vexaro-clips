# VEXARO CLIPS — AI video processing pipeline

## Current deployed foundation

- Supabase project: `pfnzqktfiatxcqrtpevm`
- Durable queue: `pgmq.q_video_processing` (basic durable PGMQ queue)
- Database trigger: new `video_jobs` rows with `source_type = 'upload'`, a non-null `source_path`, and `status = 'queued'` are added to the queue.
- Private input bucket: `source-videos` (50 MB limit)
- Private output bucket: `generated-clips`
- `process-video-job`: authenticated, owner-scoped dispatcher. It refuses YouTube jobs until authorized ingestion is implemented. It creates a short-lived source download URL and per-clip signed upload targets, then submits the job to the configured processor.
- `video-processing-callback`: accepts provider callbacks only when `VIDEO_PROCESSOR_WEBHOOK_SECRET` matches. It validates output paths and checks that MP4 objects exist in the private output bucket before saving clip rows and marking a job complete.

## Provider configuration still required

The actual video analysis and rendering engine is intentionally not faked. Configure these Supabase Edge Function secrets only after selecting and provisioning a compatible processor:

- `VIDEO_PROCESSOR_URL`: base HTTPS URL of the processor API. The dispatcher sends `POST {VIDEO_PROCESSOR_URL}/jobs`.
- `VIDEO_PROCESSOR_TOKEN`: bearer token used to authenticate dispatcher requests to the processor.
- `VIDEO_PROCESSOR_WEBHOOK_SECRET`: high-entropy secret shared with the processor for authenticated callbacks.

No provider credentials are currently configured. Until they are, `process-video-job` returns `503 VIDEO_PROCESSOR_NOT_CONFIGURED` and does not claim that any video was processed. No paid service has been enabled.

## Processor request contract

The dispatcher sends JSON containing:

- `job_id`, `user_id`
- `source_video_url`: time-limited URL for the user's private uploaded source video
- `requested_clip_count`, `aspect_ratio`, `caption_language`, `category`
- `callback_url` and `callback_authorization`
- `output_bucket = generated-clips`
- `output_upload_targets[]`: one path-scoped signed upload URL/token per requested MP4. These are temporary bearer credentials; the processor must keep them private and upload only the corresponding MP4 to each target.

The processor should respond with HTTP 202 and JSON such as `{ "job_id": "provider-job-reference" }`. It must use the supplied idempotency key to avoid duplicate jobs.

## Callback contract

The processor sends `POST callback_url` with:

```json
{
  "job_id": "the-vexaro-job-uuid",
  "status": "processing",
  "pipeline_stage": "transcribing",
  "progress_percent": 35,
  "transcript": { "segments": [] },
  "highlights": []
}
```

For completion, upload each rendered MP4 first, then send:

```json
{
  "job_id": "the-vexaro-job-uuid",
  "status": "completed",
  "transcript": { "segments": [] },
  "highlights": [],
  "clips": [
    {
      "storage_path": "user-uuid/job-uuid/clip-01.mp4",
      "title": "Clip title",
      "start_seconds": 12.5,
      "end_seconds": 42.5
    }
  ]
}
```

For failure, send `{ "job_id": "...", "status": "failed", "error": "short safe error" }`.

Callbacks must include `Authorization: Bearer <VIDEO_PROCESSOR_WEBHOOK_SECRET>`. The callback function checks that each clip belongs under the job owner's exact job folder, ends in `.mp4`, and already exists in the private bucket. It then records metadata in `generated_clips` and marks the job complete.

## Processing stages expected from a compatible provider

1. Validate and inspect the uploaded media.
2. Extract audio and produce a timestamped transcript.
3. Score candidate moments for context, completeness, and viewer interest.
4. Select up to the requested clip count without overlapping duplicate moments.
5. Render each clip in the requested aspect ratio, including reframing and readable captions.
6. Upload MP4 outputs to the signed targets.
7. Send progress and completion/failure callbacks.

## Not yet supported

- Arbitrary YouTube URL downloading. A YouTube link is metadata only; ingestion must use an authorized provider or a supported owner-authorized import flow.
- Automatic queue polling/scheduling. The durable queue and insert trigger are in place, but a queue consumer/scheduler still needs to be connected.
- A live AI transcription/highlight/rendering provider. No provider is currently configured.
- ZIP packaging and clip preview playback in the UI.

Never place Supabase service-role keys, provider tokens, or webhook secrets in frontend code or public repository files.