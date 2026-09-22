# AI Interviewer Service Levels

These are launch gates for the API-provider interviewer path. Measurements must
be split by environment, tenant, provider, model, region, and product without
including candidate names, document text, transcripts, credentials, or tokens.

## Availability and correctness

- Session preparation success: at least 99.9% over 30 days.
- Agent dispatch and join success: at least 99.5% within 15 seconds.
- Completed interviews with a durable terminal state: at least 99.9%.
- Persisted final-turn delivery: at least 99.99%.
- Duplicate paid provider requests caused by retries: below 0.1%.

## Latency

- Session API p95: below 800 ms, excluding LiveKit worker join.
- Agent join p95: below 5 seconds.
- Sarvam first partial transcript p95: below 300 ms after speech starts.
- End-of-speech to OpenAI first question token p95: below 700 ms.
- ElevenLabs request to first playable audio p95: below 300 ms.
- End-of-speech to first interviewer audio p95: below 1.5 seconds initially,
  with 1.2 seconds as the optimization target.

## Reliability

- Unexpected disconnect rate: below 1% of started interviews.
- Successful reconnect within 15 seconds: at least 95%.
- Provider fallback activation: alert above 2% in any 15-minute window.
- Worker crash/restart without phase regression: at least 99.9%.

## Cost and capacity

- Record provider requests, tokens, audio seconds, retries, and estimated cost by
  interview session and provider.
- Alert at 80% of provider project rate limits and daily spend budgets.
- Run a 60-minute soak at expected peak concurrency and a 2x burst test before
  each production capacity increase.

## Alerting

Page on session creation failure above 2%, agent join failure above 5%, missing
durable completion above 0.5%, or provider authentication failure above zero.
Create non-paging alerts for latency budget misses, reconnect degradation,
unexpected fallback usage, and cost anomalies.
