# Changelog

All notable changes to MediWise Health Suite will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Removed
- Removed the health-story engine: the eight-domain observation layer, the 24 narrative templates and style selector, per-member style preferences, the animated SVG renderer, and the MP4 video pipeline with its FFmpeg dependency.
- Removed the `health-goals` Skill and its shared goal engine: confirmed action goals, check-ins, progress, milestones, and goal evidence cards are no longer part of the product.
- `add-exercise` and device sync no longer link records to a goal, and the `exercise_records` distance and source columns were reverted with them.
- Retired the story action ids (`generate-weight-story-card`, `select-weight-card-style`, `weight-card-preferences`, `update-weight-card-preferences`, `generate-domain-health-card`, `select-health-card-style`); they now report `Unknown action`.
- The record cards no longer render a per-domain story panel, and `focus=story` is no longer accepted.

### Added
- Added complete member profile, medical record, date-filtered metric, and daily snapshot save/query action routes.
- Wearable sync results now include provider, target member, metric types, per-type counts, and the imported time range.
- Added cross-module Node action tests plus Apple Health interval, ZIP/XML validation, and PDF renderer regression tests.
- Added root and sleep-tracker OpenAI skill metadata.

### Fixed
- Action adapters now propagate Python business errors as top-level action failures instead of reporting a false success.
- Meal logging no longer writes `0` kcal when nutrition cannot be resolved. With no food data source configured, `add-meal` and `add-item` previously stored `total_calories = 0.0` and reported "共0.0kcal" while the read path correctly said `unavailable` — and `0` is a value the downstream aggregates trust, so `calorie-balance`, `nutrition-balance`, the goal comparison, and the briefing all counted the meal as a real zero-calorie intake and divided by it. Nutrition columns are now `NULL` (unknown) rather than `0`, which the schema already allows, so no migration is needed; `0` is reserved for a confirmed zero such as water. Responses carry `nutrition_status` (`resolved`/`partial`/`unresolved`), `nutrition_fields_pending`, `unresolved_items[]` with a per-item `reason`, and an `action_required` instruction to request a label or a data source. Unknown propagates per field, so a mixed meal reports no total instead of a partial sum that would read as a real calorie deficit.
- Every reader now treats an unresolved day as unknown: `daily-summary`, `weekly-summary`, `calorie-trend`, `nutrition-balance`, the daily and weekly goal comparisons, `calorie-balance`, `weekly-report`, `diet-weight-correlation`, and the health briefing. Unresolved days are reported as unresolved and excluded from every average denominator; `macro_ratio` stays empty and `on_track` is `null` rather than computed from unknown inputs, and a day with no records is no longer reported as on-track. `calorie-trend`'s denominator also changed from the whole window to the days actually recorded, so a 7-day window with 2 recorded days no longer averages in five days that were never logged.
- Apple Health imports now require the canonical `export.xml`, reject malformed/non-Health XML during full testing, support named HealthKit sleep stages, and calculate sleep from `startDate`/`endDate` intervals without double-counting overlapping in-bed records.
- Gadgetbridge imports now remove exact samples duplicated across base and extended activity tables before aggregating steps and sleep.
- Member actions no longer discard blood type, allergies, medical history, contact, emergency contact, timezone, or custom range fields.
- Doctor-visit PDF rendering now uses the same cross-platform Chrome/Chromium discovery as PNG rendering and no longer invokes Unix-wide `pkill` cleanup.
- Sleep queries now reject unknown members consistently.
- Corrected the weight workflow text that incorrectly said MediWise automatically derives a calorie target.

### Changed
- Nutrition documentation now states the three-state contract (`NULL` = unknown, `0` = confirmed zero, `> 0` = asserted value) and describes the `add-meal`/`add-item` response fields, replacing the rule text that the write path had drifted away from.
- **Existing rows were not backfilled.** A stored `0` from before this change may have meant "unknown" and cannot be distinguished from a real zero; guessing would be a second fabrication, so nothing was rewritten. Affected historical days will keep reading as zero-calorie days. Re-adding the items with real values is the only correction.
- Health Cards are now the two cards the product actually generates: the personal and family record cards, and the weight truth card. The weight truth card keeps its deterministic path — same-day medians, a Theil–Sen robust trend, and an explicit refusal to draw a line the records cannot support.
- Weight Card analysis moved out of the shared story package into `weight-manager/scripts/robust_weight.py`, where `theil_sen_fit` delegates to the single estimator rather than keeping a second copy.
- Family health cards now organize each member by current status, active medications and schedules, reminders, and explicit attention items. The family timeline has been removed.
- Installation checks now validate six JavaScript action entries instead of seven.
- Health Card typography is now larger throughout personal and family views, with more readable labels, medication schedules, timeline details, and disclaimers at both desktop and narrow widths.
- Health Cards now use a clearer medical-blue visual system with improved contrast, blue metric charts, and a compact full-width layout for the final member in odd-sized family cards.
- Documentation now distinguishes local reminder records from host-Agent proactive delivery and states the nutrition-source requirement for photo meal logging.
- Clarified that MediWise works with Hermes, OpenClaw, Claude Code, Codex, WorkBuddy, and other Skills-compatible agents; OpenClaw-specific workspace and channel instructions remain documented as an adapter path rather than a product requirement.
- Image and PDF intake now uses the current Agent's attachment-reading ability first. OCR and standalone vision services are optional fallbacks and are no longer required for installation.
- Product and Skill boundaries now explicitly limit MediWise to recording, organizing, displaying, summarizing, and reminding. Health, nutrition, weight, sleep, cycle, and monitoring outputs no longer generate treatment, medication, diet, exercise, or lifestyle instructions.
- Added a documentation center with audience-based navigation, a maintained project directory map, and clearer ownership for README, installation, Agent, and module documentation.
- Added an explicit acknowledgement of the LINUX DO (linux.do) community to the Chinese and English README files.
- Reworked the project architecture illustration as a user-facing visual abstract and restored it to the main reading path in both README files.

