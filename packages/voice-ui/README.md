# @gisul/voice-ui

Shared browser-side LiveKit building blocks for Voice AI Platform products.
This package contains no product prompts, worker names, backend URLs, or API
keys.

Product applications own their setup forms, branding, copy, completion UX, and
same-origin `/api/sessions` route. They can use the composed `VoiceSession`, or
compose a fully custom design from `VoiceRoom`, `LocalParticipantVideo`,
`VoiceAgentStatus`, and `VoiceSessionControls`.

```tsx
import {
  VoiceRoom,
  LocalParticipantVideo,
  VoiceSessionControls,
} from "@gisul/voice-ui";

<VoiceRoom credentials={credentials} choices={deviceChoices}>
  <AaptorInterviewHeader />
  <LocalParticipantVideo label="Candidate" />
  <AaptorAgentPanel />
  <VoiceSessionControls />
</VoiceRoom>;
```

The consuming application must install compatible versions of React,
`livekit-client`, and `@livekit/components-react`. When consuming the raw
TypeScript source from this monorepo, add `@gisul/voice-ui` to the Next.js
`transpilePackages` option.
