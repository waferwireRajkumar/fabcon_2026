# fabcon_2026

## Waferwire - Battery Returns Intelligence

**Participants:** Raj Kumar and Srikant Karimajji  
**Hackathon track:** Real Time Intelligence - Real Time Actions

Investigate battery-return batch spikes using Microsoft Fabric, validated
Bronze/Silver/Gold history, automated Teams investigation alerts, case traceability,
and a separate read-only AI companion. All demonstrated battery data is synthetic.

### Project and submission files

| Folder | Contents |
|---|---|
| `presentation` | Updated Partner Hack Kit, existing presentation and PDF |
| `media` | Use-case explainer, 2:42 technical walkthrough, actual screenshots |
| `fabric` | Notebook, pipeline, KQL tables/functions, dashboard and live definitions |
| `data\landing` | Exactly three CSV files and one JSON file |
| `app\companion` | Runnable server-backed HTML dashboard and AI companion |
| `src\live` | Synthetic-event generator and live KQL queries |
| `evidence` | Selected verification records |
| `docs\PROJECT_GUIDE.md` | Setup, Fabric rebinding, architecture and submission status |

This is the final consolidated copy. Development-stage labels and the superseded
dashboard export are not included. Existing cloud resources and authentic
screenshots remain unchanged.

Run `Start-Companion.cmd` after following the setup guide. Azure CLI and Copilot
sign-in plus access to the configured Fabric workspace are required. The compiled
frontend is included; opening its HTML without the server is not sufficient.

Verified demo: 12,000 return cases, 11,693 distinct batteries, 381 unknown initiators,
821 duplicate events removed and three invalid events quarantined.

The live Eventstream/Activator flow is separate from historical Gold. AI is
user-initiated; autonomous investigation, ticket creation and remediation are not
implemented. This is not an approved production customer deployment.

The dedicated approximately 90-second pitch, full customer-story packaging,
project-source publication/verification on GitHub, SharePoint upload, production
sizing and optional team photograph remain pending.