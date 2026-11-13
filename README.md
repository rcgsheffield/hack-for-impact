# Hack for Impact

> Build autonomous systems that think, act, and run anywhere, whilst also making a positive impact on the world.

Our entry for the NVIDIA [Hack for Impact Sheffield](https://events.nvidia.com/hack-for-impact-sheffield/) hackathon, **Friday 13 November 2026, 09:00 – 20:00**.

## Challenge

We are building an agentic AI solution that runs on local compute and delivers real-world impact in one of three tracks:

| Track | Focus | Goal |
|-------|-------|------|
| **Economic Systems** | How money flows through businesses, workers and markets | Agentic systems that help people and organisations make better economic decisions, unlock opportunities or optimise costs |
| **Public Services** | How people access and interact with public services and resources | Data-driven tools that make public systems easier to navigate, more efficient and more user-friendly |
| **Urban Operations** | How cities run, from large-scale infrastructure to everyday life | Systems that improve how cities function behind the scenes and in real time |

Tracks describe a theme of impact, not the scope of the idea. Any solution that delivers against a theme is eligible.

### Judging criteria

- **Impact**: does the solution address a real problem?
- **Technical execution**: how well does it use agentic AI and local compute?
- **Feasibility**: could it realistically be built or deployed beyond the hackathon?

## Chosen track and idea

_TBD. Fill this in once the team has decided._

- **Track:**
- **Problem:**
- **Who benefits:**
- **Approach:**

## Data sources

Public datasets are available, and none is mandatory:

- [Sheffield City Council Open Data portal](https://data.sheffield.gov.uk/), including Sheffield Local Insight neighbourhood indicators
- [data.gov.uk](https://www.data.gov.uk/)
- [Office for National Statistics (ONS)](https://www.ons.gov.uk/)

Keep downloaded datasets in `data/`. Raw files are git-ignored by default, so record where each came from in [`data/README.md`](data/README.md).

## Repository layout

```
.
├── docs/       Challenge brief, design notes, pitch material
├── data/       Local datasets (not committed) and their provenance
├── src/        Application and agent code
├── LICENSE
└── README.md
```

## Getting started

_Setup instructions to be added once the stack is chosen._

### Deployment (DGX Spark)

Every push to `main` deploys to the DGX Spark through a GitHub Actions [self-hosted runner](https://docs.github.com/en/actions/hosting-your-own-runners) on that machine (`.github/workflows/deploy.yml`). The runner connects out to GitHub, so the Spark needs no inbound access. The workflow runs [`deploy.sh`](deploy.sh), which syncs the code to `~/hack-for-impact` on the Spark (its local `data/` is kept) and then starts the app. To redeploy without pushing, use **Actions → Deploy to DGX Spark → Run workflow**.

One-time runner setup, done on the Spark over SSH:

1. In GitHub, go to **Settings → Actions → Runners → New self-hosted runner**, choose **Linux / ARM64**, and follow the download steps it shows.
2. Configure the runner with the `spark` label and install it as a service:
   ```bash
   ./config.sh --url https://github.com/rcgsheffield/hack-for-impact --token <TOKEN> --labels spark --unattended
   sudo ./svc.sh install && sudo ./svc.sh start
   ```
3. Make sure `rsync` is installed. If the app will use Docker, add the runner's user to the `docker` group.

## Team

_Add team members here._

## Licence

Released under the [MIT License](LICENSE).
