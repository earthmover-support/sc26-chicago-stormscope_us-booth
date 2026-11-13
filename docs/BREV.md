# Run the pipeline on NVIDIA Brev

A [Brev launchable](https://docs.nvidia.com/brev/concepts/launchables) starts a GPU VM,
asks the deployer for the Arraylake credentials, and runs the pipeline continuously, as
the Coiled setup in [GPU.md](GPU.md) does. The launchable is created in the Brev Console;
the Brev CLI cannot create launchables.

## How it works

- [`scripts/brev_setup.sh`](../scripts/brev_setup.sh) is the launchable's setup script
  (VM Mode). Brev passes the setup values to it as environment variables and deletes them
  after setup. The script clones this repo to `/opt/stormscope-us`, stores the values in
  `/etc/stormscope-us/env` (root, mode 600), and starts the systemd service
  `stormscope-us`.
- The service runs [`scripts/brev_service.sh`](../scripts/brev_service.sh). It runs the
  pipeline in the NGC PhysicsNeMo container through
  [`scripts/coiled_bootstrap.sh`](../scripts/coiled_bootstrap.sh), with `--n-steps 12`.
  The first start installs the dependencies and commits the container as the local image
  `stormscope-us:26.08-<bootstrap hash>`, so later starts skip the installs. A change to
  `coiled_bootstrap.sh` (a new dependency) changes the tag and reinstalls on the next start. systemd restarts the
  pipeline 30 s after it exits, and again after a reboot or a Brev stop/start.
- Model weights, pyspectral's lookup tables, the torch.compile cache, and local outputs live in
  `/var/lib/stormscope-us` on the VM, so a restart does not download or compile again.

## Create the launchable

In the [Brev Console](https://brev.nvidia.com), open **Launchables → Create Launchable**:

| Section | Setting |
|---|---|
| Software configuration | **VM Mode**, Jupyter off. Setup script: paste the full contents of `scripts/brev_setup.sh`. |
| Source | **I don't have any code files.** The setup script clones the repo itself, to a fixed path. |
| Default hardware configuration | 1x L40S (or any GPU with BF16 and 16 GB or more; see [GPU.md](GPU.md#single-gpu-types-below-10h)). Prefer **AWS us-east-1** when the location is offered: the GOES-19 bucket and Arraylake are there (see `AGENTS.md`). Disk: 200 GiB (the container is about 25 GB). |
| Network | Nothing to expose. The pipeline only makes outgoing connections. |
| Launch parameters | The four setup values below. |

Setup values:

| Name | Required | Type | Default | Description |
|---|---|---|---|---|
| `ARRAYLAKE_API_TOKEN` | yes | Text | none | Arraylake token with write access to the repo. Pick **Use a secret** with an org secret when deploying. |
| `ARRAYLAKE_REPO` | no | Text | `nvidia/sc26-chicago-stormscope_us-booth` | Arraylake `org/repo` to publish to. |
| `STORMSCOPE_PUBLISH_TARGET` | no | Choice: `arraylake`, `local` | `arraylake` | `local` writes to `/var/lib/stormscope-us/outputs` on the VM instead, for a test. |
| `STORMSCOPE_GIT_REF` | no | Text | `main` | Branch, tag or commit of this repo to run. |

Never store the token as a parameter default. Brev keeps launchable defaults in the
launchable itself.

## Deploy and watch

Deploy the launchable and fill in the setup values. The setup log ends with
`[brev-setup] ... started`. Then, on the VM (`brev shell <instance>`):

```bash
sudo journalctl -u stormscope-us -f
```

The first start pulls the container and installs the dependencies (about 10–15 min,
`[bootstrap]` lines), then the first forecast compiles (about 1.5 min on an L40S). After
that, each new GOES-19 scan gives a `Published to arraylake` line about 45 s later.

| Task | Command on the VM |
|---|---|
| Status | `systemctl status stormscope-us` |
| Stop the pipeline | `sudo systemctl stop stormscope-us` (the VM keeps running and costing) |
| Restart | `sudo systemctl restart stormscope-us` |
| Change a setup value | `sudo nano /etc/stormscope-us/env`, then restart |
| Run another commit | rerun the setup script with new values, e.g. `sudo ARRAYLAKE_API_TOKEN=... STORMSCOPE_GIT_REF=<ref> bash /opt/stormscope-us/scripts/brev_setup.sh` |
| Reinstall dependencies | `sudo docker rmi $(sudo docker images -q stormscope-us)`, then restart |

Stop or delete the instance in the Brev Console (or `brev stop` / `brev delete`) after
booth hours and after the event; stopping the service alone does not stop billing.

## Notes

- The token sits on the VM disk in `/etc/stormscope-us/env` and in the metadata of the
  running container, so systemd can restart the pipeline. Anyone with root on the VM
  can read it. Delete the instance after the event and revoke the token.
- The NGC container `physicsnemo:26.08` uses CUDA 13.2. The setup log prints the host
  driver version (`nvidia-smi`). If the bootstrap's torch CUDA check fails, the VM's
  driver is too old for the container; pick another instance type or provider.
- All runs into the same Arraylake repo must use the same `--n-steps` and `--region`
  (see the README). The service fixes `--n-steps 12` and full CONUS; do not run it next to
  a Coiled deployment with other settings.
