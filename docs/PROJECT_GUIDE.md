# Waferwire - Battery Returns Intelligence

Partner: Waferwire  
Participants: Raj Kumar and Srikant Karimajji  
Track: Real Time Intelligence - Real Time Actions

Verified public repository: https://github.com/waferwireRajkumar/fabcon_2026  
Default branch: `main`. At verification its root contained `README.md` only;
the project source still needs publication to the repository.

This package contains the source, synthetic inputs, Fabric definitions, updated
organizer presentation, screenshots and existing videos for the demonstrated
hackathon project. It is a downloadable project/accelerator package, not evidence
of a production customer deployment.

## Start here

1. Open `presentation\Waferwire_Partner_Hack_Kit.pptx`. Participant slides 17-25
   contain the project details. Organizer examples on slides 1-16 are unchanged.
2. Watch `media\Battery_Returns_Pipeline_Walkthrough.mp4` (2:42).
3. For the existing workspace, follow the companion setup below.
4. To rebuild in Fabric, use the notebook, pipeline, KQL and dashboard definitions
   under `fabric`, and the four inputs under `data\landing`.

## Package layout

- `presentation`: updated partner kit and the existing solution presentation/PDF.
- `media`: use-case explainer, technical walkthrough, and actual demo screenshots.
- `fabric\medallion`: safe processor notebook, pipeline and Gold serving function.
- `fabric\dashboard`: final native KQL dashboard definition.
- `fabric\live`: credential-redacted live definitions where export was available,
  plus an export-status report.
- `data\landing`: exactly three CSV files and one JSON file.
- `app\companion`: HTML/CSS/JavaScript frontend, Python backend, manifests and tests.
- `app\fabric_api.py`: scoped Azure CLI authenticated Fabric/KQL access.
- `app\config\expected.json`: source checksums and expected lineage for the app.
- `src\live`: synthetic-event generator and live KQL queries.
- `evidence\pipeline` and `evidence\dashboard`: pipeline and final dashboard verification.
- `evidence`: selected video and presentation verification records.
- `manifest.json`: file sizes and SHA-256 checksums.

## Run the local HTML / AI companion

The app is server-backed. Opening `public\index.html` alone is not sufficient.
Requirements: Python 3.12, Azure CLI, GitHub Copilot CLI, authorized Copilot access,
and an account with access to the Fabric workspace and KQL database.

In PowerShell, from the extracted project root:

```powershell
python -m venv app\companion\.venv
& .\app\companion\.venv\Scripts\python.exe -m pip install -r app\companion\requirements.txt
az login
```

Sign in to GitHub Copilot CLI using its interactive `/login` command if necessary.
Then run `Start-Companion.cmd` and open `http://localhost:8765`.
Do not start a second copy while another companion already owns port 8765.

The compiled frontend is included. Node/npm are only needed to rebuild its source:

```powershell
Set-Location app\companion
npm ci
npm run build
```

Run the existing focused backend tests:

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s tests -p test_companion.py
```

The app uses the presenter's Azure and Copilot access and binds to loopback only.
It is not a public multi-user deployment.

## Rebuild or rebind the Fabric assets

Existing demo resource references are preserved in the definitions and source.
For a different workspace, replace/rebind workspace and database IDs, Kusto URI,
default Lakehouse association, pipeline notebook IDs and dashboard data sources.
Keep credential-host checks and the AI's named read-only tool permissions intact.

1. Create a schema-enabled Lakehouse and upload the four files to
   `Files\landing`.
2. Import `fabric\medallion\BatteryReturns_Medallion_Processor.ipynb` and associate
   it with the Lakehouse. Review its deployment/serving settings for your resources.
3. Rebind the four notebook activities in `pipeline-content.json`. They pass the
   stages `bronze`, `silver`, `gold`, and `publish`, in successful-predecessor order.
4. Deploy the Gold serving table/function contract to the KQL database and import
   or reconstruct the native dashboard using its definition.
5. For the live branch, use the exported Eventstream/Activator parts where
   available; otherwise configure them in Fabric. Reconnect source credentials
   and Teams destinations through supported authenticated interfaces.

The live demo flow is Eventstream > Eventhouse > batch-condition detection >
Activator > Teams. Its demonstrated rule is three distinct batteries from one
batch within 15 minutes. It is a demo rule, not a validated operational policy.
Only import/run cloud assets after reviewing the target resources and permissions;
this package does not automatically provision or execute cloud jobs.

This is the final consolidated delivery, not a collection of development versions.
The notebook's input path is normalized for a fresh import. Existing cloud
resources were not renamed or rerun; their landing folder may differ. Screenshots
and recorded deployment evidence retain their authentic historical observations.

## Data and verified behavior

Inputs: `products.csv` (8 rows), `batteries.csv` (11,693), `shipments.csv` (10,347),
and `return_events.json` (46,442 raw events).

Silver removes 821 exact event replays and quarantines three invalid events,
retaining 45,618 valid distinct events. Gold selects the highest revision per
return ID, resulting in 12,000 cases and 381 unknown original initiators.
Valid repeated battery returns remain separate cases.

Two pipeline runs were verified. The rerun reused the publication rather than
duplicating the served cases. `ReturnsGoldLatest()` serves committed Gold only.
The raw serving table has 35 columns: 34 case fields plus `publish_id`.

Historical Gold is a fixed synthetic snapshot, separate from live alert events.
There are no sales-population denominators, measured customer ROI or validated
causal/defect-rate conclusions in this dataset.

## Submission status

Available: updated partner kit, existing server-backed HTML/AI demo source,
local accelerator code, under-three-minute use-case explainer, and 2:42 technical walkthrough.
The available videos are embedded in the updated PPT and included separately.

Still pending:

- Dedicated approximately 90-second customer elevator pitch.
- Full customer-storytelling packaging expected by the kit's example prompt.
- Project-source publication to the verified GitHub repository.
- Techdata SharePoint folder link and actual upload.
- Production sizing, approved customer references and optional team photograph.

The package does not claim these pending items are complete.

## Cost and authentication notes

The demo ran on FT1 trial capacity. The included F2 example is a dated West Central
US capacity-only PAYG illustration: USD 288 per 30 days at 24 provisioned hours/day,
from the November 4, 2026 retail snapshot. It is not an invoice, reservation quote,
workspace allocation or validated production-SKU recommendation. Storage,
transactions, bandwidth, licenses, taxes, overage and optional services are excluded.

Official calculator: https://azure.microsoft.com/en-us/pricing/calculator/

Authentication caches, tokens, machine-specific dependency directories and browser
profiles are not included. Reconfigure any redacted connection fields through
Fabric. AI responds to user questions through five read-only analytics tools;
automatic AI investigation, ticket creation and autonomous remediation are absent.