### Planned
- Integration with more wearable devices
- Expanded health record summaries and reminders
- Mobile app companion
- Export to standard medical formats (HL7, FHIR)

## [2.0.9] - 2026-07-21

### Security
- Node action routes now require `owner_id`; trusted personal installations must explicitly opt into `MEDIWISE_SINGLE_USER=1`.
- Added owner checks to sleep, monitoring, trend, threshold, dashboard, body-stat, drug-check, wearable device and sync operations; cross-tenant reads and writes are rejected.
- Removed health data, owner IDs and OAuth arguments from subprocess logs.
- Data directories, SQLite files, attachments, config and backup archives now use private `0700`/`0600` permissions.
- Backup restore now uses exact member allowlists, size limits, SHA-256 manifests, SQLite integrity checks, duplicate-member rejection, a cross-process restore lock, and full rollback when replacement, migration or post-migration validation fails.
- Pseudonyms are now stable SHA-256-derived identifiers instead of process-randomized Python hashes.

### Fixed
- Fixed all public sleep, body-stat, health-monitor and wearable routes that failed when `owner_id` was supplied.
- Backup now follows configured custom database paths and creates consistent SQLite snapshots instead of copying live WAL databases.
- Restore remains compatible with legacy official backups while identifying them as lacking manifest verification.
- Fixed macOS/BSD installer compatibility and Python 3.8 timezone support.
- Food lookup now distinguishes missing local data packs from a genuine no-result search.
- Added an explicitly enabled Open Food Facts provider with source/license attribution, bounded requests, configurable official endpoint and a global network-off switch.
- Fixed `food-lookup --source all` reporting success when every source was unavailable.
- Backup output can no longer overwrite a source database/config (including symlink and hard-link aliases), and restore normalizes all archived database paths into the active data directory.
- `.env.example` no longer enables a provider with placeholder credentials when copied unchanged.

## [1.0.15] - 2026-03-28

### Added
- **Garmin Connect provider** (`wearable-sync`): full implementation via `python-garminconnect`
  - 支持指标：全天心率、睡眠分期、夜间 HRV（RMSSD）、身体电量（Body Battery）、压力指数、步数、卡路里、血氧（SpO2）、活动记录
  - 认证错误分类处理：账号密码错误、两步验证、API 变更需升级库、限流等场景均有中文提示
  - Agent 对话引导规则：用户说"帮我绑定佳明"时，自动引导收集邮箱/密码/设备名称（历史行为；2.0.9 起密码只允许在本机终端交互输入）
  - `device.py` 新增 `--username`/`--password`/`--tokenstore` 参数
  - `list` 命令对 password 字段脱敏显示
- `normalize.py` 新增 `hrv`、`body_battery`、`stress`、`activity` 指标直通处理
- `requirements.txt` 注明 `garminconnect` 依赖

### Changed
- `wearable-sync/SKILL.md` 更新 description，修正 Garmin 绑定命令示例，补充 Agent 对话引导规则
- `wearable-sync/index.js` `device-auth` action 新增透传 Garmin 账号参数


## [0.3.0] - 2026-03-15

### Added
- `setup.py backup` command: packs all databases (`medical.db`, `lifestyle.db`, `config.json`) into a portable `.tar.gz` archive for device migration
- `setup.py restore` command: restores data from a backup archive and automatically runs schema migrations to the latest version
- `setup.py list-vision-providers` command: lists all built-in vision provider presets with default model, base URL, and API key hints
- Built-in provider presets for vision model setup (siliconflow, gemini, openai, stepfun, ollama): `--model` and `--base-url` are now auto-filled, only `--provider` and `--api-key` are required
- Conversational vision model setup guidance in `SKILL.md`: AI now guides users through configuration via chat without exposing CLI commands
- `check` command now outputs `vision_quick_setup` field with actionable next steps when vision model is not configured
- `.gitignore` now explicitly excludes `config.json` to prevent accidental API key exposure
- Updated `SKILL.md`, `INSTALLATION.md`, and `QUICKSTART.md` with backup/restore documentation, migration workflow, and simplified vision setup instructions

## [1.0.0] - 2026-03-08

### Added
- Initial release of MediWise Health Suite
- 5 health management skills:
  - `mediwise-health-tracker`: Core health records management
  - `diet-tracker`: Diet tracking
  - `weight-manager`: Weight management
  - `health-monitor`: Smart health monitoring and alerts (待完善)
  - `wearable-sync`: Wearable device sync (待完善)
- Shared SQLite database for all health data
- Doctor visit summary generation (text/image/PDF)
- Image recognition for medical reports
- Multi-level health alerts
- Medication and follow-up reminders
- Daily health briefings
- Comprehensive documentation (Chinese and English)

### Security
- All data stored locally in SQLite
- No cloud upload of personal health information
- Multi-tenant isolation support
