# Changelog

All notable changes to MediWise Health Suite will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned
- Integration with more wearable devices
- Enhanced AI-powered health insights
- Mobile app companion
- Export to standard medical formats (HL7, FHIR)

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
