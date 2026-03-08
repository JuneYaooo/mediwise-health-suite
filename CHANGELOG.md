# Changelog

All notable changes to MediWise Health Suite will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-03-08

### Added
- Initial release of MediWise Health Suite
- 11 integrated health management skills:
  - `mediwise-health-tracker`: Core health records management
  - `health-monitor`: Smart health monitoring and alerts
  - `medical-search`: Medical search and drug safety
  - `symptom-triage`: Symptom triage
  - `first-aid`: First aid guidance
  - `diagnosis-comparison`: Multi-source diagnosis comparison
  - `health-education`: Health education
  - `diet-tracker`: Diet tracking
  - `weight-manager`: Weight management
  - `wearable-sync`: Wearable device sync
  - `self-improving-agent`: Self-improvement
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

## [Unreleased]

### Planned
- Integration with more wearable devices
- Enhanced AI-powered health insights
- Mobile app companion
- Export to standard medical formats (HL7, FHIR)
