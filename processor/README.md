# VEXARO CLIPS self-hosted processor (first pass)

This service implements the HTTP contract used by the Supabase `process-video-job` function. It downloads an authorized uploaded source video, transcribes speech with faster-whisper, selects non-overlapping speech-dense highlight windows, renders MP4 clips with burned-in captions using FFmpeg, uploads clips to the supplied private Supabase signed upload targets, and calls the Supabase callback.

## Important limitations

- This is a first-pass, CPU-based pipeline. Highlight ranking is a transparent transcript heuristic, not a trained semantic highlight model.
- Captions currently follow the spoken language detected by Whisper. The `caption_language` request field is not yet used for translation.
- The container must be hosted on a machine/container service with enough RAM, CPU, and disk. Model download and first startup can take time.
- No hosting provider or paid service has been enabled by this repository change.
- The in-memory idempotency map protects only the lifetime of one running container. Use a persistent job store before multi-instance production deployment.
- YouTube URLs are intentionally not fetched. Only owner-authorized uploads supplied as signed source URLs are accepted.
- Input limit defaults to 50 MB; keep it aligned with the Supabase Storage bucket limit.

## Run locally

Requires Docker. From this directory:

```bash
docker build -t vexaro-processor .
docker run --rm -p 8080:8080 \
  -e VIDEO_PROCESSOR_TOKEN='set-a-long-random-token' \
  -e WHISPER_MODEL=base \
  -v vexaro-model-cache:/models \
  vexaro-processor
```

Health check: `GET http://localhost:8080/health`

Configure these Supabase Edge Function secrets in the Supabase project (never in the frontend):

- `VIDEO_PROCESSOR_URL`: public HTTPS base URL of this container, without a trailing slash
- `VIDEO_PROCESSOR_TOKEN`: same token passed to the container
- `VIDEO_PROCESSOR_WEBHOOK_SECRET`: same high-entropy callback secret configured for the callback function

The processor API accepts `POST /jobs` with a Bearer token and the JSON contract documented in `../docs/ai-video-processing-worker.md`.

## Production hardening still needed

- Durable external job state and retry/recovery across restarts
- Rate limits, request size controls, and per-user concurrency limits
- Semantic highlight ranking and optional translation
- Automated integration tests with a sample video
- A public HTTPS deployment and secret provisioning
