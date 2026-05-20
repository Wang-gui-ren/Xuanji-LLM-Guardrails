# Changelog

All notable changes to `Xuanji LLM Guardrails` will be documented in this file.

The format is based on Keep a Changelog, and this project follows Semantic Versioning in a pragmatic release style.

## [v1.0.0] - 2026-05-20

### Added

- Initial AstrBot plugin release for `Xuanji LLM Guardrails`.
- Input guard for prompt injection, high-risk requests, unsafe intent, and toxic language detection.
- Output guard for unsafe output review, toxic output control, and PII masking.
- Tool-chain guard wrapper for Agent tool input and output inspection without modifying AstrBot core components.
- Local audit logging for guard decisions and rewritten payloads.
- Local knowledge-base accumulation for dialogue summaries, runtime safety events, and evolution notes.
- Guard commands for status checks, provider inspection, knowledge review, manual note writing, input scan, output review, SafeDecoding calls, and evolution triggering.
- Configurable provider routing for AstrBot providers or OpenAI-compatible APIs.
- User-facing English safety block messages with risk category explanations.

### Changed

- Unified public project naming to `璇玑大模型护栏 | Xuanji LLM Guardrails`.
- Standardized release-facing metadata, README naming, author information, and project description for GitHub publication.
- Standardized the default high-risk safe response template in English for consistency with moderation prompts and audit logs.

### Security

- Added layered guard behavior across input, output, and tool-calling stages.
- Added hidden baseline sensitive lexicon support combined with user-configurable sensitive keywords.
- Added risk category attribution for blocked content, including jailbreak, violence, illegal websites, corruption, pornography, misinformation, toxic language, and related high-risk classes.

### Notes

- The internal plugin package identifier remains `astrbot_plugin_senbenzakula_guard` for compatibility with existing AstrBot installation paths and local plugin data directories.
