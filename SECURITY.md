# Security Policy

## Supported versions

Security fixes are applied to the latest release line. The project is currently in pre-release preparation; use a private deployment and do not expose an unconfigured instance to the public Internet.

## Reporting a vulnerability

Please do not publish credentials, personal signatures, database files, or an exploitable proof of concept in a public issue.

Until a dedicated security contact is configured for this repository, report security issues privately to the repository maintainer. Include:

- affected version or commit;
- deployment mode (Docker, systemd, or other);
- reproducible steps without real personal data;
- impact and any required configuration;
- suggested mitigation, if known.

Allow time for assessment and coordinated disclosure before publishing details.

## Deployment requirements

- Set a long random `ADMIN_TOKEN` before starting the service.
- Use HTTPS when the service is reachable from phones or the public Internet.
- Treat monitor credentials as write-capable credentials because the monitor can delete submissions.
- Do not commit `.env`, `.secrets/`, SQLite databases, exported signatures, or private background assets.
- Back up the SQLite database before upgrades and verify that the backup can be restored.
- Keep the service within the documented single-process, single-node deployment boundary.
