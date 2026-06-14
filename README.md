# athom-esp32-configs

ESPHome configurations for Athom ESP32 devices, layered with the
[Everything Presence Lite][epl] feature set.

## Devices

| Entry yaml | Device | mmWave chip | Targets |
| ---------- | ------ | ----------- | ------- |
| [`athom-ps02c3mz-sensor.yaml`](athom-ps02c3mz-sensor.yaml) | Athom PS02C3MZ | LD2450 | 3 |
| [`athom-ps02c3-sensor.yaml`](athom-ps02c3-sensor.yaml) | Athom PS02C3 | S3KM111L (SEN0609-compatible) | 1 |

Both devices share the same I²C BH1750 luminance sensor, the same PIR,
and the same ESP32-C3. They differ in their mmWave chip and, on the
PS02C3, an extra digital occupancy output on GPIO4.

## Layout

```
.
├── athom-ps02c3mz-sensor.yaml    # PS02C3MZ entry — used by dashboard import
├── athom-ps02c3-sensor.yaml      # PS02C3 entry — used by dashboard import
├── common/
│   ├── bluetooth-base.yaml       # Bluetooth proxy fragment
│   ├── ld2450-base.yaml          # LD2450 logic, derived from EPL upstream
│   ├── sen0609-base.yaml         # SEN0609 / S3KM111L logic, derived from EPL upstream
│   ├── ps02c3mz-base.yaml        # PS02C3MZ hardware base (LED, button, PIR, BH1750)
│   └── ps02c3-base.yaml          # PS02C3 hardware base — identical hardware to PS02C3MZ
├── upstream/                     # Vendored upstream sources, never hand-edited
│   ├── everything-presence-lite/
│   │   └── common/
│   │       ├── everything-presence-lite-base.yaml
│   │       ├── ld2450-base.yaml
│   │       ├── sen0609-base.yaml
│   │       └── modules/co2.yaml
│   └── athom-tech/
│       ├── athom-ld2450-sensor.yaml      # Athom's PS02C3MZ config
│       └── athom-presence-sensor-v3.yaml # Athom's PS02C3 config (their project_name labels it "PS01C3")
└── scripts/
    └── sync-upstream.py          # Fetches upstream files and 3-way merges into derived files
```

## Upstream sync

`.github/workflows/upstream-sync.yml` runs daily and on manual dispatch.
For each entry in [`.github/upstream-sources.yaml`](.github/upstream-sources.yaml)
it fetches the upstream file, refreshes the vendored copy under
`upstream/`, and (when a `derived:` path is configured) attempts a 3-way
merge into the local customized file using `git merge-file`.

Results:

- **No upstream change** → workflow exits without opening a PR.
- **Clean merge** → workflow opens a regular PR for review.
- **Conflict markers** → workflow opens a draft PR labelled
  `upstream-sync`, with a per-source breakdown of what needs manual
  triage in the step summary.

To track a new upstream file, add an entry to
`.github/upstream-sources.yaml` and re-run the workflow with the
`bootstrap` input set to `true` (or run
`python3 scripts/sync-upstream.py --bootstrap` locally).

> **One-time repo setting:** for the workflow to open PRs the repo needs
> *Settings → Actions → General → Workflow permissions → Allow GitHub
> Actions to create and approve pull requests* enabled.

## CI

`.github/workflows/ci.yml` runs `esphome compile` on PR for both entry
yamls via the test wrappers in `.github/test-configs/`. The test
wrappers provide the `name`, `friendly_name`, and `room` substitutions
that the user normally fills in through the ESPHome dashboard import.

## Pin map

### PS02C3MZ (LD2450)

| Function    | Pin    |
| ----------- | ------ |
| Radar TX    | GPIO8  |
| Radar RX    | GPIO5  |
| PIR         | GPIO3  |
| BH1750 SDA  | GPIO18 |
| BH1750 SCL  | GPIO19 |
| LED         | GPIO2  |
| Button      | GPIO9  |

### PS02C3 (S3KM111L / SEN0609-compatible)

| Function       | Pin    |
| -------------- | ------ |
| Radar Output   | GPIO4  |
| Radar TX       | GPIO8  |
| Radar RX       | GPIO5  |
| PIR            | GPIO3  |
| BH1750 SDA     | GPIO18 |
| BH1750 SCL     | GPIO19 |
| LED            | GPIO2  |
| Button         | GPIO9  |

[epl]: https://github.com/EverythingSmartHome/everything-presence-lite
