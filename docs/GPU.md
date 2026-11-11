# GPU options in AWS us-east-1

The pipeline runs in AWS **us-east-1**. This is the same region as the NOAA GOES-19
bucket (`noaa-goes19`), so there is no cross-region transfer (see `AGENTS.md`).
GPU VMs are started with [Coiled](https://docs.coiled.io) (dev dependency) in the
`earthmover-devs` workspace (AWS backend, default region us-west-2, so every command
passes `--region us-east-1`).

At GTC Berlin we used a B200 (`p6-b200.48xlarge`).

## Instance types

Coiled lists these GPU instance types (`coiled.list_instance_types(backend="aws")`).
Prices are us-east-1 on-demand prices from instances.vantage.sh. They are not checked
against the AWS Pricing API.

| Instance | GPUs | vCPU / RAM | On-demand $/h | $/GPU/h |
|---|---|---|---|---|
| `p6-b300.48xlarge` | 8x B300 | 192 / 4 TiB | 142.42 | 17.80 |
| `p6-b200.48xlarge` | 8x B200 | 192 / 2 TiB | 113.93 | 14.24 |
| `p5en.48xlarge` | 8x H200 | 192 / 2 TiB | 63.30 | 7.91 |
| `p5.48xlarge` | 8x H100 | 192 / 2 TiB | 55.04 | 6.88 |
| `p5.4xlarge` | 1x H100 | 16 / 256 GiB | 6.88 | 6.88 |
| `g7e.8xlarge` | 1x RTX PRO 6000 Server | 32 / 256 GiB | 5.27 | 5.27 |
| `g7e.2xlarge` | 1x RTX PRO 6000 Server | 8 / 64 GiB | 3.36 | 3.36 |
| `g6e.xlarge` | 1x L40S | 4 / 32 GiB | 1.86 | 1.86 |

Coiled also lists multi-GPU sizes of `g6e` (4x/8x L40S) and `g7e` (2x/4x/8x RTX PRO
6000 Server).

## Notes

- **B200, B300 and H200 come only as 8-GPU nodes.** A pipeline that uses one GPU
  pays for eight. A single-GPU option costs about 16x less per hour than a B200
  node. The speed difference for StormScope is not measured yet.
- **Capacity:** B200, B300 and H200 usually need a raised EC2 GPU quota or an
  [EC2 Capacity Block](https://aws.amazon.com/ec2/capacityblocks/). On-demand
  capacity in us-east-1 is often not available. Book before the booth days.
- **Single-GPU candidates**, from fastest to cheapest: `p5.4xlarge` (H100),
  `g7e.*` (RTX PRO 6000 Server, Blackwell, 96 GB), `g6e.*` (L40S, 48 GB).

## Single-GPU types below $10/h

The pipeline uses one GPU. From fastest to slowest (us-east-1 on-demand $/h):

| GPU | Instances ($/h) |
|---|---|
| H100 80 GB | `p5.4xlarge` (6.88) |
| RTX PRO 6000 Server 96 GB (Blackwell) | `g7e.2xlarge` (3.36), `g7e.4xlarge` (4.00), `g7e.8xlarge` (5.27) |
| L40S 48 GB | `g6e.xlarge` (1.86), `g6e.2xlarge` (2.24), `g6e.4xlarge` (3.00), `g6e.8xlarge` (4.53), `g6e.16xlarge` (7.58) |
| RTX PRO 4500 (Blackwell) | `g7.2xlarge` (2.52), `g7.8xlarge` (4.09) |
| L4 24 GB | `g6.xlarge` (0.80) |
| A10G 24 GB | `g5.xlarge` (1.01) |
| T4 16 GB, V100 | `g4dn`, `p3`: no BF16, which the model's mixed precision uses |

The pipeline uses about 11 GB of GPU memory (Coiled metrics, L40S, 12-step run), so
every GPU with 16 GB or more fits. L4 and A10G have about 1/3 and 1/5 of the L40S's BF16
compute; a 12-step forecast is estimated at 2-3 min on them (not measured), which still
fits the 5-min cycle but adds 1.5-2 min of latency. The same L40S on a smaller instance
(`g6e.4xlarge`, $3.00/h) costs 34% less than `g6e.8xlarge` at the same speed, and
`g6e.2xlarge` ($2.24/h) and `g6e.xlarge` ($1.86/h) are cheaper still.

**Capacity in us-east-1 changes from minute to minute.** Observed in one session, in
this order:

1. `p5.4xlarge` alone: `InsufficientInstanceCapacity` in every zone (a to f), twice.
2. A 6-type list: got `g7e.8xlarge` (failed later, see the timing log).
3. The same 6-type list: every type full.
4. The same list, first retry: got `g7e.8xlarge` again.
5. A 10-type list, first try: got `g6e.8xlarge`.

## Run on Coiled

See [Coiled GPU clusters](https://docs.coiled.io/user_guide/clusters/gpu.html). Use the
`earthmover-devs` workspace. Its default region is us-west-2, so always pass
`--region us-east-1`.

`scripts/coiled_bootstrap.sh` starts from the public NGC PhysicsNeMo image, installs
earth2studio, NATTEN and earth2grid, and then runs the pipeline.
It skips the installs when they are already done on the VM.

### Default deployment: `g6e.xlarge`

**Default and most preferred instance: `g6e.xlarge`** (1x L40S 48 GB, 4 vCPU / 32 GB,
$1.86/h, ~$45/day). It runs a forecast as fast as the bigger L40S sizes (45.5 s against
44.2 s on `g6e.4xlarge` and 45.0 s on `g6e.8xlarge`) at 62% / 41% of their price; see the
timing log. Only the first forecast after a start is slower (83.5 s; 4 vCPU slow the
torch.compile warmup).

| | |
|---|---|
| Cluster name | `stormscope-us-gpu`, workspace `earthmover-devs` |
| Job | continuous: a 12-step forecast per 5-min GOES scan, published to `nvidia/sc26-chicago-stormscope_us-booth` |
| Keepalive | none: the VM runs while the continuous loop runs, so stop it yourself |
| Stop | `uv run coiled cluster stop --workspace earthmover-devs stormscope-us-gpu` |
| Logs | `uv run coiled logs --workspace earthmover-devs --cluster stormscope-us-gpu --label none` |

### Start the pipeline

One command gets a GPU VM and runs the pipeline on it continuously. Without
`--start-time`, the pipeline loops and runs each new init, so the command never exits and
the VM needs no keepalive. `--env` sends the Arraylake token from `.env` to the VM. The
token is not stored anywhere.

The command lists `g6e.xlarge` first, then fallbacks. Coiled uses the next type if AWS
has no capacity for one. The fallbacks are the other L40S sizes (same speed, from
cheapest), then faster and pricier GPUs. If all types are full, the command fails without
starting a VM (no cost), so the loop tries again:

```bash
(set -a; . ./.env; set +a
 for n in $(seq 1 14); do
   uv run coiled run --workspace earthmover-devs --name stormscope-us-gpu --region us-east-1 \
     --ami-version DL --skip-ssd-mount \
     --vm-type g6e.xlarge --vm-type g6e.2xlarge --vm-type g6e.4xlarge --vm-type g6e.8xlarge \
     --vm-type g6e.16xlarge \
     --vm-type g7e.2xlarge --vm-type g7e.4xlarge --vm-type g7e.8xlarge --vm-type p5.4xlarge \
     --container nvcr.io/nvidia/physicsnemo/physicsnemo:26.08 --root --disk-size 200 \
     --docker-shm-size "1 GiB" --file scripts/ --detach \
     --env ARRAYLAKE_API_TOKEN="$ARRAYLAKE_API_TOKEN" \
     -- bash scripts/coiled_bootstrap.sh --n-steps 12 --publish-target arraylake \
        --arraylake-repo nvidia/sc26-chicago-stormscope_us-booth \
     > run.log 2>&1
   grep -q "VM Type: *[a-z]" run.log && break  # got a VM
   sleep 120
 done)
```

The first forecast after a start is slower because it installs the dependencies and fills
the compile cache. Check the logs (see the table above) until the first commit lands.

The repo holds 12 lead steps, so every run must use `--n-steps 12`.

**Always pass `--ami-version DL`.** Blackwell GPUs (`g7e`, `g7`, B200, B300) work only
with NVIDIA's open kernel modules. Coiled's default AMI has the proprietary driver, so
on a `g7e` the kernel logs `NVRM: ... requires use of the NVIDIA open kernel modules`
and `nvidia-smi` finds no devices. The `DL` AMI (Deep Learning Base OSS Nvidia Driver)
works on all GPU types.

**Do not pass `--keepalive` to the continuous run.** The keepalive is a hard cap, not a
grace period. Coiled stops the VM when the keepalive expires, counted from the last
`coiled run`, even while the command is still running. A VM with `--keepalive 4h` stopped
exactly 4 h after its last `coiled run`, in the middle of a healthy pipeline loop.
Another `coiled run` with the same `--name` restarts the clock but also kills the
running command.

Without a keepalive, Coiled stops the VM 10 ms after the command exits, and that GPU
can be gone on the next launch. On a `g7e.8xlarge`, a `--detach` run with no keepalive
also stopped twice during the bootstrap's first `pip install`. This did not happen with a
keepalive. So launch with `--keepalive 30m` and stop the cluster by hand when the run is
done. A later `coiled run` with the same `--name` reuses the running VM. Stop it with
`uv run coiled cluster stop --workspace earthmover-devs <name>`.

**Pass `--skip-ssd-mount`** on instances with a local NVMe SSD (`g6e`, `g6`, `g5`). On
a `g6e.4xlarge` with the `DL` AMI, Coiled could not format the SSD (`mkfs.xfs: cannot
open /dev/nvme1n1: Device or resource busy`), `/scratch` was missing, and the cluster
stopped with "Software environment exited with error code 1" before the command ran
(twice). A `g6e.8xlarge` mounted it without problems.

Do not attach to a run VM with `coiled.Cluster(name=...)`. If that VM has stopped, this
call starts a new default Dask cluster (CPU only) under the same name.

If AWS has no capacity or the quota is too low, Coiled returns an error such as
`InsufficientInstanceCapacity` or `VcpuLimitExceeded`.

## Inference timing log

One row per pipeline run on a Coiled VM. The pipeline prints `timing:` (fetch, rollout
plus write, commit) and `step times (<GPU>):`. Step 0 returns the observed analysis frame and does not
call the model. Step 1 is the first model step and includes the `torch.compile` warmup.
"s/step" is the mean of steps 2 and later, the steady state. Full CONUS, `3km_10min_flash`, 1 ensemble
member.

| Instance | GPU | n_steps | Fetch s | Step 1 s (warmup) | s/step | Commit s | Result |
|---|---|---|---|---|---|---|---|
| g7e.8xlarge | RTX PRO 6000 Server | 3 | - | - | - | - | failed: default AMI has no open kernel modules, no GPU (fixed with `--ami-version DL`) |
| g7e.8xlarge | RTX PRO 6000 Server | 3 | - | - | - | - | failed: bootstrap exited after the first pip install, cause not logged; VM stopped (no keepalive) |
| g6e.8xlarge | L40S 48 GB | 3 | 7.0 | 18.4 | 3.9 | 0.0 | OK, local store; total 33.6 s |
| g6e.8xlarge | L40S 48 GB | 12 | 6.8 | 9.2 | 3.7 (3.3 from step 4) | 0.7 | OK, Arraylake `nvidia/sc26-chicago-stormscope_us-booth`; total 55.7 s; same VM as the row above, so the compile cache was warm |
| g6e.8xlarge | L40S 48 GB | 12 | 3.3–6.4 | - | 3.4–4.0 (rollout+write 40.4–48.0 s / 12) | 0.5–0.7 | OK, continuous, 4 inits 5 min apart; total 44.3–54.9 s; published ~6 min after slot time |
| g6e.4xlarge | L40S 48 GB | 12 | 3.7 | - | 3.3 (rollout+write 40.0 s / 12) | 0.6 | OK, 4 live inits, mean of the last 3: total 44.2 s (first, cold compile cache: 62.2 s); $3.00/h, $0.037 per forecast; same speed as g6e.8xlarge (45.0 s) at 66% of the price |
| `g6e.2xlarge` | L40S 48 GB | 12 | | | | | TODO: same GPU, 8 vCPU / 64 GB RAM, $2.24/h, cheaper than g6e.4xlarge ($3.00/h) |
| g6e.xlarge | L40S 48 GB | 12 | 4.5 | - | 3.4 (rollout+write 40.5 s / 12) | 0.6 | OK, 4 live inits, mean of the last 3: total 45.5 s (first, cold compile cache: 83.5 s; 4 vCPU slow the warmup); $1.86/h, $0.024 per forecast; same steady-state speed as g6e.4xlarge/8xlarge at 62% / 41% of their price |
| `g6.xlarge` | L4 24 GB | 12 | | | | | TODO: $0.80/h (−82%); estimated 2–2.5 min per forecast |
| `g5.xlarge` | A10G 24 GB | 12 | | | | | TODO: $1.01/h (−78%); estimated 2–3 min per forecast |

## Sources

- https://instances.vantage.sh/aws/ec2/p6-b200.48xlarge?region=us-east-1
- https://instances.vantage.sh/aws/ec2/p6-b300.48xlarge?region=us-east-1
- https://instances.vantage.sh/aws/ec2/p5en.48xlarge?region=us-east-1
- https://instances.vantage.sh/aws/ec2/p5.48xlarge?region=us-east-1
- https://instances.vantage.sh/aws/ec2/p5.4xlarge?region=us-east-1
- https://instances.vantage.sh/aws/ec2/g7e.2xlarge?region=us-east-1
- https://instances.vantage.sh/aws/ec2/g7e.8xlarge?region=us-east-1
- https://instances.vantage.sh/aws/ec2/g6e.xlarge?region=us-east-1
